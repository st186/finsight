# ADR-001: Postgres + pgvector instead of a dedicated vector database

**Status:** accepted (Phase 1, 2026-07)

## Context
The RAG pipeline needs vector similarity search over ~10k chunks (Phase 1
scale), rich metadata filtering (ticker, form, period, section), and — from
Phase 2 — BM25 keyword search fused with vector results. Options considered:
dedicated vector DBs (Pinecone, Weaviate, Qdrant), Azure AI Search, or
Postgres with the pgvector extension.

## Decision
Postgres 16 + pgvector, run via Docker locally and Azure PostgreSQL Flexible
Server in Phase 5.

## Rationale
- **One engine for all three retrieval needs**: vectors (pgvector), exact
  metadata filters (plain SQL WHERE), and keyword search (native tsvector /
  full-text) — hybrid search in Phase 2 becomes a single SQL query with rank
  fusion in Python, no cross-store joins.
- Chunk metadata and vectors stay in the same row — no sync problem between
  a vector store and a metadata store.
- Free, local, and identical in the cloud (Flexible Server supports pgvector).
- LangGraph's Postgres checkpointer (Phase 3) reuses the same instance.

## Trade-offs
- pgvector is slower than specialized engines at millions of vectors — 
  irrelevant at this project's scale (thousands).
- ANN indexes cap at 2000 dimensions (see ADR-003).

## Revisit when
Corpus grows past ~1M chunks or p95 retrieval latency exceeds ~200ms.
