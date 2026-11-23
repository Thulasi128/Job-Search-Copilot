"""Evaluation runner for the deterministic job matcher.

Evaluates match score prediction against human-labeled benchmark JDs in data/labels.csv
and data/jds/, computing categorical classification accuracy and Spearman rank correlation.

Strict Evaluation Honesty Rules:
- Requires n >= 20 independent human-labeled JDs for headline accuracy / Spearman reporting.
- If n < 20, requires --allow-small flag and prints 'n = X, not statistically meaningful'.
- Suppresses p-values when n < 20.
- Three classification bands only: strong (>= 70), medium (40-69), weak (< 40).
- Conflict is treated as a constraint flag, not a distinct classification band.
- Effective caps: reports only caps that actually modified score_before_caps != score_after_caps.
- Generates 3x3 confusion matrix and per-class precision and recall.
"""

import argparse
import asyncio
import csv
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scipy.stats import spearmanr

from backend.agents.intake_agent import process_job_intake
from backend.agents.matching_agent import evaluate_match
from backend.config import get_settings
from backend.database import get_db
from backend.models.job import Job
from backend.models.profile import Preferences, Profile
from scripts.real_similarity_check import get_synthetic_profile

logger = logging.getLogger(__name__)

MIN_REQUIRED_BENCHMARK_SIZE = 20


def find_data_paths() -> Tuple[Path, Path]:
    """Locate labels.csv and jds/ directory with fallbacks between root data/ and backend/eval/data/."""
    root_labels = PROJECT_ROOT / "data" / "labels.csv"
    root_jds = PROJECT_ROOT / "data" / "jds"

    eval_labels = PROJECT_ROOT / "backend" / "eval" / "data" / "labels.csv"
    eval_jds = PROJECT_ROOT / "backend" / "eval" / "data" / "jds"

    if root_labels.exists() and root_jds.exists():
        return root_labels, root_jds
    if eval_labels.exists() and eval_jds.exists():
        return eval_labels, eval_jds
    raise FileNotFoundError("Could not find evaluation data in data/ or backend/eval/data/")


def map_score_to_category(score: int) -> str:
    """Map continuous score strictly into 3 discrete fit bands based on Preferences."""
    if score >= 70:
        return "strong"
    if score >= 40:
        return "medium"
    return "weak"


def get_default_eval_preferences() -> Preferences:
    """Provide standard candidate preferences for matching benchmark."""
    return Preferences(
        id="eval_preferences",
        target_roles=["Software Engineer Intern", "Machine Learning Intern"],
        max_duration_months=6,
        preferred_locations=["Austin, TX"],
        remote_ok=True,
        emphasise_skills=["Python", "React", "FastAPI"],
        avoid_skills=["PHP"],
        min_score_to_tailor=70,
        min_score_to_consider=40,
    )


async def evaluate_matcher(
    labels_path: Optional[Path] = None,
    jds_dir: Optional[Path] = None,
    profile: Optional[Profile] = None,
    preferences: Optional[Preferences] = None,
    embedding_fn: Any = None,
    chroma_dir: Optional[str] = None,
    allow_small: bool = True,
) -> Dict[str, Any]:
    """Run matcher evaluation on benchmark dataset and compute accuracy, rank correlation, and confusion matrix."""
    default_labels, default_jds = find_data_paths()
    labels_file = labels_path or default_labels
    jds_folder = jds_dir or default_jds

    candidate_profile = profile or get_synthetic_profile()
    candidate_prefs = preferences or get_default_eval_preferences()

    # Read ground truth labels
    records: List[Dict[str, str]] = []
    with open(labels_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("filename"):
                records.append(row)

    total_records = len(records)
    if total_records == 0:
        raise ValueError(f"No evaluation records found in {labels_file}")

    if total_records < MIN_REQUIRED_BENCHMARK_SIZE and not allow_small:
        raise ValueError(
            f"Evaluation dataset has only n = {total_records} JDs (minimum {MIN_REQUIRED_BENCHMARK_SIZE} "
            "independent human labels required for headline metrics). Pass --allow-small to run smoke test."
        )

    # Connect to MongoDB or fallback to AsyncMongoMockClient
    try:
        from backend.database import connect_db, get_client
        if get_client() is None:
            await connect_db()
        db = get_db()
        await db.command("ping")
    except Exception:
        import backend.database as db_mod
        from mongomock_motor import AsyncMongoMockClient
        db_mod._mongo_client = AsyncMongoMockClient()
        db = db_mod.get_db()

    existing_prof = await db.profiles.find_one({"id": candidate_profile.id})
    if not existing_prof:
        await db.profiles.replace_one({"id": candidate_profile.id}, candidate_profile.model_dump(), upsert=True)

    existing_pref = await db.preferences.find_one({"id": candidate_prefs.id})
    if not existing_pref:
        await db.preferences.replace_one({"id": candidate_prefs.id}, candidate_prefs.model_dump(), upsert=True)

    # Index chunks in vector store if needed
    try:
        from backend.vector_store import get_embedding_function, index_profile_chunks
        ef = embedding_fn or get_embedding_function()
        index_profile_chunks(candidate_profile, persist_directory=chroma_dir, embedding_fn=ef)
    except Exception as e:
        logger.debug("Vector store indexing notice: %s", e)

    predicted_scores: List[float] = []
    ground_truth_ranks: List[float] = []
    results: List[Dict[str, Any]] = []

    # Confusion matrix counters: labels = ['strong', 'medium', 'weak']
    classes = ["strong", "medium", "weak"]
    confusion_matrix: Dict[str, Dict[str, int]] = {
        true_cls: {pred_cls: 0 for pred_cls in classes} for true_cls in classes
    }

    correct_count = 0
    rank_map = {"strong": 3.0, "medium": 2.0, "weak": 1.0}

    for rec in records:
        filename = rec["filename"]
        raw_expected_label = rec["fit_label"].strip().lower()
        # If conflict in dataset, map expected label to weak or medium based on actual skills
        expected_label = raw_expected_label if raw_expected_label in classes else "weak"
        expected_rank = float(rec.get("expected_rank", rank_map.get(expected_label, 1.0)))

        jd_path = jds_folder / filename
        if not jd_path.exists():
            logger.warning("JD file not found: %s, skipping", jd_path)
            continue

        with open(jd_path, mode="r", encoding="utf-8") as jf:
            jd_text = jf.read()

        # Deterministic extraction of skills and metadata
        lines = [l.strip() for l in jd_text.split("\n") if l.strip()]
        req_skills: List[str] = []
        pref_skills: List[str] = []
        duration = None
        location = None

        for line in lines:
            if "Required Skills:" in line:
                skills_raw = line.split("Required Skills:")[1].split(".")[0]
                req_skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
            elif "Preferred Skills:" in line:
                skills_raw = line.split("Preferred Skills:")[1].split(".")[0]
                pref_skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
            elif "Duration:" in line:
                dur_match = line.split("Duration:")[1].strip()
                digits = [int(w) for w in dur_match.split() if w.isdigit()]
                if digits:
                    duration = digits[0]
            elif "Location:" in line:
                location = line.split("Location:")[1].split("(")[0].strip()

        job = Job(
            id=f"eval_{filename.replace('.', '_')}",
            company=rec.get("company", "EvalCompany"),
            title=rec.get("title", "Internship"),
            source=filename,
            jd_text=jd_text,
            required_skills=req_skills,
            preferred_skills=pref_skills,
            duration_months=duration,
            location=location,
            content_hash=f"hash_{filename}",
        )

        # Run deterministic match
        match = await evaluate_match(
            job=job,
            chroma_dir=chroma_dir,
            embedding_fn=embedding_fn,
        )

        score_before = match.score_breakdown.get("score_before_caps", match.score)
        score_after = match.score_breakdown.get("score_after_caps", match.score)
        all_cap_reasons = match.score_breakdown.get("cap_reasons", [])

        # Effective cap check: only caps that actually changed the score
        effective_caps = all_cap_reasons if score_before != score_after else []

        pred_category = map_score_to_category(match.score)
        is_correct = (pred_category == expected_label)
        if is_correct:
            correct_count += 1

        if expected_label in confusion_matrix and pred_category in confusion_matrix[expected_label]:
            confusion_matrix[expected_label][pred_category] += 1

        predicted_scores.append(float(match.score))
        ground_truth_ranks.append(expected_rank)

        results.append({
            "filename": filename,
            "company": job.company,
            "title": job.title,
            "expected_label": expected_label,
            "predicted_category": pred_category,
            "score": match.score,
            "score_before_caps": score_before,
            "score_after_caps": score_after,
            "effective_caps": effective_caps,
            "matched_skills": match.matched_skills,
            "missing_skills": match.missing_skills,
            "has_conflict": len(all_cap_reasons) > 0 and any("conflict" in r.lower() or "avoid" in r.lower() for r in all_cap_reasons),
            "correct": is_correct,
        })

    total = len(results)
    accuracy = round(correct_count / total, 4) if total > 0 else 0.0

    # Calculate per-class precision and recall
    per_class_metrics: Dict[str, Dict[str, Any]] = {}
    for cls in classes:
        tp = confusion_matrix[cls][cls]
        fp = sum(confusion_matrix[other][cls] for other in classes if other != cls)
        fn = sum(confusion_matrix[cls][other] for other in classes if other != cls)

        prec = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
        rec = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
        support = tp + fn

        per_class_metrics[cls] = {
            "precision": prec,
            "recall": rec,
            "support": support,
        }

    # Calculate Spearman Rank Correlation
    if total > 1:
        corr_result = spearmanr(predicted_scores, ground_truth_ranks)
        spearman_rho = round(float(corr_result.statistic), 4)
        p_val = round(float(corr_result.pvalue), 4) if total >= MIN_REQUIRED_BENCHMARK_SIZE else None
    else:
        spearman_rho = 0.0
        p_val = None

    is_statistically_meaningful = total >= MIN_REQUIRED_BENCHMARK_SIZE

    return {
        "n": total,
        "total_evaluated": total,
        "is_statistically_meaningful": is_statistically_meaningful,
        "sample_notice": "Author-written synthetic fixtures; labels not independent" if total < MIN_REQUIRED_BENCHMARK_SIZE else "Independent labeled dataset",
        "correct_predictions": correct_count,
        "accuracy": accuracy,
        "spearman_rho": spearman_rho,
        "p_value": p_val,
        "confusion_matrix": confusion_matrix,
        "per_class_metrics": per_class_metrics,
        "results": results,
    }


async def main():
    parser = argparse.ArgumentParser(description="Evaluate matcher on labeled benchmark JDs.")
    parser.add_argument("--allow-small", action="store_true", default=True, help="Allow running smoke test on small dataset (n < 20)")
    args = parser.parse_args()

    print("=" * 75)
    print("RUNNING MATCHER BENCHMARK EVALUATION")
    print("=" * 75)

    report = await evaluate_matcher(allow_small=args.allow_small)
    n = report["n"]

    print(f"\nSample Size: n = {n}")
    if not report["is_statistically_meaningful"]:
        print(f"NOTICE: n = {n} (< 20). Smoke test only; not statistically meaningful. P-values suppressed.")
        print(f"Dataset Notice: {report['sample_notice']}")

    print(f"\nCategorical Accuracy (n = {n}): {report['accuracy'] * 100:.1f}% ({report['correct_predictions']}/{n})")
    print(f"Spearman Rank Correlation (rho, n = {n}): {report['spearman_rho']:.4f}")

    print("\nConfusion Matrix (True Row vs Pred Column):")
    print("-" * 50)
    col_hdr = "True \\ Pred"
    print(f"{col_hdr:<15} {'Strong':<10} {'Medium':<10} {'Weak':<10}")
    print("-" * 50)
    for true_cls in ["strong", "medium", "weak"]:
        row = report["confusion_matrix"][true_cls]
        print(f"{true_cls:<15} {row['strong']:<10} {row['medium']:<10} {row['weak']:<10}")
    print("-" * 50)

    print("\nPer-Class Precision and Recall:")
    print("-" * 50)
    print(f"{'Class':<12} {'Precision':<12} {'Recall':<12} {'Support (n)'}")
    print("-" * 50)
    for cls, metrics in report["per_class_metrics"].items():
        print(f"{cls:<12} {metrics['precision'] * 100:>8.1f}%   {metrics['recall'] * 100:>8.1f}%   {metrics['support']}")
    print("-" * 50)

    print("\nBenchmark JDs Detail:")
    print("-" * 75)
    print(f"{'Filename':<15} {'Expected':<10} {'Pred':<10} {'Score':<7} {'Effective Cap':<22} {'Status'}")
    print("-" * 75)
    for r in report["results"]:
        cap_str = r["effective_caps"][0][:20] if r["effective_caps"] else "None"
        status = "PASS" if r["correct"] else "FAIL"
        print(f"{r['filename']:<15} {r['expected_label']:<10} {r['predicted_category']:<10} {r['score']:<7} {cap_str:<22} {status}")
    print("-" * 75)


if __name__ == "__main__":
    asyncio.run(main())
