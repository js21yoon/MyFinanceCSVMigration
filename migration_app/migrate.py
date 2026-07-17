"""Orchestrates the migration pipeline (PRD §11).

--dry-run (Phase 0-5): pivot, transform, validate, report -- no Supabase writes.
--run (Phase 6-7): actual upsert, processed one CODEID at a time so progress
can be checkpointed and an interrupted run can resume without redoing
companies it already finished (PRD §11 Phase 7).
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from typing import Callable, Optional

from checkpoint import DEFAULT_CHECKPOINT_FILE, append_checkpoint, clear_checkpoint, load_checkpoint
from csv_pivot import pivot_csv
from report import generate_dry_run_report
from supabase_client import SupabaseClient
from transform import build_company_accounting_majority, transform_all
from upsert import execute_upsert, plan_upsert

DEFAULT_CSV = r"C:\VibeCoding\11_DataMigration\dmp_financesummary.csv"
PROGRESS_EVERY = 50  # print a progress line every N codeids processed


def _prepare(csv_path: str, only_codeids: set[str] | None):
    print(f"[migrate] pivoting {csv_path} ...")
    groups, pivot_stats = pivot_csv(csv_path)
    print(f"[migrate] csv rows={pivot_stats.row_count} groups={pivot_stats.group_count}")

    if only_codeids:
        groups = {k: v for k, v in groups.items() if k[0] in only_codeids}
        print(f"[migrate] --only-codeid filter applied: {len(groups)} groups remain")

    print("[migrate] fetching companies from Supabase ...")
    client = SupabaseClient()
    ticker_to_company_id = client.fetch_companies()

    csv_codeids = {codeid for codeid, _rptdate, _term in groups}
    matched_company_ids = [ticker_to_company_id[c] for c in csv_codeids if c in ticker_to_company_id]

    print(f"[migrate] fetching existing financials keys for {len(matched_company_ids)} matched companies ...")
    existing_keys = client.fetch_existing_financials_keys(matched_company_ids)
    accounting_majority = build_company_accounting_majority(existing_keys)

    print("[migrate] transforming all groups ...")
    rows, stats = transform_all(groups, ticker_to_company_id, accounting_majority)
    return client, rows, stats, existing_keys, pivot_stats


def run_dry_run(csv_path: str, only_codeids: set[str] | None = None) -> dict:
    _client, rows, stats, _existing_keys, pivot_stats = _prepare(csv_path, only_codeids)
    return generate_dry_run_report(rows, stats, pivot_stats.row_count)


def run_upsert(
    csv_path: str,
    only_codeids: set[str] | None = None,
    resume: bool = True,
    checkpoint_path=DEFAULT_CHECKPOINT_FILE,
    progress_callback: Optional[Callable[[int, int, dict], None]] = None,
) -> dict:
    """progress_callback(done, total, totals_so_far) is invoked after every
    CODEID (not just every PROGRESS_EVERY) so a GUI can drive a progress bar."""
    client, rows, stats, existing_keys, pivot_stats = _prepare(csv_path, only_codeids)

    rows_by_codeid: dict[str, list] = defaultdict(list)
    for row in rows:
        rows_by_codeid[row.codeid].append(row)

    done_codeids = load_checkpoint(checkpoint_path) if resume else set()
    all_codeids = list(rows_by_codeid)
    remaining = [c for c in all_codeids if c not in done_codeids]
    print(
        f"[migrate] {len(done_codeids & set(all_codeids))} codeids already completed (checkpoint), "
        f"{len(remaining)} remaining of {len(all_codeids)}"
    )

    totals = {"inserted": 0, "updated": 0, "skipped_no_company": 0, "skipped_foreign_source": 0}
    start = time.monotonic()
    for i, codeid in enumerate(remaining, start=1):
        plan = plan_upsert(rows_by_codeid[codeid], existing_keys)
        result = execute_upsert(client, plan)
        totals["inserted"] += result.inserted
        totals["updated"] += result.updated
        totals["skipped_no_company"] += result.skipped_no_company
        totals["skipped_foreign_source"] += result.skipped_foreign_source
        append_checkpoint(codeid, checkpoint_path)

        if progress_callback:
            progress_callback(i, len(remaining), dict(totals))

        if i % PROGRESS_EVERY == 0 or i == len(remaining):
            elapsed = time.monotonic() - start
            rate = i / elapsed if elapsed > 0 else 0
            eta_sec = (len(remaining) - i) / rate if rate > 0 else 0
            print(
                f"[migrate] progress {i}/{len(remaining)} codeids "
                f"({elapsed:.0f}s elapsed, ETA {eta_sec:.0f}s) totals={totals}"
            )

    summary = {
        "csv_source_row_count": pivot_stats.row_count,
        "total_groups": stats.total,
        "codeids_total": len(all_codeids),
        "codeids_processed_this_run": len(remaining),
        "codeids_skipped_via_checkpoint": len(all_codeids) - len(remaining),
        **totals,
    }
    print("[migrate] done:", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="dmp_financesummary.csv -> Supabase financials migration")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="path to dmp_financesummary.csv")
    parser.add_argument(
        "--only-codeid",
        action="append",
        default=None,
        help="restrict to specific CODEID(s), e.g. --only-codeid 005930 --only-codeid 000660 "
        "(for scoped test runs before migrating the full file)",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="ignore/clear the checkpoint from a prior --run and reprocess every CODEID from scratch "
        "(the natural-key upsert logic is idempotent, so this is safe -- just slower)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="validate & report only, no DB writes (default)")
    mode.add_argument(
        "--run",
        action="store_true",
        help="execute the actual upsert to Supabase -- writes data, use --only-codeid to scope a test run first",
    )
    args = parser.parse_args()

    only_codeids = set(args.only_codeid) if args.only_codeid else None

    if args.run:
        if args.reset_checkpoint:
            clear_checkpoint(DEFAULT_CHECKPOINT_FILE)
            print("[migrate] checkpoint cleared, reprocessing all CODEIDs")
        summary = run_upsert(args.csv, only_codeids, resume=not args.reset_checkpoint)
    else:
        summary = run_dry_run(args.csv, only_codeids)

    print()
    print("=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
