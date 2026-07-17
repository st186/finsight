# PRD — FinSight: Agentic Financial Research Assistant

| | |
|---|---|
| **Author** | Subham Tiwari |
| **Status** | Living document — v1.0 covers Phases 1–2 |
| **Last updated** | July 2026 |
| **Related** | [Architecture ADRs](adr/) · [Setup guide](SETUP.md) · [Project plan](../README.md) |

---

## 1. Problem

Equity research and credit/risk analysts must read SEC filings (10-K annual
reports run 200–400 pages) to answer questions about a company's performance
and risks. An analyst covering 10 companies reads thousands of pages per
quarter. Today this is Ctrl+F, Excel, and institutional memory — slow,
error-prone, and expensive: analyst hours are among the costliest inputs in
financial research.

Generic LLM chatbots are unusable here for one reason: **a confident wrong
answer in finance is worse than no answer**. A hallucinated loan-loss figure
can move a real lending or investment decision. Banks (JPMorgan's LLM Suite,
Citigroup's regulatory summarization) are investing precisely because the
value is large *and* the trust bar is high.

## 2. Users & personas

| Persona | Job to be done | What they need from FinSight |
|---|---|---|
| **Equity research analyst** (primary) | Compare metrics & risk language across companies/years to support a rating | Fast cross-filing answers, every claim traceable to the source paragraph |
| **Credit/risk analyst** | Assess whether a borrower's risk profile changed since last review | Reliable trend data from *reported* figures, flagged risk-factor changes |
| **Compliance reviewer** (secondary) | Audit how an AI-assisted conclusion was reached | Full trace: which sources retrieved, which model, which claims cited |

## 3. Product principles (non-negotiable)

1. **Cite or refuse.** Every factual claim carries a citation to a real
   filing passage or a real API-fetched number. No citation → the claim is
   removed or the answer says "insufficient evidence."
2. **Numbers never come from the model's memory.** Financial figures are
   fetched from SEC's structured XBRL data, not generated.
3. **Low confidence → human review.** The system escalates rather than
   guesses (Phase 3 human-in-the-loop interrupt).
4. **Every answer is auditable.** Full trace of agents, sources, tokens,
   and cost per query (Phase 4 observability).

## 4. Scope

**In scope (v1):** 8–10 large-cap US companies (banks + tech), last 3 fiscal
years, filing types 10-K / 10-Q / 8-K. English. Single-turn Q&A first,
conversation memory in Phase 3.

**Explicit non-goals (v1):**
- Investment advice or buy/sell recommendations (assistive research only)
- Real-time market data, prices, or news
- Non-US filings (BSE/NSE, ESMA) — architecture allows later expansion
- Fine-tuned models — retrieval grounding is the quality lever, not tuning

Tight scoping is deliberate: a small corpus keeps evaluation iteration fast,
which matters more than coverage while retrieval quality is being tuned.

## 5. Requirements

### Functional
| ID | Requirement | Phase |
|---|---|---|
| F1 | Answer single-company questions over indexed filings with inline citations | 1 ✅ |
| F2 | Refuse out-of-scope questions explicitly rather than answer from model memory | 1 ✅ |
| F3 | Filter retrieval by company, filing type, period, section | 1 ✅ |
| F4 | Hybrid retrieval (keyword + semantic) with reranking | 2 |
| F5 | Cross-company and temporal comparison via multi-agent orchestration | 3 |
| F6 | Quantitative answers fetched from XBRL structured data with computed ratios | 3 |
| F7 | Critic agent verifies claim-to-citation mapping before release | 3 |
| F8 | Human review interrupt on low-confidence answers | 3 |
| F9 | Streaming API with auth and rate limits | 4 |

### AI quality requirements (measured, not asserted)
| ID | Requirement | Target | How measured |
|---|---|---|---|
| Q1 | Faithfulness (claims grounded in retrieved evidence) | ≥ 0.85 on golden set | RAGAS, Phase 2 |
| Q2 | Retrieval hit rate (correct source in top-k) | ≥ 0.80 | custom metric vs golden set |
| Q3 | Citation coverage (claims carrying a citation) | 100% (hard rule) | critic agent + eval |
| Q4 | Unanswerable questions correctly refused | ≥ 0.90 | golden set includes trap questions |
| Q5 | No regression ships | CI eval gate | pipeline fails if Q1 drops below threshold |

### Operational requirements
| ID | Requirement | Target |
|---|---|---|
| O1 | Cost per query, tracked and visible | < $0.05 avg (model routing keeps simple queries on the cheap model) |
| O2 | P95 answer latency | < 15s non-streaming; first token < 3s streaming |
| O3 | Model swappable without code change | config-only swap (validated in practice — see ADR-002) |

## 6. Success metrics

- **North star:** analyst time-to-answer — minutes of manual filing search
  replaced per query (proxy: % of golden-set questions answered correctly
  with citations).
- **Trust guardrails (never trade against north star):** faithfulness ≥ 0.85,
  citation coverage 100%, refusal correctness ≥ 0.90. A launch that improves
  speed but regresses any guardrail does not ship — enforced by the CI eval
  gate (Phase 5).
- **Ops health:** cost per query, p95 latency, trace completeness.

*Portfolio note: v1 has no production users; "success" is defined against
the golden dataset and the eval harness — which is exactly how an AI product
should be gated pre-launch anyway.*

## 7. Risks & mitigations (Responsible AI register)

| Risk | Likelihood | Impact | Mitigation (built, not promised) |
|---|---|---|---|
| Hallucinated claims reach users | Med | **High** | RAG grounding + cite-or-refuse prompt (P1 ✅) + critic agent (P3) + eval gate (P5) |
| Retrieval returns wrong evidence (right-sounding, wrong source) | High | High | Golden dataset + hybrid search + reranker, all measured (P2) |
| Prompt injection via filing text (filings are untrusted input) | Med | High | Injection screening on retrieved chunks before they reach the LLM (P4) |
| Vendor model retired / quota withdrawn | **Materialized (July 2026)** | Med | Config-only model swap; absorbed GPT-4o retirement with a one-line change (ADR-002) |
| PII leakage in outputs | Low | High | Output PII scan (P4); corpus is public filings, lowering baseline risk |
| Cost runaway | Med | Med | Model routing, per-user rate limits (P4), Azure budget alert (P5) |
| Over-trust: users treat assistive output as advice | Med | High | Non-goal stated; every answer carries sources so verification is one click; HITL for low confidence |

## 8. Launch gates

A phase ships only when its gate passes:

- **P1 → P2:** cited Q&A demo + correct refusal behavior — ✅ verified 2026-07-17
- **P2 → P3:** eval report shows hybrid+rerank beats baseline on Q1/Q2 with no Q4 regression
- **P3 → P4:** critic agent blocks 100% of uncited claims on the golden set
- **P4 → P5:** full trace + cost visible for every query; injection tests pass
- **P5 → done:** CI eval gate demonstrably blocks a seeded regression

## 9. Open questions

- Should refusals offer the *nearest* answerable question (recovery UX) or
  stay silent? (Decide with Phase 2 eval data on near-miss queries.)
- Where is the confidence threshold for HITL escalation? (Tune in Phase 3
  against the golden set's ambiguous questions.)
- Does Item 15 blob labeling (JPM's incorporated-by-reference MD&A) mislead
  citations enough to warrant a dedicated re-labeling pass? (Phase 2.)
