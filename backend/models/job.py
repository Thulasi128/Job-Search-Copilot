"""Pydantic schemas for Job descriptions, requests, decisions, and lifecycle statuses."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, Field, model_validator


class JobStatus(str, Enum):
    """Lifecycle status states for an internship opportunity."""

    SAVED = "saved"
    PROCESSING = "processing"
    SKIPPED = "skipped"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DRAFTING = "drafting"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_MANUAL_EDIT = "awaiting_manual_edit"
    APPROVED = "approved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    CLOSED = "closed"
    FAILED = "failed"


# Centralized dictionary of allowed lifecycle state transitions
ALLOWED_TRANSITIONS: Dict[JobStatus, Set[JobStatus]] = {
    JobStatus.SAVED: {JobStatus.PROCESSING},
    JobStatus.PROCESSING: {
        JobStatus.SKIPPED,
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.DRAFTING,
        JobStatus.FAILED,
    },
    JobStatus.AWAITING_CONFIRMATION: {
        JobStatus.DRAFTING,
        JobStatus.SKIPPED,
        JobStatus.FAILED,
    },
    JobStatus.DRAFTING: {
        JobStatus.AWAITING_APPROVAL,
        JobStatus.AWAITING_MANUAL_EDIT,
        JobStatus.FAILED,
    },
    JobStatus.AWAITING_MANUAL_EDIT: {
        JobStatus.AWAITING_APPROVAL,
        JobStatus.CLOSED,
        JobStatus.AWAITING_MANUAL_EDIT,
        JobStatus.FAILED,
    },
    JobStatus.AWAITING_APPROVAL: {
        JobStatus.APPROVED,
        JobStatus.REJECTED,
        JobStatus.AWAITING_APPROVAL,
        JobStatus.FAILED,
    },
    JobStatus.APPROVED: {JobStatus.APPLIED, JobStatus.CLOSED},
    JobStatus.APPLIED: {JobStatus.INTERVIEW, JobStatus.CLOSED},
    JobStatus.INTERVIEW: {JobStatus.CLOSED},
    JobStatus.REJECTED: {JobStatus.CLOSED},
    JobStatus.SKIPPED: {JobStatus.CLOSED, JobStatus.PROCESSING},
    JobStatus.FAILED: {JobStatus.PROCESSING},
    JobStatus.CLOSED: set(),
}

# Statuses that can be set directly by user via PATCH /jobs/{id}/status
MANUAL_STATUSES: Set[JobStatus] = {
    JobStatus.APPLIED,
    JobStatus.INTERVIEW,
    JobStatus.CLOSED,
}


class DecisionAction(str, Enum):
    """Actions the user can take at workflow interrupt decision points."""

    PROCEED = "proceed"
    SKIP = "skip"
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    SUBMIT_EDITS = "submit_edits"
    ABANDON = "abandon"


class InterruptType(str, Enum):
    """Categorization of human approval pause points in LangGraph workflow."""

    CONFIRM_TAILORING = "confirm_tailoring"
    MANUAL_EDIT_REQUIRED = "manual_edit_required"
    APPROVAL = "approval"


class DraftEdits(BaseModel):
    """User-provided manual edits for tailored resume content and cover note."""

    skills_section: List[str] = Field(default_factory=list, max_length=50)
    project_bullets: List[str] = Field(default_factory=list, max_length=30)
    cover_note: str = Field(default="", max_length=5000)


class JobDecisionRequest(BaseModel):
    """Payload to resume workflow from an interrupt checkpoint."""

    action: DecisionAction
    edits: Optional[DraftEdits] = None
    acknowledge_warnings: bool = False


class JobStatusPatchRequest(BaseModel):
    """Payload for manual status updates (applied, interview, closed)."""

    status: JobStatus


class JobCreateRequest(BaseModel):
    """Payload to create and analyze a new job posting."""

    jd_text: Optional[str] = None
    url: Optional[str] = None

    @model_validator(mode="after")
    def validate_exactly_one_source(self) -> "JobCreateRequest":
        """Enforce that exactly one of jd_text or url is provided."""
        has_text = bool(self.jd_text and self.jd_text.strip())
        has_url = bool(self.url and self.url.strip())

        if has_text == has_url:
            raise ValueError("Exactly one of 'jd_text' or 'url' must be provided.")

        if has_text and len(self.jd_text.strip()) < 200:
            raise ValueError("Job description text must be at least 200 characters.")

        return self


class Job(BaseModel):
    """Parsed and structured job opportunity."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company: Optional[str] = None
    title: Optional[str] = None
    source: str  # "pasted" or public URL
    jd_text: str
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    duration_months: Optional[int] = None
    location: Optional[str] = None
    status: JobStatus = JobStatus.SAVED
    content_hash: str
    run_number: int = 1
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobListItem(BaseModel):
    """Summary item displayed on the jobs board table."""

    id: str
    company: str = "Unknown"
    title: str = "Unknown"
    source: str
    score: Optional[int] = None
    status: JobStatus
    created_at: datetime


class JobDetailResponse(BaseModel):
    """Detailed view of a job opportunity, including pending interrupt and draft data."""

    id: str
    company: Optional[str] = None
    title: Optional[str] = None
    source: str
    jd_text: str
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    duration_months: Optional[int] = None
    location: Optional[str] = None
    status: JobStatus
    content_hash: str
    run_number: int = 1
    created_at: datetime
    pending_interrupt: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    allowed_next_statuses: List[JobStatus] = Field(default_factory=list)
    match: Optional[Dict[str, Any]] = None
    draft: Optional[Dict[str, Any]] = None
