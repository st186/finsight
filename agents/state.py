"""Shared state passed between LangGraph nodes.

Every node reads the fields it needs and returns a partial dict LangGraph
merges into this state. Keeping it one flat TypedDict makes the trace easy
to inspect and the Postgres checkpoints easy to read.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


class SubTask(TypedDict):
    kind: Literal["rag", "quant"]
    ticker: str | None
    detail: str  # what to retrieve / which metric to fetch


class FinSightState(TypedDict, total=False):
    question: str
    # supervisor output
    plan: list[str]           # human-readable decomposition
    sub_tasks: list[SubTask]
    route: Literal["rag_only", "fanout"]
    # worker outputs
    evidence: list[dict[str, Any]]   # {citation, ticker, item, text, score}
    figures: list[dict[str, Any]]    # {ticker, concept, label, year, value, unit, source}
    # synthesis + critic
    draft: str
    verdict: dict[str, Any]          # {ok: bool, issues: [str]}
    retries: int
    # control
    needs_human: bool
    trace: list[str]                 # human-readable agent-hop log
    answer: str
