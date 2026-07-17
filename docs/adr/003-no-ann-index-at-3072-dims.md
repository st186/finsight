# ADR-003: full 3072-dim embeddings, no ANN index (yet)

**Status:** accepted (Phase 1, 2026-07)

## Context
`text-embedding-3-large` outputs 3072 dimensions. pgvector's ANN indexes
(HNSW, IVFFlat) support at most 2000 dimensions, so a `vector(3072)` column
cannot be ANN-indexed — every similarity query is a sequential scan.

Alternatives: (a) request reduced dimensions from the API (the model
supports `dimensions=1024/256` with modest quality loss), (b) switch to
`text-embedding-3-small` (1536 dims, indexable), (c) keep full 3072 and
scan.

## Decision
Keep the full 3072 dimensions with no ANN index in Phase 1.

## Rationale
- At Phase 1 scale (731 rows; low thousands by Phase 2) a sequential scan
  is single-digit milliseconds — an index solves a problem we don't have.
- Full dimensions preserve maximum retrieval quality while Phase 2 builds
  the eval harness; shrinking dimensions *before* having metrics would be
  optimizing blind.
- The decision is cheap to reverse: re-embed with `dimensions=1024` and
  add HNSW once the golden dataset can measure the quality delta.

## Trade-offs
- Query cost grows linearly with corpus size.
- 3072 floats/row is ~12KB of storage per chunk (negligible here).

## Revisit when
Phase 2 evals exist (measure 1024-dim quality drop empirically) or corpus
exceeds ~50k chunks (scan latency becomes user-visible).
