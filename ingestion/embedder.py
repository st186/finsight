"""Embed parsed chunks and load them into Postgres/pgvector.

Usage (after `docker compose -f infra/docker-compose.yml up -d` and
filling .env with Azure OpenAI credentials):

    python -m ingestion.embedder            # embeds every data/parsed/*.jsonl
    python -m ingestion.embedder JPM        # only files for one ticker
"""
from __future__ import annotations

import json
import sys

import psycopg
from openai import AzureOpenAI
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
BATCH = 64  # chunks per embeddings API call


def get_openai() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
    )


def embed_texts(client: AzureOpenAI, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBED_DEPLOYMENT, input=texts)
    return [d.embedding for d in resp.data]


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
    conn.commit()
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
