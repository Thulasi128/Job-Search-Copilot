"""Tailoring agent producing truthful tailored skills and project bullets for an internship application."""

import json
import logging
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from backend.config import normalize_skill
from backend.llm.client import LLMClient, get_llm_client
from backend.models.draft import ProjectBullets, TailoredResume
from backend.models.job import Job
from backend.models.match import Match
from backend.models.profile import Preferences, Profile

logger = logging.getLogger(__name__)

PROMPT_FILE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "tailor.md"
MAX_PROJECTS = 3
MAX_BULLETS_PER_PROJECT = 3


class RawProjectBulletsOutput(BaseModel):
    """LLM output schema for a project bullets entry."""

    project_title: str
    bullets: List[str] = Field(default_factory=list)


class RawTailoredResumeOutput(BaseModel):
    """LLM output schema for tailored resume sections."""

    skills_section: List[str] = Field(default_factory=list)
    project_bullets: List[RawProjectBulletsOutput] = Field(default_factory=list)


def get_tailor_prompt() -> str:
    """Read the tailoring prompt template from disk."""
    if not PROMPT_FILE_PATH.exists():
        raise FileNotFoundError(f"Tailor prompt template not found at {PROMPT_FILE_PATH}")
    return PROMPT_FILE_PATH.read_text(encoding="utf-8")


async def tailor_resume(
    profile: Profile,
    job: Job,
    match: Match,
    preferences: Preferences,
    feedback_claims: Optional[List[str]] = None,
    llm_client: Optional[LLMClient] = None,
    version: int = 1,
) -> TailoredResume:
    """Generate a tailored resume skills section and project bullets strictly from Profile facts.

    Deterministic in-code rules:
      - skills_section must be a strict subset of Profile.skills. Unknown skills are stripped.
      - Missing skills from Match.missing_skills are explicitly excluded.
      - Skills are sorted by relevance: required skill matches first, then emphasise_skills.
      - Project titles must exactly match Profile.projects titles; invalid titles are dropped.
      - Maximum 3 projects and maximum 3 bullets per project.

    Args:
        profile: Candidate profile (source of truth).
        job: Targeted job posting.
        match: Match evaluation details.
        preferences: Candidate preferences.
        feedback_claims: Optional list of unsupported claims from previous verification failures.
        llm_client: Optional LLMClient override for testing.
        version: Draft iteration number.

    Returns:
        TailoredResume: Validated tailored resume component.
    """
    client = llm_client or get_llm_client()
    system_instruction = get_tailor_prompt()

    profile_data = {
        "name": profile.name,
        "skills": profile.skills,
        "projects": [
            {"title": p.title, "tech": p.tech, "bullets": p.bullets}
            for p in profile.projects
        ],
        "experience": [
            {"company": e.company, "role": e.role, "bullets": e.bullets}
            for e in profile.experience
        ],
        "education": [
            {"institution": ed.institution, "degree": ed.degree, "field": ed.field}
            for ed in profile.education
        ],
    }

    match_data = {
        "score": match.score,
        "matched_skills": match.matched_skills,
        "missing_skills": match.missing_skills,
    }

    prefs_data = {
        "emphasise_skills": preferences.emphasise_skills,
        "avoid_skills": preferences.avoid_skills,
    }

    user_prompt = (
        "Tailor the resume skills section and project bullets for this job:\n\n"
        f"<candidate_profile>\n{json.dumps(profile_data, indent=2)}\n</candidate_profile>\n\n"
        f"<untrusted_job_description>\n{job.jd_text[:12000]}\n</untrusted_job_description>\n\n"
        f"<match_data>\n{json.dumps(match_data, indent=2)}\n</match_data>\n\n"
        f"<preferences>\n{json.dumps(prefs_data, indent=2)}\n</preferences>\n"
    )

    if feedback_claims:
        user_prompt += (
            f"\n<verification_feedback>\n"
            "Previous attempts were rejected because of the following unsupported claims. "
            "DO NOT include or repeat these claims in the new draft:\n"
            + "\n".join(f"- {c}" for c in feedback_claims)
            + "\n</verification_feedback>\n"
        )

    # 1. LLM Generation with 1 Retry on Schema Failure
    parsed_raw: Optional[RawTailoredResumeOutput] = None
    try:
        parsed_raw = await client.generate_json(
            prompt=user_prompt,
            schema=RawTailoredResumeOutput,
            system_instruction=system_instruction,
        )
    except Exception as first_exc:
        logger.warning("Tailoring generation failed on first attempt: %s. Retrying once...", first_exc)
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"NOTE: The previous generation failed validation with error: {str(first_exc)}. "
            "Please return strictly valid JSON conforming to the schema."
        )
        parsed_raw = await client.generate_json(
            prompt=retry_prompt,
            schema=RawTailoredResumeOutput,
            system_instruction=system_instruction,
        )

    # 2. In-Code Strict Filtering: Skills Section
    # Candidate profile skills canonical map: lower -> canonical
    profile_skills_map = {normalize_skill(s).lower(): normalize_skill(s) for s in profile.skills}
    missing_skills_lower = {normalize_skill(s).lower() for s in match.missing_skills}
    avoid_skills_lower = {normalize_skill(s).lower() for s in preferences.avoid_skills}
    required_skills_lower = {normalize_skill(s).lower() for s in job.required_skills}
    emphasise_skills_lower = {normalize_skill(s).lower() for s in preferences.emphasise_skills}

    valid_skills_seen = set()
    filtered_skills = []

    for raw_skill in parsed_raw.skills_section:
        norm = normalize_skill(raw_skill)
        norm_lower = norm.lower()

        # Reject if not in candidate profile
        if norm_lower not in profile_skills_map:
            logger.info("Stripping hallucinated/unpossessed skill not in profile: '%s'", raw_skill)
            continue

        # Reject if in missing_skills
        if norm_lower in missing_skills_lower:
            logger.info("Stripping missing skill claimed in skills section: '%s'", raw_skill)
            continue

        canonical_skill = profile_skills_map[norm_lower]
        if canonical_skill.lower() not in valid_skills_seen:
            valid_skills_seen.add(canonical_skill.lower())
            filtered_skills.append(canonical_skill)

    # Order skills: Required matches first, then emphasise_skills, then other profile skills
    def skill_relevance_sort_key(skill_name: str) -> int:
        sk_lower = skill_name.lower()
        if sk_lower in avoid_skills_lower:
            return 3  # Deprioritize avoid skills
        if sk_lower in required_skills_lower:
            return 0  # Highest priority
        if sk_lower in emphasise_skills_lower:
            return 1
        return 2

    filtered_skills.sort(key=skill_relevance_sort_key)

    # 3. In-Code Strict Filtering: Project Bullets
    # Allowed project titles from Profile
    profile_projects_map = {p.title.strip(): p for p in profile.projects}
    filtered_projects: List[ProjectBullets] = []

    for proj in parsed_raw.project_bullets:
        proj_title_clean = proj.project_title.strip()
        if proj_title_clean not in profile_projects_map:
            logger.warning(
                "Stripping project with non-existent profile title: '%s'",
                proj.project_title,
            )
            continue

        # Keep at most MAX_BULLETS_PER_PROJECT
        valid_bullets = [b.strip() for b in proj.bullets if b.strip()][:MAX_BULLETS_PER_PROJECT]
        filtered_projects.append(
            ProjectBullets(
                project_title=proj_title_clean,
                bullets=valid_bullets,
            )
        )

        if len(filtered_projects) >= MAX_PROJECTS:
            break

    return TailoredResume(
        job_id=job.id,
        skills_section=filtered_skills,
        project_bullets=filtered_projects,
        version=version,
    )

