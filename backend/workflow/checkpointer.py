"""Checkpointer lifecycle management for the LangGraph workflow."""

import logging
import os
from typing import Any, Optional
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.config import get_settings
from backend.workflow.graph import compile_workflow_graph

logger = logging.getLogger(__name__)

_CHECKPOINTER_CM: Optional[Any] = None
_SAVER_INSTANCE: Optional[AsyncSqliteSaver] = None
_COMPILED_GRAPH: Optional[Any] = None


async def init_checkpointer_and_graph(db_path: Optional[str] = None) -> Any:
    """Initialize AsyncSqliteSaver and compile the global workflow graph.

    Args:
        db_path: Optional custom path to SQLite database. Defaults to config CHECKPOINT_DB_PATH.

    Returns:
        CompiledStateGraph: The compiled workflow graph.
    """
    global _CHECKPOINTER_CM, _SAVER_INSTANCE, _COMPILED_GRAPH

    path = db_path or get_settings().CHECKPOINT_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    _CHECKPOINTER_CM = AsyncSqliteSaver.from_conn_string(path)
    _SAVER_INSTANCE = await _CHECKPOINTER_CM.__aenter__()
    _COMPILED_GRAPH = compile_workflow_graph(checkpointer=_SAVER_INSTANCE)
    logger.info("Initialized AsyncSqliteSaver at %s", path)
    return _COMPILED_GRAPH


async def close_checkpointer() -> None:
    """Close the active AsyncSqliteSaver connection."""
    global _CHECKPOINTER_CM, _SAVER_INSTANCE, _COMPILED_GRAPH
    if _CHECKPOINTER_CM is not None:
        try:
            await _CHECKPOINTER_CM.__aexit__(None, None, None)
            logger.info("Closed AsyncSqliteSaver connection")
        except Exception as exc:
            logger.warning("Error closing AsyncSqliteSaver: %s", exc)
        finally:
            _CHECKPOINTER_CM = None
            _SAVER_INSTANCE = None
            _COMPILED_GRAPH = None


def get_workflow_graph() -> Any:
    """Retrieve the compiled workflow graph singleton.

    If not initialized with a checkpointer, returns an in-memory compiled graph.
    """
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = compile_workflow_graph()
    return _COMPILED_GRAPH


def set_workflow_graph(graph: Any) -> None:
    """Set the active workflow graph override (useful in testing)."""
    global _COMPILED_GRAPH
    _COMPILED_GRAPH = graph

