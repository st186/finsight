"""RAG agent node — the Phase 2 retriever as a LangGraph node.

No new retrieval logic: it runs each 'rag' sub-task through the measured
Phase 2 winner (rewrite+hybrid+rerank) and appends the cited chunks to
state['evidence']. Retrieval quality was already earned in Phase 2 (86%).
"""
from __future__ import annotations

from agents.state import FinSightState
from retrieval.search import retrieve

RETRIEVE_MODE = "rewrite+hybrid+rerank"
PER_TASK_K = 6


def rag_node(state: FinSightState) -> dict:
    tasks = [t for t in state.get("sub_tasks", []) if t["kind"] == "rag"]
    evidence = list(state.get("evidence", []))
    trace = list(state.get("trace", []))
    seen = {(e["citation"], e["text"][:60]) for e in evidence}

    for t in tasks:
        tickers = [t["ticker"]] if t.get("ticker") else None
        hits = retrieve(t["detail"], k=PER_TASK_K, mode=RETRIEVE_MODE, tickers=tickers)
        for h in hits:
            key = (h.citation, h.text[:60])
            if key in seen:
                continue
            seen.add(key)
            evidence.append({"citation": h.citation, "ticker": h.ticker,
                             "item": h.item, "text": h.text, "score": h.score})
        trace.append(
            f"[rag]        {t.get('ticker') or 'all'}: \"{t['detail'][:52]}\" "
            f"-> {len(hits)} chunks"
        )

    return {"evidence": evidence, "trace": trace}
