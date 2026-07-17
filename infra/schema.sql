CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    ticker       TEXT NOT NULL,
    form         TEXT NOT NULL,
    period       DATE NOT NULL,
    fiscal_label TEXT NOT NULL,
    item         TEXT NOT NULL,
    section_name TEXT NOT NULL,
    seq          INT  NOT NULL,
    citation     TEXT NOT NULL,
    text         TEXT NOT NULL,
    embedding    vector(3072),
    UNIQUE (ticker, form, period, item, seq)
);

-- vector similarity index (cosine); HNSW is fine at this scale
-- NOTE: pgvector indexes cap at 2000 dims, so at 3072 dims searches scan
-- sequentially — fine for Phase 1 (<10k rows). Revisit in Phase 2.
CREATE INDEX IF NOT EXISTS chunks_meta_idx ON chunks (ticker, form, period, item);

-- full-text search column for Phase 2 hybrid retrieval (BM25 side)
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
