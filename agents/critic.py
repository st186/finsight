"""Critic / verifier node — the control layer.

Checks that every factual claim in the draft maps to a provided passage or a
fetched figure. Returns {ok, issues, confidence}. The graph uses this to
either accept, loop back to synthesis (bounded retry), or escalate to a human.
"""
from __future__ import annotations

import json
import re

from agents.state import FinSightState
from config import CHAT_DEPLOYMENT
from ingestion.embedder import get_openai

MAX_RETRIES = 2

SYSTEM = """You are FinSight's critic. You verify a draft answer against the
evidence it was allowed to use.

Standard of review (important):
- A claim is SUPPORTED if the PASSAGES convey it in substance. Faithful
  paraphrase, summarization, and reasonable synthesis are fine — do NOT
  require verbatim wording.
- Only flag a claim as an issue if it is genuinely ABSENT from every passage,
  CONTRADICTS a passage, or is a NUMBER that does not match any FIGURE.
- Also flag a citation that names an item/source not present in the passages.
A correct refusal ("Insufficient evidence...") is fully valid and ok=true.

Set ok=false ONLY if there is at least one real, material issue by the above
standard. Minor wording differences are NOT issues.

Reply ONLY JSON:
{"ok": true|false,
 "confidence": 0.0-1.0,
 "issues": ["specific material problem", ...]}"""


def critic_node(state: FinSightState) -> dict:
    client = get_openai()
    evidence = state.get("evidence", [])
    figures = [f for f in state.get("figures", []) if f.get("value") is not None]

    ev = "\n".join(f"- {e['citation']}: {e['text'][:2500]}" for e in evidence) or "(none)"
    fg = "\n".join(f"- {f['ticker']} {f['metric']} {f.get('year','')}: "
                   f"{f['value']:,.0f} [{f.get('source','')}]" for f in figures) or "(none)"

    user = (f"QUESTION: {state['question']}\n\nPASSAGES:\n{ev}\n\nFIGURES:\n{fg}\n\n"
            f"DRAFT:\n{state['draft']}")

    raw = client.chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": user}],
    ).choices[0].message.content

    try:
        verdict = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        verdict.setdefault("ok", False)
        verdict.setdefault("confidence", 0.0)
        verdict.setdefault("issues", [])
    except (AttributeError, json.JSONDecodeError):
        verdict = {"ok": False, "confidence": 0.0, "issues": ["critic could not parse draft"]}

    retries = state.get("retries", 0)
    trace = list(state.get("trace", []))
    status = "ok" if verdict["ok"] else f"{len(verdict['issues'])} issue(s)"
    trace.append(f"[critic]     {status}, confidence={verdict['confidence']:.2f}"
                 + (f" (retry {retries})" if retries else ""))
    return {"verdict": verdict, "trace": trace}


def route_after_critic(state: FinSightState) -> str:
    """Conditional edge: accept, retry synthesis, or escalate to a human."""
    verdict = state.get("verdict", {})
    if verdict.get("ok") and verdict.get("confidence", 0) >= 0.6:
        return "accept"
    if state.get("retries", 0) < MAX_RETRIES:
        return "retry"
    return "human"  # exhausted retries and still not confident
