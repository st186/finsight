"""Phase 1 deliverable: CLI demo — ask a question, get a cited answer.

    python rag_cli.py "What cybersecurity risks did JPMorgan flag?" --tickers JPM
"""
from __future__ import annotations

import argparse

from rich.console import Console
from rich.panel import Panel

from config import CHAT_DEPLOYMENT
from ingestion.embedder import get_openai
from retrieval.search import search

console = Console()

SYSTEM_PROMPT = """\
You are FinSight, a financial research assistant answering questions about
SEC filings. Rules, in priority order:

1. Use ONLY the evidence passages provided below. Never use outside
   knowledge or memory for facts or figures.
2. Every factual claim MUST end with the bracketed citation of the passage
   it came from, e.g. [JPM 10-K 2025, Item 1A]. No citation -> do not make
   the claim.
3. If the evidence does not answer the question, reply exactly:
   "Insufficient evidence in the indexed filings." and say what is missing.
4. Write in the concise, neutral tone of an equity research analyst.
"""


def answer(question: str, tickers: list[str] | None, k: int = 8) -> None:
    hits = search(question, k=k, tickers=tickers)
    if not hits:
        console.print("[red]No results — is the database loaded?[/red]")
        return

    evidence = "\n\n---\n\n".join(
        f"PASSAGE {i+1} {h.citation}:\n{h.text}" for i, h in enumerate(hits)
    )
    client = get_openai()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"EVIDENCE:\n\n{evidence}\n\nQUESTION: {question}",
        },
    ]
    try:
        # temperature=0 for determinism; reasoning-tuned models (o-series,
        # gpt-5 family) reject a custom temperature, so fall back to default.
        resp = client.chat.completions.create(
            model=CHAT_DEPLOYMENT, temperature=0, messages=messages
        )
    except Exception as e:
        if "temperature" not in str(e).lower():
            raise
        resp = client.chat.completions.create(model=CHAT_DEPLOYMENT, messages=messages)
    console.print(Panel(resp.choices[0].message.content, title="FinSight"))
    console.print("[dim]Sources retrieved:[/dim]")
    for h in hits:
        console.print(f"  [dim]{h.score:.3f}  {h.citation}  {h.section_name}[/dim]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--tickers", nargs="+", default=None)
    ap.add_argument("-k", type=int, default=8)
    args = ap.parse_args()
    answer(args.question, args.tickers, args.k)
