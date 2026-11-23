"""Data model and helper for agent audit logging in MongoDB."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from backend.database import get_db

logger = logging.getLogger(__name__)


class AgentLog(BaseModel):
    """Schema for audit trail log entries in the agent_log collection."""

    agent_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str  # "success" or "failure"
    job_id: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)


async def write_agent_log(
    agent_name: str,
    status: str,
    summary: Dict[str, Any],
    job_id: Optional[str] = None,
) -> None:
    """Record an agent action in the agent_log collection.

    Note: Summary must only contain operational metrics, counts, or error details.
    Full resume text or private document contents must NEVER be written to logs.

    Args:
        agent_name: Name of the executing agent (e.g. 'profile_agent').
        status: Execution status ('success' or 'failure').
        summary: Structured summary dictionary (e.g. counts, duration, error).
        job_id: Optional linked job id.
    """
    try:
        log_entry = AgentLog(
            agent_name=agent_name,
            timestamp=datetime.now(timezone.utc),
            status=status,
            job_id=job_id,
            summary=summary,
        )
        db = get_db()
        await db.agent_log.insert_one(log_entry.model_dump())
    except Exception as exc:
        logger.error("Failed to write agent log entry for %s: %s", agent_name, exc)

