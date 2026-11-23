"""Workflow nodes and conditional edge routers for LangGraph.

Nodes are stateless and load documents on demand from MongoDB, keeping
the persisted checkpoint state strictly lean. All interrupt nodes are
side-effect free and idempotent.
"""

import logging
from typing import Any, Dict

from langgraph.types import interrupt

from backend.agents.draft_pipeline import run_draft_pipeline
from backend.agents.matching_agent import compute_preferences_hash, compute_profile_hash, evaluate_match
from backend.config import get_settings
from backend.database import get_db
from backend.models.job import DecisionAction, InterruptType, Job, JobStatus
from backend.models.logs import write_agent_log
from backend.models.match import Match
from backend.models.profile import Preferences, Profile
from backend.workflow.state import JobState
from backend.workflow.transitions import transition_job_status

logger = logging.getLogger(__name__)


async def intake_match_node(state: JobState) -> Dict[str, Any]:
    """Execute matching for the job against candidate profile facts.

    Loads the latest Profile, Job, and Preferences documents from MongoDB.
    """
    job_id = state["job_id"]
    db = get_db()
    settings = get_settings()

    job_data = await db["jobs"].find_one({"id": job_id})
    if not job_data:
        raise ValueError(f"Job not found for job_id={job_id}")
    job = Job(**job_data)

    profile_data = await db["profiles"].find_one({"id": settings.DEFAULT_PROFILE_ID})
    if not profile_data:
        raise ValueError(f"Profile not found for profile_id={settings.DEFAULT_PROFILE_ID}")
    profile = Profile(**profile_data)

    prefs_data = await db["preferences"].find_one({"$or": [{"id": "default_preferences"}, {"profile_id": settings.DEFAULT_PROFILE_ID}]})
    preferences = Preferences(**prefs_data) if prefs_data else Preferences()

    profile_hash = compute_profile_hash(profile)
    prefs_hash = compute_preferences_hash(preferences)

    # Check for existing match document
    existing_match = await db["matches"].find_one({"job_id": job_id})
    if (
        existing_match
        and existing_match.get("profile_hash") == profile_hash
        and existing_match.get("preferences_hash") == prefs_hash
    ):
        match = Match(**existing_match)
    else:
        match = await evaluate_match(job=job)

    return {
        "job_id": job_id,
        "score": match.score,
        "flags": {
            "min_score_to_consider": preferences.min_score_to_consider,
            "min_score_to_tailor": preferences.min_score_to_tailor,
        },
    }


def route_after_match(state: JobState) -> str:
    """Route according to calculated match score vs user preference thresholds."""
    score = state.get("score", 0.0) or 0.0
    flags = state.get("flags", {})
    min_consider = flags.get("min_score_to_consider", 40)
    min_tailor = flags.get("min_score_to_tailor", 70)

    if score < min_consider:
        return "auto_skip"
    if score < min_tailor:
        return "prep_confirm"
    return "tailor_pipeline"


async def auto_skip_node(state: JobState) -> Dict[str, Any]:
    """Transition low-scoring jobs automatically to skipped."""
    job_id = state["job_id"]
    await transition_job_status(job_id, JobStatus.SKIPPED)
    await write_agent_log(
        agent_name="workflow_router",
        status="success",
        summary={
            "action": "auto_skip",
            "score": state.get("score"),
            "threshold": state.get("flags", {}).get("min_score_to_consider"),
        },
        job_id=job_id,
    )
    return {}


async def prep_confirm_node(state: JobState) -> Dict[str, Any]:
    """Transition job to awaiting_confirmation prior to interrupt pause."""
    job_id = state["job_id"]
    await transition_job_status(job_id, JobStatus.AWAITING_CONFIRMATION)
    return {}


def interrupt_confirm_node(state: JobState) -> Dict[str, Any]:
    """Pause workflow to confirm whether to tailor a moderate-scoring job."""
    decision = interrupt(
        {
            "type": InterruptType.CONFIRM_TAILORING.value,
            "job_id": state["job_id"],
            "score": state.get("score"),
            "min_score_to_tailor": state.get("flags", {}).get("min_score_to_tailor", 70),
        }
    )
    action = decision.get("action") if isinstance(decision, dict) else str(decision)
    return {"flags": {**state.get("flags", {}), "confirm_action": action}}


def route_after_confirm(state: JobState) -> str:
    """Route based on user confirmation decision."""
    action = state.get("flags", {}).get("confirm_action")
    if action == DecisionAction.SKIP.value:
        return "confirm_skip"
    return "tailor_pipeline"


async def confirm_skip_node(state: JobState) -> Dict[str, Any]:
    """Transition confirmed skip to skipped status."""
    job_id = state["job_id"]
    await transition_job_status(job_id, JobStatus.SKIPPED)
    await write_agent_log(
        agent_name="workflow_router",
        status="success",
        summary={"action": "user_skipped_at_confirmation"},
        job_id=job_id,
    )
    return {}


async def tailor_pipeline_node(state: JobState) -> Dict[str, Any]:
    """Execute the tailoring, cover note generation, and verification pipeline."""
    job_id = state["job_id"]
    db = get_db()
    settings = get_settings()

    await transition_job_status(job_id, JobStatus.DRAFTING)

    job_data = await db["jobs"].find_one({"id": job_id})
    job = Job(**job_data)

    profile_data = await db["profiles"].find_one({"id": settings.DEFAULT_PROFILE_ID})
    profile = Profile(**profile_data)

    prefs_data = await db["preferences"].find_one({"$or": [{"id": "default_preferences"}, {"profile_id": settings.DEFAULT_PROFILE_ID}]})
    preferences = Preferences(**prefs_data) if prefs_data else Preferences()

    match_data = await db["matches"].find_one({"job_id": job_id})
    match = Match(**match_data)

    draft_doc = await run_draft_pipeline(
        profile=profile,
        job=job,
        match=match,
        preferences=preferences,
    )

    is_valid = draft_doc.verification_result.passed and len(draft_doc.verification_result.unsupported_claims) == 0
    return {
        "flags": {
            **state.get("flags", {}),
            "is_valid": is_valid,
            "unsupported_count": len(draft_doc.verification_result.unsupported_claims),
        }
    }


def route_after_drafting(state: JobState) -> str:
    """Route according to whether the draft passed verification or needs manual edit."""
    if state.get("flags", {}).get("is_valid", False):
        return "prep_approval"
    return "prep_manual_edit"


async def prep_manual_edit_node(state: JobState) -> Dict[str, Any]:
    """Transition job to awaiting_manual_edit prior to interrupt pause."""
    job_id = state["job_id"]
    await transition_job_status(job_id, JobStatus.AWAITING_MANUAL_EDIT)
    return {}


def interrupt_manual_edit_node(state: JobState) -> Dict[str, Any]:
    """Pause workflow requiring manual edit when automated verification fails."""
    decision = interrupt(
        {
            "type": InterruptType.MANUAL_EDIT_REQUIRED.value,
            "job_id": state["job_id"],
            "unsupported_count": state.get("flags", {}).get("unsupported_count", 0),
        }
    )
    action = decision.get("action") if isinstance(decision, dict) else str(decision)
    return {"flags": {**state.get("flags", {}), "manual_edit_action": action}}


def route_after_manual_edit(state: JobState) -> str:
    """Route after manual edit input."""
    action = state.get("flags", {}).get("manual_edit_action")
    if action == DecisionAction.ABANDON.value:
        return "abandon"
    return "prep_approval"


async def abandon_node(state: JobState) -> Dict[str, Any]:
    """Transition abandoned job to closed status."""
    job_id = state["job_id"]
    await transition_job_status(job_id, JobStatus.CLOSED)
    await write_agent_log(
        agent_name="workflow_router",
        status="success",
        summary={"action": "user_abandoned_manual_edit"},
        job_id=job_id,
    )
    return {}


async def prep_approval_node(state: JobState) -> Dict[str, Any]:
    """Transition job to awaiting_approval prior to interrupt pause."""
    job_id = state["job_id"]
    await transition_job_status(job_id, JobStatus.AWAITING_APPROVAL)
    return {}


def interrupt_approval_node(state: JobState) -> Dict[str, Any]:
    """Pause workflow for final human approval."""
    decision = interrupt(
        {
            "type": InterruptType.APPROVAL.value,
            "job_id": state["job_id"],
        }
    )
    action = decision.get("action") if isinstance(decision, dict) else str(decision)
    return {"flags": {**state.get("flags", {}), "approval_action": action}}


def route_after_approval(state: JobState) -> str:
    """Route based on final human approval action."""
    action = state.get("flags", {}).get("approval_action")
    if action == DecisionAction.APPROVE.value:
        return "approve"
    if action == DecisionAction.REJECT.value:
        return "reject"
    return "prep_approval"


async def approve_node(state: JobState) -> Dict[str, Any]:
    """Transition job to approved status (enforcing verification invariant)."""
    job_id = state["job_id"]
    await transition_job_status(job_id, JobStatus.APPROVED)
    await write_agent_log(
        agent_name="workflow_router",
        status="success",
        summary={"action": "user_approved_draft"},
        job_id=job_id,
    )
    return {}


async def reject_node(state: JobState) -> Dict[str, Any]:
    """Transition job to rejected status."""
    job_id = state["job_id"]
    await transition_job_status(job_id, JobStatus.REJECTED)
    await write_agent_log(
        agent_name="workflow_router",
        status="success",
        summary={"action": "user_rejected_application"},
        job_id=job_id,
    )
    return {}
