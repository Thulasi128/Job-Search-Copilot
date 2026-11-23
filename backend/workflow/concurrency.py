"""In-memory concurrency control for workflow executions."""

import asyncio
from typing import Dict, Set

# Lock per job_id to prevent race conditions on concurrent endpoints
_JOB_LOCKS: Dict[str, asyncio.Lock] = {}
# Set of job IDs currently executing in an active background task
_ACTIVE_RUNS: Set[str] = set()
_GLOBAL_LOCK = asyncio.Lock()


async def get_job_lock(job_id: str) -> asyncio.Lock:
    """Retrieve or create an asyncio.Lock for a specific job."""
    async with _GLOBAL_LOCK:
        if job_id not in _JOB_LOCKS:
            _JOB_LOCKS[job_id] = asyncio.Lock()
        return _JOB_LOCKS[job_id]


async def try_acquire_run(job_id: str) -> bool:
    """Attempt to mark a job as actively running.

    Returns:
        bool: True if run was acquired, False if job is already executing.
    """
    async with _GLOBAL_LOCK:
        if job_id in _ACTIVE_RUNS:
            return False
        _ACTIVE_RUNS.add(job_id)
        return True


async def release_run(job_id: str, is_terminal: bool = False) -> None:
    """Release a job from active execution.

    Args:
        job_id: Identifier of the job.
        is_terminal: If True, remove the job lock entry to avoid memory leakage.
    """
    async with _GLOBAL_LOCK:
        _ACTIVE_RUNS.discard(job_id)
        if is_terminal and job_id in _JOB_LOCKS:
            del _JOB_LOCKS[job_id]


def is_job_running(job_id: str) -> bool:
    """Check whether a job is currently executing a background task."""
    return job_id in _ACTIVE_RUNS

