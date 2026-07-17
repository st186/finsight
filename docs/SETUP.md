# FinSight — Environment & Architecture Setup (Phase 1)

Everything needed to replicate the running Phase 1 system from a blank
Windows machine. Each component says *what* it is, *why* it's there, and
*how* to verify it works before moving to the next.

## The architecture at a glance

```mermaid
flowchart LR
    subgraph internet [External services]
        EDGAR["SEC EDGAR API\n(free, no key)"]
        AOAI["Azure OpenAI\nfinsight-st (East US)\n- gpt-5-mini\n- text-embedding-3-large"]
    end

    subgraph laptop [Your machine]
        subgraph py [Python 3.14 venv]
            ING["ingestion/\ndownload, parse, chunk"]
            EMB["ingestion/embedder.py"]
            RET["retrieval/search.py"]
            CLI["rag_cli.py"]
        end
        subgraph docker [Docker Desktop]
            PG[("Postgres 16\n+ pgvector\ncontainer: finsight-db")]
        end
        FILES["data/raw/*.htm\ndata/parsed/*.jsonl"]
    end

    EDGAR --> ING --> FILES --> EMB
    EMB -->|"embeddings"| AOAI
    EMB --> PG
    CLI --> RET --> PG
    RET -->|"query embedding"| AOAI
    CLI -->|"chat completion"| AOAI
```

Three moving parts, deliberately few:

| Component | Role | Why this choice |
|---|---|---|
| Python venv | all application code | no framework lock-in in Phase 1; LangGraph arrives in Phase 3 |
| Postgres + pgvector (Docker) | vector store + metadata + (Phase 2) BM25 | one database for vectors, filters, and full-text — see ADR-001 |
| Azure OpenAI | embeddings + chat | what banks actually run; free-trial $200 covers the whole project |

---

## 1. Prerequisites (one-time installs)

| Tool | Install | Verify |
|---|---|---|
| Python 3.14+ | Microsoft Store or python.org | `python --version` |
| Git | git-scm.com | `git --version` |
| Docker Desktop | `winget install Docker.DockerDesktop` (admin terminal) or docker.com | `docker --version` |

> Docker Desktop must be **launched and fully started** (whale icon in the
> system tray stops animating) before any `docker` command works. It does
> not auto-start the daemon just because the CLI is installed — if you see
> `failed to connect to the docker API at npipe:...`, the app isn't running.

## 2. Python environment

```powershell
cd finsight
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Pinned choices worth knowing:
- `httpx` (EDGAR client), `beautifulsoup4`+`lxml` (HTML parsing),
  `openai` (works for Azure via `AzureOpenAI` class), `psycopg`+`pgvector`
  (database), `tenacity` (retries), `rich` (CLI output).
- Python 3.14 is new; if a package fails to install in later phases
  (e.g. `sentence-transformers` in Phase 2), a side-by-side Python 3.12
  is the standard fix.
- On Windows, run scripts with `python -X utf8` — filings are full of
  curly quotes that the default console codepage renders as `�`
  (display-only issue, but confusing).

## 3. Database: Postgres + pgvector in Docker

Everything is declared in two files under `infra/`:

**`docker-compose.yml`** — one service:
- image `pgvector/pgvector:pg16` (official Postgres 16 with the pgvector
  extension pre-installed — no manual extension build)
- credentials `finsight/finsight`, database `finsight`, port `5432`
- a named volume `finsight_pgdata` so data survives container restarts
- mounts `schema.sql` into `/docker-entrypoint-initdb.d/` — Postgres runs
  it automatically **on first boot only** (that's how the schema appears
  without any migration tooling)

**`schema.sql`** — one table:
- `chunks`: metadata columns (ticker, form, period, item, ...), the raw
  `text`, and `embedding vector(3072)`
- `UNIQUE (ticker, form, period, item, seq)` — makes loading idempotent
  (`ON CONFLICT DO NOTHING`), so re-running the embedder never duplicates
- `tsv tsvector GENERATED` + GIN index — pre-built for Phase 2's BM25
  hybrid search; costs nothing now
- No vector index: pgvector's HNSW/IVFFlat indexes cap at 2000 dims and
  our embeddings are 3072 — sequential scan is fine at Phase 1 scale
  (731 rows), revisit in Phase 2 (see ADR-003)

Start it:

```powershell
docker compose -f infra/docker-compose.yml up -d
```

Verify (should print the table definition):

```powershell
docker exec finsight-db psql -U finsight -d finsight -c "\d chunks"
```

Useful lifecycle commands:

```powershell
docker compose -f infra/docker-compose.yml stop      # stop, keep data
docker compose -f infra/docker-compose.yml up -d     # start again
docker compose -f infra/docker-compose.yml down -v   # DESTROY incl. data
```

> Note: if you ever change `schema.sql`, `up -d` will NOT re-apply it —
> the init script only runs when the data volume is empty. Either apply
> the change manually via `psql`, or `down -v` and reload.

## 4. Azure OpenAI

What exists in Azure after setup (all in resource group `finsight-rg`):

| Thing | Value used |
|---|---|
| Resource | `finsight-st`, type *Azure OpenAI*, region East US, Standard S0 |
| Network | public access (fine for dev; private endpoints are a Phase 5 topic) |
| Deployment 1 | name `gpt-5-mini` → model gpt-5-mini, **Global Standard** |
| Deployment 2 | name `text-embedding-3-large` → same-named model, Standard |

Steps to replicate:

1. Azure account with free trial ($200 / 30 days) at azure.com/free
2. Portal → Create a resource → "Azure OpenAI" → resource group
   `finsight-rg`, region East US, tier S0
3. Open the resource → Azure AI Foundry portal → **Deployments** →
   Deploy base model → deploy a chat model and an embedding model
4. Portal → the resource → **Keys and Endpoint** → copy endpoint + KEY 1

### Reality check: model availability (July 2026)

What the project plan says (GPT-4o / GPT-4o-mini) is **no longer
deployable** — worth knowing because you will hit this in some form:

- `gpt-4o`, `gpt-4.1` → `ServiceModelDeprecating` error: retired for new
  deployments
- `gpt-5.1` and other flagship models → "insufficient quota": free-trial
  subscriptions get **0 TPM** allocation for flagship models; the capacity
  slider can't go below zero, and the quota-increase form is a manually
  reviewed support ticket (days, often refused for trials)
- `gpt-5-mini` → deploys fine on trial quota. **Decision: use the mini
  model for every role in Phase 1** (see ADR-002). Model routing
  (supervisor on mini, synthesis on a bigger model) returns in Phase 3
  once quota allows.

Deployment *names* are labels you choose — the code only sees the label
(via `.env`), so a future model swap is a one-line `.env` edit, no code
change.

## 5. Configuration wiring (`.env`)

`config.py` loads `.env` (gitignored) and every module imports from
`config` — no secrets in code, exactly one place to change anything.

```powershell
copy .env.example .env
```

Then fill in:

```ini
AZURE_OPENAI_ENDPOINT="https://finsight-st.openai.azure.com/"
AZURE_OPENAI_API_KEY="<KEY 1 from Keys and Endpoint>"
AZURE_OPENAI_CHAT_DEPLOYMENT="gpt-5-mini"
AZURE_OPENAI_MINI_DEPLOYMENT="gpt-5-mini"
AZURE_OPENAI_EMBED_DEPLOYMENT="text-embedding-3-large"
DATABASE_URL="postgresql://finsight:finsight@localhost:5432/finsight"
EDGAR_USER_AGENT="FinSight research project <your-email>"
```

Notes:
- `EDGAR_USER_AGENT` must contain a real contact — SEC policy; they block
  anonymous scrapers.
- Never paste the API key into chats/issues/commits; if exposed,
  regenerate it (Keys and Endpoint → Regenerate).

Smoke-test the Azure wiring before anything else:

```powershell
.venv\Scripts\python -X utf8 -c "from ingestion.embedder import get_openai, embed_texts; print(len(embed_texts(get_openai(), ['test'])[0]), 'dims ok')"
```

## 6. Load data and run

```powershell
# 1. Download + parse + chunk (free, no key, cached under data/)
.venv\Scripts\python -X utf8 -m ingestion.pipeline JPM BAC --forms 10-K

# 2. Embed into pgvector (one-time; ~10+ min on trial-tier rate limits —
#    the SDK is silently backing off on 429s, this is normal)
.venv\Scripts\python -X utf8 -m ingestion.embedder

# 3. Ask
.venv\Scripts\python -X utf8 rag_cli.py "What cybersecurity risks did JPMorgan flag?" --tickers JPM
```

Verify the load:

```powershell
docker exec finsight-db psql -U finsight -d finsight -c "SELECT ticker, count(*) FROM chunks GROUP BY ticker;"
```

Expected: JPM 475, BAC 256 (FY2025 10-Ks).

## 7. Daily restart checklist

After a reboot, the only thing that doesn't come back by itself:

1. Start **Docker Desktop**, wait for it to finish starting
2. `docker compose -f infra/docker-compose.yml up -d` (a stopped
   container also restarts with just `docker start finsight-db`)

The venv, `.env`, downloaded filings, and everything in the `finsight_pgdata`
volume persist. Azure deployments keep running server-side (pay-per-token —
idle costs nothing).

## 8. Troubleshooting quick reference

| Symptom | Cause → fix |
|---|---|
| `failed to connect to the docker API at npipe:...` | Docker Desktop app not running → launch it |
| `psycopg.OperationalError: connection failed` | container not started → `docker start finsight-db` |
| `ServiceModelDeprecating` on deploy | that model snapshot is retired → pick a newer model, keep your deployment name |
| "Insufficient quota" with no slider | trial has 0 TPM for that model → use a mini model, or upgrade subscription to pay-as-you-go |
| Embedding run seems stuck | trial-tier TPM limit; SDK is retrying 429s → wait, or check progress with the count query above |
| `401` from Azure OpenAI | wrong key or endpoint in `.env`, or key was regenerated |
| `�` characters in console output | Windows codepage display issue → run with `python -X utf8` |
| Schema change not appearing | init script only runs on empty volume → apply via `psql` or `down -v` + reload |
