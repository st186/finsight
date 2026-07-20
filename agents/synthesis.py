"""Synthesis node — merge retrieved text + fetched figures into a cited answer.

Reuses the Phase 1 cite-or-refuse discipline, extended so numeric claims cite
their SEC XBRL source. If the critic sent it back, its issues are included so
the retry can fix them.
"""
from __future__ import annotations

from agents.state import FinSightState
from config import CHAT_DEPLOYMENT
from ingestion.embedder import get_openai

SYSTEM = """You are FinSight's synthesis agent. Write an analyst-style answer
using ONLY the evidence and figures provided. Rules, in priority order:
1. Every qualitative claim ends with its bracketed citation, e.g. [JPM 10-K 2025, Item 1A].
2. Every number must be one of the provided figures; state it with its source,
   e.g. "net interest income rose to $92.6B [SEC XBRL InterestIncomeExpenseNet CY2024]".
   Never invent or recall a figure that is not in the list.
3. If evidence and figures are insufficient, say exactly:
   "Insufficient evidence in the indexed filings." and state what is missing.
4. Be concise and neutral, like an equity research note."""


def synthesis_node(state: FinSightState) -> dict:
    client = get_openai()
    evidence = state.get("evidence", [])
    figures = [f for f in state.get("figures", []) if f.get("value") is not None]

    ev_block = "\n\n".join(
        f"PASSAGE {i+1} {e['citation']}:\n{e['text'][:2500]}"
        for i, e in enumerate(evidence)
    ) or "(no text evidence retrieved)"

    fig_block = "\n".join(
        f"- {f['ticker']} {f['metric']} {f.get('year','')}: {f['value']:,.0f} "
        f"{f.get('unit','')}  [{f.get('source','')}]"
        for f in figures
    ) or "(no figures fetched)"

    fixups = ""
    if state.get("verdict", {}).get("issues"):
        fixups = ("\n\nThe previous draft had these problems — fix them:\n- "
                  + "\n- ".join(state["verdict"]["issues"]))

    user = (f"QUESTION: {state['question']}\n\nTEXT EVIDENCE:\n{ev_block}\n\n"
            f"FIGURES (from SEC XBRL):\n{fig_block}{fixups}")

    draft = client.chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": user}],
    ).choices[0].message.content

    trace = list(state.get("trace", []))
    trace.append(f"[synthesis]  draft written ({len(evidence)} passages, "
                 f"{len(figures)} figures)")
    return {"draft": draft, "trace": trace}
