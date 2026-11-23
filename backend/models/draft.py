"""Pydantic schemas for tailored resume drafts, cover notes, verification, and claims."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class ProjectBullets(BaseModel):
    """Tailored project bullets preserving exact project titles."""

    project_title: str
    bullets: List[str] = Field(default_factory=list)


class TailoredResume(BaseModel):
    """Tailored candidate skills section and project bullets."""

    job_id: str
    skills_section: List[str] = Field(default_factory=list)
    project_bullets: List[ProjectBullets] = Field(default_factory=list)
    version: int = 1


class CoverNote(BaseModel):
    """Short factual candidate cover note."""

    job_id: str
    text: str
    word_count: int
    version: int = 1


class ClaimCheck(BaseModel):
    """Single verification check record identifying layer and outcome."""

    layer: str  # "layer_1_deterministic" or "layer_2_llm"
    claim: str
    reason: str
    evidence_quoted: Optional[str] = None


class VerificationResult(BaseModel):
    """Outcome of two-layer draft verification."""

    passed: bool
    unsupported_claims: List[ClaimCheck] = Field(default_factory=list)
    notes: str = ""


class DraftDocument(BaseModel):
    """Stored draft document combining tailored resume, cover note, and verification audit."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    version: int = 1
    profile_hash: str
    tailored_resume: TailoredResume
    cover_note: CoverNote
    verification_result: VerificationResult
    status: str  # "verified_ready" or "failed_verification"
    user_override: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

