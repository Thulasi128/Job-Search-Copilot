"""Execute real run-through of Phase 2 with real local embeddings and real Gemini API calls."""

import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.intake_agent import process_job_intake
from backend.agents.matching_agent import evaluate_match
from backend.config import get_settings
from backend.database import connect_db, close_db, get_db
from backend.llm.client import get_llm_client
from backend.models.profile import Preferences, Profile
from backend.vector_store import get_embedding_function, index_profile_chunks
from scripts.real_similarity_check import get_synthetic_profile

FIXTURES_DIR = PROJECT_ROOT / "backend" / "tests" / "fixtures"


async def run():
    settings = get_settings()
    temp_dir = tempfile.mkdtemp(prefix="chroma_real_run_")

    from mongomock_motor import AsyncMongoMockClient
    import backend.database as db_mod
    db_mod._mongo_client = AsyncMongoMockClient()
    db = db_mod.get_db()

    try:
        # Clear test state
        await db.profiles.delete_many({})
        await db.preferences.delete_many({})
        await db.jobs.delete_many({})
        await db.matches.delete_many({})

        # 1. Setup real profile & preferences
        profile = get_synthetic_profile()
        await db.profiles.replace_one({"id": profile.id}, profile.model_dump(), upsert=True)

        prefs = Preferences(
            id="default_preferences",
            target_roles=["Software Engineer Intern"],
            max_duration_months=6,
            preferred_locations=["Austin, TX"],
            remote_ok=True,
            emphasise_skills=["Python", "React"],
            avoid_skills=["PHP"],
            min_score_to_tailor=70,
            min_score_to_consider=40,
        )
        await db.preferences.replace_one({"id": "default_preferences"}, prefs.model_dump(), upsert=True)

        # 2. Index real embeddings in Chroma
        real_emb_fn = get_embedding_function()
        indexed_count = index_profile_chunks(profile, persist_directory=temp_dir, embedding_fn=real_emb_fn)
        print(f"Indexed {indexed_count} chunks in Chroma using {settings.EMBEDDING_MODEL}")

        # 3. Real LLM client (Gemini)
        client = get_llm_client()
        print(f"Using real LLM Provider: {settings.LLM_PROVIDER} ({settings.LLM_MODEL})\n" + "=" * 70)

        fixtures = [
            ("CloudWave Systems (Strong)", "jd_strong_match.txt"),
            ("Vintage Web Media (Conflict)", "jd_conflict_match.txt"),
            ("Quantum Micro-Circuits (Weak)", "jd_weak_match.txt"),
        ]

        for label, filename in fixtures:
            jd_path = FIXTURES_DIR / filename
            jd_text = jd_path.read_text(encoding="utf-8")

            print(f"--- Running Intake for: {label} ---")
            job = await process_job_intake(jd_text=jd_text, llm_client=client)
            print(f"Extracted: Company='{job.company}', Title='{job.title}', Duration={job.duration_months}m, Loc='{job.location}'")
            print(f"Required Skills ({len(job.required_skills)}): {job.required_skills}")
            print(f"Preferred Skills ({len(job.preferred_skills)}): {job.preferred_skills}")

            print(f"--- Evaluating Match for: {label} ---")
            match = await evaluate_match(job=job, llm_client=client, chroma_dir=temp_dir, embedding_fn=real_emb_fn)
            print(f"FINAL SCORE: {match.score} (Before caps: {match.score_breakdown.get('score_before_caps')}, After caps: {match.score_breakdown.get('score_after_caps')})")
            print(f"Cap reasons: {match.score_breakdown.get('cap_reasons')}")
            print(f"Matched skills: {match.matched_skills}")
            print(f"Missing skills: {match.missing_skills}")
            print(f"Preference conflicts: {match.preference_conflicts}")
            print(f"Raw similarity: {match.score_breakdown.get('raw_similarity')}, Calibrated: {match.score_breakdown.get('calibrated_similarity')}")
            print(f"Reasoning (real LLM generated, fallback={match.reasoning_fallback}):\n  \"{match.reasoning}\"\n")

    finally:
        try:
            await close_db()
        except Exception:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run())
