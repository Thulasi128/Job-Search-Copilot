"""FastAPI routes for job intake, matching evaluation, workflow execution, decisions, and status lifecycle."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.agents.intake_agent import process_job_intake
from backend.agents.matching_agent import evaluate_match
from backend.agents.verifier_agent import verify_drafts
from backend.config import get_settings
from backend.database import get_db
from backend.models.draft import CoverNote, DraftDocument, ProjectBullets, TailoredResume
from backend.models.job import (
    ALLOWED_TRANSITIONS,
    MANUAL_STATUSES,
    DecisionAction,
    DraftEdits,
    InterruptType,
    Job,
    JobCreateRequest,
    JobDecisionRequest,
    JobDetailResponse,
    JobListItem,
    JobStatus,
    JobStatusPatchRequest,
)
from backend.models.logs import write_agent_log
from backend.models.match import Match
from backend.models.profile import Preferences, Profile
from backend.workflow.concurrency import is_job_running
from backend.workflow.runner import get_job_interrupt, run_workflow_background
from backend.workflow.transitions import (
    ApprovalInvariantError,
    InvalidTransitionError,
    transition_job_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs & Workflow"])


class JobActionResponse(BaseModel):
    """Response returned when initiating background workflow actions."""

    job_id: str
    status: JobStatus


@router.post("", response_model=JobActionResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_and_evaluate_job(request: JobCreateRequest) -> JobActionResponse:
    """Ingest a job posting and launch matching and tailoring workflow in background.

    Validates:
      - A candidate profile must exist in MongoDB (409 if missing).
      - Exactly one of 'jd_text' or 'url' must be provided (422 if invalid).
      - Deduplicates by JD text hash.
      - If duplicate exists and is active/paused, returns existing job without starting duplicate run.
      - Starts LangGraph workflow in background task and returns 202 Accepted.

    Args:
        request: JobCreateRequest with jd_text or url.

    Returns:
        JobActionResponse: Job ID and initial processing status.
    """
    settings = get_settings()
    db = get_db()

    # Verify that a candidate profile exists
    profile_doc = await db.profiles.find_one({"id": settings.DEFAULT_PROFILE_ID})
    if not profile_doc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No candidate profile found. Please upload your resume first before adding jobs.",
        )

    # Step 1: Intake (deduplicates by JD text hash)
    job = await process_job_intake(jd_text=request.jd_text, url=request.url)

    # Step 2: Check if job is currently active or paused in workflow
    active_statuses = {
        JobStatus.PROCESSING,
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.DRAFTING,
        JobStatus.AWAITING_APPROVAL,
        JobStatus.AWAITING_MANUAL_EDIT,
    }
    if job.status in active_statuses or is_job_running(job.id):
        logger.info("Job %s is already active or in progress, returning existing status.", job.id)
        return JobActionResponse(job_id=job.id, status=job.status)

    # Step 3: Transition to processing and launch background workflow
    await db.jobs.update_one(
        {"id": job.id},
        {"$set": {"status": JobStatus.PROCESSING.value, "error_message": None}},
    )

    asyncio.create_task(run_workflow_background(job_id=job.id, run_number=job.run_number))
    return JobActionResponse(job_id=job.id, status=JobStatus.PROCESSING)


@router.get("", response_model=List[JobListItem], status_code=status.HTTP_200_OK)
async def list_jobs() -> List[JobListItem]:
    """List all ingested jobs with current match scores and lifecycle statuses."""
    db = get_db()
    jobs_cursor = db.jobs.find().sort("created_at", -1)
    jobs_list = await jobs_cursor.to_list(length=500)

    items: List[JobListItem] = []
    for j_doc in jobs_list:
        job = Job.model_validate(j_doc)
        match_doc = await db.matches.find_one({"job_id": job.id})
        score = match_doc.get("score") if match_doc else None

        items.append(
            JobListItem(
                id=job.id,
                company=job.company or "Unknown",
                title=job.title or "Unknown",
                source=job.source,
                score=score,
                status=job.status,
                created_at=job.created_at,
            )
        )

    return items


@router.get("/{job_id}", response_model=JobDetailResponse, status_code=status.HTTP_200_OK)
async def get_job_detail(job_id: str) -> JobDetailResponse:
    """Retrieve full details of a job. Strictly read-only; never runs or advances the graph.

    Returns:
        JobDetailResponse: Job fields, pending interrupt, error message, allowed next statuses,
            latest match, and latest draft with verification results.
    """
    db = get_db()
    job_doc = await db.jobs.find_one({"id": job_id})
    if not job_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found.",
        )
    job = Job.model_validate(job_doc)

    # Read pending interrupt from checkpoint
    pending_interrupt = await get_job_interrupt(job.id, job.run_number)

    # Allowed transitions
    allowed_next = list(ALLOWED_TRANSITIONS.get(job.status, set()))

    # Read latest match and draft
    match_doc = await db.matches.find_one({"job_id": job_id}, {"_id": 0})
    draft_doc = await db.drafts.find_one({"job_id": job_id}, {"_id": 0}, sort=[("created_at", -1)])

    return JobDetailResponse(
        id=job.id,
        company=job.company,
        title=job.title,
        source=job.source,
        jd_text=job.jd_text,
        required_skills=job.required_skills,
        preferred_skills=job.preferred_skills,
        duration_months=job.duration_months,
        location=job.location,
        status=job.status,
        content_hash=job.content_hash,
        run_number=job.run_number,
        created_at=job.created_at,
        pending_interrupt=pending_interrupt,
        error=job.error_message,
        allowed_next_statuses=allowed_next,
        match=match_doc,
        draft=draft_doc,
    )


@router.post("/{job_id}/decision", status_code=status.HTTP_200_OK)
async def submit_decision(job_id: str, request: JobDecisionRequest) -> Any:
    """Submit a human decision for a paused workflow interrupt checkpoint.

    - Validates action against the pending interrupt type.
    - If edits are provided (submit_edits or edit): executes server-side verification before resume.
    - If unverified claims exist and acknowledge_warnings is False, returns 422 with warnings.
    - If acknowledge_warnings is True, records user override and updates draft.
    - Terminal decisions (skip, reject, abandon) return 200 OK.
    - Resuming decisions (proceed, approve, submit_edits, edit) return 202 Accepted and run in background.
    """
    db = get_db()
    settings = get_settings()

    job_doc = await db.jobs.find_one({"id": job_id})
    if not job_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found.",
        )
    job = Job.model_validate(job_doc)

    if is_job_running(job_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is currently executing in background.",
        )

    pending_interrupt = await get_job_interrupt(job.id, job.run_number)
    if not pending_interrupt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' has no pending decision checkpoint.",
        )

    int_type = pending_interrupt.get("type")
    action = request.action

    # Validate action vs interrupt type
    if int_type == InterruptType.CONFIRM_TAILORING.value:
        if action not in {DecisionAction.PROCEED, DecisionAction.SKIP}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Action '{action.value}' is not valid for interrupt '{int_type}'. Expected proceed or skip.",
            )
    elif int_type == InterruptType.APPROVAL.value:
        if action not in {DecisionAction.APPROVE, DecisionAction.REJECT, DecisionAction.EDIT}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Action '{action.value}' is not valid for interrupt '{int_type}'. Expected approve, reject, or edit.",
            )
    elif int_type == InterruptType.MANUAL_EDIT_REQUIRED.value:
        if action not in {DecisionAction.SUBMIT_EDITS, DecisionAction.ABANDON}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Action '{action.value}' is not valid for interrupt '{int_type}'. Expected submit_edits or abandon.",
            )

    # Handle edits validation and verification if edits are submitted
    if request.edits is not None or action == DecisionAction.SUBMIT_EDITS:
        edits = request.edits or DraftEdits()
        profile_doc = await db.profiles.find_one({"id": settings.DEFAULT_PROFILE_ID})
        profile = Profile.model_validate(profile_doc)
        match_doc = await db.matches.find_one({"job_id": job_id})
        match = Match.model_validate(match_doc) if match_doc else await evaluate_match(job=job)

        # Build TailoredResume and CoverNote from edits
        existing_draft_doc = await db.drafts.find_one({"job_id": job_id}, sort=[("created_at", -1)])
        existing_bullets = []
        if existing_draft_doc and "tailored_resume" in existing_draft_doc:
            existing_bullets = [
                ProjectBullets(**pb)
                for pb in existing_draft_doc["tailored_resume"].get("project_bullets", [])
            ]

        # Adapt project_bullets from edits
        if edits.project_bullets and isinstance(edits.project_bullets[0], str):
            # Simple strings wrapped in single project bullet block
            proj_title = existing_bullets[0].project_title if existing_bullets else "Key Project"
            adapted_bullets = [ProjectBullets(project_title=proj_title, bullets=edits.project_bullets)]
        elif edits.project_bullets:
            adapted_bullets = edits.project_bullets
        else:
            adapted_bullets = existing_bullets

        proposed_tailored = TailoredResume(
            job_id=job.id,
            skills_section=edits.skills_section,
            project_bullets=adapted_bullets,
            version=job.run_number,
        )
        proposed_cover_note = CoverNote(
            job_id=job.id,
            text=edits.cover_note,
            word_count=len(edits.cover_note.split()),
            version=job.run_number,
        )

        try:
            verification = await verify_drafts(
                profile=profile,
                job=job,
                match=match,
                tailored_resume=proposed_tailored,
                cover_note=proposed_cover_note,
            )
        except Exception as exc:
            logger.error("Verifier LLM service error during edit validation: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Verifier LLM service unavailable: {str(exc)}",
            )

        # Check for service down failure
        for claim in verification.unsupported_claims:
            if "Verifier LLM service failed to validate claims" in claim.reason:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Verifier LLM service unavailable while verifying edits.",
                )

        unsupported = verification.unsupported_claims
        if unsupported and not request.acknowledge_warnings:
            # Reject resume; keep workflow paused
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "needs_acknowledgement",
                    "warnings": [c.model_dump() for c in unsupported],
                },
            )

        # Update draft document in MongoDB
        user_override = bool(unsupported and request.acknowledge_warnings)
        if user_override:
            await write_agent_log(
                agent_name="verifier_agent",
                status="success",
                summary={
                    "action": "user_override",
                    "unsupported_count": len(unsupported),
                    "job_id": job.id,
                },
                job_id=job.id,
            )

        updated_draft_doc = DraftDocument(
            job_id=job.id,
            version=job.run_number,
            profile_hash=profile_doc.get("content_hash", ""),
            tailored_resume=proposed_tailored,
            cover_note=proposed_cover_note,
            verification_result=verification,
            status="verified_ready" if (verification.passed or user_override) else "failed_verification",
            user_override=user_override,
        )
        await db.drafts.replace_one(
            {"job_id": job.id},
            updated_draft_doc.model_dump(),
            upsert=True,
        )

    # Terminal decisions: skip, reject, abandon -> return 200 OK immediately
    if action == DecisionAction.SKIP:
        await transition_job_status(job.id, JobStatus.SKIPPED)
        asyncio.create_task(run_workflow_background(job.id, job.run_number, resume_payload={"action": "skip"}))
        return {"job_id": job.id, "status": JobStatus.SKIPPED}

    if action == DecisionAction.REJECT:
        await transition_job_status(job.id, JobStatus.REJECTED)
        asyncio.create_task(run_workflow_background(job.id, job.run_number, resume_payload={"action": "reject"}))
        return {"job_id": job.id, "status": JobStatus.REJECTED}

    if action == DecisionAction.ABANDON:
        await transition_job_status(job.id, JobStatus.CLOSED)
        asyncio.create_task(run_workflow_background(job.id, job.run_number, resume_payload={"action": "abandon"}))
        return {"job_id": job.id, "status": JobStatus.CLOSED}

    # Resuming decisions: proceed, approve, submit_edits, edit -> return 202 Accepted
    resume_payload = {"action": action.value}
    asyncio.create_task(run_workflow_background(job.id, job.run_number, resume_payload=resume_payload))

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job_id": job.id, "status": JobStatus.PROCESSING.value},
    )


@router.post("/{job_id}/retry", response_model=JobActionResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_failed_job(job_id: str) -> JobActionResponse:
    """Retry execution of a failed job from its last checkpoint.

    Args:
        job_id: Unique job ID.

    Returns:
        JobActionResponse: Job ID and new processing status.
    """
    db = get_db()
    job_doc = await db.jobs.find_one({"id": job_id})
    if not job_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found.",
        )
    job = Job.model_validate(job_doc)

    if job.status != JobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is in status '{job.status.value}', only failed jobs can be retried.",
        )

    if is_job_running(job_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is currently running.",
        )

    await transition_job_status(job.id, JobStatus.PROCESSING, expected_current_status=JobStatus.FAILED)
    asyncio.create_task(run_workflow_background(job.id, job.run_number))

    return JobActionResponse(job_id=job.id, status=JobStatus.PROCESSING)


@router.post("/{job_id}/rematch", response_model=JobActionResponse, status_code=status.HTTP_202_ACCEPTED)
async def rematch_job(job_id: str) -> JobActionResponse:
    """Force fresh re-run of matching and tailoring for an existing job.

    Allowed only when job is saved, skipped, or failed. Increments run_number
    to use a fresh LangGraph checkpoint thread.
    """
    db = get_db()
    job_doc = await db.jobs.find_one({"id": job_id})
    if not job_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found.",
        )
    job = Job.model_validate(job_doc)

    allowed_rematch_statuses = {JobStatus.SAVED, JobStatus.SKIPPED, JobStatus.FAILED}
    if job.status not in allowed_rematch_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Job '{job_id}' is in status '{job.status.value}'. "
                "Rematch is only permitted for saved, skipped, or failed jobs."
            ),
        )

    if is_job_running(job_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is currently executing in background.",
        )

    new_run_number = job.run_number + 1
    await db.jobs.update_one(
        {"id": job.id},
        {
            "$set": {
                "run_number": new_run_number,
                "status": JobStatus.PROCESSING.value,
                "error_message": None,
            }
        },
    )

    asyncio.create_task(run_workflow_background(job.id, new_run_number))
    return JobActionResponse(job_id=job.id, status=JobStatus.PROCESSING)


@router.patch("/{job_id}/status", response_model=JobDetailResponse, status_code=status.HTTP_200_OK)
async def update_job_status(job_id: str, request: JobStatusPatchRequest) -> JobDetailResponse:
    """Manually update the post-application status of a job (applied, interview, closed).

    Rejects attempts to set internal workflow statuses (409 Conflict).
    """
    if request.status not in MANUAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Status '{request.status.value}' cannot be set manually. "
                f"Allowed manual statuses: {[s.value for s in MANUAL_STATUSES]}"
            ),
        )

    try:
        await transition_job_status(job_id, request.status)
    except (InvalidTransitionError, ApprovalInvariantError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return await get_job_detail(job_id)
