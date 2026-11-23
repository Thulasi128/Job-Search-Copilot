"""TypedDict state representation for the LangGraph workflow.

Holds only minimal IDs, counters, scores, and lightweight flags to keep
checkpoints small and avoid duplicating personal profile or resume data.
"""

from typing import Any, Dict, Optional, TypedDict


class JobState(TypedDict, total=False):
    """Lean workflow state persisted in the SQLite checkpointer."""

    job_id: str
    run_number: int
    score: Optional[float]
    retry_count: int
    error_message: Optional[str]
    flags: Dict[str, Any]

