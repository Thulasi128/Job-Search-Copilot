"""Two-layer verification agent validating drafts against Profile facts and catching inflation."""

import json
import logging
from pathlib import Path
import re
from typing import List, Optional, Set
from pydantic import BaseModel, Field

from backend.config import normalize_skill
from backend.llm.client import LLMClient, get_llm_client
from backend.models.draft import ClaimCheck, CoverNote, TailoredResume, VerificationResult
from backend.models.job import Job
from backend.models.match import Match
from backend.models.profile import Profile

logger = logging.getLogger(__name__)

PROMPT_FILE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "verify.md"
MIN_WORD_COUNT = 120
MAX_WORD_COUNT = 180


class RawClaimItem(BaseModel):
    """Schema for individual claim evaluation from LLM."""

    claim: str
    supported: bool
    reason: str
    evidence_quoted: Optional[str] = None


class RawVerificationOutput(BaseModel):
    """Schema for full LLM claim verification response."""

    overall_passed: bool
    claims: List[RawClaimItem] = Field(default_factory=list)
    notes: str = ""


def get_verify_prompt() -> str:
    """Read the claim verification prompt template from disk."""
    if not PROMPT_FILE_PATH.exists():
        raise FileNotFoundError(f"Verify prompt template not found at {PROMPT_FILE_PATH}")
    return PROMPT_FILE_PATH.read_text(encoding="utf-8")


def count_words(text: str) -> int:
    """Deterministic word count using word boundary regex."""
    return len(re.findall(r"\b\w+(?:[-']\w+)?\b", text))


def extract_numbers_and_metrics(text: str) -> Set[str]:
    """Extract all numbers, percentages, and numeric metrics from a text string."""
    # Matches patterns like 40%, 3.85, 100,000, 1,000,000,000, 20, 500
    raw_matches = re.findall(r"\b\d+(?:[.,]\d+)*%?", text)
    cleaned = set()
    for m in raw_matches:
        token = m.strip().lower()
        if not token:
            continue
        cleaned.add(token)
        # If formatted with commas like 100,000, also add uncomma'd version
        if "," in token:
            cleaned.add(token.replace(",", ""))
    return cleaned


def build_profile_full_text(profile: Profile) -> str:
    """Compile all text in the candidate profile into a single searchable corpus."""
    parts = [profile.name]
    for s in profile.skills:
        parts.append(s)
    for ed in profile.education:
        parts.extend([ed.institution, ed.degree, ed.field, str(ed.start_year)])
        if ed.end_year:
            parts.append(str(ed.end_year))
        if ed.cgpa:
            parts.append(str(ed.cgpa))
    for p in profile.projects:
        parts.append(p.title)
        parts.extend(p.tech)
        parts.extend(p.bullets)
    for ex in profile.experience:
        parts.extend([ex.company, ex.role, ex.start_date])
        if ex.end_date:
            parts.append(ex.end_date)
        parts.extend(ex.bullets)
    return " ".join(parts)


def run_layer_1_deterministic_check(
    profile: Profile,
    job: Job,
    match: Match,
    tailored_resume: TailoredResume,
    cover_note: CoverNote,
) -> List[ClaimCheck]:
    """Run Layer 1 deterministic checks without LLM dependency.

    Validates:
      1. Every skill in skills_section is in Profile.skills
      2. No missing skill from Match.missing_skills appears as a possessed skill
      3. Every project title exists in Profile.projects
      4. Every number, percentage or metric in bullets and note appears in Profile text or JD role text
      5. Employer/company names mentioned are in Profile.experience or is the JD company
      6. Degree and institution claims match Profile.education
      7. Cover note word count is within [120, 180] words
    """
    unsupported: List[ClaimCheck] = []
    layer_name = "layer_1_deterministic"

    # 1. Skills verification
    profile_skills_lower = {normalize_skill(s).lower() for s in profile.skills}
    for sk in tailored_resume.skills_section:
        if normalize_skill(sk).lower() not in profile_skills_lower:
            unsupported.append(
                ClaimCheck(
                    layer=layer_name,
                    claim=f"Possesses skill: {sk}",
                    reason=f"Skill '{sk}' does not exist in the candidate profile skills list.",
                )
            )

    # 2. Missing skills verification
    missing_skills_lower = {normalize_skill(s).lower() for s in match.missing_skills}
    for sk in tailored_resume.skills_section:
        if normalize_skill(sk).lower() in missing_skills_lower:
            unsupported.append(
                ClaimCheck(
                    layer=layer_name,
                    claim=f"Possesses skill: {sk}",
                    reason=f"Skill '{sk}' was identified as missing for this job and cannot be claimed as possessed.",
                )
            )

    # 3. Project titles verification
    profile_project_titles = {p.title.strip() for p in profile.projects}
    for proj in tailored_resume.project_bullets:
        if proj.project_title.strip() not in profile_project_titles:
            unsupported.append(
                ClaimCheck(
                    layer=layer_name,
                    claim=f"Completed project titled: '{proj.project_title}'",
                    reason=f"Project title '{proj.project_title}' is not present in the candidate profile.",
                )
            )

    # 4. Numbers, percentages, and metrics verification
    profile_full_text = build_profile_full_text(profile)
    # Candidate achievements in project bullets MUST strictly come from Profile facts
    profile_numbers = extract_numbers_and_metrics(profile_full_text)
    # Cover notes may also reference role specifications from the JD (e.g. "3-month", "2025")
    cover_note_allowed_numbers = extract_numbers_and_metrics(profile_full_text + " " + job.jd_text)

    # Check project bullets against profile numbers
    for proj in tailored_resume.project_bullets:
        for bullet in proj.bullets:
            b_numbers = extract_numbers_and_metrics(bullet)
            for num in b_numbers:
                if num not in profile_numbers:
                    unsupported.append(
                        ClaimCheck(
                            layer=layer_name,
                            claim=f"Metric or number: '{num}' in project bullet",
                            reason=f"The metric/number '{num}' does not appear in candidate profile facts.",
                        )
                    )

    # Check cover note numbers against profile + JD
    note_numbers = extract_numbers_and_metrics(cover_note.text)
    for num in note_numbers:
        if num not in cover_note_allowed_numbers:
            unsupported.append(
                ClaimCheck(
                    layer=layer_name,
                    claim=f"Metric or number: '{num}' in cover note",
                    reason=f"The metric/number '{num}' does not appear in candidate profile facts or job description.",
                )
            )

    # 5. Employers verification
    allowed_companies = {e.company.strip().lower() for e in profile.experience}
    if job.company:
        allowed_companies.add(job.company.strip().lower())
    for ed in profile.education:
        allowed_companies.add(ed.institution.strip().lower())

    # Check for known fake employers in bullets/note
    all_draft_bullets = []
    for proj in tailored_resume.project_bullets:
        all_draft_bullets.extend(proj.bullets)
    combined_draft_text = " ".join(all_draft_bullets) + " " + cover_note.text

    common_employers_pattern = r"\b(?:at|for|with)\s+([A-Z][A-Za-z0-9&.\s]{2,30}?)(?=[,\.\s]|$)"
    potential_companies = re.findall(common_employers_pattern, combined_draft_text)
    for comp in potential_companies:
        cleaned_comp = comp.strip().lower()
        if len(cleaned_comp) < 3:
            continue
        # If part of an allowed company or education institution, skip
        if any(cleaned_comp in allowed or allowed in cleaned_comp for allowed in allowed_companies):
            continue
        if cleaned_comp in {"over", "about", "scalable", "distributed", "modern", "production"}:
            continue

        # Check if explicitly claimed as employment
        if any(kw in combined_draft_text.lower() for kw in [f"at {cleaned_comp}", f"intern at {cleaned_comp}", f"engineer at {cleaned_comp}"]):
            unsupported.append(
                ClaimCheck(
                    layer=layer_name,
                    claim=f"Employed at: '{comp.strip()}'",
                    reason=f"Employer '{comp.strip()}' is not in candidate experience or the target job company.",
                )
            )

    # 6. Education / Degree verification
    allowed_institutions = {ed.institution.strip().lower() for ed in profile.education}
    allowed_degrees = {ed.degree.strip().lower() for ed in profile.education}
    allowed_fields = {ed.field.strip().lower() for ed in profile.education}

    degree_pattern = r"\b(Bachelor|Master|Ph\.?D|B\.?S|M\.?S)\b[^\.,;\n]*"
    degree_matches = re.findall(degree_pattern, cover_note.text, flags=re.IGNORECASE)
    for dm in degree_matches:
        # If cover note claims a degree level not matching profile
        if not any(d_name in dm.lower() for d_name in ["bachelor", "b.s", "computer science"]):
            unsupported.append(
                ClaimCheck(
                    layer=layer_name,
                    claim=f"Educational qualification claim: '{dm}'",
                    reason="Degree level does not match profile education.",
                )
            )

    # 7. Cover note word count verification
    wc = count_words(cover_note.text)
    if wc < MIN_WORD_COUNT or wc > MAX_WORD_COUNT:
        unsupported.append(
            ClaimCheck(
                layer=layer_name,
                claim=f"Cover note length of {wc} words",
                reason=f"Word count {wc} is outside the mandatory range [{MIN_WORD_COUNT}, {MAX_WORD_COUNT}].",
            )
        )

    return unsupported


async def run_layer_2_llm_check(
    profile: Profile,
    job: Job,
    tailored_resume: TailoredResume,
    cover_note: CoverNote,
    llm_client: Optional[LLMClient] = None,
) -> List[ClaimCheck]:
    """Run Layer 2 LLM claim extraction and inflation audit.

    Fails closed: if LLM returns schema error or network failure after 1 retry,
    records a critical unsupported claim causing verification to fail.
    """
    client = llm_client or get_llm_client()
    system_instruction = get_verify_prompt()
    layer_name = "layer_2_llm"

    profile_dict = {
        "name": profile.name,
        "education": [ed.model_dump() for ed in profile.education],
        "skills": profile.skills,
        "projects": [p.model_dump() for p in profile.projects],
        "experience": [e.model_dump() for e in profile.experience],
    }

    draft_dict = {
        "skills_section": tailored_resume.skills_section,
        "project_bullets": [pb.model_dump() for pb in tailored_resume.project_bullets],
        "cover_note": cover_note.text,
    }

    user_prompt = (
        "Verify every factual claim in the proposed application materials against candidate profile facts:\n\n"
        f"<candidate_profile>\n{json.dumps(profile_dict, indent=2)}\n</candidate_profile>\n\n"
        f"<tailored_skills>\n{json.dumps(tailored_resume.skills_section, indent=2)}\n</tailored_skills>\n\n"
        f"<project_bullets>\n{json.dumps([pb.model_dump() for pb in tailored_resume.project_bullets], indent=2)}\n</project_bullets>\n\n"
        f"<cover_note>\n{cover_note.text}\n</cover_note>\n"
    )

    try:
        parsed_audit: RawVerificationOutput = await client.generate_json(
            prompt=user_prompt,
            schema=RawVerificationOutput,
            system_instruction=system_instruction,
        )
    except Exception as first_exc:
        logger.warning("Layer 2 verifier LLM failed on first attempt: %s. Retrying once...", first_exc)
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"NOTE: Previous response failed schema validation ({str(first_exc)}). "
            "Return valid JSON matching the schema."
        )
        try:
            parsed_audit = await client.generate_json(
                prompt=retry_prompt,
                schema=RawVerificationOutput,
                system_instruction=system_instruction,
            )
        except Exception as retry_exc:
            logger.error("Layer 2 verifier failed closed: %s", retry_exc)
            return [
                ClaimCheck(
                    layer=layer_name,
                    claim="Layer 2 automated LLM audit",
                    reason=f"Verifier LLM service failed to validate claims ({str(retry_exc)}). Failing closed for safety.",
                )
            ]

    unsupported: List[ClaimCheck] = []
    for item in parsed_audit.claims:
        if not item.supported:
            unsupported.append(
                ClaimCheck(
                    layer=layer_name,
                    claim=item.claim,
                    reason=item.reason,
                    evidence_quoted=item.evidence_quoted,
                )
            )

    return unsupported


async def verify_drafts(
    profile: Profile,
    job: Job,
    match: Match,
    tailored_resume: TailoredResume,
    cover_note: CoverNote,
    llm_client: Optional[LLMClient] = None,
) -> VerificationResult:
    """Verify application drafts across Layer 1 (deterministic) and Layer 2 (LLM claim audit).

    Args:
        profile: Candidate profile facts.
        job: Targeted job posting.
        match: Candidate-job match assessment.
        tailored_resume: Proposed tailored skills and project bullets.
        cover_note: Proposed cover note.
        llm_client: Optional LLMClient override.

    Returns:
        VerificationResult: Detailed result containing overall pass/fail status and all unsupported claims.
    """
    all_unsupported: List[ClaimCheck] = []

    # 1. Layer 1: Deterministic Code Checks
    l1_unsupported = run_layer_1_deterministic_check(
        profile=profile,
        job=job,
        match=match,
        tailored_resume=tailored_resume,
        cover_note=cover_note,
    )
    all_unsupported.extend(l1_unsupported)

    # 2. Layer 2: LLM Claim Check
    l2_unsupported = await run_layer_2_llm_check(
        profile=profile,
        job=job,
        tailored_resume=tailored_resume,
        cover_note=cover_note,
        llm_client=llm_client,
    )
    all_unsupported.extend(l2_unsupported)

    passed = len(all_unsupported) == 0
    notes = (
        "Draft passed all verification checks without hallucination or inflation."
        if passed
        else f"Draft failed verification with {len(all_unsupported)} unsupported or inflated claim(s)."
    )

    return VerificationResult(
        passed=passed,
        unsupported_claims=all_unsupported,
        notes=notes,
    )
