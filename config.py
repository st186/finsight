"""Central configuration loaded from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

EDGAR_USER_AGENT = os.getenv(
    "EDGAR_USER_AGENT", "FinSight research project subham.tiwari186@gmail.com"
)

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-5-mini")
MINI_DEPLOYMENT = os.getenv("AZURE_OPENAI_MINI_DEPLOYMENT", "gpt-5-mini")
EMBED_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-large")
EMBED_DIMENSIONS = 3072  # text-embedding-3-large native size

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://finsight:finsight@localhost:5432/finsight"
)

DATA_RAW = ROOT / "data" / "raw"
DATA_PARSED = ROOT / "data" / "parsed"

# Phase 1 scope: 6 banks + 4 tech for contrast
COMPANIES = {
    "JPM": "JPMorgan Chase & Co.",
    "BAC": "Bank of America Corp.",
    "C": "Citigroup Inc.",
    "GS": "Goldman Sachs Group Inc.",
    "MS": "Morgan Stanley",
    "WFC": "Wells Fargo & Co.",
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "GOOGL": "Alphabet Inc.",
    "NVDA": "NVIDIA Corp.",
}
