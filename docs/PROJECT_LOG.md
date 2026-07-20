# FinSight — Project Log

A chronological record of how this project was actually built: decisions,
detours, errors hit, and how they were resolved. Kept honest on purpose —
the detours are the most instructive part.

---

## 2026-07-16 — Project kickoff

**Planning.** Started from the 10-week project plan
(`FinSight_Project_Plan.pdf`): an agentic financial research assistant over
SEC filings — RAG, LangGraph agents, MLOps on Azure, built for GenAI
architect interview preparation. Appended a "Skills Required" section to the
plan mapping 9 skill groups to the phases where each is used, plus a
prerequisites-vs-learn-by-building table per phase.

**Environment surprises (before any code):**
- No Python installed → installed Python 3.14.6 (noted risk: very new
  version, some ML wheels may lag; keep 3.12 as fallback).
- No Docker → deferred; chose Docker Desktop over Supabase/local Postgres to
  match the plan's `docker compose` story.
- LLM provider decision: Azure free trial ($200/30 days) over OpenAI API or
  local Ollama — matches the plan's target ("what banks actually use") and
  the credit comfortably covers the whole project.

## 2026-07-16 — Phase 1 build (code)

Scaffolded the repo (ingestion / retrieval / agents / tools / api / evals /
infra / docs), then built and tested against live SEC data:

- **EDGAR client** — ticker→CIK resolution, filing listing, downloads;
  SEC-required User-Agent header and ~8 req/s throttle. Downloaded
  JPMorgan's FY2025 10-K: **12.9 MB** of inline-XBRL HTML.
- **Section parser** — HTML→text with tables flattened to pipe-rows, then
  regex split on `Item N.` headings. Two real-world lessons:
  - Table-of-contents entries duplicate every heading → drop matches with
    <200 chars of body; keep the longest occurrence per item.
  - A `�` scare in the console turned out to be Windows codepage display,
    not a data bug (the bytes were correct U+2019 apostrophes) → run
    everything with `python -X utf8`.
- **Chunker** — ~4,000-char chunks on paragraph boundaries, one-paragraph
  overlap, metadata header `[JPM | 10-K FY2025 | Item 1A: Risk Factors]`
  and a ready-made citation on every chunk.
- **Pipeline results:** JPM 10-K → 12 sections → 475 chunks; BAC 10-K →
  16 sections → 256 chunks.
- **Known quirks logged:** JPM incorporates MD&A/financials by reference
  into a ~1M-char Item 15 blob (content indexed, label imperfect); EDGAR's
  submissions API only lists ~1000 most recent filings, so heavy filers
  show fewer historical 10-Ks.

Also written (pending infra): embedder, pgvector schema with a generated
`tsvector` column pre-staged for Phase 2 BM25, vector search with metadata
filters, and `rag_cli.py` with a cite-or-refuse system prompt.

## 2026-07-17 — The Azure OpenAI saga

The most instructive day of Phase 1. The plan said "deploy GPT-4o and
GPT-4o-mini." Reality, one error at a time:

1. `gpt-4o` → **`ServiceModelDeprecating`** — retired for new deployments.
2. `gpt-4.1` (the suggested fallback) → same deprecation error.
3. Newest flagship (`gpt-5.1`) → **"insufficient quota"**: free-trial
   subscriptions get 0 TPM for flagship models; the capacity slider can't
   fix a zero allocation.
4. Detour into Microsoft's quota-increase form → recognized as a
   manually-reviewed support ticket (days, often refused for trials) →
   backed out.
5. **`gpt-5-mini` deployed successfully** (Global Standard), plus
   `text-embedding-3-large` (Standard).

**Resolution:** use the mini model for every LLM role in Phase 1; the
architecture routes all model choices through `.env`, so the future upgrade
is a one-line config change. Documented as ADR-002 — and it became the
centerpiece "vendor risk that materialized" story in the PRD risk register.

Also: an API key was pasted into a chat during setup → key regenerated the
same day (hygiene rule: keys only ever live in `.env`, which is gitignored).

## 2026-07-17 — Phase 1 verified end-to-end

Docker Desktop installed and running → `pgvector/pgvector:pg16` container up,
schema auto-applied via `docker-entrypoint-initdb.d`. Embedded all 731
chunks (~10+ min on trial-tier rate limits — the SDK silently retries 429s).

**The two tests that define the product:**
- *"What cybersecurity risks did JPMorgan flag?"* → multi-bullet
  analyst-style answer, **every bullet cited** `[JPM 10-K 2025, Item 1A]`,
  retrieval scores ~0.67–0.74. Correctly surfaced third-party/vendor risks
  from the Item 15 blob.
- *"What did Tesla say about vehicle recall risks?"* (not in index) →
  **"Insufficient evidence in the indexed filings."** — refusal instead of
  hallucination, retrieval scores collapsed to ~0.27.

Initial commit `4ceb918` (25 files), published public at
**github.com/st186/finsight** with topics rag / langgraph / azure-openai /
genai / sec-edgar / pgvector.

## 2026-07-17 — Documentation & explainability layer

- **`notebooks/phase1_walkthrough.ipynb`** — executed notebook replaying
  every pipeline stage with raw data visible: raw EDGAR JSON, the XBRL soup,
  before/after preprocessing, TOC-trap evidence, chunk overlap proof,
  cosine-similarity demo, live retrieval, and both RAG tests.
- **`docs/SETUP.md`** — blank-machine replication guide with architecture
  diagram (mermaid), the model-availability reality check, daily restart
  checklist, and a troubleshooting table of every error actually hit.
- **Three ADRs** — pgvector over dedicated vector DBs; gpt-5-mini for all
  roles (temporary, config-reversible); no ANN index at 3072 dims until
  Phase 2 evals can measure the trade-off.
- **`docs/PRD.md`** (AI PM lens) — personas, cite-or-refuse product
  principles, measurable AI quality requirements (faithfulness ≥ 0.85,
  citation coverage 100%, refusal correctness ≥ 0.90), launch gates per
  phase, and a Responsible-AI risk register where one risk (vendor model
  retirement) is marked *materialized and absorbed*.
- **`docs/phase1_manual_guide.html`** — self-contained do-it-yourself
  setup guide with expected-output checkpoints at every step.

## 2026-07-17 — Build-in-public setup

- LinkedIn content series planned (8 posts mapped to milestones); Post #1
  drafted. Drafts live in `docs/linkedin/` — **gitignored**, the playbook
  stays private.
- Cloud routine "FinSight LinkedIn drafter" scheduled (Mon & Fri 9:00 IST):
  reviews recent commits, drafts a post under strict voice rules (concrete
  numbers, one lesson, never fabricate), delivers as a Gmail draft for
  human review before posting. Direct LinkedIn posting was ruled out
  deliberately: no API access for personal profiles, ToS risk, and the
  human-review step is a feature, not a limitation.

---

## Scoreboard after Phase 1

| Metric | Value |
|---|---|
| Filings indexed | 2 (JPM, BAC FY2025 10-Ks) |
| Chunks in pgvector | 731 (3072-dim embeddings) |
| Citation behavior | every claim cited or answer refused (verified) |
| Azure spend so far | a few dollars of the $200 credit |
| Files committed | 28+ · public repo · 4 commits |

## 2026-07-18 — Phase 2: Retrieval quality & evaluation

**Corpus expansion.** Ingested the remaining 8 companies (13 filings total,
some with two fiscal years). Three data-quality findings, all documented
rather than hidden:
- **Citi & Morgan Stanley parse as one giant "Item FULL" section** — they
  format Item headings inside HTML tables, which the regex misses after
  table-flattening. Content indexed; section filtering degraded.
- **Wells Fargo's primary document is a ~150K-char wrapper** — the real
  report lives in a separate exhibit file (incorporation by reference, in a
  different *file*, unlike JPM's same-file variant). Exhibit fetching is
  backlog.
- Confirmed again: EDGAR's submissions API window (~1000 filings) hides
  older 10-Ks for heavy filers.

**The embedding saga, round 2.** The full-corpus embed hit trial-tier
reality twice:
1. Hard 429s killed the loader mid-file and per-file commits rolled back
   Citi's progress → fix: wait out quota windows (10×65s) + **commit per
   batch** so runs resume where they stopped.
2. Then it sat in an endless 429 loop anyway — the 64-chunk batches
   (~60-90K tokens) exceeded the deployment's entire per-minute budget, so
   no wait could ever succeed → fix: **batch size 12**. Rows flowed
   immediately; a TPM bump in the Azure portal then took throughput from
   ~12 to ~330 chunks/min. Total: **2,845 chunks, 10 companies**.
   (A progress monitor with a stall alarm now watches long loads — "alive"
   and "making progress" are different things.)

**Phase 2 infrastructure built and committed:**
- **Hybrid search**: Postgres full-text (pre-staged `tsv` column) +
  reciprocal rank fusion with the vector ranking.
- **Cross-encoder reranker**: BAAI/bge-reranker-base on CPU —
  sentence-transformers/PyTorch 2.13 installed *cleanly* on Python 3.14;
  the feared wheel gap never materialized.
- **Query rewriting**: mini-model expands vague questions into 2-3
  filing-vocabulary sub-queries, all lists RRF-fused.
- **Golden dataset**: 44 questions (18 single-fact, 6 section, 5
  comparison, 6 temporal, 10 unanswerable), every answerable one grounded
  in a verbatim phrase verified in the corpus *before* the question was
  written.
- **Eval harness**: deterministic retrieval hit rate + temporal citation
  accuracy; LLM-judge faithfulness/relevancy; deterministic refusal check.
- **Learning artifacts**: phase2_deepdive.ipynb, full_flow.ipynb (Phases
  1+2 end-to-end), docs/phase2_manual_guide.html.

**Eval-design lesson learned early:** the harness's first smoke test showed
the reranker confidently surfacing JPM's *balance-sheet* chunks (Item 15)
for a total-assets question while the golden phrase pinned the Item 1 prose
wording — the fact lives in multiple places. Verbatim-phrase hit rate is
deliberately strict; interpreting misses requires classifying them
(corpus problem vs retrieval problem vs golden-set problem).

**The eval runs — three rounds of measure → fix → re-measure:**

| Mode | Round 1 | After fixes |
|---|---|---|
| vector (baseline) | 83% | 83% |
| keyword | **14%** | **66%** (OR-of-keywords fallback after strict AND) |
| hybrid (RRF) | 83% | 80% |
| hybrid+rerank | **74%** (worse than no reranker!) | **83%** (blend CE ranking with hybrid via RRF instead of replacing) |
| rewrite+hybrid+rerank | 74% (was accidentally using un-blended rerank) | **86% — winner** |

Two findings demos would never have caught: naive Postgres FTS AND-semantics
starved keyword recall to 14%, and adding a cross-encoder reranker *hurt*
until its ranking was fused rather than substituted. One code-consistency
bug (rewrite mode still calling the old pure-CE path) was diagnosed from
its miss signature matching the pure-CE failure pattern.

**Answer-level results (best mode): faithfulness 0.91, relevancy 1.00,
refusals 10/10.** All PRD Phase 2 quality gates passed (Q1 ≥0.85 ✅,
Q2 ≥0.80 ✅, Q4 ≥0.90 ✅).

Remaining misses concentrate in multi-company comparisons (two filings'
evidence must share one top-8) — the designed fix is Phase 3's supervisor
decomposing questions per company.

## 2026-07-20 — Phase 3: Agents & orchestration (LangGraph)

Built the multi-agent system: `supervisor → rag → quant → synthesis →
critic → {accept | retry | human}`, LangGraph with a Postgres checkpointer
in the same `finsight-db`.

**Nodes:** supervisor (mini model decomposes + routes; text-only questions
skip the quant path — cost control); rag (wraps the Phase 2
rewrite+hybrid+rerank retriever); quant (real OpenAI tool-calling loop over
`tools/xbrl.py`); synthesis (cite-or-refuse, now also cites XBRL figure
sources); critic (verifies every claim, bounded retry then HITL); graph +
run CLI.

**LangGraph 1.2.9 + langchain-core 1.4.9 install cleanly on Python 3.14.**

**XBRL was the real work.** The SEC company-facts API is messier than the
plan implies: the `frame` field (CY<year>) is too sparse for recent
filings, so annual figures are keyed by the period-END year with
form=10-K/fp=FY selection and latest-FILED dedup for restatements. Issuers
also switch and vary US-GAAP tags — JPM moved from
`InterestAndDividendIncomeOperating` to `InterestIncomeOperating`, and net
interest income is reported directly as `InterestIncomeExpenseNet` (cleaner
than income − expense). Fixed concept resolution to be year-aware (pick the
candidate tag that actually covers the requested years) — that alone fixed
AAPL/MSFT revenue returning null. Verified figures against the filings: JPM
NII 89.3→92.6→95.4B, BAC 56.9→56.1→60.1B across 2023–25.

**Best bug — the critic evidence asymmetry.** The critic initially flagged
~10 "unsupported claim" issues on a perfectly good answer and never
accepted it (looping to the HITL interrupt every time). Root cause: the
synthesizer saw 1,200 chars per passage but the critic only saw **300** —
so the supporting text was literally truncated out of the critic's view. It
wasn't judging the answer, it was judging a smaller excerpt. Fix: give the
critic the full passage text (2,500 chars, matching synthesis) and instruct
it to accept faithful paraphrase rather than demand verbatim matches. Critic
then accepted the same answer at confidence 0.92. A perfect illustration of
why the critic is only as good as the evidence you show it.

**Deliverable met:** the NIM-comparison demo produces a visible agent-hop
trace, every number sourced to SEC XBRL and every claim cited, and the
Postgres checkpointer wrote 8 checkpoints (one per hop) — resumable and
auditable. HITL verified end-to-end: the graph pauses at `interrupt()` with
a review payload and resumes from the checkpoint on the human's decision.

## Next: Phase 4 — Productionization

FastAPI (streaming SSE) + API-key auth; Langfuse tracing on every node
(tokens/latency/cost per query); guardrails (prompt-injection scan on
retrieved chunks, output PII scan, rate limits); multi-stage Dockerfile;
`docker compose up` → API + Postgres + Langfuse.
