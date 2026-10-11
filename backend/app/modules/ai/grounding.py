"""Unsupported-claim check: every number in a coach answer must be traceable to a tool result.

The coach is told to quote figures only from tool results and never to compute new ones. This module checks that
mechanically, so a figure the model made up (or worked out itself) is caught rather than shown as fact.

A number in the answer is *supported* when, at the precision the answer shows, it equals a number in the evidence:

* money and plain numbers: ``$2,728`` matches ``2728.40`` (rounded to 0 decimals); the sign is ignored, because
  "a loss of $202" quotes ``-202``;
* percentages: ``75%`` matches the ratio ``0.7500`` (and a value that is already a percentage);
* R multiples: ``-2.02R`` matches ``-2.0200``;
* durations: any field ending in ``_seconds`` also offers minutes and hours.

Not checked: dates and times, citation markers like ``[E1]``, list numbering, years, small counts from 0 to 10
written without a unit (they are too ambiguous to check reliably), and numbers the user wrote in their question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_STRIP = [
    re.compile(r"\[E\d+\]"),  # citations
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"),  # ISO dates
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),  # clock times
    re.compile(rf"\b{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?", re.I),  # March 4, 2024
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}(?:\s+\d{{4}})?", re.I),  # 4 March 2024
    re.compile(r"^\s*\d+[.)]\s", re.M),  # list numbering
    re.compile(r"\b[A-Z]{2,}\d+[A-Z0-9]*\b"),  # symbols like ESH4, US500
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),  # ids
]
_NUM = re.compile(
    r"(?<![\w.])(?P<sign>[-−+])?\s?(?P<cur>[$€£¥])?\s?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?"
    r"(?:\s?(?P<pct>%|percent\b)|(?P<r>R)\b)?"
)
_YEAR = re.compile(r"^(19|20)\d{2}$")
_DATE_STR = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NUM_STR = re.compile(r"^-?\d+(\.\d+)?$")
_CITE = re.compile(r"\[(E\d+)\]")


@dataclass(frozen=True)
class Figure:
    text: str
    value: Decimal  # absolute value as written
    decimals: int
    percent: bool


@dataclass
class GroundingReport:
    checked: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    cited: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    uncited_lines: int = 0

    @property
    def grounded(self) -> bool:
        return not self.unsupported and not self.invalid_refs


def extract_figures(text: str) -> list[Figure]:
    for pat in _STRIP:
        text = pat.sub(" ", text)
    out = []
    for m in _NUM.finditer(text):
        whole = m.group("int").replace(",", "")
        dec = m.group("dec") or ""
        pct = bool(m.group("pct"))
        unit = pct or bool(m.group("cur")) or bool(m.group("r"))
        if not dec and not unit and (_YEAR.match(whole) or int(whole) <= 10):
            continue
        try:
            v = Decimal(whole + dec)
        except InvalidOperation:  # pragma: no cover - the regex only admits digits
            continue
        out.append(Figure(m.group(0).strip(), v, len(dec) - 1 if dec else 0, pct))
    return out


def evidence_values(payload: Any) -> set[Decimal]:
    """Every number in a tool result (Decimal strings, ints and floats), plus minutes/hours for *_seconds fields."""
    vals: set[Decimal] = set()

    def add(v: Decimal, key: str | None) -> None:
        vals.add(abs(v))
        if key and key.endswith("_seconds"):
            vals.add(abs(v) / 60)
            vals.add(abs(v) / 3600)

    def walk(x: Any, key: str | None = None) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list | tuple):
            for v in x:
                walk(v, key)
        elif isinstance(x, bool) or x is None:
            return
        elif isinstance(x, int | float | Decimal):
            add(Decimal(str(x)), key)
        elif isinstance(x, str) and _NUM_STR.match(x) and not _DATE_STR.match(x):
            add(Decimal(x), key)

    walk(payload)
    return vals


def _rounds_to(v: Decimal, target: Decimal, decimals: int) -> bool:
    q = Decimal(1).scaleb(-decimals)
    return any(v.quantize(q, rounding=r) == target for r in (ROUND_HALF_UP, ROUND_HALF_EVEN))


def supported(fig: Figure, values: set[Decimal]) -> bool:
    for v in values:
        if _rounds_to(v, fig.value, fig.decimals):
            return True
        if fig.percent and _rounds_to(v * 100, fig.value, fig.decimals):
            return True
    return False


def check(
    answer: str, evidence: dict[str, Any], question: str = "", extra_texts: list[str] | None = None
) -> GroundingReport:
    """`evidence` maps refs ("E1") to tool results. Numbers the user wrote in the question are allowed."""
    rep = GroundingReport()
    values: set[Decimal] = set()
    for res in evidence.values():
        values |= evidence_values(res)
    asked = {f.value for f in extract_figures(question)}
    for text in [answer, *(extra_texts or [])]:
        for fig in extract_figures(text):
            rep.checked.append(fig.text)
            if fig.value in asked or supported(fig, values):
                continue
            rep.unsupported.append(fig.text)
    refs = _CITE.findall(answer)
    rep.cited = sorted(set(refs) & set(evidence), key=lambda r: int(r[1:]))
    rep.invalid_refs = sorted(set(refs) - set(evidence))
    for line in re.split(r"\n+|(?<=[.!?])\s+", answer):
        if extract_figures(line) and not _CITE.search(line):
            rep.uncited_lines += 1
    rep.unsupported = list(dict.fromkeys(rep.unsupported))
    return rep
