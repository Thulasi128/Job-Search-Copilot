"""Comprehensive Two-Layer Verifier Benchmark.

Evaluates hallucination detection across:
1. 12 injection types x 3 base drafts = 36 adversarial test cases:
   - fake_skill
   - inflated_number
   - fake_employer
   - inflated_verb
   - fake_degree
   - fake_project
   - missing_skill_as_possessed
   - extended_duration
   - fabricated_outcome_no_number
   - expert_level_claim
   - plausible_unlisted_tool
   - claim_true_for_jd_not_candidate
2. 20 clean drafts (legitimately reworded and reordered) for false-positive rate measurement.
3. Catch rate per type for Layer 1 (deterministic) alone and Layer 1 + Layer 2 (LLM).
"""

import asyncio
import copy
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.verifier_agent import (
    run_layer_1_deterministic_check,
    verify_drafts,
)
from backend.models.draft import (
    ClaimCheck,
    CoverNote,
    ProjectBullets,
    TailoredResume,
    VerificationResult,
)
from backend.models.job import Job
from backend.models.match import Match
from backend.models.profile import Profile
from scripts.real_similarity_check import get_synthetic_profile

logger = logging.getLogger(__name__)


def build_base_drafts(job: Job, profile: Profile) -> List[Tuple[TailoredResume, CoverNote, Match]]:
    """Build 3 distinct verified clean base drafts for candidate Alex Chen."""
    # Base Draft 1: Backend microservices focus
    d1_tailored = TailoredResume(
        job_id=job.id,
        skills_section=["Python", "FastAPI", "Docker", "SQL", "Git"],
        project_bullets=[
            ProjectBullets(
                project_title="TaskStreamer — Real-Time Collaboration Workspace",
                bullets=[
                    "Architected scalable MongoDB aggregation pipelines improving dashboard load latency by 35%.",
                    "Developed collaboration features supporting concurrent WebSocket editing for over 500 active users.",
                ],
            ),
            ProjectBullets(
                project_title="DataPipeline CLI — Distributed Ingestion Framework",
                bullets=[
                    "Containerized worker microservices with Docker Compose for consistent staging environments.",
                    "Built a concurrent stream processing engine ingesting 100,000 JSON records daily into PostgreSQL.",
                ],
            ),
        ],
    )
    d1_note = CoverNote(
        job_id=job.id,
        text=(
            f"Dear Hiring Team at {job.company},\n\n"
            f"I am writing to express my strong interest in the {job.title} position in Austin, TX. "
            "As a Computer Science student at State University of Technology with a 3.85 GPA, I have developed "
            "a solid foundation in backend systems development. Through my TaskStreamer project, I gained practical "
            "experience building REST APIs and handling WebSocket connections for over 500 active users, while optimizing "
            "database latency by 35%. In addition, developing the DataPipeline CLI framework allowed me to containerize "
            "microservices using Docker and ingest 100,000 records daily into PostgreSQL. My proficiency in Python, FastAPI, "
            "and relational databases allows me to contribute meaningfully to your backend infrastructure from day one. "
            "Thank you for your time and consideration, and I look forward to discussing how my experience fits your team.\n\n"
            "Sincerely,\nAlex Chen"
        ),
        word_count=138,
    )
    d1_match = Match(
        job_id=job.id, score=92, matched_skills=["Python", "FastAPI", "Docker"], missing_skills=["Go"],
        reasoning="Good backend fit.", profile_hash="p1", preferences_hash="pr1",
    )

    # Base Draft 2: Data engineering & pipeline focus
    d2_tailored = TailoredResume(
        job_id=job.id,
        skills_section=["Python", "SQL", "Docker", "Linux", "Git"],
        project_bullets=[
            ProjectBullets(
                project_title="DataPipeline CLI — Distributed Ingestion Framework",
                bullets=[
                    "Built a concurrent event stream processing engine ingesting 100,000 JSON records daily into PostgreSQL.",
                    "Containerized worker microservices with Docker Compose for consistent local development and staging environments.",
                ],
            ),
        ],
    )
    d2_note = CoverNote(
        job_id=job.id,
        text=(
            f"Dear Engineering Manager at {job.company},\n\n"
            f"I am enthusiastic about applying for the {job.title} role. As a senior Computer Science "
            "undergraduate at State University of Technology maintaining a 3.85 GPA, I focus on distributed data "
            "pipelines and scalable backend services. Developing the DataPipeline CLI project gave me direct experience "
            "orchestrating event streams that processed 100,000 JSON records daily into PostgreSQL, using asynchronous "
            "concurrency to eliminate data bottlenecks. Furthermore, I containerized deployment modules with Docker Compose "
            "to ensure staging parity. With strong competencies in Python, SQL, and container technologies, I am eager "
            "to support your engineering deliverables and build reliable software. Thank you for considering my application, "
            "and I welcome the opportunity to discuss my qualifications.\n\n"
            "Best regards,\nAlex Chen"
        ),
        word_count=128,
    )
    d2_match = Match(
        job_id=job.id, score=88, matched_skills=["Python", "Docker", "SQL"], missing_skills=["Spark"],
        reasoning="Solid data pipeline foundation.", profile_hash="p2", preferences_hash="pr2",
    )

    # Base Draft 3: Full-stack web focus
    d3_tailored = TailoredResume(
        job_id=job.id,
        skills_section=["Python", "React", "FastAPI", "Git"],
        project_bullets=[
            ProjectBullets(
                project_title="TaskStreamer — Real-Time Collaboration Workspace",
                bullets=[
                    "Developed an open-source collaboration board supporting concurrent WebSocket editing for over 500 active users.",
                    "Architected scalable MongoDB aggregation pipelines improving dashboard load latency by 35%.",
                    "Implemented automated integration suites in GitHub Actions achieving 92% code coverage.",
                ],
            ),
        ],
    )
    d3_note = CoverNote(
        job_id=job.id,
        text=(
            f"Dear Technical Recruiter at {job.company},\n\n"
            f"I am writing to apply for the {job.title} position in Austin, TX. Currently completing my "
            "Computer Science degree at State University of Technology with a 3.85 GPA, I specialize in full-stack "
            "application engineering. On the TaskStreamer project, I implemented interactive dashboards and WebSocket "
            "synchronization serving over 500 active users, while optimizing MongoDB queries to reduce dashboard latency "
            "by 35%. I also established CI/CD automated testing workflows with GitHub Actions that achieved 92% code coverage. "
            "My experience connecting Python backend endpoints with modern React client interfaces enables me to support "
            "cross-functional engineering tasks efficiently. Thank you for reviewing my application, and I look forward to "
            "the possibility of an interview.\n\n"
            "Sincerely,\nAlex Chen"
        ),
        word_count=132,
    )
    d3_match = Match(
        job_id=job.id, score=95, matched_skills=["Python", "React", "FastAPI"], missing_skills=[],
        reasoning="Excellent web full-stack match.", profile_hash="p3", preferences_hash="pr3",
    )

    return [(d1_tailored, d1_note, d1_match), (d2_tailored, d2_note, d2_match), (d3_tailored, d3_note, d3_match)]


class PerturbationSuite:
    """Implements 12 distinct hallucination and inflation injections."""

    @staticmethod
    def apply_injection(
        injection_type: str,
        tailored: TailoredResume,
        note: CoverNote,
        match: Match,
        job: Job,
    ) -> Tuple[TailoredResume, CoverNote, Match, str]:
        """Apply a specific perturbation to a base draft."""
        t = copy.deepcopy(tailored)
        n = copy.deepcopy(note)
        m = copy.deepcopy(match)

        if injection_type == "fake_skill":
            t.skills_section.append("COBOL")
            desc = "Injected unearned skill: COBOL"

        elif injection_type == "inflated_number":
            # Inflate 500 users to 5,000,000 users or 100,000 to 50,000,000
            n.text = n.text.replace("500", "5,000,000").replace("100,000", "50,000,000")
            for p in t.project_bullets:
                p.bullets = [b.replace("500", "5,000,000").replace("100,000", "50,000,000") for b in p.bullets]
            n.word_count = len(n.text.split())
            desc = "Inflated user/record counts to 5,000,000+"

        elif injection_type == "fake_employer":
            n.text = n.text.replace("Through my work", "As a Senior Software Engineer at Netflix, through my work")
            n.word_count = len(n.text.split())
            desc = "Fabricated previous employer: Netflix"

        elif injection_type == "inflated_verb":
            # Exaggerated leadership verbs on student project
            for p in t.project_bullets:
                p.bullets[0] = "Directed enterprise-wide organizational architecture and managed 50 senior engineers."
            desc = "Inflated leadership verb ('Directed enterprise-wide architecture')"

        elif injection_type == "fake_degree":
            n.text = n.text.replace("Computer Science student", "Ph.D. Graduate in Quantum Machine Learning")
            n.word_count = len(n.text.split())
            desc = "Fabricated academic degree (Ph.D. in Quantum ML)"

        elif injection_type == "fake_project":
            t.project_bullets.append(
                ProjectBullets(
                    project_title="Autonomous Satellite Navigation Logic",
                    bullets=["Programmed real-time trajectory guidance algorithms in Ada."],
                )
            )
            desc = "Fabricated project: Autonomous Satellite Navigation Logic"

        elif injection_type == "missing_skill_as_possessed":
            m.missing_skills = ["Kubernetes"]
            t.skills_section.append("Kubernetes")
            desc = "Claimed identified missing skill (Kubernetes) in skills section"

        elif injection_type == "extended_duration":
            n.text = n.text.replace("As a Computer Science student", "With over 8 years of professional software experience")
            n.word_count = len(n.text.split())
            desc = "Extended duration claim (8 years experience for student)"

        elif injection_type == "fabricated_outcome_no_number":
            for p in t.project_bullets:
                p.bullets.append("Directly secured Series A venture capital funding and generated multi-million dollar enterprise contracts.")
            desc = "Fabricated business revenue/funding outcome without numbers"

        elif injection_type == "expert_level_claim":
            n.text = n.text.replace("developed a solid foundation", "am recognized as a world-class authority and industry expert")
            n.word_count = len(n.text.split())
            desc = "Unearned expert claim ('world-class authority and industry expert')"

        elif injection_type == "plausible_unlisted_tool":
            t.skills_section.append("MySQL")
            for p in t.project_bullets:
                p.bullets = [b.replace("PostgreSQL", "MySQL") for b in p.bullets]
            desc = "Plausible unlisted technical tool (MySQL substituted for PostgreSQL)"

        elif injection_type == "claim_true_for_jd_not_candidate":
            for p in t.project_bullets:
                p.bullets.append("Administered high-availability Apache Cassandra clusters for real-time mission-critical telemetry.")
            desc = "Claim true for JD role requirements but unearned by candidate (Cassandra)"

        else:
            raise ValueError(f"Unknown injection type: {injection_type}")

        return t, n, m, desc


# Alias for backward compatibility with test_eval.py
PerturbationEngine = PerturbationSuite


def generate_clean_draft_variations(job: Job, profile: Profile, n_count: int = 20) -> List[Dict[str, Any]]:
    """Generate 20 distinct legitimate clean drafts to test false positive rate."""
    base_skills = [
        ["Python", "FastAPI", "React", "Docker", "SQL", "Git"],
        ["Python", "Docker", "SQL", "Git", "PostgreSQL"],
        ["FastAPI", "Python", "React", "SQL"],
        ["Python", "React", "Git", "Docker", "PostgreSQL"],
    ]

    clean_test_cases = []
    base_drafts = build_base_drafts(job, profile)

    for i in range(n_count):
        base_idx = i % len(base_drafts)
        base_t, base_n, base_m = base_drafts[base_idx]

        t = copy.deepcopy(base_t)
        n = copy.deepcopy(base_n)
        m = copy.deepcopy(base_m)

        # Vary skills order legitimately (all genuine profile skills)
        skill_set = base_skills[i % len(base_skills)]
        t.skills_section = skill_set

        # Vary word phrasing slightly while staying strictly within profile facts & word count [120, 180]
        if i % 2 == 1:
            n.text = n.text.replace("I am writing to express my strong interest", "I am delighted to express my enthusiastic interest")
        if i % 3 == 0:
            n.text = n.text.replace("solid foundation", "rigorous foundation")

        n.word_count = len(n.text.split())

        clean_test_cases.append({
            "id": f"CLEAN_CONTROL_{i+1:02d}",
            "description": f"Legitimate clean reordering variation #{i+1}",
            "tailored": t,
            "cover_note": n,
            "match": m,
        })

    return clean_test_cases


async def evaluate_verifier(
    profile: Optional[Profile] = None,
    job: Optional[Job] = None,
    llm_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run comprehensive verifier evaluation across 36 adversarial cases and 20 clean controls."""
    candidate_profile = profile or get_synthetic_profile()
    target_job = job or Job(
        id="eval_job_verifier",
        company="TechCorp Innovations",
        title="Software Engineering Intern",
        source="pasted",
        jd_text="Software Engineering Intern needed in Austin, TX for 3 months. Python, FastAPI, React.",
        required_skills=["Python", "FastAPI", "React"],
        content_hash="eval_hash",
    )

    base_drafts = build_base_drafts(target_job, candidate_profile)

    injection_types = [
        "fake_skill",
        "inflated_number",
        "fake_employer",
        "inflated_verb",
        "fake_degree",
        "fake_project",
        "missing_skill_as_possessed",
        "extended_duration",
        "fabricated_outcome_no_number",
        "expert_level_claim",
        "plausible_unlisted_tool",
        "claim_true_for_jd_not_candidate",
    ]

    adversarial_cases: List[Dict[str, Any]] = []

    # Generate 12 injection types x 3 base drafts = 36 test cases
    case_num = 1
    for inj in injection_types:
        for b_idx, (b_t, b_n, b_m) in enumerate(base_drafts):
            t_mut, n_mut, m_mut, desc = PerturbationSuite.apply_injection(inj, b_t, b_n, b_m, target_job)
            adversarial_cases.append({
                "id": f"ADV_{case_num:02d}_{inj[:10]}",
                "injection_type": inj,
                "base_draft_id": b_idx + 1,
                "description": desc,
                "tailored": t_mut,
                "cover_note": n_mut,
                "match": m_mut,
            })
            case_num += 1

    clean_cases = generate_clean_draft_variations(target_job, candidate_profile, n_count=20)

    # 1. Evaluate Layer 1 on Adversarial Cases
    l1_caught_per_type: Dict[str, int] = {inj: 0 for inj in injection_types}
    l1_adversarial_caught = 0
    adv_results = []

    for c in adversarial_cases:
        unsupported = run_layer_1_deterministic_check(
            profile=candidate_profile,
            job=target_job,
            match=c["match"],
            tailored_resume=c["tailored"],
            cover_note=c["cover_note"],
        )
        caught_l1 = len(unsupported) > 0
        if caught_l1:
            l1_adversarial_caught += 1
            l1_caught_per_type[c["injection_type"]] += 1

        adv_results.append({
            "id": c["id"],
            "injection_type": c["injection_type"],
            "base_draft_id": c["base_draft_id"],
            "description": c["description"],
            "caught_by_l1": caught_l1,
            "l1_unsupported_count": len(unsupported),
            "sample_l1_claim": unsupported[0].claim if unsupported else None,
        })

    # 2. Evaluate Layer 1 on 20 Clean Controls
    clean_passed = 0
    clean_results = []
    for cl in clean_cases:
        unsupported = run_layer_1_deterministic_check(
            profile=candidate_profile,
            job=target_job,
            match=cl["match"],
            tailored_resume=cl["tailored"],
            cover_note=cl["cover_note"],
        )
        passed = len(unsupported) == 0
        if passed:
            clean_passed += 1
        clean_results.append({
            "id": cl["id"],
            "passed": passed,
            "unsupported_count": len(unsupported),
            "sample_false_positive": unsupported[0].claim if unsupported else None,
        })

    total_adv = len(adversarial_cases)
    total_clean = len(clean_cases)

    l1_catch_rate = round(l1_adversarial_caught / total_adv, 4) if total_adv > 0 else 0.0
    false_positive_rate = round((total_clean - clean_passed) / total_clean, 4) if total_clean > 0 else 0.0

    # Per-type catch rates
    type_breakdown = {}
    for inj in injection_types:
        caught_count = l1_caught_per_type[inj]
        type_breakdown[inj] = {
            "tested": 3,
            "caught_l1": caught_count,
            "catch_rate_l1": round(caught_count / 3, 2),
            "layer_1_status": "FULL_CATCH" if caught_count == 3 else ("PARTIAL" if caught_count > 0 else "MISSED_BY_L1"),
        }

    return {
        "adversarial_total": total_adv,
        "adversarial_cases_tested": total_adv,
        "adversarial_caught_l1": l1_adversarial_caught,
        "adversarial_cases_caught": l1_adversarial_caught,
        "layer_1_adversarial_caught": l1_adversarial_caught,
        "l1_overall_catch_rate": l1_catch_rate,
        "layer_1_catch_rate": l1_catch_rate,
        "catch_rate": l1_catch_rate,
        "clean_total": total_clean,
        "clean_drafts_tested": total_clean,
        "clean_controls_tested": total_clean,
        "clean_passed": clean_passed,
        "clean_controls_passed": clean_passed,
        "false_positive_rate": false_positive_rate,
        "total_test_cases": total_adv + total_clean,
        "layer_1_catches": l1_adversarial_caught,
        "layer_2_catches": 0,
        "type_breakdown": type_breakdown,
        "layer_2_status": "NOT VERIFIED (Live LLM key not available)",
        "adv_results": adv_results,
        "clean_results": clean_results,
        "results": adv_results + clean_results,
    }


async def main():
    print("=" * 75)
    print("COMPREHENSIVE TWO-LAYER VERIFIER EVALUATION")
    print("=" * 75)

    report = await evaluate_verifier()
    print(f"\nAdversarial Test Cases (12 types x 3 base drafts): n = {report['adversarial_total']}")
    print(f"Layer 1 Overall Catch Rate: {report['l1_overall_catch_rate'] * 100:.1f}% ({report['adversarial_caught_l1']}/{report['adversarial_total']})")
    print(f"Layer 2 Status: {report['layer_2_status']}")

    print(f"\nClean Negative Controls Tested: n = {report['clean_total']}")
    print(f"False Positive Rate: {report['false_positive_rate'] * 100:.1f}% ({report['clean_total'] - report['clean_passed']}/{report['clean_total']})")

    print("\nLayer 1 Catch Rate by Injection Category (n = 3 each):")
    print("-" * 75)
    print(f"{'Injection Category':<35} {'Tested':<8} {'Caught L1':<12} {'Rate':<8} {'Status'}")
    print("-" * 75)
    for inj, b in report["type_breakdown"].items():
        print(f"{inj:<35} {b['tested']:<8} {b['caught_l1']:<12} {b['catch_rate_l1']*100:>5.1f}%  {b['layer_1_status']}")
    print("-" * 75)

    misses = [r for r in report["adv_results"] if not r["caught_by_l1"]]
    if misses:
        print(f"\nAdversarial Cases Missed by Layer 1 Alone (Deferred to Layer 2 LLM): {len(misses)}")
        for m in misses:
            print(f" - [{m['injection_type']}] {m['id']}: {m['description']}")


if __name__ == "__main__":
    asyncio.run(main())
