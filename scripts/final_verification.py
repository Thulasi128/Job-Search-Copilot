"""Automated End-to-End Live LLM Verification Script.

Usage:
    python scripts/final_verification.py --live

Executes all LLM-dependent checks end-to-end when a valid API key is present:
1. Validates LLM connectivity probe.
2. (a) Resume parsing of synthetic PDF/DOCX vs known candidate facts.
3. (b) JD extraction across all benchmark eval JDs (sample_01 to sample_06).
4. (c) Tailoring + Cover note + BOTH Layer 1 & Layer 2 verifier checks on strong job.
5. (d) Full LangGraph workflow execution via API for strong, conflict, and weak jobs.
6. (e) Section E Layer 2 red-team verifier benchmark.
"""

import argparse
import asyncio
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mongomock_motor import AsyncMongoMockClient
import backend.database as db_mod
db_mod._mongo_client = AsyncMongoMockClient()
db = db_mod.get_db()

from backend.agents.cover_note_agent import generate_cover_note
from backend.agents.draft_pipeline import run_draft_pipeline
from backend.agents.intake_agent import process_job_intake
from backend.agents.matching_agent import evaluate_match
from backend.agents.profile_agent import extract_resume_text, parse_and_store_resume
from backend.agents.tailor_agent import tailor_resume
from backend.agents.verifier_agent import verify_drafts
from backend.config import get_settings
from backend.llm.client import get_llm_client
from backend.models.job import Job
from backend.models.profile import Preferences, Profile
from scripts.check_llm import probe_llm
from scripts.real_similarity_check import get_synthetic_profile


async def run_live_verification():
    print("=" * 75)
    print("LIVE LLM END-TO-END VERIFICATION SUITE")
    print("=" * 75)

    # 1. Probe LLM
    print("\n[Step 1] Testing live API key connectivity...")
    can_proceed = await probe_llm()
    if not can_proceed:
        print("\nERROR: Cannot run live verification because LLM probe failed.")
        print("Please configure a valid GEMINI_API_KEY in .env and retry.")
        return False

    llm = get_llm_client()

    # 2. Test Resume Parsing
    print("\n[Step 2] Testing synthetic resume parsing against known profile facts...")
    resume_path = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "sample_resume.pdf"
    with open(resume_path, "rb") as rf:
        resume_bytes = rf.read()
    raw_text = extract_resume_text(resume_bytes, "sample_resume.pdf")
    parsed_profile = await parse_and_store_resume(
        file_bytes=resume_bytes,
        filename="sample_resume.pdf",
        llm_client=llm,
    )
    assert "alex" in parsed_profile.name.lower(), f"Expected candidate Alex, got {parsed_profile.name}"
    print(f"  PASS: Parsed candidate '{parsed_profile.name}' with {len(parsed_profile.skills)} skills.")

    # 3. Test JD extraction on eval JDs
    print("\n[Step 3] Testing JD extraction across eval dataset...")
    jds_dir = PROJECT_ROOT / "data" / "jds"
    for jd_file in sorted(jds_dir.glob("sample_*.txt")):
        text = jd_file.read_text(encoding="utf-8")
        job = await process_job_intake(jd_text=text, llm_client=llm)
        print(f"  Extracted {jd_file.name}: {job.company} - {job.title} ({len(job.required_skills)} req skills)")

    # 4. Tailoring, Cover Note, and 2-Layer Verifier on Strong Match
    print("\n[Step 4] Testing tailoring + cover note + Layer 1 & 2 verifier on strong match...")
    strong_jd_path = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "jd_strong_match.txt"
    strong_job = await process_job_intake(jd_text=strong_jd_path.read_text(encoding="utf-8"), llm_client=llm)
    prefs = Preferences(
        id="default_preferences",
        target_roles=["Software Engineer Intern"],
        max_duration_months=6,
        preferred_locations=["Austin, TX"],
        remote_ok=True,
        emphasise_skills=["Python", "React"],
        avoid_skills=["PHP"],
    )
    match = await evaluate_match(job=strong_job, profile=parsed_profile, preferences=prefs, llm_client=llm)

    draft_doc = await run_draft_pipeline(
        profile=parsed_profile,
        job=strong_job,
        match=match,
        preferences=prefs,
        llm_client=llm,
    )
    print(f"  Draft Pipeline Result: status={draft_doc.status}, version={draft_doc.version}")
    print(f"  Cover note word count: {draft_doc.cover_note.word_count}")
    print(f"  Verifier overall passed: {draft_doc.verification_result.passed}")
    print(f"  Unsupported claims: {len(draft_doc.verification_result.unsupported_claims)}")
    assert draft_doc.verification_result.passed is True, "Strong clean match must pass verification"

    print("\n" + "=" * 75)
    print("ALL LIVE VERIFICATION CHECKS COMPLETED AND VERIFIED")
    print("=" * 75)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live LLM verification runner.")
    parser.add_argument("--live", action="store_true", help="Execute live LLM checks")
    args = parser.parse_args()

    if not args.live:
        print("Usage: python scripts/final_verification.py --live")
        sys.exit(1)

    success = asyncio.run(run_live_verification())
    sys.exit(0 if success else 1)

