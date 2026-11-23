"""Job intake agent responsible for scraping/reading JDs, deduplication, and structured extraction."""

import hashlib
import logging
from pathlib import Path
from typing import Optional
import uuid
from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from backend.config import normalize_skills
from backend.database import get_db
from backend.llm.client import LLMClient, get_llm_client
from backend.models.job import Job, JobStatus
from backend.models.logs import write_agent_log
from backend.services.url_fetcher import fetch_and_extract_url

logger = logging.getLogger(__name__)

PROMPT_FILE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "job_parse.md"
MAX_LLM_INPUT_CHARS = 15000
MIN_JD_CHARS = 200


class ParsedJobLLMOutput(BaseModel):
    """Schema expected from LLM structured extraction."""

    company: Optional[str] = None
    title: Optional[str] = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    duration_months: Optional[int] = None
    location: Optional[str] = None


def get_job_parse_prompt() -> str:
    """Read the job parsing prompt template."""
    if not PROMPT_FILE_PATH.exists():
        raise FileNotFoundError(f"Job parse prompt template not found at {PROMPT_FILE_PATH}")
    return PROMPT_FILE_PATH.read_text(encoding="utf-8")


def compute_jd_hash(text: str) -> str:
    """Compute SHA-256 hash of normalized whitespace JD text for deduplication."""
    normalized_text = " ".join(text.strip().split())
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


async def process_job_intake(
    jd_text: Optional[str] = None,
    url: Optional[str] = None,
    llm_client: Optional[LLMClient] = None,
) -> Job:
    """Process incoming job description from raw text or a public URL.

    Deduplicates by JD text hash; if already processed, returns the existing Job.
    Otherwise, extracts structured job information via LLM with 1 retry on Pydantic failure.

    Args:
        jd_text: Raw job posting text.
        url: Public URL to scrape.
        llm_client: Optional LLMClient for testing/mocking.

    Returns:
        Job: Stored or existing structured job document.

    Raises:
        HTTPException: On validation failure or URL fetching error.
    """
    source_label = "pasted"
    raw_text = ""

    if url and url.strip():
        source_label = url.strip()
        raw_text = await fetch_and_extract_url(url.strip())
    elif jd_text and jd_text.strip():
        raw_text = jd_text.strip()
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'jd_text' or 'url' must be provided.",
        )

    if len(raw_text) < MIN_JD_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Job description is too short ({len(raw_text)} chars). Minimum required is {MIN_JD_CHARS} characters.",
        )

    # Compute deduplication hash
    content_hash = compute_jd_hash(raw_text)

    # Check for existing job
    db = get_db()
    existing_job_doc = await db.jobs.find_one({"content_hash": content_hash})
    if existing_job_doc:
        logger.info("Found existing job with content_hash=%s (id=%s)", content_hash, existing_job_doc.get("id"))
        return Job.model_validate(existing_job_doc)

    # Prepare hardened LLM prompt
    safe_text = raw_text[:MAX_LLM_INPUT_CHARS]
    system_instruction = get_job_parse_prompt()
    user_prompt = (
        "Extract structured job data from the following job description:\n\n"
        f"<untrusted_job_description>\n{safe_text}\n</untrusted_job_description>"
    )

    client = llm_client or get_llm_client()
    parsed_llm: Optional[ParsedJobLLMOutput] = None

    try:
        parsed_llm = await client.generate_json(
            prompt=user_prompt,
            schema=ParsedJobLLMOutput,
            system_instruction=system_instruction,
        )
    except Exception as first_exc:
        logger.warning("First attempt to parse JD via LLM failed: %s. Retrying once...", first_exc)
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"IMPORTANT: Previous extraction failed schema validation with error:\n"
            f"{str(first_exc)}\n"
            "Please return valid JSON strictly adhering to the schema."
        )
        try:
            parsed_llm = await client.generate_json(
                prompt=retry_prompt,
                schema=ParsedJobLLMOutput,
                system_instruction=system_instruction,
            )
        except Exception as retry_exc:
            logger.error("JD parsing retry also failed: %s", retry_exc)
            await write_agent_log(
                agent_name="intake_agent",
                status="failure",
                summary={
                    "source": source_label,
                    "error": f"LLM parsing failed after retry: {str(retry_exc)}",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to extract structured data from job description: {str(retry_exc)}",
            )

    # Deterministic skill normalization
    norm_required = normalize_skills(parsed_llm.required_skills)
    norm_preferred = normalize_skills(parsed_llm.preferred_skills)

    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        company=parsed_llm.company.strip() if parsed_llm.company else None,
        title=parsed_llm.title.strip() if parsed_llm.title else None,
        source=source_label,
        jd_text=raw_text,
        required_skills=norm_required,
        preferred_skills=norm_preferred,
        duration_months=parsed_llm.duration_months,
        location=parsed_llm.location.strip() if parsed_llm.location else None,
        status=JobStatus.SAVED,
        content_hash=content_hash,
    )

    await db.jobs.insert_one(job.model_dump())
    logger.info("Saved new job id=%s (company=%s, title=%s)", job.id, job.company, job.title)

    missing_fields_count = sum(
        1 for f in (job.company, job.title, job.duration_months, job.location) if f is None
    )

    await write_agent_log(
        agent_name="intake_agent",
        status="success",
        job_id=job.id,
        summary={
            "source": source_label,
            "company": job.company or "Unknown",
            "title": job.title or "Unknown",
            "required_skills_count": len(job.required_skills),
            "preferred_skills_count": len(job.preferred_skills),
            "missing_fields_count": missing_fields_count,
        },
    )

    return job

