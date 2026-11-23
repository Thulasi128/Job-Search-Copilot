"""Matching agent computing deterministic candidate-job fit scores and LLM-written explanations."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from pydantic import BaseModel

from backend.config import get_settings
from backend.database import get_db
from backend.llm.client import LLMClient, get_llm_client
from backend.models.job import Job
from backend.models.logs import write_agent_log
from backend.models.match import Match
from backend.models.profile import Preferences, Profile
from backend.vector_store import query_profile_chunks

logger = logging.getLogger(__name__)

PROMPT_FILE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "match_reason.md"


class ReasoningOutput(BaseModel):
    """Schema for LLM-generated reasoning."""

    reasoning: str


def get_match_reason_prompt() -> str:
    """Read the match reasoning prompt template."""
    if not PROMPT_FILE_PATH.exists():
        raise FileNotFoundError(f"Match reason prompt template not found at {PROMPT_FILE_PATH}")
    return PROMPT_FILE_PATH.read_text(encoding="utf-8")


def compute_profile_hash(profile: Profile) -> str:
    """Compute deterministic SHA-256 hash of the profile for staleness detection."""
    summary = {
        "skills": sorted(profile.skills),
        "projects": [{"title": p.title, "tech": sorted(p.tech)} for p in profile.projects],
        "experience": [{"company": e.company, "role": e.role} for e in profile.experience],
    }
    encoded = json.dumps(summary, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_preferences_hash(preferences: Preferences) -> str:
    """Compute deterministic SHA-256 hash of preferences for staleness detection."""
    encoded = json.dumps(preferences.model_dump(), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_fallback_reasoning(
    score: int,
    matched_skills: List[str],
    missing_skills: List[str],
    conflicts: List[str],
) -> str:
    """Generate a clean deterministic templated reasoning if the LLM call fails."""
    matched_str = ", ".join(matched_skills) if matched_skills else "none"
    missing_str = ", ".join(missing_skills) if missing_skills else "none"
    conflict_str = "; ".join(conflicts) if conflicts else "no preference conflicts"
    return (
        f"The candidate achieved an overall fit score of {score}/100. "
        f"Demonstrated core skill matches include {matched_str}. "
        f"Key missing required areas: {missing_str}. "
        f"Identified preference alignment notes: {conflict_str}."
    )


async def evaluate_match(
    job: Job,
    llm_client: Optional[LLMClient] = None,
    chroma_dir: Optional[str] = None,
    embedding_fn: Optional[Any] = None,
) -> Match:
    """Evaluate candidate-job fit using deterministic scoring and LLM explanation.

    Scoring components:
      1. Required skill coverage (~50%): normalised required skills vs Profile skills.
         If 0 required skills listed, redistributes weight proportionally to semantic (60%) and preference (40%).
      2. Semantic similarity (~30%): Top 3 Chroma chunk calibrated cosine similarities.
      3. Preference fit (~20%): max duration, location mismatch, avoid skills, and emphasise bonus.

    Args:
        job: Stored Job document.
        llm_client: Optional LLMClient for testing.
        chroma_dir: Optional Chroma persist directory override.
        embedding_fn: Optional embedding function override for tests.

    Returns:
        Match: Evaluated match document with complete score breakdown.

    Raises:
        HTTPException: 409 if candidate profile does not exist.
    """
    settings = get_settings()
    db = get_db()

    # 1. Verify profile existence
    profile_doc = await db.profiles.find_one({"id": settings.DEFAULT_PROFILE_ID})
    if not profile_doc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No candidate profile exists yet. Please upload a resume before evaluating jobs.",
        )
    profile = Profile.model_validate(profile_doc)

    # 2. Load preferences
    pref_doc = await db.preferences.find_one({"id": "default_preferences"})
    preferences = Preferences.model_validate(pref_doc) if pref_doc else Preferences()

    profile_hash = compute_profile_hash(profile)
    preferences_hash = compute_preferences_hash(preferences)

    # ---------------------------------------------------------
    # Component 1: Required Skills Coverage (~50%)
    # ---------------------------------------------------------
    profile_skills_lower = {s.lower() for s in profile.skills}
    matched_skills = [s for s in job.required_skills if s.lower() in profile_skills_lower]
    missing_skills = [s for s in job.required_skills if s.lower() not in profile_skills_lower]

    has_required_skills = len(job.required_skills) > 0
    if has_required_skills:
        coverage_score = (len(matched_skills) / len(job.required_skills)) * 100.0
        w_req = settings.WEIGHT_REQUIRED_SKILLS
        w_sem = settings.WEIGHT_PROJECT_SEMANTIC
        w_pref = settings.WEIGHT_PREFERENCE_FIT
    else:
        coverage_score = 0.0
        w_req = 0.0
        denom = settings.WEIGHT_PROJECT_SEMANTIC + settings.WEIGHT_PREFERENCE_FIT
        w_sem = round(settings.WEIGHT_PROJECT_SEMANTIC / denom, 4)
        w_pref = round(settings.WEIGHT_PREFERENCE_FIT / denom, 4)

    # ---------------------------------------------------------
    # Component 2: Semantic Similarity (~30%)
    # ---------------------------------------------------------
    if has_required_skills:
        query_text = (
            f"Required Skills: {', '.join(job.required_skills)}. "
            f"Overview: {job.jd_text[:1000]}"
        )
        query_text_source = "required_skills_and_summary"
    else:
        query_text = job.jd_text[:1500]
        query_text_source = "jd_body_first_1500_chars"

    matched_chunks = await query_profile_chunks(
        query_text=query_text,
        top_k=3,
        persist_directory=chroma_dir,
        embedding_fn=embedding_fn,
    )

    if matched_chunks:
        raw_sim_avg = sum(c["raw_similarity"] for c in matched_chunks) / len(matched_chunks)
        calibrated_sim_avg = sum(c["calibrated_similarity"] for c in matched_chunks) / len(matched_chunks)
        semantic_score = calibrated_sim_avg * 100.0
    else:
        raw_sim_avg = 0.0
        calibrated_sim_avg = 0.0
        semantic_score = 0.0

    # ---------------------------------------------------------
    # Component 3: Preference Fit (~20%)
    # ---------------------------------------------------------
    preference_score = 100.0
    preference_conflicts: List[str] = []
    preference_penalties: List[Dict[str, Any]] = []

    # Duration Check (neutral if null)
    if job.duration_months is not None and job.duration_months > preferences.max_duration_months:
        penalty = 35.0
        preference_score -= penalty
        conflict_msg = (
            f"Duration of {job.duration_months} months exceeds preferred maximum "
            f"of {preferences.max_duration_months} months."
        )
        preference_conflicts.append(conflict_msg)
        preference_penalties.append({"type": "duration_exceeded", "penalty": penalty, "detail": conflict_msg})

    # Location Check (neutral if null)
    if job.location is not None:
        loc_lower = job.location.lower()
        is_job_remote = "remote" in loc_lower
        matches_preferred = any(p_loc.lower() in loc_lower for p_loc in preferences.preferred_locations)

        if not is_job_remote and not matches_preferred and not preferences.remote_ok:
            penalty = 35.0
            preference_score -= penalty
            conflict_msg = (
                f"Location '{job.location}' does not match preferred locations "
                f"{preferences.preferred_locations} and remote work is disabled."
            )
            preference_conflicts.append(conflict_msg)
            preference_penalties.append({"type": "location_mismatch", "penalty": penalty, "detail": conflict_msg})

    # Avoid Skills Check
    all_job_skills = {s.lower() for s in job.required_skills + job.preferred_skills}
    avoid_lower = {s.lower(): s for s in preferences.avoid_skills}
    for avoided_key, original_skill in avoid_lower.items():
        if avoided_key in all_job_skills:
            penalty = 30.0
            preference_score -= penalty
            conflict_msg = f"Job specifies avoided skill: {original_skill}."
            preference_conflicts.append(conflict_msg)
            preference_penalties.append({"type": "avoid_skill", "penalty": penalty, "skill": original_skill})

    # Emphasise Skills Bonus
    emphasise_lower = {s.lower(): s for s in preferences.emphasise_skills}
    for emph_key, original_skill in emphasise_lower.items():
        if emph_key in all_job_skills:
            bonus = 10.0
            preference_score += bonus
            preference_penalties.append({"type": "emphasise_bonus", "bonus": bonus, "skill": original_skill})

    preference_score = max(0.0, min(100.0, preference_score))

    # Overall Weighted Score (Deterministic)
    overall_numeric = round(
        w_req * coverage_score + w_sem * semantic_score + w_pref * preference_score
    )
    score_before_caps = max(0, min(100, overall_numeric))
    score_after_caps = score_before_caps
    cap_reasons: List[str] = []

    # 1. Coverage gate: if the JD has required skills and coverage < config min_coverage_gate (default 0.25),
    # cap the final score at prefs.min_score_to_consider - 1
    coverage_ratio = (len(matched_skills) / len(job.required_skills)) if has_required_skills else 1.0
    if has_required_skills and coverage_ratio < settings.MIN_COVERAGE_GATE:
        gate_cap = preferences.min_score_to_consider - 1
        if score_after_caps > gate_cap:
            score_after_caps = gate_cap
        cap_reasons.append(
            f"Coverage ({coverage_ratio:.1%}) is below minimum coverage gate ({settings.MIN_COVERAGE_GATE:.1%}); "
            f"capped at {gate_cap} (min_score_to_consider - 1)."
        )

    # 2. Conflict cap: if duration exceeds max_duration_months, or any avoid_skill appears in the JD's
    # required or preferred skills, cap the final score at prefs.min_score_to_tailor - 1
    has_duration_conflict = job.duration_months is not None and job.duration_months > preferences.max_duration_months
    conflicted_avoid_skills = [orig for key, orig in avoid_lower.items() if key in all_job_skills]

    if has_duration_conflict or conflicted_avoid_skills:
        conflict_cap = preferences.min_score_to_tailor - 1
        if score_after_caps > conflict_cap:
            score_after_caps = conflict_cap
        conflict_details = []
        if has_duration_conflict:
            conflict_details.append(f"duration {job.duration_months}m > max {preferences.max_duration_months}m")
        if conflicted_avoid_skills:
            conflict_details.append(f"avoided skills: {', '.join(conflicted_avoid_skills)}")
        cap_reasons.append(
            f"Preference conflict ({'; '.join(conflict_details)}); "
            f"capped at {conflict_cap} (min_score_to_tailor - 1)."
        )

    score_after_caps = max(0, min(100, score_after_caps))
    final_score = score_after_caps

    score_breakdown = {
        "coverage_score": round(coverage_score, 2),
        "semantic_score": round(semantic_score, 2),
        "preference_score": round(preference_score, 2),
        "raw_similarity": round(raw_sim_avg, 4),
        "calibrated_similarity": round(calibrated_sim_avg, 4),
        "weights_used": {
            "required_skills": w_req,
            "project_semantic": w_sem,
            "preference_fit": w_pref,
        },
        "query_text_source": query_text_source,
        "preference_penalties": preference_penalties,
        "score_before_caps": score_before_caps,
        "score_after_caps": score_after_caps,
        "cap_reasons": cap_reasons,
    }

    # ---------------------------------------------------------
    # Component 4: Reasoning Generation (LLM with Fallback)
    # ---------------------------------------------------------
    client = llm_client or get_llm_client()
    system_instruction = get_match_reason_prompt()

    facts_summary = {
        "score": final_score,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "preference_conflicts": preference_conflicts,
        "top_relevant_chunks": [c["document"][:200] for c in matched_chunks],
    }

    user_prompt = (
        "Explain the candidate-job fit score to the student based on these precomputed facts:\n\n"
        f"<evaluation_facts>\n{json.dumps(facts_summary, indent=2)}\n</evaluation_facts>"
    )

    reasoning_text = ""
    reasoning_fallback = False

    try:
        parsed_reason = await client.generate_json(
            prompt=user_prompt,
            schema=ReasoningOutput,
            system_instruction=system_instruction,
        )
        reasoning_text = parsed_reason.reasoning.strip()
    except Exception as first_exc:
        logger.warning("First attempt to generate reasoning failed: %s. Retrying once...", first_exc)
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"IMPORTANT: The previous output failed JSON validation: {str(first_exc)}. "
            "Please return valid JSON with a 'reasoning' string field containing 2 to 4 sentences."
        )
        try:
            parsed_reason = await client.generate_json(
                prompt=retry_prompt,
                schema=ReasoningOutput,
                system_instruction=system_instruction,
            )
            reasoning_text = parsed_reason.reasoning.strip()
        except Exception as retry_exc:
            logger.error("Reasoning retry also failed: %s. Using deterministic fallback.", retry_exc)
            reasoning_text = build_fallback_reasoning(
                score=final_score,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                conflicts=preference_conflicts,
            )
            reasoning_fallback = True

    match_result = Match(
        job_id=job.id,
        score=final_score,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        reasoning=reasoning_text,
        preference_conflicts=preference_conflicts,
        score_breakdown=score_breakdown,
        profile_hash=profile_hash,
        preferences_hash=preferences_hash,
        reasoning_fallback=reasoning_fallback,
    )

    await db.matches.replace_one({"job_id": job.id}, match_result.model_dump(), upsert=True)
    logger.info("Saved match result for job_id=%s with score=%d", job.id, final_score)

    await write_agent_log(
        agent_name="matching_agent",
        status="success",
        job_id=job.id,
        summary={
            "score": final_score,
            "coverage_score": score_breakdown["coverage_score"],
            "semantic_score": score_breakdown["semantic_score"],
            "preference_score": score_breakdown["preference_score"],
            "matched_skills_count": len(matched_skills),
            "missing_skills_count": len(missing_skills),
            "conflicts_count": len(preference_conflicts),
            "reasoning_fallback": reasoning_fallback,
        },
    )

    return match_result

