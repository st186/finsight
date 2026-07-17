"""SEC EDGAR API client.

Free, no key required. SEC fair-access policy: max ~10 requests/second
and a User-Agent header that identifies you. Both are enforced here.

Endpoints used:
  - https://www.sec.gov/files/company_tickers.json      ticker -> CIK map
  - https://data.sec.gov/submissions/CIK{cik:010d}.json  filing index per company
  - https://www.sec.gov/Archives/edgar/data/...          the filing documents
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import DATA_RAW, EDGAR_USER_AGENT

_MIN_INTERVAL = 0.12  # seconds between requests (~8 req/s, under SEC's 10)


@dataclass
class Filing:
    ticker: str
    cik: int
    form: str  # "10-K", "10-Q", "8-K"
    accession: str  # e.g. "0000019617-25-000123"
    filing_date: str  # "2025-02-14"
    report_date: str  # period the filing covers
    primary_document: str  # e.g. "jpm-20241231.htm"

    @property
    def document_url(self) -> str:
        acc = self.accession.replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{self.cik}/{acc}/{self.primary_document}"
        )

    @property
    def local_path(self) -> Path:
        return DATA_RAW / self.ticker / f"{self.form}_{self.report_date}.htm"


class EdgarClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": EDGAR_USER_AGENT},
            timeout=30,
            follow_redirects=True,
        )
        self._last_request = 0.0
        self._ticker_map: dict[str, int] | None = None

    def _throttle(self) -> None:
        wait = self._last_request + _MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=20))
    def _get(self, url: str) -> httpx.Response:
        self._throttle()
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp

    def cik_for_ticker(self, ticker: str) -> int:
        if self._ticker_map is None:
            data = self._get("https://www.sec.gov/files/company_tickers.json").json()
            self._ticker_map = {
                row["ticker"].upper(): row["cik_str"] for row in data.values()
            }
        return self._ticker_map[ticker.upper()]

    def list_filings(
        self,
        ticker: str,
        forms: tuple[str, ...] = ("10-K", "10-Q", "8-K"),
        since: str = "2023-01-01",
    ) -> list[Filing]:
        """Return recent filings of the given form types since a date."""
        cik = self.cik_for_ticker(ticker)
        data = self._get(
            f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        ).json()
        recent = data["filings"]["recent"]
        filings = []
        for i, form in enumerate(recent["form"]):
            if form in forms and recent["filingDate"][i] >= since:
                filings.append(
                    Filing(
                        ticker=ticker.upper(),
                        cik=cik,
                        form=form,
                        accession=recent["accessionNumber"][i],
                        filing_date=recent["filingDate"][i],
                        report_date=recent["reportDate"][i] or recent["filingDate"][i],
                        primary_document=recent["primaryDocument"][i],
                    )
                )
        return filings

    def download_filing(self, filing: Filing, force: bool = False) -> Path:
        """Download the primary document to data/raw/, return the local path."""
        path = filing.local_path
        if path.exists() and not force:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        resp = self._get(filing.document_url)
        path.write_bytes(resp.content)
        # sidecar metadata so the parser knows what this file is
        meta = path.with_suffix(".json")
        meta.write_text(json.dumps(filing.__dict__, indent=2))
        return path
