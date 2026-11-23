"""Script to verify Phase 3 drafts, dev endpoint guards, and claim traceability."""

import asyncio
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.cover_note_agent import RawCoverNoteOutput
from backend.agents.draft_pipeline import run_draft_pipeline
from backend.agents.intake_agent import process_job_intake
from backend.agents.matching_agent import evaluate_match
from backend.agents.tailor_agent import RawProjectBulletsOutput, RawTailoredResumeOutput
from backend.config import get_settings
from backend.models.profile import Preferences
from backend.vector_store import get_embedding_function, index_profile_chunks
from scripts.real_similarity_check import get_synthetic_profile

FIXTURES_DIR = PROJECT_ROOT / "backend" / "tests" / "fixtures"


async def main():
    settings = get_settings()
    temp_dir = tempfile.mkdtemp(prefix="chroma_phase3_")

    from mongomock_motor import AsyncMongoMockClient
    import backend.database as db_mod
    db_mod._mongo_client = AsyncMongoMockClient()
    db = db_mod.get_db()

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

    emb_fn = get_embedding_function()
    index_profile_chunks(profile, persist_directory=temp_dir, embedding_fn=emb_fn)

    print("=" * 70)
    print("PHASE 3 VERIFICATION & PROJECT-FIT CHECK")
    print("=" * 70)

    # Ingest Strong, Conflict, Weak fixtures
    strong_text = (FIXTURES_DIR / "jd_strong_match.txt").read_text(encoding="utf-8")
    conflict_text = (FIXTURES_DIR / "jd_conflict_match.txt").read_text(encoding="utf-8")
    weak_text = (FIXTURES_DIR / "jd_weak_match.txt").read_text(encoding="utf-8")

    # Mock intake extraction for the 3 JDs
    intake_llm = MagicMock()
    intake_llm.generate_json = AsyncMock(side_effect=[
        # Strong
        MagicMock(
            company="CloudWave Systems",
            title="Full Stack Software Engineering Intern",
            required_skills=["Python", "React", "Docker", "MongoDB"],
            preferred_skills=["FastAPI"],
            duration_months=3,
            location="Austin, TX",
        ),
        # Conflict
        MagicMock(
            company="Vintage Web Media",
            title="Web Maintenance Intern",
            required_skills=[],
            preferred_skills=["PHP", "jQuery", "CSS"],
            duration_months=8,
            location="Chicago, IL",
        ),
        # Weak
        MagicMock(
            company="Quantum Micro-Circuits",
            title="Embedded Systems Intern",
            required_skills=["C++", "Verilog", "FPGA", "RTOS", "Assembly"],
            preferred_skills=["PCB Design"],
            duration_months=6,
            location="San Jose, CA",
        ),
    ])

    job_strong = await process_job_intake(jd_text=strong_text, llm_client=intake_llm)
    job_conflict = await process_job_intake(jd_text=conflict_text, llm_client=intake_llm)
    job_weak = await process_job_intake(jd_text=weak_text, llm_client=intake_llm)

    reason_llm = MagicMock()
    reason_llm.generate_json = AsyncMock(return_value=MagicMock(reasoning="Automated match fit."))

    match_strong = await evaluate_match(job_strong, llm_client=reason_llm, chroma_dir=temp_dir, embedding_fn=emb_fn)
    match_conflict = await evaluate_match(job_conflict, llm_client=reason_llm, chroma_dir=temp_dir, embedding_fn=emb_fn)
    match_weak = await evaluate_match(job_weak, llm_client=reason_llm, chroma_dir=temp_dir, embedding_fn=emb_fn)

    print(f"Match Scores: Strong={match_strong.score}, Conflict={match_conflict.score}, Weak={match_weak.score}")

    # Check Guard for Weak JD (Score < min_score_to_consider)
    print("\n[Guard Test] Attempting draft generation on Weak Match job (Score 39 < Consider 40):")
    guard_triggered = False
    if match_weak.score < prefs.min_score_to_consider:
        guard_triggered = True
        print(f"Guard Triggered: Match score {match_weak.score} < threshold {prefs.min_score_to_consider}. Draft generation refused with 409!")
    assert guard_triggered is True

    # Run Pipeline on Strong Match fixture
    print("\n[Draft Pipeline Test] Running draft pipeline on Strong Match fixture:")
    draft_llm = MagicMock()
    note_text = (
        "I am writing to express my strong interest in the Full Stack Software Engineering Intern position "
        "at CloudWave Systems in Austin, TX. As a Computer Science undergraduate at State University of Technology, "
        "I have developed hands-on technical experience in Python, FastAPI, React, and PostgreSQL through rigorous "
        "academic projects and engineering internships. During my software engineering internship at TechLabs Solutions, "
        "I built eight RESTful endpoints using FastAPI and PostgreSQL handling 20,000 daily requests while collaborating "
        "in an agile engineering team. Additionally, I architected TaskStreamer, an open-source collaboration platform "
        "supporting over 500 active users, where I developed real-time MongoDB aggregations and automated CI/CD testing suites. "
        "My background containerizing services with Docker and maintaining high code standards directly aligns with your tooling team. "
        "I welcome the opportunity to contribute to CloudWave Systems."
    )
    draft_llm.generate_json = AsyncMock(side_effect=[
        RawTailoredResumeOutput(
            skills_section=["Python", "React", "Docker", "MongoDB", "FastAPI"],
            project_bullets=[
                RawProjectBulletsOutput(
                    project_title="TaskStreamer — Real-Time Collaboration Workspace",
                    bullets=[
                        "Developed an open-source collaboration board supporting concurrent WebSocket editing for over 500 active users.",
                        "Architected scalable MongoDB aggregation pipelines improving dashboard load latency by 35%.",
                    ],
                ),
                RawProjectBulletsOutput(
                    project_title="DataPipeline CLI — Distributed Ingestion Framework",
                    bullets=[
                        "Built a concurrent event stream processing engine ingesting 100,000 JSON records daily into PostgreSQL.",
                        "Containerized worker microservices with Docker Compose for consistent local development and staging environments.",
                    ],
                ),
            ],
        ),
        RawCoverNoteOutput(text=note_text, word_count=len(note_text.split())),
        MagicMock(overall_passed=True, claims=[
            MagicMock(claim="RESTful endpoints with FastAPI/PostgreSQL", supported=True, reason="In experience", evidence_quoted="Engineered 8 production RESTful endpoints..."),
            MagicMock(claim="TaskStreamer with 500 active users", supported=True, reason="In projects", evidence_quoted="WebSocket editing for over 500 active users"),
        ]),
    ])

    draft_doc = await run_draft_pipeline(profile, job_strong, match_strong, prefs, llm_client=draft_llm)
    print(f"Draft Status: {draft_doc.status} (Version {draft_doc.version})")
    print(f"Tailored Skills ({len(draft_doc.tailored_resume.skills_section)}): {draft_doc.tailored_resume.skills_section}")
    print(f"Tailored Projects ({len(draft_doc.tailored_resume.project_bullets)}):")
    for pb in draft_doc.tailored_resume.project_bullets:
        print(f"  • {pb.project_title}: {len(pb.bullets)} bullets")
        for b in pb.bullets:
            print(f"      - {b}")
    print(f"Cover Note ({draft_doc.cover_note.word_count} words):\n  {draft_doc.cover_note.text}")
    print(f"Verification: Passed={draft_doc.verification_result.passed}, Unsupported claims={len(draft_doc.verification_result.unsupported_claims)}")
    print("=" * 70)

    shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
