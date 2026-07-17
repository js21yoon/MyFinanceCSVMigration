"""Streams dmp_financesummary.csv and pivots it from long format
(one row per KEYDATA) to wide format (one row per CODEID+RPTDATE+REPORT_TERM),
per PRD §4.1.

EVENTTIME, DATASOURCE, VALDATAUNIT are dropped entirely (per instructions).
REPORTSEQ is read only to help flag anomalies -- it is never used as a
mapping key (PRD §2: the same REPORTSEQ number means different KEYDATA
depending on which era of the CSV a row came from).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from mapping import KEYDATA_TO_COLUMN

USECOLS = ["RPTDATE", "REPORT_TERM", "CODEID", "KEYDATA", "VALDATA", "REPORTSEQ"]
GroupKey = tuple[str, str, str]  # (CODEID, RPTDATE, REPORT_TERM)


@dataclass
class PivotStats:
    row_count: int = 0
    group_count: int = 0
    unknown_keydata: set[str] = field(default_factory=set)
    duplicate_keydata_in_group: int = 0


def pivot_csv(
    csv_path: str, chunksize: int = 100_000, warn: Callable[[str], None] = print
) -> tuple[dict[GroupKey, dict[str, float]], PivotStats]:
    groups: dict[GroupKey, dict[str, float]] = {}
    stats = PivotStats()

    dtype = {"RPTDATE": str, "REPORT_TERM": str, "CODEID": str, "KEYDATA": str}
    for chunk in pd.read_csv(csv_path, usecols=USECOLS, dtype=dtype, chunksize=chunksize):
        for rptdate, report_term, codeid, keydata, valdata, _reportseq in chunk.itertuples(
            index=False, name=None
        ):
            stats.row_count += 1
            column = KEYDATA_TO_COLUMN.get(keydata)
            if column is None:
                stats.unknown_keydata.add(keydata)
                continue
            key = (codeid, rptdate, report_term)
            values = groups.setdefault(key, {})
            if column in values:
                stats.duplicate_keydata_in_group += 1
            values[column] = float(valdata)

    stats.group_count = len(groups)
    if stats.unknown_keydata:
        warn(f"[csv_pivot] unknown KEYDATA values skipped: {sorted(stats.unknown_keydata)}")
    if stats.duplicate_keydata_in_group:
        warn(
            f"[csv_pivot] {stats.duplicate_keydata_in_group} duplicate KEYDATA-in-group "
            "overwrites detected (last value wins)"
        )
    return groups, stats


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else r"C:\VibeCoding\11_DataMigration\dmp_financesummary.csv"
    groups, stats = pivot_csv(path)
    print(f"row_count={stats.row_count} group_count={stats.group_count}")
    print(f"unknown_keydata={stats.unknown_keydata} duplicate_keydata_in_group={stats.duplicate_keydata_in_group}")

    sample_key = ("067290", "2009.12", "YEAR")
    print(f"sample {sample_key} -> {groups.get(sample_key)}")
    sample_key2 = ("067290", "2011.09", "QUARTER")
    print(f"sample {sample_key2} -> {groups.get(sample_key2)}")
