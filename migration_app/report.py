"""Builds the dry-run validation report described in PRD §11 Phase 5:
group counts, per-column NULL rates, accounting_standard distribution,
low-confidence fiscal_quarter rows, and the company-match failure list.
Writes nothing to Supabase.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from mapping import NUMERIC_COLUMNS
from transform import TransformedRow, TransformStats

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def _null_rates(rows: list[TransformedRow]) -> dict[str, float]:
    total = len(rows)
    missing = {col: 0 for col in NUMERIC_COLUMNS}
    for row in rows:
        for col in NUMERIC_COLUMNS:
            if col not in row.values:
                missing[col] += 1
    return {col: round(100 * missing[col] / total, 2) for col in NUMERIC_COLUMNS} if total else {}


def generate_dry_run_report(
    rows: list[TransformedRow], stats: TransformStats, pivot_row_count: int
) -> dict:
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    null_rates = _null_rates(rows)

    summary = {
        "generated_at": timestamp,
        "csv_source_row_count": pivot_row_count,
        "total_groups": stats.total,
        "company_matched": stats.company_matched,
        "company_unmatched": stats.company_unmatched,
        "unmatched_codeid_count": len(stats.unmatched_codeids),
        "accounting_standard": {
            "GAAP": stats.gaap_count,
            "IFRS_CONSOLIDATED": stats.ifrs_consolidated_count,
            "IFRS_SEPARATE": stats.ifrs_separate_count,
        },
        "fiscal_quarter": {
            "ok": stats.fiscal_quarter_ok_count,
            "fallback_low_confidence": stats.fiscal_quarter_fallback_count,
        },
        "null_rate_percent_by_column": null_rates,
    }

    summary_path = REPORTS_DIR / f"dry_run_summary_{timestamp}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    unmatched_path = REPORTS_DIR / f"unmatched_codeids_{timestamp}.txt"
    with unmatched_path.open("w", encoding="utf-8") as f:
        f.write(f"# CODEID not found in companies.ticker ({len(stats.unmatched_codeids)})\n")
        for codeid in sorted(stats.unmatched_codeids):
            f.write(codeid + "\n")

    low_conf_path = REPORTS_DIR / f"low_confidence_fiscal_quarter_{timestamp}.csv"
    with low_conf_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["codeid", "rptdate", "report_term", "period_end", "fiscal_year", "fiscal_quarter"])
        for row in rows:
            if row.fiscal_quarter_is_fallback:
                writer.writerow(
                    [row.codeid, row.rptdate, row.report_term, row.period_end, row.fiscal_year, row.fiscal_quarter]
                )

    print(f"[report] summary        -> {summary_path}")
    print(f"[report] unmatched list -> {unmatched_path}")
    print(f"[report] low-confidence -> {low_conf_path}")
    return summary
