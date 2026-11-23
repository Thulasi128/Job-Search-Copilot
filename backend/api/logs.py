"""FastAPI route for inspecting the agent audit log."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query, status

from backend.database import get_db

router = APIRouter(prefix="/logs", tags=["Audit Logs"])


@router.get("", response_model=List[Dict[str, Any]], status_code=status.HTTP_200_OK)
async def get_logs(
    job_id: Optional[str] = Query(None, description="Optional job ID to filter audit logs"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of log entries to retrieve"),
) -> List[Dict[str, Any]]:
    """Retrieve audit log entries from the agent_log collection.

    Entries contain operational summaries, counts, and error metadata. Full JD
    or resume content is never logged.

    Args:
        job_id: Optional job ID filter.
        limit: Limit count of returned logs.

    Returns:
        List[Dict[str, Any]]: List of log records in reverse chronological order.
    """
    db = get_db()
    query: Dict[str, Any] = {}
    if job_id:
        query["job_id"] = job_id

    cursor = db.agent_log.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
    return await cursor.to_list(length=limit)

