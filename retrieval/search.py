"""Retrieval: dense vector search, BM25-style keyword search, and hybrid
fusion (reciprocal rank fusion), with optional cross-encoder reranking.

Phase 1 shipped vector-only `search()`. Phase 2 adds:
  - keyword_search(): Postgres full-text (the pre-staged `tsv` column)
  - hybrid_search(): RRF fusion of vector + keyword rankings
  - retrieve(): one entry point with mode = "vector" | "hybrid" | "hybrid+rerank"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg
from pgvector.psycopg import register_vector

from config import DATABASE_URL
from ingestion.embedder import embed_texts, get_openai

RRF_K = 60  # standard reciprocal-rank-fusion constant
CANDIDATES = 30  # candidates fetched from each retriever before fusion/rerank


@dataclass
class Hit:
    id: int
    citation: str
    ticker: str
    item: str
    section_name: str
    text: str
    score: float  # meaning depends on mode: cosine sim, ts_rank, RRF, or CE score


def _filters(tickers: list[str] | None, items: list[str] | None):
    where, params = [], {}
    if tickers:
        where.append("ticker = ANY(%(tickers)s)")
        params["tickers"] = [t.upper() for t in tickers]
    if items:
        where.append("item = ANY(%(items)s)")
        params["items"] = items
    return where, params


def vector_search(
    query: str,
    k: int = 8,
    tickers: list[str] | None = None,
    items: list[str] | None = None,
) -> list[Hit]:
    """Dense retrieval: cosine similarity over pgvector embeddings."""
    qvec = embed_texts(get_openai(), [query])[0]
    where, params = _filters(tickers, items)
    where.append("embedding IS NOT NULL")
    params |= {"qvec": qvec, "k": k}
    sql = f"""
        SELECT id, citation, ticker, item, section_name, text,
               1 - (embedding <=> %(qvec)s::vector) AS score
        FROM chunks
        WHERE {' AND '.join(where)}
        ORDER BY embedding <=> %(qvec)s::vector
        LIMIT %(k)s
    """
    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        rows = conn.execute(sql, params).fetchall()
    return [Hit(*row) for row in rows]


_STOPWORDS = frozenset(
    "the a an and or of to in on for with about what which how does did is are "
    "was were according its their his her when where why who whom that this "
    "these those say said each per most latest".split()
)


def _or_tsquery(query: str) -> str:
    """OR-of-keywords fallback. websearch_to_tsquery ANDs every term, so a
    long natural-language question matches almost nothing (eval finding:
    14% hit rate). OR-ing the meaningful words restores recall; ts_rank_cd
    still rewards chunks matching MORE of them."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", query.lower())
    keep = [w for w in words if w not in _STOPWORDS]
    return " | ".join(dict.fromkeys(keep)) or query


def keyword_search(
    query: str,
    k: int = 8,
    tickers: list[str] | None = None,
    items: list[str] | None = None,
) -> list[Hit]:
    """Sparse retrieval: Postgres full-text search over the generated tsv
    column. Strict AND semantics first (precise when it matches), then an
    OR-of-keywords fallback to fill remaining slots (recall)."""
    where, params = _filters(tickers, items)
    base_where = list(where)

    def run(tsquery_fn: str, qparam: str, limit: int) -> list[Hit]:
        w = base_where + [f"tsv @@ {tsquery_fn}('english', %(q)s)"]
        sql = f"""
            SELECT id, citation, ticker, item, section_name, text,
                   ts_rank_cd(tsv, {tsquery_fn}('english', %(q)s)) AS score
            FROM chunks
            WHERE {' AND '.join(w)}
            ORDER BY score DESC
            LIMIT %(k)s
        """
        with psycopg.connect(DATABASE_URL) as conn:
            rows = conn.execute(sql, {**params, "q": qparam, "k": limit}).fetchall()
        return [Hit(*row) for row in rows]

    hits = run("websearch_to_tsquery", query, k)
    if len(hits) < k:
        seen = {h.id for h in hits}
        extra = [h for h in run("to_tsquery", _or_tsquery(query), k * 2)
                 if h.id not in seen]
        hits += extra[: k - len(hits)]
    return hits


def hybrid_search(
    query: str,
    k: int = 8,
    tickers: list[str] | None = None,
    items: list[str] | None = None,
) -> list[Hit]:
    """Reciprocal rank fusion of vector + keyword rankings.

    Each document's fused score = sum over rankings of 1/(RRF_K + rank).
    A chunk that ranks well in BOTH lists beats one that tops only one.
    """
    dense = vector_search(query, CANDIDATES, tickers, items)
    sparse = keyword_search(query, CANDIDATES, tickers, items)

    fused: dict[int, float] = {}
    by_id: dict[int, Hit] = {}
    for hits in (dense, sparse):
        for rank, hit in enumerate(hits):
            fused[hit.id] = fused.get(hit.id, 0.0) + 1.0 / (RRF_K + rank + 1)
            by_id.setdefault(hit.id, hit)

    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
    return [
        Hit(h.id, h.citation, h.ticker, h.item, h.section_name, h.text, score)
        for cid, score in ranked
        for h in [by_id[cid]]
    ]


def retrieve(
    query: str,
    k: int = 8,
    mode: str = "hybrid",
    tickers: list[str] | None = None,
    items: list[str] | None = None,
) -> list[Hit]:
    """Single entry point used by the RAG chain and the eval harness."""
    if mode == "vector":
        return vector_search(query, k, tickers, items)
    if mode == "keyword":
        return keyword_search(query, k, tickers, items)
    if mode == "hybrid":
        return hybrid_search(query, k, tickers, items)
    if mode == "hybrid+rerank":
        candidates = hybrid_search(query, max(k * 3, 24), tickers, items)
        return _blend_rerank(query, candidates, k)
    if mode == "rewrite+hybrid+rerank":
        from retrieval.rewriter import rewrite_query

        # retrieve for each sub-query, fuse all candidate lists by RRF
        fused: dict[int, float] = {}
        by_id: dict[int, Hit] = {}
        for sub in rewrite_query(query):
            for rank, hit in enumerate(hybrid_search(sub, CANDIDATES, tickers, items)):
                fused[hit.id] = fused.get(hit.id, 0.0) + 1.0 / (RRF_K + rank + 1)
                by_id.setdefault(hit.id, hit)
        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
        candidates = [by_id[cid] for cid, _ in ranked[: max(k * 3, 24)]]
        return _blend_rerank(query, candidates, k)
    raise ValueError(f"unknown retrieval mode: {mode}")


def _blend_rerank(query: str, candidates: list[Hit], k: int) -> list[Hit]:
    """Cross-encoder reranking, blended with the incoming ranking by RRF.

    Eval finding: REPLACING the hybrid order with the pure cross-encoder
    order regressed hit rate (74% vs 83%) — the CE sometimes demotes the
    phrase-bearing chunk in favor of plausible-looking neighbors. Fusing
    the two rankings keeps both signals; a chunk must look bad to BOTH to
    drop out of the top-k."""
    from retrieval.reranker import rerank  # lazy: torch import is slow

    ce_order = rerank(query, candidates, len(candidates))
    fused: dict[int, float] = {}
    by_id: dict[int, Hit] = {}
    for ranking in (candidates, ce_order):
        for rank, hit in enumerate(ranking):
            fused[hit.id] = fused.get(hit.id, 0.0) + 1.0 / (RRF_K + rank + 1)
            by_id.setdefault(hit.id, hit)
    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
    return [
        Hit(h.id, h.citation, h.ticker, h.item, h.section_name, h.text, s)
        for cid, s in ranked for h in [by_id[cid]]
    ]


# Backwards-compatible alias (Phase 1 API used by rag_cli / notebooks)
def search(query: str, k: int = 8, tickers=None, items=None) -> list[Hit]:
    return vector_search(query, k, tickers, items)
