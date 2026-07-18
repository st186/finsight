"""Phase 2 eval harness.

Two levels of evaluation against evals/golden_dataset.jsonl:

1. RETRIEVAL (cheap, deterministic, run on every mode):
   - hit rate: fraction of answerable questions where ALL expected verbatim
     phrases appear somewhere in the top-k retrieved chunks
   - citation accuracy (temporal questions): the expected filing-year
     citation appears among the retrieved chunks' citations

2. ANSWERS (costs LLM calls; run on the chosen final config):
   - faithfulness: LLM judge scores whether every claim in the answer is
     supported by the retrieved evidence (0-10, reported /10)
   - answer relevancy: LLM judge scores whether the answer addresses the
     question (0-10)
   - refusal correctness: unanswerable questions must produce the literal
     "insufficient evidence" refusal

Usage:
    python -m evals.run_evals --modes vector keyword hybrid hybrid+rerank
    python -m evals.run_evals --modes hybrid+rerank --answers
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from rich.console import Console
from rich.table import Table

from config import CHAT_DEPLOYMENT
from ingestion.embedder import get_openai
from retrieval.search import retrieve

console = Console()
GOLDEN = Path(__file__).parent / "golden_dataset.jsonl"
K = 8


def _norm(s: str) -> str:
    """Normalize for phrase matching: lowercase, straight quotes, collapsed
    whitespace — so curly apostrophes or line breaks never cause a miss."""
    s = s.lower().replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s)


def load_golden() -> list[dict]:
    return [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------- retrieval
def eval_retrieval(mode: str, questions: list[dict]) -> dict:
    answerable = [q for q in questions if q["answerable"]]
    hits_ok, cite_ok, cite_total = 0, 0, 0
    misses = []
    for q in answerable:
        results = retrieve(
            q["question"], k=K, mode=mode,
            tickers=q.get("tickers"), items=q.get("items"),
        )
        blob = _norm(" ".join(h.text for h in results))
        found_all = all(_norm(p) in blob for p in q["expected_phrases"])
        hits_ok += found_all
        if not found_all:
            misses.append(q["id"])
        if q.get("expected_citation"):
            cite_total += 1
            cite_ok += any(q["expected_citation"] in h.citation for h in results)
    return {
        "mode": mode,
        "hit_rate": hits_ok / len(answerable),
        "n": len(answerable),
        "citation_acc": (cite_ok / cite_total) if cite_total else None,
        "misses": misses,
    }


# ------------------------------------------------------------------ answers
SYSTEM_PROMPT = None  # imported lazily from rag_cli to stay in sync

JUDGE_PROMPT = """You are grading a financial research assistant's answer.

QUESTION: {question}

EVIDENCE the assistant was given:
{evidence}

ASSISTANT'S ANSWER:
{answer}

Score two things from 0 to 10 and reply with ONLY a JSON object:
- "faithfulness": are all factual claims in the answer supported by the
  evidence? (10 = every claim supported; 0 = fabricated)
- "relevancy": does the answer directly address the question? (10 = fully)

Reply: {{"faithfulness": <int>, "relevancy": <int>}}"""


def eval_answers(mode: str, questions: list[dict]) -> dict:
    global SYSTEM_PROMPT
    from rag_cli import SYSTEM_PROMPT as SP
    SYSTEM_PROMPT = SP
    client = get_openai()

    faith, rel, judged = 0.0, 0.0, 0
    refusals_ok, refusals_total = 0, 0
    for q in questions:
        results = retrieve(q["question"], k=K, mode=mode,
                           tickers=q.get("tickers"), items=q.get("items"))
        evidence = "\n\n---\n\n".join(
            f"PASSAGE {i+1} {h.citation}:\n{h.text}" for i, h in enumerate(results)
        )
        answer = client.chat.completions.create(
            model=CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": f"EVIDENCE:\n\n{evidence}\n\nQUESTION: {q['question']}"},
            ],
        ).choices[0].message.content

        if not q["answerable"]:
            refusals_total += 1
            refusals_ok += "insufficient evidence" in answer.lower()
            continue

        verdict = client.chat.completions.create(
            model=CHAT_DEPLOYMENT,
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(
                question=q["question"], evidence=evidence[:24000], answer=answer)}],
        ).choices[0].message.content
        try:
            scores = json.loads(re.search(r"\{.*\}", verdict, re.S).group(0))
            faith += scores["faithfulness"]
            rel += scores["relevancy"]
            judged += 1
        except (AttributeError, KeyError, json.JSONDecodeError):
            console.print(f"[yellow]judge parse failure on {q['id']}[/yellow]")

    return {
        "mode": mode,
        "faithfulness": faith / judged / 10 if judged else None,
        "relevancy": rel / judged / 10 if judged else None,
        "judged": judged,
        "refusal_correctness": refusals_ok / refusals_total if refusals_total else None,
        "refusals": f"{refusals_ok}/{refusals_total}",
    }


# --------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+",
                    default=["vector", "keyword", "hybrid", "hybrid+rerank"])
    ap.add_argument("--answers", action="store_true",
                    help="also run the (costly) answer-level eval")
    ap.add_argument("--subset", help="only question ids starting with this prefix")
    args = ap.parse_args()

    questions = load_golden()
    if args.subset:
        questions = [q for q in questions if q["id"].startswith(args.subset)]
    console.print(f"golden set: {len(questions)} questions "
                  f"({sum(q['answerable'] for q in questions)} answerable)")

    table = Table(title=f"Retrieval eval (k={K})")
    for col in ("mode", "hit rate", "citation acc (temporal)", "misses"):
        table.add_column(col)
    for mode in args.modes:
        r = eval_retrieval(mode, questions)
        table.add_row(
            r["mode"], f"{r['hit_rate']:.0%}",
            f"{r['citation_acc']:.0%}" if r["citation_acc"] is not None else "—",
            ", ".join(r["misses"]) or "none",
        )
        console.print(f"  {mode}: done")
    console.print(table)

    if args.answers:
        for mode in args.modes:
            a = eval_answers(mode, questions)
            console.print(
                f"\n[bold]{mode}[/bold] answers: "
                f"faithfulness={a['faithfulness']:.2f} "
                f"relevancy={a['relevancy']:.2f} "
                f"refusals={a['refusals']} "
                f"({a['refusal_correctness']:.0%} correct)"
            )


if __name__ == "__main__":
    main()
