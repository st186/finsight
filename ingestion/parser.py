"""Parse SEC filing HTML into named sections.

Strategy: convert the HTML to plain text (tables flattened to rows of
cell text), then locate "Item N." headings with a regex. Filings repeat
item titles in the table of contents, so for each item we keep the LAST
occurrence that is followed by a substantial body of text.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Canonical 10-K item names (subset that matters for analysis; the parser
# still splits on any item number so section boundaries stay correct).
ITEM_NAMES_10K = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "5": "Market for Registrant's Common Equity",
    "6": "Selected Financial Data",
    "7": "Management's Discussion and Analysis (MD&A)",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules (incl. content incorporated by reference: MD&A, financial statements)",
}

ITEM_NAMES_10Q = {
    "1": "Financial Statements / Legal Proceedings",
    "1A": "Risk Factors",
    "2": "MD&A / Unregistered Sales",
    "3": "Market Risk / Defaults",
    "4": "Controls and Procedures / Mine Safety",
}

_ITEM_RE = re.compile(
    r"(?:^|\n)\s*ITEM\s+(\d{1,2}[A-C]?)\s*[.:—\-]",
    re.IGNORECASE,
)

_MIN_SECTION_CHARS = 200  # anything shorter is a TOC entry or cross-reference


@dataclass
class Section:
    item: str  # "1A"
    name: str  # "Risk Factors"
    text: str


def _decode(html: str | bytes) -> str:
    if isinstance(html, str):
        return html
    # filings sometimes declare utf-8 but contain cp1252 bytes (curly quotes)
    try:
        return html.decode("utf-8")
    except UnicodeDecodeError:
        return html.decode("cp1252", errors="replace")


def html_to_text(html: str | bytes) -> str:
    soup = BeautifulSoup(_decode(html), "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Flatten tables into pipe-separated rows so numbers keep row context.
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [
                c.get_text(" ", strip=True)
                for c in tr.find_all(["td", "th"])
            ]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with("\n".join(rows) + "\n")
    text = soup.get_text("\n")
    # normalize whitespace but keep line structure for heading detection
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def split_items(text: str, form: str) -> list[Section]:
    """Split filing text into item sections, dropping TOC duplicates."""
    names = ITEM_NAMES_10K if form == "10-K" else ITEM_NAMES_10Q
    matches = list(_ITEM_RE.finditer(text))
    if not matches:
        return [Section(item="FULL", name="Full Filing", text=text)]

    # candidate sections between consecutive item headings
    candidates: dict[str, Section] = {}
    for m, nxt in zip(matches, matches[1:] + [None]):
        item = m.group(1).upper()
        end = nxt.start() if nxt else len(text)
        body = text[m.start():end].strip()
        if len(body) < _MIN_SECTION_CHARS:
            continue  # table-of-contents entry
        # keep the longest occurrence of each item (TOC/cross-refs are short)
        if item not in candidates or len(body) > len(candidates[item].text):
            candidates[item] = Section(
                item=item,
                name=names.get(item, f"Item {item}"),
                text=body,
            )

    # preserve filing order
    order = {item: i for i, item in enumerate(dict.fromkeys(
        m.group(1).upper() for m in matches
    ))}
    return sorted(candidates.values(), key=lambda s: order.get(s.item, 99))


def parse_filing(html: str | bytes, form: str) -> list[Section]:
    return split_items(html_to_text(html), form)
