# ADR-002: gpt-5-mini for every LLM role in Phase 1

**Status:** accepted (Phase 1, 2026-07) — expected to be superseded in Phase 3

## Context
The plan called for model routing: GPT-4o for synthesis/critic, GPT-4o-mini
for routing/classification. Reality on a fresh Azure free-trial subscription
(July 2026):

- `gpt-4o` and `gpt-4.1`: **retired for new deployments**
  (`ServiceModelDeprecating`).
- `gpt-5.1` and other flagship models: **0 TPM default quota** on trial
  subscriptions; quota increases require a manually-reviewed support ticket.
- `gpt-5-mini`: deploys immediately within trial quota.

## Decision
Deploy `gpt-5-mini` (Global Standard) and point both the chat and the
mini/routing config at it. Deployment names are wired through `.env`, so a
future upgrade is a config edit, not a code change.

## Rationale
- Phase 1's goal is proving the pipeline (ingest → retrieve → cite), not
  maximizing answer quality; the mini model demonstrably handles cited
  synthesis and refusal behavior (verified 2026-07-17).
- Unblocks development today instead of waiting days on a quota ticket.
- The cost-routing story survives: the architecture still has two named
  roles (CHAT_DEPLOYMENT / MINI_DEPLOYMENT); only the binding is temporary.

## Trade-offs
- Weaker synthesis and critique quality than a flagship model.
- Reasoning-tuned models reject some legacy params (e.g. `temperature`);
  the CLI has a fallback path for this.

## Revisit when
Quota for a flagship model is granted (or subscription upgraded to
pay-as-you-go) — swap `AZURE_OPENAI_CHAT_DEPLOYMENT` in `.env`, rerun evals.
