"""Phase 1 retrieval: dense vector search with metadata filters.

(Phase 2 adds BM25 + reciprocal rank fusion + reranking here.)
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg
from pgvector.psycopg import register_vector

from config import DATABASE_URL
from ingestion.embedder import embed_texts, get_openai


@dataclass
class Hit:
    citation: str
    ticker: str
    item: str
    section_name: str
    text: str
    score: float  # cosine similarity


def search(
    query: str,
    k: int = 8,
    tickers: list[str] | None = None,
    items: list[str] | None = None,
) -> list[Hit]:
    client = get_openai()
    qvec = embed_texts(client, [query])[0]

    where, params = ["embedding IS NOT NULL"], {"qvec": qvec, "k": k}
    if tickers:
        where.append("ticker = ANY(%(tickers)s)")
        params["tickers"] = [t.upper() for t in tickers]
    if items:
        where.append("item = ANY(%(items)s)")
        params["items"] = items

    sql = f"""
        SELECT citation, ticker, item, section_name, text,
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
