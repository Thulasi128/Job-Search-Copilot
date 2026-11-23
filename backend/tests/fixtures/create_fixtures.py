"""Script to generate synthetic PDF and DOCX resume fixtures for test suites."""

import io
from pathlib import Path
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    StreamObject,
)

FIXTURES_DIR = Path(__file__).resolve().parent
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

SYNTHETIC_RESUME_TEXT = """ALEX RIVERA
Email: alex.rivera.fake@example.com | Phone: (555) 019-2834 | Location: Austin, TX
GitHub: https://github.com/alexrivera-fake | LinkedIn: https://linkedin.com/in/alexrivera-fake

EDUCATION
State University of Technology, Austin, TX
Bachelor of Science in Computer Science | Expected May 2025
CGPA: 3.85 / 4.0 | Relevant Coursework: Data Structures, Distributed Systems, Web Architectures

TECHNICAL SKILLS
Languages: Python, TypeScript, JavaScript, SQL, Go
Frameworks & Libraries: ReactJS, Node.js, FastAPI, Express
Tools & Cloud: Docker, PostgreSQL, MongoDB, Git, CI/CD, AWS

PROJECTS
TaskStreamer — Real-Time Collaboration Workspace (React, Node, MongoDB)
• Developed an open-source collaboration board supporting concurrent WebSocket editing for over 500 active users.
• Architected scalable MongoDB aggregation pipelines improving dashboard load latency by 35%.
• Implemented automated integration suites in GitHub Actions achieving 92% code coverage.

DataPipeline CLI — Distributed Ingestion Framework (Python, Docker, PostgreSQL)
• Built a concurrent event stream processing engine ingesting 100,000 JSON records daily into PostgreSQL.
• Containerized worker microservices with Docker Compose for consistent local development and staging environments.

EXPERIENCE
Software Engineering Intern | TechLabs Solutions, Austin, TX
June 2024 – August 2024
• Engineered 8 production RESTful endpoints using FastAPI and PostgreSQL handling 20,000 daily requests.
• Collaborated in an agile team of 6 engineers, participating in bi-weekly sprints and rigorous code reviews.
• Reduced continuous deployment pipeline cycle time by 20% by introducing parallel test runners.
"""

SHORT_TEXT = "Alex Rivera - Resume. Contact: test@example.com"


def create_pdf(text: str, output_path: Path) -> None:
    """Create a valid searchable text PDF using pypdf without external binary dependencies."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    # Encode text safely for PDF Tj operator
    safe_lines = []
    y_pos = 720
    for line in text.split("\n"):
        clean = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        safe_lines.append(f"1 0 0 1 50 {y_pos} Tm ({clean}) Tj")
        y_pos -= 14

    stream_content = "BT /F1 10 Tf\n" + "\n".join(safe_lines) + "\nET"

    font_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_dict}),
    })
    page[NameObject("/Resources")] = resources

    stream = StreamObject()
    stream._data = stream_content.encode("latin-1", "replace")
    stream[NameObject("/Length")] = NumberObject(len(stream._data))
    page[NameObject("/Contents")] = stream

    with open(output_path, "wb") as f:
        writer.write(f)


def create_docx(text: str, output_path: Path) -> None:
    """Create a valid DOCX file using python-docx."""
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    doc.save(output_path)


if __name__ == "__main__":
    pdf_path = FIXTURES_DIR / "sample_resume.pdf"
    docx_path = FIXTURES_DIR / "sample_resume.docx"
    scanned_path = FIXTURES_DIR / "scanned_resume.pdf"

    print("Generating sample_resume.pdf...")
    create_pdf(SYNTHETIC_RESUME_TEXT, pdf_path)

    print("Generating sample_resume.docx...")
    create_docx(SYNTHETIC_RESUME_TEXT, docx_path)

    print("Generating scanned_resume.pdf (<200 chars)...")
    create_pdf(SHORT_TEXT, scanned_path)

    print("All fixtures generated successfully.")

