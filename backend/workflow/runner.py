"""Background execution runner for LangGraph workflow tasks."""

import asyncio
import logging
from typing import Any, Dict, Optional

from langgraph.types import Command

from backend.database import get_db
from backend.models.job import JobStatus
from backend.models.logs import write_agent_log
from backend.workflow.checkpointer import get_workflow_graph
from backend.workflow.concurrency import release_run, try_acquire_run

logger = logging.getLogger(__name__)


async def get_job_interrupt(job_id: str, run_number: int = 1) -> Optional[Dict[str, Any]]:
    """Retrieve any pending interrupt payload from the graph checkpoint.

    Args:
        job_id: Identifier of the job.
        run_number: Execution iteration number.

    Returns:
        Optional[Dict[str, Any]]: The interrupt payload dictionary, or None.
    """
    graph = get_workflow_graph()
    config = {"configurable": {"thread_id": f"{job_id}:{run_number}"}}
    try:
        state = await graph.aget_state(config)
        if state and state.tasks:
            for task in state.tasks:
                if getattr(task, "interrupts", None):
                    for intr in task.interrupts:
                        val = getattr(intr, "value", intr)
                        if isinstance(val, dict):
                            return val
                        return {"payload": val}
    except Exception as exc:
        logger.debug("Failed to read checkpoint interrupt for job %s: %s", job_id, exc)
    return None


async def run_workflow_background(
    job_id: str,
    run_number: int = 1,
    resume_payload: Optional[Any] = None,
) -> None:
    """Execute or resume the LangGraph workflow in a background asyncio task.

    Guarantees concurrency bounds, failure logging, error recording in MongoDB,
    and checkpoint retention.

    Args:
        job_id: Identifier of the job.
        run_number: Execution run iteration.
        resume_payload: Optional payload passed to Command(resume=...) when resuming.
    """
    acquired = await try_acquire_run(job_id)
    if not acquired:
        logger.warning("Job %s is already running in background, skipping invocation.", job_id)
        return

    graph = get_workflow_graph()
    thread_id = f"{job_id}:{run_number}"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        logger.info("Starting background graph execution for %s (run=%d)", job_id, run_number)
        db = get_db()
        job_doc = await db.jobs.find_one({"id": job_id})
        if job_doc and job_doc.get("status") == JobStatus.SAVED.value:
            from backend.workflow.transitions import transition_job_status
            await transition_job_status(job_id, JobStatus.PROCESSING)

        if resume_payload is not None:
            await graph.ainvoke(Command(resume=resume_payload), config=config)
        else:
            await graph.ainvoke(
                {
                    "job_id": job_id,
                    "run_number": run_number,
                    "retry_count": 0,
                    "flags": {},
                },
                config=config,
            )
        logger.info("Background graph execution step completed for %s", job_id)
    except Exception as exc:
        logger.exception("Error executing workflow for job %s: %s", job_id, exc)
        db = get_db()
        error_msg = str(exc)
        # Update job to failed status while keeping existing checkpoint
        await db.jobs.update_one(
            {"id": job_id},
            {"$set": {"status": JobStatus.FAILED.value, "error_message": error_msg}},
        )
        await write_agent_log(
            agent_name="workflow_runner",
            status="failure",
            summary={
                "action": "run_workflow_background",
                "job_id": job_id,
                "run_number": run_number,
                "error": error_msg,
            },
            job_id=job_id,
        )
    finally:
        # Check if job reached a terminal state
        db = get_db()
        job_doc = await db.jobs.find_one({"id": job_id})
        status_val = job_doc.get("status") if job_doc else None
        is_term = status_val in {
            JobStatus.CLOSED.value,
            JobStatus.REJECTED.value,
            JobStatus.SKIPPED.value,
            JobStatus.APPROVED.value,
        }
        await release_run(job_id, is_terminal=is_term)


async def recover_interrupted_jobs() -> int:
    """Startup sweep: transitions any jobs left in 'processing' status (e.g. killed

    abruptly by server restart) to 'failed' with 'interrupted by restart'.

    Returns:
        int: Count of recovered jobs.
    """
    db = get_db()
    result = await db.jobs.update_many(
        {"status": JobStatus.PROCESSING.value},
        {
            "$set": {
                "status": JobStatus.FAILED.value,
                "error_message": "interrupted by restart",
            }
        },
    )
    if result.modified_count > 0:
        logger.info("Recovered %d interrupted processing job(s) to failed", result.modified_count)
    return result.modified_count
