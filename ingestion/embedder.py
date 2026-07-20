"""Embed parsed chunks and load them into Postgres/pgvector.

Usage (after `docker compose -f infra/docker-compose.yml up -d` and
filling .env with Azure OpenAI credentials):

    python -m ingestion.embedder            # embeds every data/parsed/*.jsonl
    python -m ingestion.embedder JPM        # only files for one ticker
"""
from __future__ import annotations

import json
import sys
import time

import psycopg
from openai import AzureOpenAI, RateLimitError
from pgvector.psycopg import register_vector
from rich.console import Console

from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    DATA_PARSED,
    DATABASE_URL,
    EMBED_DEPLOYMENT,
)

console = Console()
# Small batches on purpose: a 64-chunk batch can exceed a trial-tier
# deployment's entire per-minute token budget, producing endless 429s.
# 12 chunks (~15K tokens) fits comfortably inside one quota window.
BATCH = 12


def get_openai() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
    )


def embed_texts(client: AzureOpenAI, texts: list[str]) -> list[list[float]]:
    # Trial-tier deployments have low TPM; on a hard 429 the SDK's built-in
    # retries can run out, so wait out the quota window ourselves.
    for attempt in range(10):
        try:
            resp = client.embeddings.create(model=EMBED_DEPLOYMENT, input=texts)
            return [d.embedding for d in resp.data]
        except RateLimitError:
            wait = 65
            console.print(f"[yellow]429 rate limit — sleeping {wait}s "
                          f"(attempt {attempt + 1}/10)[/yellow]")
            time.sleep(wait)
    raise RuntimeError("embedding rate limit persisted after 10 waits")


def load_file(conn: psycopg.Connection, client: AzureOpenAI, path) -> int:
    chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    inserted = 0
    with conn.cursor() as cur:
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i : i + BATCH]
            vectors = embed_texts(client, [c["text"] for c in batch])
            for chunk, vec in zip(batch, vectors):
                cur.execute(
                    """
                    INSERT INTO chunks (ticker, form, period, fiscal_label,
                                        item, section_name, seq, citation,
                                        text, embedding)
                    VALUES (%(ticker)s, %(form)s, %(period)s, %(fiscal_label)s,
                            %(item)s, %(section_name)s, %(seq)s, %(citation)s,
                            %(text)s, %(embedding)s)
                    ON CONFLICT (ticker, form, period, item, seq) DO NOTHING
                    """,
                    {**chunk, "embedding": vec},
                )
                inserted += cur.rowcount
            conn.commit()  # per batch, so progress survives a crash
    return inserted


def main() -> None:
    only = sys.argv[1].upper() if len(sys.argv) > 1 else None
    files = sorted(DATA_PARSED.glob(f"{only or '*'}*.jsonl"))
    if not files:
        console.print("[red]No parsed files found. Run ingestion.pipeline first.[/red]")
        return
    client = get_openai()
    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        for path in files:
            n = load_file(conn, client, path)
            console.print(f"{path.name}: {n} new chunks embedded")


if __name__ == "__main__":
    main()
