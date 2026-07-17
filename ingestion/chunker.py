"""Section-aware chunking with metadata headers.

Each chunk gets a metadata header line so both the embedding and the LLM
see the provenance, e.g.:

    [JPM | 10-K FY2024 | Item 1A: Risk Factors]

Chunks split on paragraph boundaries, targeting ~1000 tokens (~4000
chars) with one-paragraph overlap between consecutive chunks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ingestion.parser import Section

TARGET_CHARS = 4000
MAX_CHARS = 6000  # hard cap; oversized paragraphs are split mid-text


@dataclass
class Chunk:
    ticker: str
    form: str
    period: str  # report date, e.g. "2024-12-31"
    fiscal_label: str  # e.g. "FY2024" or "Q1 2025"
    item: str
    section_name: str
    seq: int  # position within section
    text: str  # includes the metadata header
    citation: str = field(init=False)  # e.g. "[JPM 10-K 2024, Item 1A]"

    def __post_init__(self) -> None:
        year = self.period[:4]
        self.citation = f"[{self.ticker} {self.form} {year}, Item {self.item}]"


def fiscal_label(form: str, report_date: str) -> str:
    year, month = report_date[:4], int(report_date[5:7])
    if form == "10-K":
        return f"FY{year}"
    if form == "10-Q":
        quarter = (month - 1) // 3 + 1
        return f"Q{quarter} {year}"
    return report_date


def _split_paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    out: list[str] = []
    for p in paras:
        while len(p) > MAX_CHARS:  # pathological long paragraph/table
            out.append(p[:MAX_CHARS])
            p = p[MAX_CHARS:]
        out.append(p)
    return out


def chunk_section(
    section: Section, ticker: str, form: str, period: str
) -> list[Chunk]:
    label = fiscal_label(form, period)
    header = f"[{ticker} | {form} {label} | Item {section.item}: {section.name}]"
    paras = _split_paragraphs(section.text)

    chunks: list[Chunk] = []
    buf: list[str] = []
    size = 0
    for para in paras:
        if size + len(para) > TARGET_CHARS and buf:
            chunks.append(_make(header, buf, ticker, form, period, label,
                                section, len(chunks)))
            buf = [buf[-1]]  # one-paragraph overlap
            size = len(buf[0])
        buf.append(para)
        size += len(para)
    if buf:
        chunks.append(_make(header, buf, ticker, form, period, label,
                            section, len(chunks)))
    return chunks


def _make(header, paras, ticker, form, period, label, section, seq) -> Chunk:
    return Chunk(
        ticker=ticker,
        form=form,
        period=period,
        fiscal_label=label,
        item=section.item,
        section_name=section.name,
        seq=seq,
        text=header + "\n" + "\n\n".join(paras),
    )
