"""Ingestion pipeline: EDGAR -> parse -> chunk -> data/parsed/*.jsonl

Usage:
    python -m ingestion.pipeline                # all companies, 10-K only
    python -m ingestion.pipeline JPM BAC        # subset
    python -m ingestion.pipeline --forms 10-K 10-Q

Embedding/DB loading is a separate step (ingestion.embedder) so you can
re-run parsing without paying for embeddings twice.
"""
from __future__ import annotations

import argparse
import dataclasses
import json

from rich.console import Console

from config import COMPANIES, DATA_PARSED
from ingestion.chunker import chunk_section
from ingestion.edgar_client import EdgarClient
from ingestion.parser import parse_filing

console = Console()


def ingest(tickers: list[str], forms: tuple[str, ...], since: str) -> None:
    client = EdgarClient()
    DATA_PARSED.mkdir(parents=True, exist_ok=True)

    for ticker in tickers:
        filings = client.list_filings(ticker, forms=forms, since=since)
        console.print(f"[bold]{ticker}[/bold]: {len(filings)} filings")
        for filing in filings:
            out = DATA_PARSED / f"{ticker}_{filing.form}_{filing.report_date}.jsonl"
            if out.exists():
                console.print(f"  {filing.form} {filing.report_date}: cached")
                continue
            path = client.download_filing(filing)
            sections = parse_filing(path.read_bytes(), filing.form)
            chunks = [
                chunk
                for section in sections
                for chunk in chunk_section(
                    section, ticker, filing.form, filing.report_date
                )
            ]
            with out.open("w", encoding="utf-8") as f:
                for chunk in chunks:
                    f.write(json.dumps(dataclasses.asdict(chunk)) + "\n")
            console.print(
                f"  {filing.form} {filing.report_date}: "
                f"{len(sections)} sections -> {len(chunks)} chunks"
            )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", default=list(COMPANIES))
    ap.add_argument("--forms", nargs="+", default=["10-K"])
    ap.add_argument("--since", default="2023-01-01")
    args = ap.parse_args()
    ingest(args.tickers or list(COMPANIES), tuple(args.forms), args.since)
