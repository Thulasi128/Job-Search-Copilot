"""Profile agent responsible for resume extraction, LLM parsing, normalization, and indexing."""

import logging
from pathlib import Path
from typing import Any, Optional
from fastapi import HTTPException, status

from backend.config import get_settings, normalize_skills
from backend.database import get_db
from backend.llm.client import LLMClient, get_llm_client
from backend.models.logs import write_agent_log
from backend.models.profile import Profile
from backend.services.resume_parser import extract_resume_text
from backend.vector_store import index_profile_chunks

logger = logging.getLogger(__name__)

PROMPT_FILE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "profile_parse.md"


def get_profile_parse_prompt() -> str:
    """Read the profile parse prompt template from the backend/prompts/ directory.

    Returns:
        str: Prompt template instructions for the LLM.
    """
    if not PROMPT_FILE_PATH.exists():
        raise FileNotFoundError(f"Profile parse prompt template not found at {PROMPT_FILE_PATH}")
    return PROMPT_FILE_PATH.read_text(encoding="utf-8")


async def parse_and_store_resume(
    file_bytes: bytes,
    filename: str,
    llm_client: Optional[LLMClient] = None,
    chroma_dir: Optional[str] = None,
    embedding_fn: Optional[Any] = None,
) -> Profile:
    """Process an uploaded resume: extract text, parse via LLM with retry, normalize skills, save, and index.

    Order of operations:
      1. Extract text from file (checks 5MB limit, binary signature, min text length).
      2. LLM JSON extraction with automatic 1-retry on Pydantic validation failure.
      3. Deterministic Python skill normalization and deduplication.
      4. Save validated Profile to MongoDB.
      5. Index chunks into ChromaDB (deleting all prior chunks for this profile first).
      6. Record audit summary in agent_log.

    Args:
        file_bytes: Raw file content bytes.
        filename: Name of the uploaded file.
        llm_client: Optional LLMClient instance (for testing/mocking).
        chroma_dir: Optional Chroma directory override.
        embedding_fn: Optional embedding function override for ChromaDB.

    Returns:
        Profile: Stored and validated candidate profile.

    Raises:
        HTTPException: On validation failure, parsing failure, or database/vector error.
    """
    settings = get_settings()
    profile_id = settings.DEFAULT_PROFILE_ID

    # Step 1: Text extraction
    extracted_text = extract_resume_text(file_bytes, filename)

    # Step 2: LLM JSON extraction with 1 retry on Pydantic failure
    client = llm_client or get_llm_client()
    system_prompt = get_profile_parse_prompt()
    user_prompt = f"Extract the profile from this resume text:\n\n{extracted_text}"

    parsed_profile: Optional[Profile] = None
    try:
        parsed_profile = await client.generate_json(
            prompt=user_prompt,
            schema=Profile,
            system_instruction=system_prompt,
        )
    except Exception as first_exc:
        logger.warning(
            "Initial LLM profile parsing validation failed: %s. Retrying once with error feedback...",
            first_exc,
        )
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"IMPORTANT: The previous output failed Pydantic validation with this error:\n"
            f"{str(first_exc)}\n"
            "Please ensure the JSON strictly conforms to the Profile schema."
        )
        try:
            parsed_profile = await client.generate_json(
                prompt=retry_prompt,
                schema=Profile,
                system_instruction=system_prompt,
            )
        except Exception as retry_exc:
            logger.error("LLM profile parsing retry failed: %s", retry_exc)
            await write_agent_log(
                agent_name="profile_agent",
                status="failure",
                summary={
                    "filename": filename,
                    "error": f"LLM parsing validation failed after retry: {str(retry_exc)}",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to parse resume into structured profile: {str(retry_exc)}",
            )

    # Step 3: Deterministic Python skill normalisation and deduplication
    parsed_profile.id = profile_id
    parsed_profile.skills = normalize_skills(parsed_profile.skills)
    for project in parsed_profile.projects:
        project.tech = normalize_skills(project.tech)

    # Step 4: Save to MongoDB
    try:
        db = get_db()
        await db.profiles.replace_one(
            {"id": profile_id},
            parsed_profile.model_dump(),
            upsert=True,
        )
        logger.info("Saved profile to MongoDB for profile_id=%s", profile_id)
    except Exception as db_exc:
        logger.error("Failed to save profile to MongoDB: %s", db_exc)
        await write_agent_log(
            agent_name="profile_agent",
            status="failure",
            summary={"filename": filename, "error": f"MongoDB write failed: {str(db_exc)}"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save profile to database: {str(db_exc)}",
        )

    # Step 5: Index chunks into ChromaDB (deletes all existing chunks first)
    try:
        chunk_count = index_profile_chunks(
            profile=parsed_profile,
            persist_directory=chroma_dir,
            embedding_fn=embedding_fn,
        )
    except Exception as chroma_exc:
        logger.error("ChromaDB vector indexing failed: %s", chroma_exc)
        await write_agent_log(
            agent_name="profile_agent",
            status="failure",
            summary={
                "filename": filename,
                "error": f"ChromaDB indexing failed: {str(chroma_exc)}",
                "skills_count": len(parsed_profile.skills),
                "projects_count": len(parsed_profile.projects),
                "experiences_count": len(parsed_profile.experience),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Profile saved to database, but vector indexing failed: {str(chroma_exc)}",
        )

    # Step 6: Log success audit summary (only summary stats, never raw text)
    await write_agent_log(
        agent_name="profile_agent",
        status="success",
        summary={
            "filename": filename,
            "skills_count": len(parsed_profile.skills),
            "projects_count": len(parsed_profile.projects),
            "experiences_count": len(parsed_profile.experience),
            "chunks_indexed": chunk_count,
        },
    )

    return parsed_profile


async def update_profile(
    profile_data: Profile,
    chroma_dir: Optional[str] = None,
    embedding_fn: Optional[Any] = None,
) -> Profile:
    """Update profile in MongoDB and re-index vector chunks in ChromaDB.

    Args:
        profile_data: Updated Profile model.
        chroma_dir: Optional Chroma directory override.
        embedding_fn: Optional embedding function override.

    Returns:
        Profile: Updated profile.
    """
    settings = get_settings()
    profile_id = settings.DEFAULT_PROFILE_ID

    # Deterministic normalization
    profile_data.id = profile_id
    profile_data.skills = normalize_skills(profile_data.skills)
    for project in profile_data.projects:
        project.tech = normalize_skills(project.tech)

    # Save to MongoDB
    db = get_db()
    await db.profiles.replace_one(
        {"id": profile_id},
        profile_data.model_dump(),
        upsert=True,
    )

    # Re-index ChromaDB chunks
    chunk_count = index_profile_chunks(
        profile=profile_data,
        persist_directory=chroma_dir,
        embedding_fn=embedding_fn,
    )

    # Audit log
    await write_agent_log(
        agent_name="profile_agent",
        status="success",
        summary={
            "action": "profile_update",
            "skills_count": len(profile_data.skills),
            "projects_count": len(profile_data.projects),
            "experiences_count": len(profile_data.experience),
            "chunks_indexed": chunk_count,
        },
    )

    return profile_data

