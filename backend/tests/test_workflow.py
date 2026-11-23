"""Comprehensive tests for Phase 4: LangGraph workflow, human interrupts, concurrency, and approvals."""

import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from backend.agents.matching_agent import compute_preferences_hash, compute_profile_hash
from backend.database import get_db
from backend.models.draft import (
    ClaimCheck,
    CoverNote,
    DraftDocument,
    ProjectBullets,
    TailoredResume,
    VerificationResult,
)
from backend.models.job import Job, JobStatus
from backend.models.match import Match
from backend.models.profile import Preferences, Profile
from backend.workflow.checkpointer import init_checkpointer_and_graph
from backend.workflow.concurrency import release_run, try_acquire_run
from backend.workflow.runner import get_job_interrupt, recover_interrupted_jobs, run_workflow_background
from backend.workflow.transitions import (
    ApprovalInvariantError,
    check_approval_invariant,
    transition_job_status,
)


@pytest.fixture
def workflow_profile():
    return Profile(
        id="default_profile",
        name="Alex Rivera",
        skills=["Python", "React", "Docker", "PostgreSQL", "FastAPI"],
        education=[],
        projects=[],
        experience=[],
    )


@pytest.fixture
def workflow_preferences():
    return Preferences(
        id="default_preferences",
        target_roles=["Software Engineer Intern"],
        max_duration_months=6,
        preferred_locations=["Austin, TX"],
        remote_ok=True,
        min_score_to_consider=40,
        min_score_to_tailor=70,
    )


@pytest.mark.asyncio
async def test_auto_skip_low_match_score(async_client: AsyncClient, workflow_profile, workflow_preferences, tmp_path):
    """Verify that a job with score < min_score_to_consider (e.g. 25 < 40) auto-skips to skipped status."""
    db = get_db()
    await db.profiles.replace_one({"id": "default_profile"}, workflow_profile.model_dump(), upsert=True)
    await db.preferences.replace_one({"id": "default_preferences"}, workflow_preferences.model_dump(), upsert=True)

    db_path = str(tmp_path / "test_chk_skip.sqlite")
    await init_checkpointer_and_graph(db_path=db_path)

    job = Job(
        id="job_low_match",
        company="LowFit Corp",
        title="Hardware Engineer",
        source="pasted",
        jd_text="A" * 250,
        required_skills=["Verilog"],
        content_hash="hash_low",
        status=JobStatus.SAVED,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)

    prof_hash = compute_profile_hash(workflow_profile)
    pref_hash = compute_preferences_hash(workflow_preferences)

    # Low match score
    low_match = Match(
        job_id=job.id,
        score=25,
        matched_skills=[],
        missing_skills=["Verilog"],
        reasoning="Low fit.",
        preference_conflicts=[],
        profile_hash=prof_hash,
        preferences_hash=pref_hash,
    )
    await db.matches.replace_one({"job_id": job.id}, low_match.model_dump(), upsert=True)

    # Run workflow directly to completion
    await run_workflow_background(job.id, job.run_number)

    updated_job = await db.jobs.find_one({"id": job.id})
    assert updated_job["status"] == JobStatus.SKIPPED.value


@pytest.mark.asyncio
async def test_confirm_tailoring_interrupt_and_skip(async_client: AsyncClient, workflow_profile, workflow_preferences, tmp_path):
    """Verify moderate-scoring job pauses at confirm_tailoring and can be skipped."""
    db = get_db()
    await db.profiles.replace_one({"id": "default_profile"}, workflow_profile.model_dump(), upsert=True)
    await db.preferences.replace_one({"id": "default_preferences"}, workflow_preferences.model_dump(), upsert=True)

    db_path = str(tmp_path / "test_chk_confirm.sqlite")
    await init_checkpointer_and_graph(db_path=db_path)

    job = Job(
        id="job_mid_score",
        company="MidFit Inc",
        title="Full Stack Intern",
        source="pasted",
        jd_text="B" * 250,
        required_skills=["Python", "C++"],
        content_hash="hash_mid",
        status=JobStatus.SAVED,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)

    prof_hash = compute_profile_hash(workflow_profile)
    pref_hash = compute_preferences_hash(workflow_preferences)

    # Score between 40 and 70 (e.g. 55)
    mid_match = Match(
        job_id=job.id,
        score=55,
        matched_skills=["Python"],
        missing_skills=["C++"],
        reasoning="Moderate fit.",
        preference_conflicts=[],
        profile_hash=prof_hash,
        preferences_hash=pref_hash,
    )
    await db.matches.replace_one({"job_id": job.id}, mid_match.model_dump(), upsert=True)

    # Step 1: Run workflow until interrupt
    await run_workflow_background(job.id, job.run_number)

    # Check paused status and interrupt
    paused_job = await db.jobs.find_one({"id": job.id})
    assert paused_job["status"] == JobStatus.AWAITING_CONFIRMATION.value

    intr = await get_job_interrupt(job.id, job.run_number)
    assert intr is not None
    assert intr["type"] == "confirm_tailoring"
    assert intr["score"] == 55

    # Step 2: Skip via decision endpoint
    resp = await async_client.post(f"/jobs/{job.id}/decision", json={"action": "skip"})
    assert resp.status_code == 200
    assert resp.json()["status"] == JobStatus.SKIPPED.value

    final_job = await db.jobs.find_one({"id": job.id})
    assert final_job["status"] == JobStatus.SKIPPED.value


@pytest.mark.asyncio
async def test_approval_interrupt_and_approve(async_client: AsyncClient, workflow_profile, workflow_preferences, tmp_path):
    """Verify high-scoring verified job pauses at approval and can be approved."""
    db = get_db()
    await db.profiles.replace_one({"id": "default_profile"}, workflow_profile.model_dump(), upsert=True)
    await db.preferences.replace_one({"id": "default_preferences"}, workflow_preferences.model_dump(), upsert=True)

    db_path = str(tmp_path / "test_chk_approve.sqlite")
    await init_checkpointer_and_graph(db_path=db_path)

    job = Job(
        id="job_high_score",
        company="HighFit Corp",
        title="Backend Intern",
        source="pasted",
        jd_text="C" * 250,
        required_skills=["Python", "FastAPI"],
        content_hash="hash_high",
        status=JobStatus.SAVED,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)

    prof_hash = compute_profile_hash(workflow_profile)
    pref_hash = compute_preferences_hash(workflow_preferences)

    high_match = Match(
        job_id=job.id,
        score=85,
        matched_skills=["Python", "FastAPI"],
        missing_skills=[],
        reasoning="Strong fit.",
        preference_conflicts=[],
        profile_hash=prof_hash,
        preferences_hash=pref_hash,
    )
    await db.matches.replace_one({"job_id": job.id}, high_match.model_dump(), upsert=True)

    # Mock successful drafting and verification
    mock_draft = DraftDocument(
        job_id=job.id,
        version=1,
        profile_hash=prof_hash,
        tailored_resume=TailoredResume(
            job_id=job.id,
            skills_section=["Python", "FastAPI"],
            project_bullets=[ProjectBullets(project_title="Key Project", bullets=["Built API"])],
        ),
        cover_note=CoverNote(job_id=job.id, text="Good note" * 25, word_count=50),
        verification_result=VerificationResult(passed=True, unsupported_claims=[]),
        status="verified_ready",
    )

    with patch("backend.workflow.nodes.run_draft_pipeline", AsyncMock(return_value=mock_draft)):
        # Run workflow to approval interrupt
        await run_workflow_background(job.id, job.run_number)

    paused_job = await db.jobs.find_one({"id": job.id})
    assert paused_job["status"] == JobStatus.AWAITING_APPROVAL.value

    intr = await get_job_interrupt(job.id, job.run_number)
    assert intr is not None
    assert intr["type"] == "approval"

    # Also persist draft in db for approval invariant check
    await db.drafts.replace_one({"job_id": job.id}, mock_draft.model_dump(), upsert=True)

    # Submit approve decision
    resp = await async_client.post(f"/jobs/{job.id}/decision", json={"action": "approve"})
    assert resp.status_code == 202

    # Give background task brief cycle to complete approve_node
    await asyncio.sleep(0.1)

    approved_job = await db.jobs.find_one({"id": job.id})
    assert approved_job["status"] == JobStatus.APPROVED.value


@pytest.mark.asyncio
async def test_approval_invariant_enforcement(workflow_profile):
    """Verify that approving a job whose latest draft failed verification raises ApprovalInvariantError."""
    db = get_db()
    job = Job(
        id="job_failing_invariant",
        company="Invariant Test",
        title="Intern",
        source="pasted",
        jd_text="D" * 250,
        content_hash="inv_hash",
        status=JobStatus.AWAITING_APPROVAL,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)

    prof_hash = compute_profile_hash(workflow_profile)

    # Stored draft with unsupported claims and no override
    failed_draft = DraftDocument(
        job_id=job.id,
        version=1,
        profile_hash=prof_hash,
        tailored_resume=TailoredResume(job_id=job.id, skills_section=[], project_bullets=[]),
        cover_note=CoverNote(job_id=job.id, text="text", word_count=1),
        verification_result=VerificationResult(
            passed=False,
            unsupported_claims=[ClaimCheck(layer="l1", claim="Fake Claim", reason="Hallucinated")],
        ),
        status="failed_verification",
        user_override=False,
    )
    await db.drafts.replace_one({"job_id": job.id}, failed_draft.model_dump(), upsert=True)

    # Direct invariant check must raise
    with pytest.raises(ApprovalInvariantError):
        await check_approval_invariant(job.id)

    # Direct transition must fail
    with pytest.raises(ApprovalInvariantError):
        await transition_job_status(job.id, JobStatus.APPROVED)


@pytest.mark.asyncio
async def test_manual_edit_flow_with_warning_acknowledgement(async_client: AsyncClient, workflow_profile, workflow_preferences, tmp_path):
    """Verify manual edit flow: unverified edits require acknowledge_warnings=True to resume."""
    db = get_db()
    await db.profiles.replace_one({"id": "default_profile"}, workflow_profile.model_dump(), upsert=True)
    await db.preferences.replace_one({"id": "default_preferences"}, workflow_preferences.model_dump(), upsert=True)

    db_path = str(tmp_path / "test_chk_manual_edit.sqlite")
    await init_checkpointer_and_graph(db_path=db_path)

    job = Job(
        id="job_manual_edit",
        company="EditFit",
        title="Developer",
        source="pasted",
        jd_text="E" * 250,
        content_hash="hash_edit",
        status=JobStatus.SAVED,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)

    prof_hash = compute_profile_hash(workflow_profile)
    pref_hash = compute_preferences_hash(workflow_preferences)

    high_match = Match(
        job_id=job.id,
        score=80,
        matched_skills=["Python"],
        missing_skills=[],
        reasoning="Good.",
        preference_conflicts=[],
        profile_hash=prof_hash,
        preferences_hash=pref_hash,
    )
    await db.matches.replace_one({"job_id": job.id}, high_match.model_dump(), upsert=True)

    # Draft failing verification
    unsupported_claim = ClaimCheck(layer="l1", claim="Inflated Metric 99%", reason="Not in resume")
    failed_draft = DraftDocument(
        job_id=job.id,
        version=1,
        profile_hash=prof_hash,
        tailored_resume=TailoredResume(job_id=job.id, skills_section=["Python"], project_bullets=[]),
        cover_note=CoverNote(job_id=job.id, text="Note with 99%", word_count=20),
        verification_result=VerificationResult(passed=False, unsupported_claims=[unsupported_claim]),
        status="failed_verification",
    )

    with patch("backend.workflow.nodes.run_draft_pipeline", AsyncMock(return_value=failed_draft)):
        await run_workflow_background(job.id, job.run_number)

    paused_job = await db.jobs.find_one({"id": job.id})
    assert paused_job["status"] == JobStatus.AWAITING_MANUAL_EDIT.value

    # Case 1: Submit edits that still fail verification, without acknowledgement -> returns 422
    failing_verification = VerificationResult(passed=False, unsupported_claims=[unsupported_claim])
    with patch("backend.api.jobs.verify_drafts", AsyncMock(return_value=failing_verification)):
        resp_unack = await async_client.post(
            f"/jobs/{job.id}/decision",
            json={
                "action": "submit_edits",
                "edits": {
                    "skills_section": ["Python"],
                    "project_bullets": [],
                    "cover_note": "Still claim 99%",
                },
                "acknowledge_warnings": False,
            },
        )
        assert resp_unack.status_code == 422
        assert resp_unack.json()["detail"]["code"] == "needs_acknowledgement"

    # Workflow must still be paused at manual edit
    paused_job = await db.jobs.find_one({"id": job.id})
    assert paused_job["status"] == JobStatus.AWAITING_MANUAL_EDIT.value

    # Case 2: Submit edits with acknowledge_warnings=True -> records override and returns 202
    with patch("backend.api.jobs.verify_drafts", AsyncMock(return_value=failing_verification)):
        resp_ack = await async_client.post(
            f"/jobs/{job.id}/decision",
            json={
                "action": "submit_edits",
                "edits": {
                    "skills_section": ["Python"],
                    "project_bullets": [],
                    "cover_note": "User insisted on 99%",
                },
                "acknowledge_warnings": True,
            },
        )
        assert resp_ack.status_code == 202

    # Verify override was recorded
    draft = await db.drafts.find_one({"job_id": job.id})
    assert draft["user_override"] is True


@pytest.mark.asyncio
async def test_concurrency_lock_prevents_duplicate_runs():
    """Verify that concurrency lock prevents simultaneous runs on the same job."""
    job_id = "job_concurrency_test"
    acq1 = await try_acquire_run(job_id)
    assert acq1 is True

    # Second acquisition fails
    acq2 = await try_acquire_run(job_id)
    assert acq2 is False

    await release_run(job_id)
    acq3 = await try_acquire_run(job_id)
    assert acq3 is True
    await release_run(job_id, is_terminal=True)


@pytest.mark.asyncio
async def test_startup_recovery_sweeps_interrupted_jobs():
    """Verify startup recovery marks any jobs left in 'processing' status as failed."""
    db = get_db()
    interrupted_job = Job(
        id="job_crashed_on_server",
        company="Crash Corp",
        title="Intern",
        source="pasted",
        jd_text="F" * 250,
        content_hash="crash_hash",
        status=JobStatus.PROCESSING,
    )
    await db.jobs.replace_one({"id": interrupted_job.id}, interrupted_job.model_dump(), upsert=True)

    recovered_count = await recover_interrupted_jobs()
    assert recovered_count >= 1

    doc = await db.jobs.find_one({"id": interrupted_job.id})
    assert doc["status"] == JobStatus.FAILED.value
    assert doc["error_message"] == "interrupted by restart"


@pytest.mark.asyncio
async def test_retry_and_rematch_lifecycle(async_client: AsyncClient, workflow_profile, workflow_preferences):
    """Verify retry on failed jobs and rematch on skipped/failed jobs."""
    db = get_db()
    await db.profiles.replace_one({"id": "default_profile"}, workflow_profile.model_dump(), upsert=True)

    # 1. Retry failed job
    failed_job = Job(
        id="job_failed_for_retry",
        company="Retry Corp",
        title="Intern",
        source="pasted",
        jd_text="G" * 250,
        content_hash="retry_hash",
        status=JobStatus.FAILED,
        error_message="Simulated node network crash",
    )
    await db.jobs.replace_one({"id": failed_job.id}, failed_job.model_dump(), upsert=True)

    with patch("backend.api.jobs.run_workflow_background", AsyncMock()):
        resp_retry = await async_client.post(f"/jobs/{failed_job.id}/retry")
        assert resp_retry.status_code == 202
        assert resp_retry.json()["status"] == JobStatus.PROCESSING.value

    # 2. Rematch allowed on failed job
    with patch("backend.api.jobs.run_workflow_background", AsyncMock()):
        await db.jobs.update_one({"id": failed_job.id}, {"$set": {"status": JobStatus.FAILED.value}})
        resp_rematch = await async_client.post(f"/jobs/{failed_job.id}/rematch")
        assert resp_rematch.status_code == 202
        assert resp_rematch.json()["status"] == JobStatus.PROCESSING.value

        updated = await db.jobs.find_one({"id": failed_job.id})
        assert updated["run_number"] == 2

    # 3. Rematch disallowed on active drafting job -> 409
    await db.jobs.update_one({"id": failed_job.id}, {"$set": {"status": JobStatus.DRAFTING.value}})
    resp_disallowed = await async_client.post(f"/jobs/{failed_job.id}/rematch")
    assert resp_disallowed.status_code == 409


@pytest.mark.asyncio
async def test_patch_status_manual_lifecycle(async_client: AsyncClient):
    """Verify PATCH /jobs/{id}/status only allows applied, interview, closed."""
    db = get_db()
    job = Job(
        id="job_patch_test",
        company="Patch Corp",
        title="Intern",
        source="pasted",
        jd_text="H" * 250,
        content_hash="patch_hash",
        status=JobStatus.APPROVED,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)

    # Disallowed internal status -> 409
    resp_bad = await async_client.patch(f"/jobs/{job.id}/status", json={"status": "drafting"})
    assert resp_bad.status_code == 409

    # Allowed: applied
    resp_applied = await async_client.patch(f"/jobs/{job.id}/status", json={"status": "applied"})
    assert resp_applied.status_code == 200
    assert resp_applied.json()["status"] == JobStatus.APPLIED.value

    # Allowed: interview
    resp_interview = await async_client.patch(f"/jobs/{job.id}/status", json={"status": "interview"})
    assert resp_interview.status_code == 200
    assert resp_interview.json()["status"] == JobStatus.INTERVIEW.value

    # Allowed: closed
    resp_closed = await async_client.patch(f"/jobs/{job.id}/status", json={"status": "closed"})
    assert resp_closed.status_code == 200
    assert resp_closed.json()["status"] == JobStatus.CLOSED.value


@pytest.mark.asyncio
async def test_audit_logs_endpoint(async_client: AsyncClient):
    """Verify GET /logs returns audit entries with job_id filtering."""
    db = get_db()
    from backend.models.logs import write_agent_log

    test_job_id = "job_audit_test"
    await write_agent_log(
        agent_name="test_agent",
        status="success",
        summary={"metric_count": 5},
        job_id=test_job_id,
    )

    resp = await async_client.get(f"/logs?job_id={test_job_id}")
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 1
    assert logs[0]["job_id"] == test_job_id
    assert logs[0]["agent_name"] == "test_agent"
