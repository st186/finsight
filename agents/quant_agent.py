"""Quant agent node — tool-calling over the SEC XBRL tools.

The LLM decides which figures the question needs and emits tool calls;
our code runs them against the real company-facts API and feeds results
back. Numbers therefore always originate from the SEC, never the model.
Every fetched figure (with its source tag) lands in state['figures'].
"""
from __future__ import annotations

import json

from agents.state import FinSightState
from config import CHAT_DEPLOYMENT
from ingestion.embedder import get_openai
from tools import xbrl

# ---- expose the XBRL tools to the model as callable functions ------------
TOOLS = [
    {"type": "function", "function": {
        "name": "get_metric",
        "description": "One reported annual figure for a company from SEC XBRL data.",
        "parameters": {"type": "object", "properties": {
            "ticker": {"type": "string"},
            "metric": {"type": "string", "description":
                       "one of: net_interest_income, interest_income, interest_expense, "
                       "provision_for_credit_losses, revenue, net_income, total_assets, "
                       "stockholders_equity"},
            "year": {"type": "integer"}},
            "required": ["ticker", "metric", "year"]}}},
    {"type": "function", "function": {
        "name": "compare_trend",
        "description": "A metric across several years plus first->last % change.",
        "parameters": {"type": "object", "properties": {
            "ticker": {"type": "string"},
            "metric": {"type": "string"},
            "years": {"type": "array", "items": {"type": "integer"}}},
            "required": ["ticker", "metric", "years"]}}},
    {"type": "function", "function": {
        "name": "net_interest_income",
        "description": "Net interest income (bank profit metric) for one year.",
        "parameters": {"type": "object", "properties": {
            "ticker": {"type": "string"}, "year": {"type": "integer"}},
            "required": ["ticker", "year"]}}},
]

_DISPATCH = {
    "get_metric": lambda a: xbrl.get_metric(a["ticker"], a["metric"], a["year"]),
    "compare_trend": lambda a: xbrl.compare_trend(a["ticker"], a["metric"], a["years"]),
    "net_interest_income": lambda a: xbrl.net_interest_income(a["ticker"], a["year"]),
}

SYSTEM = """You are the quant agent for a financial research assistant.
Use the tools to fetch the exact figures needed to answer the question.
Call tools for every company and year the question requires. Never state a
number you did not fetch. When you have the figures, reply with a one-line
confirmation (the figures are recorded automatically)."""

MAX_STEPS = 6


def quant_node(state: FinSightState) -> dict:
    tasks = [t for t in state.get("sub_tasks", []) if t["kind"] == "quant"]
    if not tasks:
        return {}

    client = get_openai()
    ask = "; ".join(f"{t.get('ticker') or ''} {t['detail']}".strip() for t in tasks)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Question context: {state['question']}\n"
                                             f"Fetch figures for: {ask}"}]
    figures = list(state.get("figures", []))
    trace = list(state.get("trace", []))
    calls = 0

    for _ in range(MAX_STEPS):
        resp = client.chat.completions.create(
            model=CHAT_DEPLOYMENT, messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            break
        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            result = _DISPATCH[tc.function.name](args)
            calls += 1
            _record(result, figures)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result)})

    got = sum(1 for f in figures if f.get("value") is not None)
    trace.append(f"[quant]      {calls} tool call(s) -> {got} figure(s) from SEC XBRL")
    return {"figures": figures, "trace": trace}


def _record(result: dict, figures: list) -> None:
    """Flatten a tool result into one or more provenance-carrying figures."""
    if "points" in result:  # compare_trend
        for year, val in result["points"].items():
            figures.append({"ticker": result["ticker"], "metric": result["metric"],
                            "year": int(year), "value": val,
                            "source": result.get("source"),
                            "pct_change": result.get("pct_change_first_to_last")})
    elif result.get("value") is not None:  # get_metric / net_interest_income
        figures.append({"ticker": result.get("ticker"), "metric": result.get("metric"),
                        "year": result.get("year"), "value": result["value"],
                        "unit": result.get("unit"), "source": result.get("source")})
