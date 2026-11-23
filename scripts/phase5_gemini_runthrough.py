"""Run-through of full tailoring, cover note, and verifier pipeline using LIVE Gemini API calls."""

import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mongomock_motor import AsyncMongoMockClient

import backend.database as db_mod
db_mod._mongo_client = AsyncMongoMockClient()

from backend.agents.draft_pipeline import run_draft_pipeline
from backend.agents.matching_agent import evaluate_match
from backend.llm.client import get_llm_client
from backend.models.job import Job
from backend.models.profile import Preferences
from backend.vector_store import get_embedding_function, index_profile_chunks
from scripts.real_similarity_check import get_synthetic_profile


async def run_live_gemini():
    print("=" * 70)
    print("LIVE GEMINI API + REAL EMBEDDINGS RUN-THROUGH")
    print("=" * 70)

    llm = get_llm_client()
    profile = get_synthetic_profile()

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

    db = db_mod.get_db()
    await db.profiles.replace_one({"id": profile.id}, profile.model_dump(), upsert=True)
    await db.preferences.replace_one({"id": "default_preferences"}, prefs.model_dump(), upsert=True)

    job = Job(
        id="live_demo_job_1",
        company="NexTech Systems",
        title="Software Engineering Intern",
        source="pasted",
        jd_text="NexTech Systems is seeking an ambitious Software Engineering Intern in Austin, TX for 3 months. The intern will build microservices using Python and FastAPI, develop interactive dashboards in React, and deploy containerized services. Required skills: Python, React, FastAPI. Preferred: Docker.",
        required_skills=["Python", "React", "FastAPI"],
        preferred_skills=["Docker"],
        duration_months=3,
        location="Austin, TX",
        content_hash="live_hash_1",
    )

    print("\n[1] Evaluating match with real SentenceTransformer embeddings...")
    match = await evaluate_match(job=job, llm_client=llm)
    print(f"  Match Score: {match.score}")
    print(f"  Matched Skills: {match.matched_skills}")
    print(f"  LLM Reasoning: {match.reasoning}")

    print("\n[2] Executing live Gemini drafting pipeline (tailoring + cover note + 2-layer verifier)...")
    draft_doc = await run_draft_pipeline(
        profile=profile,
        job=job,
        match=match,
        preferences=prefs,
        llm_client=llm,
    )

    print("\n[3] Draft Document Generated:")
    print(f"  Status: {draft_doc.status}")
    print(f"  Version: {draft_doc.version}")
    print(f"  Tailored Skills: {draft_doc.tailored_resume.skills_section}")
    print("  Tailored Projects:")
    for proj in draft_doc.tailored_resume.project_bullets:
        print(f"    * {proj.project_title}:")
        for b in proj.bullets:
            print(f"      - {b}")
    print(f"\n  Cover Note ({draft_doc.cover_note.word_count} words):\n{draft_doc.cover_note.text}")
    print(f"\n  Verification Result: passed={draft_doc.verification_result.passed}")
    print(f"  Unsupported Claims: {len(draft_doc.verification_result.unsupported_claims)}")
    print(f"  Notes: {draft_doc.verification_result.notes}")

    print("\n" + "=" * 70)
    print("LIVE GEMINI RUN-THROUGH COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_live_gemini())
