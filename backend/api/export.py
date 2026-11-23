"""FastAPI routes for exporting tailored application materials (DOCX and Markdown)."""

import io
import logging
from typing import Optional
from docx import Document
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from backend.database import get_db
from backend.models.draft import DraftDocument
from backend.models.job import Job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["Application Export"])


def generate_markdown(job: Job, draft: DraftDocument) -> str:
    """Generate Markdown text from job and draft document."""
    md_lines = [
        f"# Application Draft: {job.title or 'Internship Role'} at {job.company or 'Target Company'}",
        f"*Source: {job.source} | Job ID: {job.id}*",
        "",
        "## Tailored Skills",
        "",
    ]
    for skill in (draft.tailored_resume.skills_section or []):
        md_lines.append(f"- {skill}")

    md_lines.extend(["", "## Tailored Project Experience", ""])
    for proj in (draft.tailored_resume.project_bullets or []):
        md_lines.append(f"### {proj.project_title}")
        for bullet in (proj.bullets or []):
            md_lines.append(f"- {bullet}")
        md_lines.append("")

    md_lines.extend(["## Cover Note", "", draft.cover_note.text or "", ""])
    return "\n".join(md_lines)


def generate_docx(job: Job, draft: DraftDocument) -> bytes:
    """Generate DOCX bytes from job and draft document."""
    doc = Document()

    # Document Header
    title = f"Application Draft: {job.title or 'Internship Role'}"
    doc.add_heading(title, level=0)
    p_sub = doc.add_paragraph()
    p_sub.add_run(f"Target Company: {job.company or 'Unknown Company'}\n")
    p_sub.add_run(f"Job ID: {job.id} | Source: {job.source}")

    # Section 1: Tailored Skills
    doc.add_heading("Tailored Skills", level=1)
    for skill in (draft.tailored_resume.skills_section or []):
        doc.add_paragraph(skill, style="List Bullet")

    # Section 2: Tailored Project Experience
    doc.add_heading("Tailored Project Experience", level=1)
    for proj in (draft.tailored_resume.project_bullets or []):
        doc.add_heading(proj.project_title, level=2)
        for bullet in (proj.bullets or []):
            doc.add_paragraph(bullet, style="List Bullet")

    # Section 3: Cover Note
    doc.add_heading("Cover Note", level=1)
    cover_text = draft.cover_note.text or ""
    for para in cover_text.split("\n\n"):
        if para.strip():
            doc.add_paragraph(para.strip())

    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)
    return stream.getvalue()


@router.get("/{job_id}", status_code=status.HTTP_200_OK)
async def export_application(
    job_id: str,
    format: Optional[str] = Query("docx", description="Export format: 'docx' or 'md'"),
) -> Response:
    """Export tailored application draft (skills, project bullets, cover note) as DOCX or Markdown.

    Args:
        job_id: Identifier of the job opportunity.
        format: Desired export format ('docx' or 'md').

    Returns:
        StreamingResponse or Response: Downloadable file attachment.

    Raises:
        HTTPException: 404 if job or draft document does not exist, 400 if unsupported format.
    """
    db = get_db()
    job_doc = await db.jobs.find_one({"id": job_id})
    if not job_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found.",
        )
    job = Job.model_validate(job_doc)

    # Export is permitted only for approved or applied/interview/closed jobs
    from backend.models.job import JobStatus
    allowed_export_statuses = {JobStatus.APPROVED, JobStatus.APPLIED, JobStatus.INTERVIEW, JobStatus.CLOSED}
    if job.status not in allowed_export_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is in status '{job.status.value}'. Materials can only be exported after human approval.",
        )

    draft_doc = await db.drafts.find_one({"job_id": job_id}, sort=[("created_at", -1)])
    if not draft_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No application draft found for job '{job_id}'. Please run tailoring first.",
        )
    draft = DraftDocument.model_validate(draft_doc)

    fmt = (format or "docx").lower().strip()
    company_clean = (job.company or "Job").replace(" ", "_")
    safe_filename_base = f"Application_{company_clean}_{job.id[:8]}"

    if fmt in ("md", "markdown"):
        md_content = generate_markdown(job, draft)
        return Response(
            content=md_content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename_base}.md"'},
        )

    elif fmt == "docx":
        docx_bytes = generate_docx(job, draft)
        return StreamingResponse(
            io.BytesIO(docx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename_base}.docx"'},
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{fmt}'. Allowed formats are 'docx' and 'md'.",
        )
