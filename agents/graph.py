"""Assemble the FinSight agent graph (LangGraph).

Flow:
    supervisor -> rag -> quant -> synthesis -> critic -> {accept | retry | human}
                                      ^__________ retry (bounded) __________|
                                                                 human -> interrupt

The rag and quant nodes each no-op when the supervisor assigned them no
sub-tasks, so a single-company text question runs supervisor -> rag ->
(quant skips) -> synthesis -> critic with no quant cost.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from agents.state import FinSightState
from agents.supervisor import supervisor_node
from agents.rag_agent import rag_node
from agents.quant_agent import quant_node
from agents.synthesis import synthesis_node
from agents.critic import critic_node, route_after_critic


def revise_node(state: FinSightState) -> dict:
    trace = list(state.get("trace", []))
    trace.append("[revise]     looping back to synthesis with critic feedback")
    return {"retries": state.get("retries", 0) + 1, "trace": trace}


def human_review_node(state: FinSightState) -> dict:
    """Escalation: pause for a person. LangGraph checkpoints state here and
    interrupt() suspends the run until it is resumed with a decision."""
    decision = interrupt({
        "reason": "low confidence after retries",
        "issues": state.get("verdict", {}).get("issues", []),
        "draft": state.get("draft", ""),
    })
    trace = list(state.get("trace", []))
    trace.append(f"[human]      resumed with decision: {decision}")
    answer = state.get("draft", "")
    if isinstance(decision, str) and decision.lower().startswith("reject"):
        answer = "Insufficient evidence in the indexed filings. (flagged by human review)"
    return {"needs_human": True, "answer": answer, "trace": trace}


def finalize_node(state: FinSightState) -> dict:
    trace = list(state.get("trace", []))
    trace.append("[done]       answer accepted")
    return {"answer": state.get("draft", ""), "trace": trace}


def build_graph(checkpointer=None):
    g = StateGraph(FinSightState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("rag", rag_node)
    g.add_node("quant", quant_node)
    g.add_node("synthesis", synthesis_node)
    g.add_node("critic", critic_node)
    g.add_node("revise", revise_node)
    g.add_node("human_review", human_review_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "supervisor")
    g.add_edge("supervisor", "rag")
    g.add_edge("rag", "quant")
    g.add_edge("quant", "synthesis")
    g.add_edge("synthesis", "critic")
    g.add_conditional_edges("critic", route_after_critic,
                            {"accept": "finalize", "retry": "revise",
                             "human": "human_review"})
    g.add_edge("revise", "synthesis")
    g.add_edge("human_review", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
