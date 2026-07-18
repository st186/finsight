"""Cross-encoder reranking (Phase 2).

A bi-encoder (our embedding model) scores query and document independently —
fast, but it can't see interactions between the two texts. A cross-encoder
reads the query and a candidate TOGETHER and outputs a relevance score —
slower but noticeably more accurate. Standard pattern: retrieve a wide
candidate set cheaply, then rerank the top ~24 with the cross-encoder.

Model: BAAI/bge-reranker-base — runs fine on CPU, downloaded once on first
use (~1 GB into the local HuggingFace cache).
"""
from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "BAAI/bge-reranker-base"


@lru_cache(maxsize=1)
def _model():
    # Lazy import + cache: torch takes seconds to import and the model
    # download happens only on the very first call.
    from sentence_transformers import CrossEncoder

    return CrossEncoder(MODEL_NAME, max_length=512)


def rerank(query: str, hits: list, k: int = 8) -> list:
    """Re-score `hits` against `query` with the cross-encoder; return top-k
    as new Hit objects whose score is the cross-encoder relevance score."""
    if not hits:
        return []
    pairs = [(query, h.text) for h in hits]
    scores = _model().predict(pairs)
    ranked = sorted(zip(hits, scores), key=lambda t: t[1], reverse=True)[:k]
    return [
        type(h)(h.id, h.citation, h.ticker, h.item, h.section_name, h.text, float(s))
        for h, s in ranked
    ]
