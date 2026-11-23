"""FastAPI routes for resume profile upload, profile management, and job preferences."""

import logging
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.agents.profile_agent import parse_and_store_resume, update_profile
from backend.config import get_settings
from backend.database import get_db
from backend.models.profile import Preferences, Profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Profile & Preferences"])


@router.post("/profile/upload", response_model=Profile, status_code=status.HTTP_200_OK)
async def upload_resume(file: UploadFile = File(...)) -> Profile:
    """Upload and parse a resume file (PDF or DOCX).

    Extracts text, parses into structured Profile via LLM, saves to MongoDB,
    and indexes experience and project chunks into ChromaDB.

    Args:
        file: Uploaded PDF or DOCX file.

    Returns:
        Profile: Stored profile document.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename.",
        )

    file_bytes = await file.read()
    return await parse_and_store_resume(file_bytes=file_bytes, filename=file.filename)


@router.get("/profile", response_model=Profile, status_code=status.HTTP_200_OK)
async def get_profile() -> Profile:
    """Retrieve the current user profile.

    Returns:
        Profile: Stored profile document.

    Raises:
        HTTPException: 404 if no profile has been uploaded yet.
    """
    settings = get_settings()
    db = get_db()
    doc = await db.profiles.find_one({"id": settings.DEFAULT_PROFILE_ID})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Please upload a resume first.",
        )
    return Profile.model_validate(doc)


@router.put("/profile", response_model=Profile, status_code=status.HTTP_200_OK)
async def put_profile(profile_data: Profile) -> Profile:
    """Update the candidate profile and re-index vector chunks in ChromaDB.

    Args:
        profile_data: Updated Profile fields.

    Returns:
        Profile: The updated profile document.
    """
    return await update_profile(profile_data=profile_data)


@router.get("/preferences", response_model=Preferences, status_code=status.HTTP_200_OK)
async def get_preferences() -> Preferences:
    """Retrieve job preferences. Returns system defaults if none have been set.

    Returns:
        Preferences: Active or default preferences model.
    """
    db = get_db()
    doc = await db.preferences.find_one({"id": "default_preferences"})
    if not doc:
        return Preferences()
    return Preferences.model_validate(doc)


@router.put("/preferences", response_model=Preferences, status_code=status.HTTP_200_OK)
async def put_preferences(preferences: Preferences) -> Preferences:
    """Save or update job search preferences.

    Validates that:
      - max_duration_months > 0
      - 0 <= min_score_to_consider < min_score_to_tailor <= 100

    Args:
        preferences: Updated preferences.

    Returns:
        Preferences: Stored preferences.
    """
    db = get_db()
    pref_dict = preferences.model_dump()
    pref_dict["id"] = "default_preferences"
    await db.preferences.replace_one(
        {"id": "default_preferences"},
        pref_dict,
        upsert=True,
    )
    return preferences

