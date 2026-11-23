"""Status transitions and approval invariant validation for jobs."""

from datetime import datetime, timezone
from typing import Optional

from backend.database import get_db
from backend.models.job import ALLOWED_TRANSITIONS, JobStatus


class InvalidTransitionError(Exception):
    """Raised when an illegal status transition is attempted."""


class ApprovalInvariantError(Exception):
    """Raised when approving a job whose latest draft has not passed verification or override."""


def can_transition(current_status: JobStatus, target_status: JobStatus) -> bool:
    """Check whether a transition between two statuses is permitted.

    Args:
        current_status: Current lifecycle status of the job.
        target_status: Desired destination status.

    Returns:
        bool: True if allowed by ALLOWED_TRANSITIONS, False otherwise.
    """
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    return target_status in allowed


async def check_approval_invariant(job_id: str) -> None:
    """Enforce the hard invariant: a job can ONLY become 'approved' if its latest

    draft passed verification or an explicit user override is recorded.

    Args:
        job_id: Unique identifier of the job.

    Raises:
        ApprovalInvariantError: If the latest draft failed verification and lacks an override.
    """
    db = get_db()
    draft = await db["drafts"].find_one(
        {"job_id": job_id},
        sort=[("created_at", -1)],
    )

    if not draft:
        raise ApprovalInvariantError(f"Cannot approve job {job_id}: no draft exists.")

    user_override = bool(draft.get("user_override", False))
    if user_override:
        return

    verification = draft.get("verification_result") or draft.get("verification")
    if not verification:
        raise ApprovalInvariantError(
            f"Cannot approve job {job_id}: latest draft has no verification results."
        )

    passed = verification.get("passed", False) if isinstance(verification, dict) else getattr(verification, "passed", False)
    unsupported = verification.get("unsupported_claims", []) if isinstance(verification, dict) else getattr(verification, "unsupported_claims", [])

    if not passed or len(unsupported) > 0:
        raise ApprovalInvariantError(
            f"Cannot approve job {job_id}: draft contains {len(unsupported)} unverified claim(s) "
            "and no user override was recorded."
        )


async def transition_job_status(
    job_id: str,
    target_status: JobStatus,
    expected_current_status: Optional[JobStatus] = None,
    error_message: Optional[str] = None,
) -> JobStatus:
    """Atomically transitions a job's status in MongoDB after validating allowed transitions

    and checking domain invariants.

    Args:
        job_id: Unique identifier of the job.
        target_status: Target JobStatus to transition into.
        expected_current_status: Optional expected current status. If provided, raises
            InvalidTransitionError if current status does not match.
        error_message: Optional error message string to record (e.g. on failure).

    Returns:
        JobStatus: The newly set status.

    Raises:
        ValueError: If the job does not exist.
        InvalidTransitionError: If the transition is disallowed or a race condition occurred.
        ApprovalInvariantError: If attempting to approve without passing verification.
    """
    db = get_db()
    job_doc = await db["jobs"].find_one({"id": job_id})
    if not job_doc:
        raise ValueError(f"Job not found: {job_id}")

    current_status = JobStatus(job_doc["status"])

    if expected_current_status and current_status != expected_current_status:
        raise InvalidTransitionError(
            f"Job {job_id} is in status '{current_status.value}', expected '{expected_current_status.value}'"
        )

    if not can_transition(current_status, target_status):
        raise InvalidTransitionError(
            f"Illegal status transition for job {job_id}: cannot transition from "
            f"'{current_status.value}' to '{target_status.value}'"
        )

    if target_status == JobStatus.APPROVED:
        await check_approval_invariant(job_id)

    update_fields = {
        "status": target_status.value,
        "updated_at": datetime.now(timezone.utc),
    }

    if error_message is not None:
        update_fields["error_message"] = error_message
    elif target_status != JobStatus.FAILED:
        update_fields["error_message"] = None

    # Atomic conditional update
    result = await db["jobs"].update_one(
        {"id": job_id, "status": current_status.value},
        {"$set": update_fields},
    )

    if result.modified_count == 0:
        raise InvalidTransitionError(
            f"Concurrent modification detected while transitioning job {job_id} "
            f"from '{current_status.value}' to '{target_status.value}'"
        )

    return target_status
