"""Phase 5 Real Run-Through and Adversarial Edge Case Verification Script.

Covers:
1. Real SentenceTransformer embeddings & Chroma vector store
2. Real export generation (DOCX and Markdown) from real/synthetic tailored draft
3. Verification of exported document structure, headings, bullet points, and cover note
4. Frontend build verification (dist bundle existence, HTML structure)
5. API Contract parity check (frontend/src/api.js routes vs FastAPI router routes)
6. Five adversarial edge cases specific to Phase 5:
   - Case 1: Export nonexistent job ID -> 404
   - Case 2: Export existing job with no draft -> 404
   - Case 3: Export with unsupported format parameter -> 400
   - Case 4: Export draft with empty cover note or empty skills -> graceful export without crashes
   - Case 5: API contract validation & route parity between frontend and backend
"""

import asyncio
from io import BytesIO
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mongomock_motor import AsyncMongoMockClient

import backend.database as db_mod
db_mod._mongo_client = AsyncMongoMockClient()
db = db_mod.get_db()

from docx import Document
from fastapi.testclient import TestClient

from backend.agents.intake_agent import process_job_intake
from backend.agents.matching_agent import evaluate_match
from backend.api.export import generate_docx, generate_markdown, router as export_router
from backend.config import get_settings
from backend.main import app
from backend.models.draft import ClaimCheck, CoverNote, DraftDocument, ProjectBullets, TailoredResume, VerificationResult
from backend.models.job import Job, JobStatus
from backend.models.match import Match
from backend.models.profile import Preferences
from backend.vector_store import get_embedding_function, index_profile_chunks
from scripts.real_similarity_check import get_synthetic_profile


async def run_phase5_verification():
    print("=" * 75)
    print("PHASE 5: REAL RUN-THROUGH & ADVERSARIAL VALIDATION")
    print("=" * 75)

    temp_chroma = tempfile.mkdtemp(prefix="chroma_phase5_")

    try:
        # Step 1: Profile & Preferences setup
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

        print("\n[Step 1] Profile & Real SentenceTransformer Embeddings")
        emb_fn = get_embedding_function()
        index_profile_chunks(profile, persist_directory=temp_chroma, embedding_fn=emb_fn)
        print("  Real embeddings model loaded and synthetic candidate profile indexed.")

        # Step 2: Intake & Real Scoring
        strong_jd_path = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "jd_strong_match.txt"
        with open(strong_jd_path, "r", encoding="utf-8") as f:
            strong_jd_text = f.read()

        intake_llm = MagicMock()
        intake_llm.generate_json = AsyncMock(return_value=MagicMock(
            company="TechCorp Innovations",
            title="Full Stack Software Engineering Intern",
            duration_months=3,
            location="Austin, TX",
            remote=False,
            summary="Exciting 3-month full-stack internship in Austin working with React and Python.",
            required_skills=["Python", "React", "Docker"],
            preferred_skills=["FastAPI", "TypeScript"],
            responsibilities=["Develop web features", "Write automated tests", "Containerize apps"],
        ))

        with patch("backend.agents.intake_agent.get_llm_client", return_value=intake_llm):
            job = await process_job_intake(jd_text=strong_jd_text)

        with patch("backend.agents.matching_agent.get_llm_client") as mock_match_llm:
            mock_match_llm.return_value.generate_json = AsyncMock(return_value=MagicMock(
                reasoning="Candidate shows strong skills in Python and React, fitting well with TechCorp requirements."
            ))
            match = await evaluate_match(job=job, chroma_dir=temp_chroma, embedding_fn=emb_fn)

        print(f"  Job {job.id} matched: score = {match.score}")
        print(f"  Match reasoning: {match.reasoning}")

        # Step 3: Create tailored DraftDocument
        draft = DraftDocument(
            id=f"draft_{job.id}_run_1",
            job_id=job.id,
            version=1,
            profile_hash="fakehash123",
            status="verified_ready",
            tailored_resume=TailoredResume(
                job_id=job.id,
                skills_section=["Python", "FastAPI", "React", "Docker", "SQL", "Git"],
                project_bullets=[
                    ProjectBullets(
                        project_title="Inventory Management System",
                        bullets=[
                            "Engineered RESTful microservices with Python and FastAPI handling 10k daily requests.",
                            "Constructed responsive dashboards in React with real-time state synchronization.",
                        ],
                    ),
                    ProjectBullets(
                        project_title="Data Analytics Pipeline",
                        bullets=[
                            "Orchestrated Docker containers for streamlined deployment across staging clusters.",
                        ],
                    ),
                ],
            ),
            cover_note=CoverNote(
                job_id=job.id,
                text="Dear Hiring Team at TechCorp Innovations,\n\nI am enthusiastic about applying for the Full Stack Software Engineering Intern position. With proven experience building scalable backend microservices in Python and interactive interfaces in React, I am eager to contribute effectively to your Austin engineering team.\n\nBest regards,\nAlex Chen",
                word_count=48,
            ),
            verification_result=VerificationResult(
                passed=True,
                unsupported_claims=[],
                notes="Verified against profile.",
            ),
        )

        job.status = JobStatus.APPROVED
        await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)
        await db.drafts.replace_one({"id": draft.id}, draft.model_dump(), upsert=True)

        print("\n[Step 2] Real Export Generation (DOCX & Markdown)")
        # Test Markdown Generation
        md_text = generate_markdown(job, draft)
        assert "# Application Draft: Full Stack Software Engineering Intern at TechCorp Innovations" in md_text
        assert "## Tailored Skills" in md_text
        assert "- Python" in md_text
        assert "### Inventory Management System" in md_text
        assert "## Cover Note" in md_text
        print("  Markdown generation verified. Length:", len(md_text), "bytes")

        # Test DOCX Generation
        docx_bytes = generate_docx(job, draft)
        assert len(docx_bytes) > 1000
        doc = Document(BytesIO(docx_bytes))
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        print(f"  DOCX generation verified. Total bytes: {len(docx_bytes)}. Headings found: {headings}")
        assert "Tailored Skills" in headings
        assert "Tailored Project Experience" in headings
        assert "Cover Note" in headings

        # Step 4: Frontend Static Build Inspection
        print("\n[Step 3] Frontend Build Artifacts Inspection")
        dist_dir = PROJECT_ROOT / "frontend" / "dist"
        dist_html = dist_dir / "index.html"
        assert dist_html.exists(), "frontend/dist/index.html does not exist!"
        html_content = dist_html.read_text(encoding="utf-8")
        assert "Job-Search Copilot" in html_content
        assert "/assets/index-" in html_content
        assets = list((dist_dir / "assets").glob("*"))
        print(f"  frontend/dist built cleanly. Assets found: {[a.name for a in assets]}")

        # Step 5: Adversarial Edge Cases
        print("\n[Step 4] Running 5 Adversarial Edge Cases")
        client = TestClient(app)

        # Adversarial 1: Export non-existent job ID -> 404
        print("  1. Adversarial: Export non-existent job ID ->")
        res1 = client.get("/export/non_existent_job_12345?format=docx")
        assert res1.status_code == 404
        assert "Job with id 'non_existent_job_12345' not found" in res1.json()["detail"]
        print("     PASS: 404 returned correctly with message:", res1.json()["detail"])

        # Adversarial 2: Export job with no draft -> 404
        print("  2. Adversarial: Export job with no draft ->")
        no_draft_job = Job(
            id="job_nodraft_999",
            source="pasted",
            jd_text="A full description with enough characters for validation purposes to test the draft 404 response.",
            content_hash="hash999",
            status=JobStatus.APPROVED,
        )
        await db.jobs.replace_one({"id": no_draft_job.id}, no_draft_job.model_dump(), upsert=True)
        res2 = client.get("/export/job_nodraft_999?format=docx")
        assert res2.status_code == 404
        assert "No application draft found" in res2.json()["detail"]
        print("     PASS: 404 returned correctly with message:", res2.json()["detail"])

        # Adversarial 3: Unsupported format -> 400
        print("  3. Adversarial: Export unsupported format (?format=pdf) ->")
        res3 = client.get(f"/export/{job.id}?format=pdf")
        assert res3.status_code == 400
        assert "Unsupported format" in res3.json()["detail"]
        print("     PASS: 400 returned correctly with message:", res3.json()["detail"])

        # Adversarial 4: Export with draft containing empty fields (empty skills/cover note) -> Graceful handling
        print("  4. Adversarial: Export draft with empty sections ->")
        empty_draft = DraftDocument(
            id=f"draft_{job.id}_empty",
            job_id=job.id,
            version=2,
            profile_hash="fakehash123",
            status="verified_ready",
            tailored_resume=TailoredResume(job_id=job.id, skills_section=[], project_bullets=[]),
            cover_note=CoverNote(job_id=job.id, text="", word_count=0),
            verification_result=VerificationResult(passed=True, unsupported_claims=[], notes=""),
        )
        md_empty = generate_markdown(job, empty_draft)
        assert "# Application Draft:" in md_empty
        docx_empty = generate_docx(job, empty_draft)
        assert len(docx_empty) > 500
        print(f"     PASS: Graceful export without crash (MD: {len(md_empty)} chars, DOCX: {len(docx_empty)} bytes)")

        # Adversarial 5: API route parity check between frontend client and FastAPI routes
        print("  5. Adversarial: Frontend API client to backend route contract check ->")
        api_js_path = PROJECT_ROOT / "frontend" / "src" / "api.js"
        api_js_content = api_js_path.read_text(encoding="utf-8")
        
        # Check essential endpoints invoked by frontend
        expected_endpoints = [
            "/profile",
            "/preferences",
            "/jobs",
            "/export",
            "/logs",
            "/health",
        ]
        for ep in expected_endpoints:
            assert ep in api_js_content, f"Frontend missing route reference to {ep}"
        
        # Verify FastAPI registered routes include all expected prefixes
        app_routes = list(app.openapi()["paths"].keys())
        for ep in ["/profile", "/preferences", "/jobs", "/health", "/logs", "/export"]:
            matching = [r for r in app_routes if r.startswith(ep)]
            assert len(matching) > 0, f"Backend missing expected route for prefix {ep}"
        print(f"     PASS: All {len(expected_endpoints)} route endpoints verified matching between frontend and backend.")

        print("\n" + "=" * 75)
        print("PHASE 5 VERIFICATION COMPLETED SUCCESSFULLY (ALL CHECKS PASSED)")
        print("=" * 75)

    finally:
        shutil.rmtree(temp_chroma, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_phase5_verification())
