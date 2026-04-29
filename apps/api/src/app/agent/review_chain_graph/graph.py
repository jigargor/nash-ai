from __future__ import annotations

from typing import Any

from app.agent.review_chain_graph.state import ReviewChainState

try:  # pragma: no cover - optional dependency in local dev
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover
    END = "__end__"
    StateGraph = None


def compute_branch_flags(
    *,
    findings_after_policy: int,
    max_mode_enabled: bool,
    is_light_review: bool,
) -> ReviewChainState:
    should_run_max_mode = findings_after_policy > 0 and max_mode_enabled and not is_light_review
    should_run_editor = findings_after_policy > 0
    return {
        "findings_after_policy": findings_after_policy,
        "max_mode_enabled": max_mode_enabled,
        "is_light_review": is_light_review,
        "should_run_max_mode": should_run_max_mode,
        "should_run_editor": should_run_editor,
        "chain_short_circuit": not should_run_editor,
    }


def build_review_branching_graph() -> Any | None:
    if StateGraph is None:
        return None
    graph = StateGraph(ReviewChainState)
    graph.add_node("policy_gate", lambda state: state)
    graph.add_node("max_mode", lambda state: state)
    graph.add_node("editor", lambda state: state)
    graph.add_node("final_post", lambda state: state)
    graph.set_entry_point("policy_gate")
    graph.add_conditional_edges(
        "policy_gate",
        lambda state: "max_mode" if bool(state.get("should_run_max_mode")) else "editor",
        {"max_mode": "max_mode", "editor": "editor"},
    )
    graph.add_edge("max_mode", "editor")
    graph.add_conditional_edges(
        "editor",
        lambda state: "final_post" if bool(state.get("should_run_editor")) else "final_post",
        {"final_post": "final_post"},
    )
    graph.add_edge("final_post", END)
    return graph.compile()


def run_branching_preview(state: ReviewChainState) -> ReviewChainState:
    graph = build_review_branching_graph()
    if graph is None:
        return state
    result = graph.invoke(state)
    return result if isinstance(result, dict) else state
