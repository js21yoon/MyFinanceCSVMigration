"""Builds Supabase `financials` payloads from TransformedRow objects and
plans/executes the insert-vs-update decision (PRD §4.3, §5.6, §5.7, §11 Phase 6).

The live database enforces a unique constraint `uq_financials` on
(company_id, period_type, period_end, accounting_standard) -- NOT including
is_estimate (discovered empirically via a 23505 duplicate-key error during
a scoped test run; it wasn't visible in the DDL originally shared). So
"upsert" here means: look up that 4-column natural key in the existing-rows
index fetched via SupabaseClient.fetch_existing_financials_keys, then:
  - no existing row              -> INSERT
  - existing row, source == 'legacy_csv_migration' -> PATCH by id (this
    migration tool's own prior run; safe to overwrite, keeps re-runs idempotent)
  - existing row, any other source (e.g. the live scraper) -> SKIP, never
    overwritten (PRD §5.6: legacy CSV data must not clobber more current data)
Rows with no matched company_id are also skipped (PRD §5.5) and returned
separately, never sent to Supabase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mapping import NUMERIC_COLUMNS
from supabase_client import SupabaseClient
from transform import TransformedRow

NaturalKey = tuple[str, str, str, str]
LEGACY_SOURCE_MARKER = "legacy_csv_migration"


def natural_key(row: TransformedRow) -> NaturalKey:
    assert row.company_id is not None
    return (row.company_id, row.period_type, row.period_end, row.accounting_standard)


def _base_payload(row: TransformedRow) -> dict[str, Any]:
    return {
        "company_id": row.company_id,
        "period_type": row.period_type,
        "period_end": row.period_end,
        "fiscal_year": row.fiscal_year,
        "fiscal_quarter": row.fiscal_quarter,
        "accounting_standard": row.accounting_standard,
        "is_estimate": row.is_estimate,
        "source": row.source,
    }


def build_insert_payload(row: TransformedRow) -> dict[str, Any]:
    """Every row in a single POST batch must have identical keys (PostgREST
    PGRST102: 'All object keys must match'), so every numeric column is
    included explicitly -- missing ones (e.g. PER/PBR on legacy-era rows)
    are sent as null rather than omitted."""
    payload = _base_payload(row)
    for col in NUMERIC_COLUMNS:
        payload[col] = row.values.get(col)
    return payload


def build_update_payload(row: TransformedRow) -> dict[str, Any]:
    """Each update is one PATCH per id (not a batch array), so there is no
    key-uniformity constraint. Numeric columns absent from this CSV group
    are omitted entirely rather than sent as null, so they don't overwrite
    an already-populated value with nothing."""
    payload = _base_payload(row)
    payload.update(row.values)
    return payload


@dataclass
class UpsertPlan:
    to_insert: list[dict[str, Any]] = field(default_factory=list)
    to_update: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    skipped_no_company: list[TransformedRow] = field(default_factory=list)
    skipped_foreign_source: list[TransformedRow] = field(default_factory=list)


def plan_upsert(
    rows: list[TransformedRow], existing_keys: dict[NaturalKey, tuple[int, str | None]]
) -> UpsertPlan:
    plan = UpsertPlan()
    for row in rows:
        if row.company_id is None:
            plan.skipped_no_company.append(row)
            continue
        existing = existing_keys.get(natural_key(row))
        if existing is None:
            plan.to_insert.append(build_insert_payload(row))
            continue
        existing_id, existing_source = existing
        if existing_source == LEGACY_SOURCE_MARKER:
            plan.to_update.append((existing_id, build_update_payload(row)))
        else:
            plan.skipped_foreign_source.append(row)
    return plan


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    skipped_no_company: int = 0
    skipped_foreign_source: int = 0


def execute_upsert(client: SupabaseClient, plan: UpsertPlan) -> UpsertResult:
    inserted = client.insert_financials(plan.to_insert)
    updated = client.update_financials(plan.to_update)
    return UpsertResult(
        inserted=inserted,
        updated=updated,
        skipped_no_company=len(plan.skipped_no_company),
        skipped_foreign_source=len(plan.skipped_foreign_source),
    )
