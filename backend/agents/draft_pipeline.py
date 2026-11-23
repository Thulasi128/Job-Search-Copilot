"""Drafting pipeline coordinating tailoring, cover note generation, and verifier retry loops."""

import logging
import time
from typing import List, Optional

from backend.agents.cover_note_agent import generate_cover_note
from backend.agents.matching_agent import compute_profile_hash
from backend.agents.tailor_agent import tailor_resume
from backend.agents.verifier_agent import verify_drafts
from backend.database import get_db
from backend.llm.client import LLMClient, get_llm_client
from backend.models.draft import DraftDocument, VerificationResult
from backend.models.job import Job
from backend.models.logs import write_agent_log
from backend.models.match import Match
from backend.models.profile import Preferences, Profile

logger = logging.getLogger(__name__)
MAX_RETRIES = 2  # Up to 3 total attempts (attempt 1 + 2 retries)


async def run_draft_pipeline(
    profile: Profile,
    job: Job,
    match: Match,
    preferences: Preferences,
    llm_client: Optional[LLMClient] = None,
) -> DraftDocument:
    """Coordinate the draft preparation loop: tailor -> cover note -> verify -> retry on failure.

    Args:
        profile: Candidate profile facts.
        job: Targeted job posting.
        match: Evaluated match record.
        preferences: Candidate preferences.
        llm_client: Optional LLMClient override.

    Returns:
        DraftDocument: The final draft document (status='verified_ready' if passed,
            or 'failed_verification' if all retries exhausted).
    """
    client = llm_client or get_llm_client()
    db = get_db()
    profile_hash = compute_profile_hash(profile)

    start_time = time.perf_counter()
    feedback_claims: List[str] = []
    last_draft_doc: Optional[DraftDocument] = None

    for attempt in range(1, MAX_RETRIES + 2):
        logger.info(
            "Running draft pipeline iteration %d for job_id=%s (company=%s)",
            attempt,
            job.id,
            job.company,
        )

        # 1. Tailor Resume (Skills + Project Bullets)
        tailored_resume = await tailor_resume(
            profile=profile,
            job=job,
            match=match,
            preferences=preferences,
            feedback_claims=feedback_claims if feedback_claims else None,
            llm_client=client,
            version=attempt,
        )

        # 2. Generate Cover Note
        cover_note = await generate_cover_note(
            profile=profile,
            job=job,
            match=match,
            preferences=preferences,
            feedback_claims=feedback_claims if feedback_claims else None,
            llm_client=client,
            version=attempt,
        )

        # 3. Two-Layer Verification
        verification = await verify_drafts(
            profile=profile,
            job=job,
            match=match,
            tailored_resume=tailored_resume,
            cover_note=cover_note,
            llm_client=client,
        )

        current_status = "verified_ready" if verification.passed else "failed_verification"
        last_draft_doc = DraftDocument(
            job_id=job.id,
            version=attempt,
            profile_hash=profile_hash,
            tailored_resume=tailored_resume,
            cover_note=cover_note,
            verification_result=verification,
            status=current_status,
        )

        if verification.passed:
            duration = time.perf_counter() - start_time
            logger.info("Draft passed verification on attempt %d for job_id=%s", attempt, job.id)

            # Persist to MongoDB drafts collection
            await db.drafts.replace_one(
                {"job_id": job.id},
                last_draft_doc.model_dump(),
                upsert=True,
            )

            # Write summary-only agent log
            await write_agent_log(
                agent_name="draft_pipeline",
                status="success",
                summary={
                    "action": "generate_and_verify_draft",
                    "duration_seconds": round(duration, 3),
                    "version": attempt,
                    "retries": attempt - 1,
                    "skills_count": len(tailored_resume.skills_section),
                    "projects_count": len(tailored_resume.project_bullets),
                    "cover_note_word_count": cover_note.word_count,
                    "passed": True,
                },
                job_id=job.id,
            )
            return last_draft_doc

        # Accumulate feedback for next attempt
        new_feedback = [
            f"[{c.layer}] {c.claim}: {c.reason}" for c in verification.unsupported_claims
        ]
        feedback_claims.extend(new_feedback)
        logger.warning(
            "Draft iteration %d failed verification with %d unsupported claims: %s",
            attempt,
            len(verification.unsupported_claims),
            [c.claim for c in verification.unsupported_claims],
        )

    # All retries exhausted without passing verification
    duration = time.perf_counter() - start_time
    logger.error("Draft pipeline failed verification after %d attempts for job_id=%s", MAX_RETRIES + 1, job.id)

    # Persist the failed draft document for inspection/manual edit
    assert last_draft_doc is not None
    await db.drafts.replace_one(
        {"job_id": job.id},
        last_draft_doc.model_dump(),
        upsert=True,
    )

    # Write summary-only agent log
    await write_agent_log(
        agent_name="draft_pipeline",
        status="failure",
        summary={
            "action": "generate_and_verify_draft",
            "duration_seconds": round(duration, 3),
            "error": f"Failed verification after {MAX_RETRIES + 1} attempts.",
            "version": last_draft_doc.version,
            "retries": MAX_RETRIES,
            "unsupported_claims_count": len(last_draft_doc.verification_result.unsupported_claims),
            "passed": False,
        },
        job_id=job.id,
    )

    return last_draft_doc
