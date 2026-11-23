"""Unit tests for the application export endpoint (DOCX and Markdown)."""

import io
from docx import Document
import pytest
from httpx import AsyncClient

from backend.database import get_db
from backend.models.draft import CoverNote, DraftDocument, ProjectBullets, TailoredResume, VerificationResult
from backend.models.job import Job, JobStatus


@pytest.fixture
async def sample_job_and_draft():
    db = get_db()
    job = Job(
        id="job_export_test",
        company="Acme Robotics",
        title="Software Intern",
        source="pasted",
        jd_text="A" * 250,
        content_hash="hash_export",
        status=JobStatus.APPROVED,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)

    draft = DraftDocument(
        job_id=job.id,
        version=1,
        profile_hash="prof_hash",
        tailored_resume=TailoredResume(
            job_id=job.id,
            skills_section=["Python", "FastAPI", "Docker", "ROS"],
            project_bullets=[
                ProjectBullets(
                    project_title="RoboVision System",
                    bullets=[
                        "Implemented OpenCV object detection pipeline reaching 30 FPS.",
                        "Integrated ROS node publishing coordinate topics with 99.8% uptime.",
                    ],
                )
            ],
        ),
        cover_note=CoverNote(
            job_id=job.id,
            text="Dear Hiring Team at Acme Robotics,\n\nI am eager to contribute to software robotics.",
            word_count=15,
        ),
        verification_result=VerificationResult(passed=True, unsupported_claims=[]),
        status="verified_ready",
    )
    await db.drafts.replace_one({"job_id": job.id}, draft.model_dump(), upsert=True)

    return job, draft


@pytest.mark.asyncio
async def test_export_markdown(async_client: AsyncClient, sample_job_and_draft):
    job, _ = sample_job_and_draft
    resp = await async_client.get(f"/export/{job.id}?format=md")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert f'filename="Application_Acme_Robotics_{job.id[:8]}.md"' in resp.headers["content-disposition"]

    text = resp.text
    assert "# Application Draft: Software Intern at Acme Robotics" in text
    assert "## Tailored Skills" in text
    assert "- Python" in text
    assert "- ROS" in text
    assert "### RoboVision System" in text
    assert "Implemented OpenCV object detection" in text
    assert "## Cover Note" in text
    assert "Dear Hiring Team at Acme Robotics" in text


@pytest.mark.asyncio
async def test_export_docx(async_client: AsyncClient, sample_job_and_draft):
    job, _ = sample_job_and_draft
    resp = await async_client.get(f"/export/{job.id}?format=docx")
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in resp.headers["content-type"]
    assert f'filename="Application_Acme_Robotics_{job.id[:8]}.docx"' in resp.headers["content-disposition"]

    # Read binary bytes back with docx
    file_bytes = io.BytesIO(resp.content)
    doc = Document(file_bytes)

    full_text = "\n".join([p.text for p in doc.paragraphs])
    assert "Application Draft: Software Intern" in full_text
    assert "Target Company: Acme Robotics" in full_text
    assert "Tailored Skills" in full_text
    assert "Python" in full_text
    assert "RoboVision System" in full_text
    assert "Dear Hiring Team at Acme Robotics" in full_text


@pytest.mark.asyncio
async def test_export_404_for_missing_job(async_client: AsyncClient):
    resp = await async_client.get("/export/non_existent_job_id")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_404_for_missing_draft(async_client: AsyncClient):
    db = get_db()
    job = Job(
        id="job_without_draft",
        company="Draftless Corp",
        title="Intern",
        source="pasted",
        jd_text="B" * 250,
        content_hash="h_no_draft",
        status=JobStatus.APPROVED,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)
    await db.drafts.delete_many({"job_id": job.id})

    resp = await async_client.get(f"/export/{job.id}")
    assert resp.status_code == 404
    assert "no application draft found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_409_for_unapproved_job(async_client: AsyncClient):
    db = get_db()
    job = Job(
        id="job_unapproved_export",
        company="Pending Corp",
        title="Intern",
        source="pasted",
        jd_text="C" * 250,
        content_hash="h_unapproved",
        status=JobStatus.AWAITING_APPROVAL,
    )
    await db.jobs.replace_one({"id": job.id}, job.model_dump(), upsert=True)

    resp = await async_client.get(f"/export/{job.id}")
    assert resp.status_code == 409
    assert "only be exported after human approval" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_400_for_invalid_format(async_client: AsyncClient, sample_job_and_draft):
    job, _ = sample_job_and_draft
    resp = await async_client.get(f"/export/{job.id}?format=pdf")
    assert resp.status_code == 400
    assert "unsupported format 'pdf'" in resp.json()["detail"].lower()

