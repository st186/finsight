"""SEC XBRL company-facts tools for the quant agent.

Financial FIGURES must never come from the LLM's memory. These tools fetch
the actual reported numbers from the SEC's free company-facts API:

    https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json

The LLM decides which metric/company/years it needs; the value comes from
here. Every returned figure carries its provenance (concept tag + fiscal
year), which is the numeric equivalent of a citation.

Annual figures are identified by the XBRL "frame" CY<year> (a full calendar
year), which is far more reliable than the per-fact `fy` field.
"""
from __future__ import annotations

import re
import time
from functools import lru_cache

import httpx

from config import EDGAR_USER_AGENT
from ingestion.edgar_client import EdgarClient

_client = httpx.Client(headers={"User-Agent": EDGAR_USER_AGENT}, timeout=30,
                       follow_redirects=True)
_edgar = EdgarClient()
_last = 0.0

# Human-friendly metric name -> candidate US-GAAP concept tags (first that
# resolves wins). Banks and tech tag differently, and issuers switch tags
# over time, so we keep ordered alternatives (newest/most-common first).
METRIC_CONCEPTS: dict[str, list[str]] = {
    "net_interest_income": ["InterestIncomeExpenseNet"],
    "interest_income": ["InterestIncomeOperating", "InterestAndDividendIncomeOperating",
                        "InterestAndFeeIncomeLoansAndLeases"],
    "interest_expense": ["InterestExpense"],
    "provision_for_credit_losses": ["ProvisionForLoanLeaseAndOtherLosses",
                                    "ProvisionForLoanAndLeaseLosses",
                                    "ProvisionForDoubtfulAccounts"],
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "stockholders_equity": ["StockholdersEquity"],
}


def _throttle() -> None:
    global _last
    wait = _last + 0.15 - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


@lru_cache(maxsize=32)
def _company_facts(ticker: str) -> dict:
    cik = _edgar.cik_for_ticker(ticker)
    _throttle()
    r = _client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
    r.raise_for_status()
    return r.json()


def _annual_series(ticker: str, concept: str) -> dict[int, tuple[float, str]]:
    """year -> (value, unit) of annual 10-K figures for one concept, or {}.

    Keyed by the period-END year (works across calendar and off-calendar
    fiscal years). The `frame` field is too sparse for recent filings, so
    we select on form=10-K + fp=FY instead, keep full-year durations only
    (flows), accept point-in-time snapshots (balance-sheet items), and on
    duplicate years keep the latest-FILED value (restatements win)."""
    facts = _company_facts(ticker).get("facts", {}).get("us-gaap", {})
    if concept not in facts:
        return {}
    best: dict[int, tuple[float, str, str]] = {}  # year -> (val, unit, filed)
    for unit, rows in facts[concept]["units"].items():
        for r in rows:
            if r.get("form") != "10-K" or r.get("fp") != "FY":
                continue
            start, end = r.get("start"), r.get("end", "")
            if start:  # duration (flow): keep only ~full-year spans
                days = (_d(end) - _d(start)).days
                if not (330 <= days <= 400):
                    continue
            year = int(end[:4])
            filed = r.get("filed", "")
            if year not in best or filed > best[year][2]:
                best[year] = (float(r["val"]), unit, filed)
    return {y: (v, u) for y, (v, u, _f) in best.items()}


def _d(s: str):
    from datetime import date
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _resolve(ticker: str, metric: str, need_years: list[int] | None = None
             ) -> tuple[str, dict[int, tuple[float, str]]]:
    """Map a friendly metric to a concept tag. Issuers switch tags and use
    different ones, so pick the candidate whose series covers the requested
    years (or, absent a request, the one with the most annual data points)."""
    candidates = METRIC_CONCEPTS.get(metric, [metric])
    best: tuple[str, dict[int, tuple[float, str]]] = (metric, {})
    for concept in candidates:
        series = _annual_series(ticker, concept)
        if not series:
            continue
        if need_years and all(y in series for y in need_years):
            return concept, series  # fully covers the request — take it
        if len(series) > len(best[1]):
            best = (concept, series)
    return best


# ---------------------------------------------------------------- the tools
def get_metric(ticker: str, metric: str, year: int) -> dict:
    """One reported figure. metric is a friendly name (see METRIC_CONCEPTS)
    or a raw US-GAAP concept tag. Returns a dict with provenance."""
    concept, series = _resolve(ticker, metric, [year])
    if year not in series:
        return {"ticker": ticker.upper(), "metric": metric, "year": year,
                "value": None, "error": f"no reported value for {metric} {year}",
                "available_years": sorted(series)}
    value, unit = series[year]
    return {"ticker": ticker.upper(), "metric": metric, "concept": concept,
            "year": year, "value": value, "unit": unit,
            "source": f"SEC XBRL {concept} CY{year}"}


def compare_trend(ticker: str, metric: str, years: list[int]) -> dict:
    """A metric across several years, plus first->last % change."""
    concept, series = _resolve(ticker, metric, years)
    points = {y: series[y][0] for y in years if y in series}
    change = None
    if len(points) >= 2:
        ys = sorted(points)
        first, last = points[ys[0]], points[ys[-1]]
        if first:
            change = round(100 * (last - first) / abs(first), 1)
    return {"ticker": ticker.upper(), "metric": metric, "concept": concept,
            "points": points, "pct_change_first_to_last": change,
            "source": f"SEC XBRL {concept}",
            "missing_years": [y for y in years if y not in series]}


def compute_ratio(numerator: float, denominator: float) -> dict:
    """A safe division helper for the agent (e.g. a margin)."""
    if not denominator:
        return {"value": None, "error": "division by zero"}
    return {"value": round(numerator / denominator, 4)}


def net_interest_income(ticker: str, year: int) -> dict:
    """Net interest income — the bank profit metric. Prefers the directly
    reported InterestIncomeExpenseNet concept; falls back to income minus
    expense if an issuer doesn't tag the net figure."""
    direct = get_metric(ticker, "net_interest_income", year)
    if direct["value"] is not None:
        return direct
    inc = get_metric(ticker, "interest_income", year)
    exp = get_metric(ticker, "interest_expense", year)
    if inc["value"] is None or exp["value"] is None:
        return {"ticker": ticker.upper(), "metric": "net_interest_income",
                "year": year, "value": None,
                "error": "no reported net interest income and cannot derive it"}
    return {"ticker": ticker.upper(), "metric": "net_interest_income",
            "year": year, "value": inc["value"] - exp["value"], "unit": "USD",
            "source": f"SEC XBRL {inc['concept']} - {exp['concept']} CY{year}"}
