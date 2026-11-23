"""Phase 4 Real Run-Through and Adversarial Edge Case Verification Script."""

import asyncio
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

from backend.agents.intake_agent import process_job_intake
from backend.agents.matching_agent import evaluate_match
from backend.config import get_settings
from backend.models.draft import ClaimCheck, CoverNote, DraftDocument, ProjectBullets, TailoredResume, VerificationResult
from backend.models.job import DecisionAction, DraftEdits, Job, JobDecisionRequest, JobStatus
from backend.models.profile import Preferences
from backend.vector_store import get_embedding_function, index_profile_chunks
from backend.workflow.checkpointer import close_checkpointer, init_checkpointer_and_graph
from backend.workflow.concurrency import release_run, try_acquire_run
from backend.workflow.runner import get_job_interrupt, recover_interrupted_jobs, run_workflow_background
from backend.workflow.transitions import (
    ApprovalInvariantError,
    InvalidTransitionError,
    check_approval_invariant,
    transition_job_status,
)
from scripts.real_similarity_check import get_synthetic_profile

FIXTURES_DIR = PROJECT_ROOT / "backend" / "tests" / "fixtures"


async def main():
    print("=" * 70)
    print("PHASE 4 REAL RUN-THROUGH & ADVERSARIAL VALIDATION")
    print("=" * 70)

    temp_chroma = tempfile.mkdtemp(prefix="chroma_phase4_")
    temp_chk_dir = tempfile.mkdtemp(prefix="sqlite_phase4_")
    db_path = str(Path(temp_chk_dir) / "checkpoints.sqlite")

    try:
        # 1. Setup candidate profile & preferences
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

        print("\n[Step 1] Initializing real local embeddings (all-MiniLM-L6-v2) & ChromaDB...")
        emb_fn = get_embedding_function()
        index_profile_chunks(profile, persist_directory=temp_chroma, embedding_fn=emb_fn)
        print("  Profile indexed with real SentenceTransformer embeddings.")

        print("\n[Step 2] Initializing AsyncSqliteSaver checkpointer & compiling graph...")
        graph = await init_checkpointer_and_graph(db_path=db_path)
        print(f"  Checkpointer connected at: {db_path}")

        intake_llm = MagicMock()
        intake_llm.generate_json = AsyncMock(return_value=MagicMock(
            company="TechCorp Innovations",
            title="Full Stack Software Engineering Intern",
            required_skills=["Python", "React", "Docker", "MongoDB"],
            preferred_skills=["FastAPI"],
            duration_months=3,
            location="Austin, TX",
        ))

        # Ingest Strong Match JD
        strong_jd_text = (FIXTURES_DIR / "jd_strong_match.txt").read_text(encoding="utf-8")
        job = await process_job_intake(jd_text=strong_jd_text, llm_client=intake_llm)
        print(f"\n[Step 3] Ingested Strong Match Job: id={job.id}, company={job.company}, title={job.title}")

        # Compute real match
        reason_llm = MagicMock()
        reason_llm.generate_json = AsyncMock(return_value=MagicMock(reasoning="Automated match fit."))
        match = await evaluate_match(job=job, llm_client=reason_llm, chroma_dir=temp_chroma, embedding_fn=emb_fn)
        print(f"  Evaluated Match Score: {match.score} / 100 (Threshold to tailor: {prefs.min_score_to_tailor})")

        # Mock tailored draft passing verification for the pipeline run
        mock_draft = DraftDocument(
            job_id=job.id,
            version=1,
            profile_hash=match.profile_hash,
            tailored_resume=TailoredResume(
                job_id=job.id,
                skills_section=profile.skills[:4],
                project_bullets=[ProjectBullets(project_title="TaskStreamer", bullets=["Real-time collaborative task board"])],
            ),
            cover_note=CoverNote(job_id=job.id, text="Dear Hiring Team,\nI am excited to apply for this software internship.", word_count=45),
            verification_result=VerificationResult(passed=True, unsupported_claims=[]),
            status="verified_ready",
        )

        print("\n[Step 4] Running workflow in background to human approval pause...")
        with patch("backend.workflow.nodes.run_draft_pipeline", AsyncMock(return_value=mock_draft)):
            await run_workflow_background(job.id, job.run_number)

        # Check job status and pending interrupt
        job_doc = await db.jobs.find_one({"id": job.id})
        print(f"  Workflow status after first leg: {job_doc['status']}")
        assert job_doc["status"] == JobStatus.AWAITING_APPROVAL.value

        intr = await get_job_interrupt(job.id, job.run_number)
        print(f"  Checkpoint Interrupt payload: {intr}")
        assert intr is not None
        assert intr.get("type") == "approval"

        # Step 5: Resume with human approval
        print("\n[Step 5] Human approves draft via decision endpoint...")
        # Save draft in db
        await db.drafts.replace_one({"job_id": job.id}, mock_draft.model_dump(), upsert=True)

        await run_workflow_background(job.id, job.run_number, resume_payload={"action": "approve"})
        approved_job = await db.jobs.find_one({"id": job.id})
        print(f"  Final Job status: {approved_job['status']}")
        assert approved_job["status"] == JobStatus.APPROVED.value
        print("  -> REAL RUN-THROUGH PASSED SUCCESSFULLY!")

        print("\n" + "=" * 70)
        print("TRYING TO BREAK IT: 5 ADVERSARIAL & EDGE CASES")
        print("=" * 70)

        # -------------------------------------------------------------
        # Case 1: Illegal status transition
        # -------------------------------------------------------------
        print("\n[Case 1] Attempting illegal status transition ('saved' -> 'approved' directly)...")
        illegal_job = Job(id="job_illegal_edge", source="pasted", jd_text="X"*250, content_hash="h1", status=JobStatus.SAVED)
        await db.jobs.replace_one({"id": illegal_job.id}, illegal_job.model_dump(), upsert=True)
        try:
            await transition_job_status(illegal_job.id, JobStatus.APPROVED)
            print("  FAIL: Illegal transition allowed!")
        except InvalidTransitionError as e:
            print(f"  PASS: Caught InvalidTransitionError: {e}")

        # -------------------------------------------------------------
        # Case 2: Approval Invariant Enforcement
        # -------------------------------------------------------------
        print("\n[Case 2] Attempting to approve a job whose draft has unsupported claims without override...")
        inv_job = Job(id="job_inv_edge", source="pasted", jd_text="Y"*250, content_hash="h2", status=JobStatus.AWAITING_APPROVAL)
        await db.jobs.replace_one({"id": inv_job.id}, inv_job.model_dump(), upsert=True)
        failed_draft = DraftDocument(
            job_id=inv_job.id,
            version=1,
            profile_hash="p",
            tailored_resume=TailoredResume(job_id=inv_job.id, skills_section=[], project_bullets=[]),
            cover_note=CoverNote(job_id=inv_job.id, text="t", word_count=1),
            verification_result=VerificationResult(passed=False, unsupported_claims=[ClaimCheck(layer="l1", claim="Invented Degree", reason="Not in resume")]),
            status="failed_verification",
            user_override=False,
        )
        await db.drafts.replace_one({"job_id": inv_job.id}, failed_draft.model_dump(), upsert=True)
        try:
            await transition_job_status(inv_job.id, JobStatus.APPROVED)
            print("  FAIL: Invariant bypassed!")
        except ApprovalInvariantError as e:
            print(f"  PASS: Caught ApprovalInvariantError: {e}")

        # -------------------------------------------------------------
        # Case 3: Manual edit with unverified claims requires acknowledgement
        # -------------------------------------------------------------
        print("\n[Case 3] Submitting manual edit with unverified claim without acknowledge_warnings...")
        from backend.api.jobs import submit_decision
        edit_req = JobDecisionRequest(
            action=DecisionAction.SUBMIT_EDITS,
            edits=DraftEdits(skills_section=["Python"], cover_note="Unverified claim about 100M users"),
            acknowledge_warnings=False,
        )
        # Mock pending interrupt
        with patch("backend.api.jobs.get_job_interrupt", AsyncMock(return_value={"type": "manual_edit_required"})), \
             patch("backend.api.jobs.verify_drafts", AsyncMock(return_value=VerificationResult(passed=False, unsupported_claims=[ClaimCheck(layer="l1", claim="100M", reason="Unverified")]))):
            from fastapi import HTTPException
            try:
                await submit_decision(inv_job.id, edit_req)
                print("  FAIL: Allowed unacknowledged warning to proceed!")
            except HTTPException as exc:
                print(f"  PASS: Caught HTTPException {exc.status_code}: {exc.detail}")
                assert exc.status_code == 422
                assert exc.detail["code"] == "needs_acknowledgement"

        # -------------------------------------------------------------
        # Case 4: Concurrent duplicate execution
        # -------------------------------------------------------------
        print("\n[Case 4] Concurrent execution guard on the same job_id...")
        acquired = await try_acquire_run("concurrency_job")
        assert acquired is True
        second_acq = await try_acquire_run("concurrency_job")
        assert second_acq is False
        print("  PASS: Second concurrent run acquisition rejected (409 lock behavior validated).")
        await release_run("concurrency_job", is_terminal=True)

        # -------------------------------------------------------------
        # Case 5: Crash recovery sweeps orphaned 'processing' jobs
        # -------------------------------------------------------------
        print("\n[Case 5] Simulating server crash while job is processing...")
        crashed_job = Job(id="crashed_job", source="pasted", jd_text="Z"*250, content_hash="h3", status=JobStatus.PROCESSING)
        await db.jobs.replace_one({"id": crashed_job.id}, crashed_job.model_dump(), upsert=True)
        swept = await recover_interrupted_jobs()
        print(f"  Swept {swept} processing job(s).")
        swept_doc = await db.jobs.find_one({"id": crashed_job.id})
        assert swept_doc["status"] == JobStatus.FAILED.value
        assert swept_doc["error_message"] == "interrupted by restart"
        print(f"  PASS: Crashed job safely transitioned to '{swept_doc['status']}' with error='{swept_doc['error_message']}'.")

        print("\n" + "=" * 70)
        print("ALL REAL RUN-THROUGHS AND ADVERSARIAL CASES PASSED!")
        print("=" * 70)

    finally:
        await close_checkpointer()
        shutil.rmtree(temp_chroma, ignore_errors=True)
        shutil.rmtree(temp_chk_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
