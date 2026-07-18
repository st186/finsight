"""LLM query rewriting (Phase 2).

Vague or compound analyst questions often retrieve poorly as-is:
"How do the two big banks think about rates?" names no bank and no metric.
A cheap LLM expands the question into 2-3 concrete sub-queries phrased the
way filings actually talk; we retrieve for each and RRF-fuse the results.
"""
from __future__ import annotations

import json
import re

from config import MINI_DEPLOYMENT
from ingestion.embedder import get_openai

REWRITE_PROMPT = """Rewrite this financial research question into 2-3 short,
concrete search queries using vocabulary that SEC filings actually use
(e.g. "net interest income", "provision for credit losses", "Risk Factors").
Cover different aspects if the question is compound.

QUESTION: {question}

Reply with ONLY a JSON array of strings, e.g. ["query one", "query two"]."""


def rewrite_query(question: str) -> list[str]:
    """Return the original question plus 2-3 LLM-expanded sub-queries."""
    client = get_openai()
    resp = client.chat.completions.create(
        model=MINI_DEPLOYMENT,
        messages=[{"role": "user", "content": REWRITE_PROMPT.format(question=question)}],
    ).choices[0].message.content
    try:
        subs = json.loads(re.search(r"\[.*\]", resp, re.S).group(0))
        subs = [s for s in subs if isinstance(s, str) and s.strip()][:3]
    except (AttributeError, json.JSONDecodeError):
        subs = []
    return [question] + subs
