"""Cover note agent generating concise, 100% factual application notes within 120-180 words."""

import json
import logging
from pathlib import Path
import re
from typing import List, Optional
from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from backend.llm.client import LLMClient, get_llm_client
from backend.models.draft import CoverNote
from backend.models.job import Job
from backend.models.match import Match
from backend.models.profile import Preferences, Profile

logger = logging.getLogger(__name__)

PROMPT_FILE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "cover_note.md"
MIN_WORD_COUNT = 120
MAX_WORD_COUNT = 180


class RawCoverNoteOutput(BaseModel):
    """Schema expected from LLM cover note drafting."""

    text: str
    word_count: int = Field(default=0)


def get_cover_note_prompt() -> str:
    """Read the cover note prompt template from disk."""
    if not PROMPT_FILE_PATH.exists():
        raise FileNotFoundError(f"Cover note prompt template not found at {PROMPT_FILE_PATH}")
    return PROMPT_FILE_PATH.read_text(encoding="utf-8")


def count_words(text: str) -> int:
    """Count actual words in a text block deterministically using regex word boundaries."""
    return len(re.findall(r"\b\w+(?:[-']\w+)?\b", text))


def trim_to_word_limit(text: str, max_words: int) -> str:
    """Trim a text block to the nearest complete sentence within max_words."""
    words = re.findall(r"\b\w+(?:[-']\w+)?\b", text)
    if len(words) <= max_words:
        return text

    # Split into sentences and reconstruct within word limit
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result_sentences = []
    current_count = 0

    for s in sentences:
        s_words = len(re.findall(r"\b\w+(?:[-']\w+)?\b", s))
        if current_count + s_words <= max_words:
            result_sentences.append(s)
            current_count += s_words
        else:
            break

    if result_sentences and current_count >= MIN_WORD_COUNT:
        return " ".join(result_sentences)

    # Fallback: slice directly by words if sentence trimming drops below minimum
    tokens = text.split()
    return " ".join(tokens[:max_words])


async def generate_cover_note(
    profile: Profile,
    job: Job,
    match: Match,
    preferences: Preferences,
    feedback_claims: Optional[List[str]] = None,
    llm_client: Optional[LLMClient] = None,
    version: int = 1,
) -> CoverNote:
    """Draft a concise, factual 120-180 word cover note strictly anchored in Profile and JD facts.

    Enforces 120-180 words in deterministic code with 1 retry on length violation.

    Args:
        profile: Candidate profile.
        job: Targeted job posting.
        match: Candidate-job match assessment.
        preferences: Candidate preferences.
        feedback_claims: Unsupported claims from previous verification failure.
        llm_client: Optional LLMClient override.
        version: Draft iteration number.

    Returns:
        CoverNote: Validated cover note with exact word count.

    Raises:
        HTTPException: 422 if generation repeatedly violates word count bounds.
    """
    client = llm_client or get_llm_client()
    system_instruction = get_cover_note_prompt()

    profile_summary = {
        "name": profile.name,
        "education": [
            f"{e.degree} in {e.field} from {e.institution}" for e in profile.education
        ],
        "top_skills": profile.skills[:10],
        "projects": [
            {"title": p.title, "bullets": p.bullets[:2]} for p in profile.projects[:2]
        ],
        "experience": [
            {"company": e.company, "role": e.role, "bullets": e.bullets[:2]}
            for e in profile.experience[:2]
        ],
    }

    match_summary = {
        "matched_skills": match.matched_skills,
        "missing_skills": match.missing_skills,
    }

    user_prompt = (
        "Draft a truthful, professional cover note strictly between 120 and 180 words:\n\n"
        f"<candidate_profile>\n{json.dumps(profile_summary, indent=2)}\n</candidate_profile>\n\n"
        f"<untrusted_job_description>\n{job.jd_text[:8000]}\n</untrusted_job_description>\n\n"
        f"<match_data>\n{json.dumps(match_summary, indent=2)}\n</match_data>\n"
    )

    if feedback_claims:
        user_prompt += (
            f"\n<verification_feedback>\n"
            "Do NOT include or repeat the following unsupported claims:\n"
            + "\n".join(f"- {c}" for c in feedback_claims)
            + "\n</verification_feedback>\n"
        )

    # 1. First Attempt
    parsed_note = await client.generate_json(
        prompt=user_prompt,
        schema=RawCoverNoteOutput,
        system_instruction=system_instruction,
    )
    actual_words = count_words(parsed_note.text)

    # 2. If outside 120-180 words, retry once with explicit word count instruction
    if actual_words < MIN_WORD_COUNT or actual_words > MAX_WORD_COUNT:
        logger.warning(
            "Cover note word count (%d words) outside [%d, %d]. Retrying once...",
            actual_words,
            MIN_WORD_COUNT,
            MAX_WORD_COUNT,
        )
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"CRITICAL REQUIREMENT: Your previous draft was {actual_words} words. "
            f"The cover note MUST be strictly between {MIN_WORD_COUNT} and {MAX_WORD_COUNT} words. "
            "Adjust your length to satisfy this requirement exactly."
        )
        parsed_note = await client.generate_json(
            prompt=retry_prompt,
            schema=RawCoverNoteOutput,
            system_instruction=system_instruction,
        )
        actual_words = count_words(parsed_note.text)

    # 3. Post-Retry Enforcement (Trim if slightly over; fail if still under)
    final_text = parsed_note.text.strip()
    if actual_words > MAX_WORD_COUNT:
        final_text = trim_to_word_limit(final_text, MAX_WORD_COUNT)
        actual_words = count_words(final_text)

    if actual_words < MIN_WORD_COUNT or actual_words > MAX_WORD_COUNT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cover note word count ({actual_words} words) violates the mandatory "
                f"[{MIN_WORD_COUNT}, {MAX_WORD_COUNT}] words boundary after retry."
            ),
        )

    return CoverNote(
        job_id=job.id,
        text=final_text,
        word_count=actual_words,
        version=version,
    )

