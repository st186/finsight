"""Supervisor node — classify, decompose, route.

A cheap model reads the question and produces a plan: which companies are
involved, whether real figures are needed (quant sub-tasks) and/or filing
text (rag sub-tasks). Simple single-company text questions route straight
to RAG so they never invoke the quant path (dynamic routing = cost control).
"""
from __future__ import annotations

import json
import re

from agents.state import FinSightState
from config import MINI_DEPLOYMENT, COMPANIES
from ingestion.embedder import get_openai

PLAN_PROMPT = """You plan how to answer a question about SEC filings for these
companies (ticker: name):
{companies}

Break the QUESTION into sub-tasks. Two kinds:
- "rag":   retrieve filing TEXT (risks, strategy, management discussion, qualitative)
- "quant": fetch a reported NUMBER from SEC data (revenue, net interest income,
           provision for credit losses, net income, total assets, etc.)

Rules:
- Use ONLY tickers from the list above; if the question names a company not
  listed, still include it as rag with your best ticker guess.
- One sub-task per (company, aspect). For comparisons, emit one per company.
- Numbers/trends over years -> quant. Wording/risks/strategy -> rag.

Return ONLY JSON:
{{"plan": ["short step", ...],
  "sub_tasks": [{{"kind":"rag|quant","ticker":"XXX","detail":"what to fetch"}}]}}

QUESTION: {question}"""


def supervisor_node(state: FinSightState) -> dict:
    client = get_openai()
    companies = "\n".join(f"  {t}: {n}" for t, n in COMPANIES.items())
    resp = client.chat.completions.create(
        model=MINI_DEPLOYMENT,
        messages=[{"role": "user", "content": PLAN_PROMPT.format(
            companies=companies, question=state["question"])}],
    ).choices[0].message.content

    try:
        parsed = json.loads(re.search(r"\{.*\}", resp, re.S).group(0))
        plan = parsed.get("plan", [])
        sub_tasks = [t for t in parsed.get("sub_tasks", [])
                     if t.get("kind") in ("rag", "quant") and t.get("detail")]
    except (AttributeError, json.JSONDecodeError):
        plan, sub_tasks = ["retrieve filing text"], []

    if not sub_tasks:  # fallback: single RAG pass over the raw question
        sub_tasks = [{"kind": "rag", "ticker": None, "detail": state["question"]}]

    has_quant = any(t["kind"] == "quant" for t in sub_tasks)
    route = "fanout" if has_quant else "rag_only"

    n_rag = sum(t["kind"] == "rag" for t in sub_tasks)
    n_quant = sum(t["kind"] == "quant" for t in sub_tasks)
    trace = [f"[supervisor] plan: {n_rag} rag + {n_quant} quant sub-task(s) "
             f"-> route={route}"]
    return {"plan": plan, "sub_tasks": sub_tasks, "route": route,
            "trace": trace, "retries": 0}
