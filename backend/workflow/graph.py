"""LangGraph workflow definition and compilation."""

from typing import Any, Optional
from langgraph.graph import END, START, StateGraph

from backend.workflow.nodes import (
    abandon_node,
    approve_node,
    auto_skip_node,
    confirm_skip_node,
    intake_match_node,
    interrupt_approval_node,
    interrupt_confirm_node,
    interrupt_manual_edit_node,
    prep_approval_node,
    prep_confirm_node,
    prep_manual_edit_node,
    reject_node,
    route_after_approval,
    route_after_confirm,
    route_after_drafting,
    route_after_manual_edit,
    route_after_match,
    tailor_pipeline_node,
)
from backend.workflow.state import JobState


def create_workflow_graph() -> StateGraph:
    """Build the state graph with all processing, interrupt, and routing nodes."""
    workflow = StateGraph(JobState)

    # Add processing and interrupt nodes
    workflow.add_node("intake_match", intake_match_node)
    workflow.add_node("auto_skip", auto_skip_node)
    workflow.add_node("prep_confirm", prep_confirm_node)
    workflow.add_node("interrupt_confirm", interrupt_confirm_node)
    workflow.add_node("confirm_skip", confirm_skip_node)
    workflow.add_node("tailor_pipeline", tailor_pipeline_node)
    workflow.add_node("prep_manual_edit", prep_manual_edit_node)
    workflow.add_node("interrupt_manual_edit", interrupt_manual_edit_node)
    workflow.add_node("abandon", abandon_node)
    workflow.add_node("prep_approval", prep_approval_node)
    workflow.add_node("interrupt_approval", interrupt_approval_node)
    workflow.add_node("approve", approve_node)
    workflow.add_node("reject", reject_node)

    # Define edges and conditional routings
    workflow.add_edge(START, "intake_match")

    workflow.add_conditional_edges(
        "intake_match",
        route_after_match,
        {
            "auto_skip": "auto_skip",
            "prep_confirm": "prep_confirm",
            "tailor_pipeline": "tailor_pipeline",
        },
    )

    workflow.add_edge("auto_skip", END)

    workflow.add_edge("prep_confirm", "interrupt_confirm")
    workflow.add_conditional_edges(
        "interrupt_confirm",
        route_after_confirm,
        {
            "confirm_skip": "confirm_skip",
            "tailor_pipeline": "tailor_pipeline",
        },
    )

    workflow.add_edge("confirm_skip", END)

    workflow.add_conditional_edges(
        "tailor_pipeline",
        route_after_drafting,
        {
            "prep_approval": "prep_approval",
            "prep_manual_edit": "prep_manual_edit",
        },
    )

    workflow.add_edge("prep_manual_edit", "interrupt_manual_edit")
    workflow.add_conditional_edges(
        "interrupt_manual_edit",
        route_after_manual_edit,
        {
            "abandon": "abandon",
            "prep_approval": "prep_approval",
        },
    )

    workflow.add_edge("abandon", END)

    workflow.add_edge("prep_approval", "interrupt_approval")
    workflow.add_conditional_edges(
        "interrupt_approval",
        route_after_approval,
        {
            "approve": "approve",
            "reject": "reject",
            "prep_approval": "prep_approval",
        },
    )

    workflow.add_edge("approve", END)
    workflow.add_edge("reject", END)

    return workflow


def compile_workflow_graph(checkpointer: Optional[Any] = None) -> Any:
    """Compile the StateGraph into an executable Pregel graph with checkpointer.

    Args:
        checkpointer: Async checkpointer instance (e.g. AsyncSqliteSaver).

    Returns:
        CompiledStateGraph: Executable workflow graph.
    """
    builder = create_workflow_graph()
    return builder.compile(checkpointer=checkpointer)

