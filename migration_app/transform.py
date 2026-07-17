"""Derives the non-KEYDATA `financials` columns from a pivoted CSV group,
per PRD §4.2 and §5.1-5.5.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from csv_pivot import GroupKey

IFRS_CUTOFF = date(2011, 1, 1)
SOURCE_MARKER = "legacy_csv_migration"

# (company_id, period_type, period_end iso string, accounting_standard) -> (id, source)
# is_estimate is deliberately excluded -- it's not part of the real DB unique
# constraint `uq_financials` (see supabase_client.fetch_existing_financials_keys).
ExistingFinancialsKey = tuple[str, str, str, str]


def parse_rptdate(rptdate: str) -> tuple[int, int, bool]:
    is_estimate = rptdate.endswith("(E)")
    core = rptdate[:-3] if is_estimate else rptdate
    year_str, month_str = core.split(".")
    return int(year_str), int(month_str), is_estimate


def month_end(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def to_period_type(report_term: str) -> str:
    return "ANNUAL" if report_term == "YEAR" else "QUARTER"


def compute_fiscal_quarter(period_end: date, anchor: Optional[date]) -> tuple[int, bool]:
    """Returns (fiscal_quarter in 1..4, used_fallback). Caller should only
    call this for QUARTER rows; ANNUAL rows always get fiscal_quarter=None."""
    if anchor is not None:
        months = (period_end.year - anchor.year) * 12 + (period_end.month - anchor.month)
        if 0 < months <= 12:
            return -(-months // 3), False  # ceil division, guaranteed in 1..4
    return -(-period_end.month // 3), True


def build_year_end_index(groups: dict[GroupKey, dict[str, float]]) -> dict[str, list[date]]:
    """Per-company sorted list of YEAR period_end dates, used as fiscal_quarter anchors."""
    by_company: dict[str, list[date]] = defaultdict(list)
    for codeid, rptdate, report_term in groups:
        if report_term != "YEAR":
            continue
        year, month, _is_estimate = parse_rptdate(rptdate)
        by_company[codeid].append(month_end(year, month))
    for codeid in by_company:
        by_company[codeid].sort()
    return by_company


def build_company_accounting_majority(
    existing_keys: dict[ExistingFinancialsKey, tuple[int, Optional[str]]]
) -> dict[str, str]:
    """Majority-vote accounting_standard per company_id from existing financials rows.
    Ties resolve to IFRS_CONSOLIDATED (PRD §5.1)."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for company_id, _period_type, _period_end, accounting_standard in existing_keys:
        counts[company_id][accounting_standard] += 1
    majority: dict[str, str] = {}
    for company_id, c in counts.items():
        best = max(c.items(), key=lambda kv: (kv[1], kv[0] == "IFRS_CONSOLIDATED"))
        majority[company_id] = best[0]
    return majority


def determine_accounting_standard(
    period_end: date, company_id: Optional[str], majority_map: dict[str, str]
) -> str:
    if period_end < IFRS_CUTOFF:
        return "GAAP"
    if company_id and company_id in majority_map:
        return majority_map[company_id]
    return "IFRS_CONSOLIDATED"


@dataclass
class TransformedRow:
    codeid: str
    rptdate: str
    report_term: str
    company_id: Optional[str]
    period_type: str
    period_end: str  # ISO date string
    fiscal_year: int
    fiscal_quarter: Optional[int]
    is_estimate: bool
    accounting_standard: str
    source: str
    values: dict[str, float]
    fiscal_quarter_is_fallback: bool = False


@dataclass
class TransformStats:
    total: int = 0
    company_matched: int = 0
    company_unmatched: int = 0
    unmatched_codeids: set = field(default_factory=set)
    gaap_count: int = 0
    ifrs_consolidated_count: int = 0
    ifrs_separate_count: int = 0
    fiscal_quarter_fallback_count: int = 0
    fiscal_quarter_ok_count: int = 0


def transform_all(
    groups: dict[GroupKey, dict[str, float]],
    ticker_to_company_id: dict[str, str],
    accounting_majority: dict[str, str],
) -> tuple[list[TransformedRow], TransformStats]:
    year_end_index = build_year_end_index(groups)
    rows: list[TransformedRow] = []
    stats = TransformStats()

    for (codeid, rptdate, report_term), values in groups.items():
        stats.total += 1
        year, month, is_estimate = parse_rptdate(rptdate)
        pe = month_end(year, month)
        period_type = to_period_type(report_term)

        company_id = ticker_to_company_id.get(codeid)
        if company_id:
            stats.company_matched += 1
        else:
            stats.company_unmatched += 1
            stats.unmatched_codeids.add(codeid)

        fiscal_quarter: Optional[int]
        is_fallback = False
        if period_type == "QUARTER":
            anchor = None
            for ye in reversed(year_end_index.get(codeid, [])):
                if ye < pe:
                    anchor = ye
                    break
            fiscal_quarter, is_fallback = compute_fiscal_quarter(pe, anchor)
            if is_fallback:
                stats.fiscal_quarter_fallback_count += 1
            else:
                stats.fiscal_quarter_ok_count += 1
        else:
            fiscal_quarter = None

        accounting_standard = determine_accounting_standard(pe, company_id, accounting_majority)
        if accounting_standard == "GAAP":
            stats.gaap_count += 1
        elif accounting_standard == "IFRS_SEPARATE":
            stats.ifrs_separate_count += 1
        else:
            stats.ifrs_consolidated_count += 1

        rows.append(
            TransformedRow(
                codeid=codeid,
                rptdate=rptdate,
                report_term=report_term,
                company_id=company_id,
                period_type=period_type,
                period_end=pe.isoformat(),
                fiscal_year=year,
                fiscal_quarter=fiscal_quarter,
                is_estimate=is_estimate,
                accounting_standard=accounting_standard,
                source=SOURCE_MARKER,
                values=values,
                fiscal_quarter_is_fallback=is_fallback,
            )
        )
    return rows, stats
