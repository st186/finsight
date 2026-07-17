# FinSight

An agentic financial research assistant over SEC filings — RAG, LangGraph,
agents, and MLOps on Azure. See `docs/` and the project plan PDF for the full
10-week architecture.

## Status

- [x] **Phase 1 — Ingestion & baseline RAG** (code complete; needs Azure key + Docker to run end-to-end)
- [ ] Phase 2 — Retrieval quality & evaluation
- [ ] Phase 3 — Agents & orchestration (LangGraph)
- [ ] Phase 4 — Productionization
- [ ] Phase 5 — Azure deployment & MLOps

## Phase 1 pipeline

```
EDGAR API ──> HTML section parser ──> section-aware chunker ──> jsonl
 (free)        (Item 1A, Item 7…)      (metadata headers)         │
                                                                  ▼
   cited answer <── GPT-4o <── vector search <── pgvector <── embeddings
   (rag_cli.py)               (metadata filters)            (text-embedding-3-large)
```

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env    # then fill in Azure OpenAI credentials
```

**Database** (needs Docker Desktop):

```powershell
docker compose -f infra/docker-compose.yml up -d
```

**Azure OpenAI**: create an Azure OpenAI resource, deploy three models —
`gpt-4o`, `gpt-4o-mini`, `text-embedding-3-large` — and put the endpoint +
key in `.env`.

## Run Phase 1

```powershell
# 1. Download + parse + chunk filings (no API key needed)
.venv\Scripts\python -m ingestion.pipeline JPM BAC --forms 10-K

# 2. Embed chunks into pgvector (needs Azure key + Docker db)
.venv\Scripts\python -m ingestion.embedder

# 3. Ask questions with citations
.venv\Scripts\python rag_cli.py "What cybersecurity risks did JPMorgan flag?" --tickers JPM
```

## Documentation

- [docs/PRD.md](docs/PRD.md) — product requirements: personas, AI quality
  targets, risk register, launch gates
- [docs/SETUP.md](docs/SETUP.md) — full environment/architecture replication
  guide (Docker, database, Azure OpenAI, `.env`, troubleshooting)
- [docs/adr/](docs/adr/) — Architecture Decision Records
- [notebooks/phase1_deepdive.ipynb](notebooks/phase1_deepdive.ipynb) —
  **start here if you're new to RAG/vector DBs.** Spoon-fed Phase 1 from
  scratch: concept explainers, before/after for every transformation, real
  raw data, live DB inspection
- [notebooks/phase1_walkthrough.ipynb](notebooks/phase1_walkthrough.ipynb) —
  the concise version for readers already comfortable with RAG

## Repository layout

```
ingestion/   EDGAR client, section parser, chunker, embedding pipeline
retrieval/   vector search (Phase 2: hybrid + reranker)
agents/      Phase 3: LangGraph supervisor/RAG/quant/critic agents
tools/       Phase 3: XBRL financial-data tools
api/         Phase 4: FastAPI app
evals/       Phase 2: golden dataset + RAGAS harness
infra/       docker-compose (Postgres+pgvector), schema, later IaC
docs/        architecture notes, ADRs
```

## Known Phase 1 limitations (Phase 2 fodder)

- JPM-style 10-Ks incorporate MD&A/financials by reference into Item 15's
  exhibit blob; sections are still indexed but under the Item 15 label.
- EDGAR `submissions` API only returns the ~1000 most recent filings, so
  heavy filers (banks) may show fewer historical 10-Ks; older index files
  are a TODO.
- Dense-only retrieval, no reranking, no eval harness yet — that is Phase 2.
