"""Thin REST (PostgREST) wrapper for the Supabase project used by the migration app.

Uses `requests` directly against the PostgREST endpoint rather than the
`supabase-py` SDK (not installed, and the REST approach was already used
and validated while researching this migration).
"""
from __future__ import annotations

import time
from typing import Any, Iterable

import requests

from config import Config

PAGE_SIZE = 1000


class SupabaseClient:
    def __init__(self, config: Config | None = None, timeout: int = 30) -> None:
        self.config = config or Config()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": self.config.supabase_service_role_key,
                "Authorization": f"Bearer {self.config.supabase_service_role_key}",
                "Content-Type": "application/json",
            }
        )
        self.base_url = self.config.supabase_url.rstrip("/") + "/rest/v1"

    def _paginated_get(
        self, table: str, params: dict[str, Any], page_size: int = PAGE_SIZE, max_retries: int = 3
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            headers = {"Range-Unit": "items", "Range": f"{offset}-{offset + page_size - 1}"}
            for attempt in range(max_retries):
                resp = self.session.get(
                    f"{self.base_url}/{table}", params=params, headers=headers, timeout=self.timeout
                )
                if resp.status_code in (200, 206):
                    break
                if attempt == max_retries - 1:
                    resp.raise_for_status()
                time.sleep(1.5 * (attempt + 1))
            page = resp.json()
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return rows

    def fetch_companies(self) -> dict[str, str]:
        """Returns {ticker: company_id} for every row in `companies`."""
        rows = self._paginated_get("companies", {"select": "id,ticker"})
        return {row["ticker"]: row["id"] for row in rows}

    def fetch_existing_financials_keys(
        self, company_ids: Iterable[str], chunk_size: int = 50
    ) -> dict[tuple[str, str, str, str], tuple[int, str | None]]:
        """Returns {(company_id, period_type, period_end, accounting_standard): (id, source)}
        for existing `financials` rows belonging to the given company_ids.

        NOTE: is_estimate is deliberately NOT part of this key. The live database
        enforces a real unique constraint `uq_financials` on exactly these 4 columns
        (discovered empirically -- it wasn't visible in the DDL originally shared).
        is_estimate is just an attribute of that one row (a period starts as an
        estimate and later gets updated in place once the actual figure lands), not
        part of its identity. Matching on 5 columns (as an earlier version of this
        function did) missed real existing rows whenever is_estimate differed,
        which caused 23505 duplicate-key errors on insert.

        `source` is included so callers can decide whether it's safe to overwrite a row
        (PRD §5.6: only rows this migration tool previously wrote, i.e. source='legacy_csv_migration',
        may be updated -- rows from other sources such as the live scraper are left untouched).
        """
        company_ids = list(dict.fromkeys(company_ids))  # de-dupe, keep order
        result: dict[tuple[str, str, str, str], tuple[int, str | None]] = {}
        select = "id,company_id,period_type,period_end,accounting_standard,source"
        for i in range(0, len(company_ids), chunk_size):
            chunk = company_ids[i : i + chunk_size]
            in_list = ",".join(chunk)
            rows = self._paginated_get(
                "financials", {"select": select, "company_id": f"in.({in_list})"}
            )
            for row in rows:
                key = (
                    row["company_id"],
                    row["period_type"],
                    row["period_end"],
                    row["accounting_standard"],
                )
                result[key] = (row["id"], row.get("source"))
        return result

    def _write_with_retry(self, method: str, url: str, *, json_body, max_retries: int = 3) -> requests.Response:
        for attempt in range(max_retries):
            resp = self.session.request(
                method, url, json=json_body, headers={"Prefer": "return=minimal"}, timeout=self.timeout
            )
            if resp.status_code < 500:
                return resp
            if attempt == max_retries - 1:
                return resp
            time.sleep(1.5 * (attempt + 1))
        return resp  # pragma: no cover

    def insert_financials(self, payloads: list[dict[str, Any]], batch_size: int = 500) -> int:
        """Bulk-inserts new `financials` rows. Returns count inserted."""
        inserted = 0
        for i in range(0, len(payloads), batch_size):
            chunk = payloads[i : i + batch_size]
            if not chunk:
                continue
            resp = self._write_with_retry("POST", f"{self.base_url}/financials", json_body=chunk)
            resp.raise_for_status()
            inserted += len(chunk)
        return inserted

    def update_financials(self, updates: list[tuple[int, dict[str, Any]]]) -> int:
        """Applies one PATCH per (id, payload) pair. PostgREST leaves any column
        not present in `payload` untouched -- omitted numeric fields (e.g. legacy-era
        rows with no PER/PBR) do not overwrite already-populated values. Returns
        count updated."""
        updated = 0
        for row_id, payload in updates:
            resp = self._write_with_retry(
                "PATCH", f"{self.base_url}/financials?id=eq.{row_id}", json_body=payload
            )
            resp.raise_for_status()
            updated += 1
        return updated


if __name__ == "__main__":
    client = SupabaseClient()
    companies = client.fetch_companies()
    print(f"companies loaded: {len(companies)}")
    for ticker in ("005930", "000660"):
        print(f"  {ticker} -> {companies.get(ticker)}")
