"""Comprehensive tests for Profile Agent, resume parser, ChromaDB vector indexing, and API routes."""

import io
import os
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from chromadb.api.types import EmbeddingFunction
from fastapi import HTTPException
from httpx import AsyncClient

from backend.agents.profile_agent import parse_and_store_resume, update_profile
from backend.config import get_settings, normalize_skills
from backend.database import get_db
from backend.main import app
from backend.models.profile import Education, Experience, Preferences, Profile, Project
from backend.services.resume_parser import extract_resume_text, validate_file_metadata
from backend.vector_store import (
    delete_profile_chunks,
    get_chroma_client,
    index_profile_chunks,
)


class MockEmbeddingFunction(EmbeddingFunction):
    """Fast, deterministic in-memory mock embedding function for test isolation."""

    def name(self) -> str:
        return "mock_embedding"

    def __call__(self, input):
        return [[0.1] * 384 for _ in input]


@pytest.fixture
def mock_embedding_fn():
    """Fixture returning deterministic mock embedding function."""
    return MockEmbeddingFunction()


@pytest.fixture
def temp_chroma_dir():
    """Fixture creating and cleaning up a temporary directory for ChromaDB in tests."""
    temp_dir = tempfile.mkdtemp(prefix="chroma_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_profile_data():
    """Fixture returning synthetic valid Profile model."""
    return Profile(
        id="default_profile",
        name="Alex Rivera",
        education=[
            Education(
                institution="State University of Technology",
                degree="Bachelor of Science",
                field="Computer Science",
                start_year=2021,
                end_year=2025,
                cgpa=3.85,
            )
        ],
        skills=["reactjs", "node", "Python", "Docker", "k8s"],
        projects=[
            Project(
                title="TaskStreamer",
                bullets=["Developed collaboration board with WebSocket support.", "Improved DB latency by 35%."],
                tech=["ReactJS", "node", "MongoDB"],
            )
        ],
        experience=[
            Experience(
                company="TechLabs Solutions",
                role="Software Engineering Intern",
                start_date="June 2024",
                end_date="August 2024",
                bullets=["Engineered 8 RESTful endpoints.", "Cut CI/CD pipeline time by 20%."],
            )
        ],
        links={"github": "https://github.com/alexrivera-fake"},
    )


# ---------------------------------------------------------------------------
# 1. Resume Parser Tests (Size, Extension, Signature, Scanned / Short text)
# ---------------------------------------------------------------------------

def test_resume_parser_rejects_oversized_file():
    """Verify that files exceeding 5 MB trigger HTTP 413."""
    oversized_bytes = b"0" * (5 * 1024 * 1024 + 10)
    with pytest.raises(HTTPException) as exc_info:
        validate_file_metadata(oversized_bytes, "large_resume.pdf")
    assert exc_info.value.status_code == 413
    assert "exceeds maximum allowed size" in exc_info.value.detail


def test_resume_parser_rejects_unsupported_extension():
    """Verify that unsupported extensions trigger HTTP 400."""
    with pytest.raises(HTTPException) as exc_info:
        validate_file_metadata(b"plain content", "resume.txt")
    assert exc_info.value.status_code == 400
    assert "Unsupported file format" in exc_info.value.detail


def test_resume_parser_rejects_invalid_file_signature():
    """Verify that file extension and binary magic signature mismatch triggers HTTP 400."""
    fake_pdf = b"NOT_A_PDF_HEADER_CONTENT"
    with pytest.raises(HTTPException) as exc_info:
        validate_file_metadata(fake_pdf, "resume.pdf")
    assert exc_info.value.status_code == 400
    assert "Invalid file signature" in exc_info.value.detail

    fake_docx = b"NOT_A_PK_ZIP_HEADER"
    with pytest.raises(HTTPException) as exc_info:
        validate_file_metadata(fake_docx, "resume.docx")
    assert exc_info.value.status_code == 400
    assert "Invalid file signature" in exc_info.value.detail


def test_resume_parser_scanned_pdf_triggers_422():
    """Verify that extracted text under 200 characters triggers HTTP 422."""
    short_content = b"%PDF-1.4\nshort content"
    with patch("backend.services.resume_parser.extract_text_from_pdf", return_value="Short text"):
        with pytest.raises(HTTPException) as exc_info:
            extract_resume_text(short_content, "scanned.pdf")
        assert exc_info.value.status_code == 422
        assert "under 200 characters" in exc_info.value.detail


def test_resume_parser_synthetic_pdf_and_docx_fixtures():
    """Verify that synthetic PDF and DOCX fixture files parse text successfully."""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    pdf_path = os.path.join(fixtures_dir, "sample_resume.pdf")
    docx_path = os.path.join(fixtures_dir, "sample_resume.docx")

    assert os.path.exists(pdf_path)
    assert os.path.exists(docx_path)

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    pdf_text = extract_resume_text(pdf_bytes, "sample_resume.pdf")
    assert len(pdf_text) >= 200
    assert "Alex Rivera" in pdf_text or "ALEX RIVERA" in pdf_text

    with open(docx_path, "rb") as f:
        docx_bytes = f.read()
    docx_text = extract_resume_text(docx_bytes, "sample_resume.docx")
    assert len(docx_text) >= 200
    assert "Alex Rivera" in docx_text or "ALEX RIVERA" in docx_text


# ---------------------------------------------------------------------------
# 2. Skill Normalization Tests
# ---------------------------------------------------------------------------

def test_skill_normalization_canonical_and_deduplication():
    """Verify deterministic skill deduplication and canonical alias mapping."""
    raw_skills = ["reactjs", "React", "node", "Node.js", "Python", "python3", "k8s", "Docker"]
    normalized = normalize_skills(raw_skills)
    assert normalized == ["React", "Node.js", "Python", "Kubernetes", "Docker"]


# ---------------------------------------------------------------------------
# 3. ChromaDB Chunking and Duplicate Prevention
# ---------------------------------------------------------------------------

def test_chroma_indexing_and_duplicate_prevention(temp_chroma_dir, mock_embedding_fn, sample_profile_data):
    """Verify ChromaDB indexes chunks and deletes old ones on re-upload to avoid duplicates."""
    count1 = index_profile_chunks(
        sample_profile_data,
        persist_directory=temp_chroma_dir,
        embedding_fn=mock_embedding_fn,
    )
    assert count1 == 3  # 1 skills chunk + 1 project chunk + 1 experience chunk

    client = get_chroma_client(temp_chroma_dir)
    collection = client.get_collection("profile_chunks")
    assert collection.count() == 3

    # Re-indexing the same profile (e.g. after edits)
    sample_profile_data.skills = ["React", "Python"]
    count2 = index_profile_chunks(
        sample_profile_data,
        persist_directory=temp_chroma_dir,
        embedding_fn=mock_embedding_fn,
    )
    assert count2 == 3
    # Total count in collection must still be exactly 3, not 6
    assert collection.count() == 3


# ---------------------------------------------------------------------------
# 4. Profile Agent LLM Retry and Failure Handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_profile_agent_llm_retry_on_validation_failure(temp_chroma_dir, mock_embedding_fn, sample_profile_data):
    """Verify that if LLM parsing initially fails, profile_agent retries once with error feedback."""
    mock_llm = MagicMock()
    # First attempt raises ValueError (simulating schema mismatch), second attempt succeeds
    mock_llm.generate_json = AsyncMock(side_effect=[
        ValueError("Missing required field 'name'"),
        sample_profile_data,
    ])

    fake_pdf = b"%PDF-1.4\n" + (b"Alex Rivera Resume Content " * 20)
    with patch("backend.services.resume_parser.extract_text_from_pdf", return_value="Alex Rivera " * 30):
        profile = await parse_and_store_resume(
            file_bytes=fake_pdf,
            filename="resume.pdf",
            llm_client=mock_llm,
            chroma_dir=temp_chroma_dir,
            embedding_fn=mock_embedding_fn,
        )
        assert profile.name == "Alex Rivera"
        assert mock_llm.generate_json.await_count == 2


@pytest.mark.asyncio
async def test_profile_agent_llm_failure_logs_and_stores_nothing(temp_chroma_dir, mock_embedding_fn):
    """Verify that if LLM parsing fails twice, HTTP 422 is raised and failure is logged in agent_log."""
    mock_llm = MagicMock()
    mock_llm.generate_json = AsyncMock(side_effect=ValueError("Persistent schema error"))

    fake_pdf = b"%PDF-1.4\n" + (b"Alex Rivera Resume Content " * 20)
    with patch("backend.services.resume_parser.extract_text_from_pdf", return_value="Alex Rivera " * 30):
        with pytest.raises(HTTPException) as exc_info:
            await parse_and_store_resume(
                file_bytes=fake_pdf,
                filename="resume.pdf",
                llm_client=mock_llm,
                chroma_dir=temp_chroma_dir,
                embedding_fn=mock_embedding_fn,
            )
        assert exc_info.value.status_code == 422
        assert "Failed to parse resume" in exc_info.value.detail

        # Check agent_log contains failure entry with summary only
        db = get_db()
        last_log = await db.agent_log.find_one({"agent_name": "profile_agent"}, sort=[("timestamp", -1)])
        assert last_log is not None
        assert last_log["status"] == "failure"
        assert "error" in last_log["summary"]


# ---------------------------------------------------------------------------
# 5. Preferences Validation Tests
# ---------------------------------------------------------------------------

def test_preferences_validation_thresholds():
    """Verify validation rules: min_score_to_consider < min_score_to_tailor and max_duration_months > 0."""
    valid = Preferences(
        min_score_to_consider=40,
        min_score_to_tailor=70,
        max_duration_months=6,
    )
    assert valid.min_score_to_consider == 40

    with pytest.raises(ValueError, match="strictly less than"):
        Preferences(min_score_to_consider=80, min_score_to_tailor=70)

    with pytest.raises(ValueError, match="greater than 0"):
        Preferences(max_duration_months=0)


# ---------------------------------------------------------------------------
# 6. API Endpoints Integration Tests (Upload, GET, PUT Profile & Preferences)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_profile_and_preferences_lifecycle(async_client: AsyncClient, sample_profile_data, temp_chroma_dir, mock_embedding_fn):
    """Test full API lifecycle: GET empty profile (404), PUT & GET preferences, upload resume, GET profile."""
    db = get_db()
    await db.profiles.delete_many({})
    await db.preferences.delete_many({})

    # 1. GET /profile on empty database returns 404
    resp = await async_client.get("/profile")
    assert resp.status_code == 404

    # 2. GET /preferences returns defaults
    resp_pref = await async_client.get("/preferences")
    assert resp_pref.status_code == 200
    pref_data = resp_pref.json()
    assert pref_data["min_score_to_tailor"] == 70
    assert pref_data["min_score_to_consider"] == 40
    assert pref_data["max_duration_months"] == 6

    # 3. PUT /preferences with invalid data returns 422
    resp_bad_pref = await async_client.put(
        "/preferences",
        json={"min_score_to_consider": 85, "min_score_to_tailor": 70, "max_duration_months": 6},
    )
    assert resp_bad_pref.status_code == 422

    # 4. PUT /preferences with valid data returns 200
    resp_good_pref = await async_client.put(
        "/preferences",
        json={
            "target_roles": ["Software Engineer Intern"],
            "max_duration_months": 4,
            "min_score_to_tailor": 75,
            "min_score_to_consider": 45,
            "preferred_locations": ["Austin, TX"],
            "remote_ok": True,
            "emphasise_skills": ["Python", "React"],
            "avoid_skills": [],
        },
    )
    assert resp_good_pref.status_code == 200
    assert resp_good_pref.json()["min_score_to_tailor"] == 75

    # 5. POST /profile/upload with mocked LLM and vector store
    fake_pdf_bytes = b"%PDF-1.4\n" + (b"Alex Rivera Synthetic Resume Content " * 20)
    with patch("backend.api.profile.parse_and_store_resume") as mock_parse:
        mock_parse.return_value = sample_profile_data
        files = {"file": ("alex_rivera_resume.pdf", io.BytesIO(fake_pdf_bytes), "application/pdf")}
        upload_resp = await async_client.post("/profile/upload", files=files)
        assert upload_resp.status_code == 200
        data = upload_resp.json()
        assert data["name"] == "Alex Rivera"

    # 6. PUT /profile update
    with patch("backend.api.profile.update_profile", return_value=sample_profile_data):
        put_resp = await async_client.put("/profile", json=sample_profile_data.model_dump())
        assert put_resp.status_code == 200
        assert put_resp.json()["name"] == "Alex Rivera"


# ---------------------------------------------------------------------------
# 7. Slow Real SentenceTransformer Test
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_real_sentence_transformers_embedding(temp_chroma_dir, sample_profile_data):
    """Slow integration test executing real local sentence-transformers model without mock."""
    count = index_profile_chunks(sample_profile_data, persist_directory=temp_chroma_dir)
    assert count == 3
