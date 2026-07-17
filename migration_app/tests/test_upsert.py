import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transform import TransformedRow
from upsert import build_insert_payload, build_update_payload, execute_upsert, natural_key, plan_upsert


def make_row(company_id="c1", period_end="2020-12-31", is_estimate=False, values=None) -> TransformedRow:
    return TransformedRow(
        codeid="005930",
        rptdate="2020.12",
        report_term="YEAR",
        company_id=company_id,
        period_type="ANNUAL",
        period_end=period_end,
        fiscal_year=2020,
        fiscal_quarter=None,
        is_estimate=is_estimate,
        accounting_standard="IFRS_CONSOLIDATED",
        source="legacy_csv_migration",
        values=values or {"revenue": 100.0, "net_income": 10.0},
    )


class TestBuildInsertPayload(unittest.TestCase):
    def test_payload_contains_all_non_keydata_fields_and_values(self):
        row = make_row()
        payload = build_insert_payload(row)
        self.assertEqual(payload["company_id"], "c1")
        self.assertEqual(payload["period_type"], "ANNUAL")
        self.assertEqual(payload["period_end"], "2020-12-31")
        self.assertEqual(payload["source"], "legacy_csv_migration")
        self.assertEqual(payload["revenue"], 100.0)
        self.assertEqual(payload["net_income"], 10.0)

    def test_missing_numeric_columns_are_explicit_null_for_batch_key_uniformity(self):
        # PostgREST rejects a POST array whose objects have differing keys
        # (PGRST102), so every insert payload must carry all 16 columns.
        row = make_row(values={"revenue": 100.0})
        payload = build_insert_payload(row)
        self.assertIsNone(payload["per"])
        self.assertIsNone(payload["pbr"])
        self.assertEqual(payload["revenue"], 100.0)

    def test_all_insert_payloads_share_identical_key_sets(self):
        legacy_row = make_row(values={"revenue": 1.0})
        modern_row = make_row(values={"revenue": 1.0, "per": 10.0, "pbr": 1.5})
        self.assertEqual(set(build_insert_payload(legacy_row)), set(build_insert_payload(modern_row)))


class TestBuildUpdatePayload(unittest.TestCase):
    def test_missing_numeric_columns_are_omitted_not_nulled(self):
        row = make_row(values={"revenue": 100.0})
        payload = build_update_payload(row)
        self.assertNotIn("per", payload)
        self.assertEqual(payload["revenue"], 100.0)


class TestPlanUpsert(unittest.TestCase):
    def test_row_with_no_company_match_is_skipped(self):
        row = make_row(company_id=None)
        plan = plan_upsert([row], existing_keys={})
        self.assertEqual(plan.skipped_no_company, [row])
        self.assertEqual(plan.to_insert, [])
        self.assertEqual(plan.to_update, [])

    def test_row_with_no_existing_match_is_inserted(self):
        row = make_row()
        plan = plan_upsert([row], existing_keys={})
        self.assertEqual(len(plan.to_insert), 1)
        self.assertEqual(plan.to_update, [])

    def test_row_matching_existing_legacy_row_is_updated(self):
        row = make_row()
        key = natural_key(row)
        plan = plan_upsert([row], existing_keys={key: (999, "legacy_csv_migration")})
        self.assertEqual(plan.to_insert, [])
        self.assertEqual(plan.to_update, [(999, build_update_payload(row))])
        self.assertEqual(plan.skipped_foreign_source, [])

    def test_row_matching_existing_foreign_source_row_is_skipped_not_overwritten(self):
        row = make_row()
        key = natural_key(row)
        plan = plan_upsert([row], existing_keys={key: (999, "finance.naver.com")})
        self.assertEqual(plan.to_insert, [])
        self.assertEqual(plan.to_update, [])
        self.assertEqual(plan.skipped_foreign_source, [row])

    def test_natural_key_ignores_values_only_identity_fields(self):
        row_a = make_row(values={"revenue": 1.0})
        row_b = make_row(values={"revenue": 2.0})
        self.assertEqual(natural_key(row_a), natural_key(row_b))

    def test_natural_key_ignores_is_estimate(self):
        # Regression test: the real DB's uq_financials constraint covers
        # (company_id, period_type, period_end, accounting_standard) only --
        # NOT is_estimate. An earlier version of natural_key included
        # is_estimate, which caused a live 23505 duplicate-key error because
        # a legacy "(E)" CSV row wasn't recognized as clashing with an
        # already-actual row for the same period.
        estimate_row = make_row(is_estimate=True)
        actual_row = make_row(is_estimate=False)
        self.assertEqual(natural_key(estimate_row), natural_key(actual_row))

    def test_foreign_source_actual_row_blocks_legacy_estimate_insert(self):
        # The exact scenario hit during the live 000660 test run: DB already
        # has an actual (is_estimate=False) row from the live scraper; CSV
        # only has a stale estimate ("(E)") row for the same period. Must be
        # skipped, not inserted as a duplicate.
        incoming_estimate = make_row(is_estimate=True)
        existing_actual_from_scraper = {natural_key(incoming_estimate): (113, "finance.naver.com")}
        plan = plan_upsert([incoming_estimate], existing_keys=existing_actual_from_scraper)
        self.assertEqual(plan.to_insert, [])
        self.assertEqual(plan.skipped_foreign_source, [incoming_estimate])


class TestExecuteUpsert(unittest.TestCase):
    def test_counts_reflect_client_calls(self):
        client = MagicMock()
        client.insert_financials.return_value = 2
        client.update_financials.return_value = 0

        rows = [make_row(company_id="c1"), make_row(company_id="c1", period_end="2021-12-31"), make_row(company_id=None)]
        plan = plan_upsert(rows, existing_keys={})
        result = execute_upsert(client, plan)

        self.assertEqual(result.inserted, 2)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.skipped_no_company, 1)
        self.assertEqual(result.skipped_foreign_source, 0)
        client.insert_financials.assert_called_once()
        client.update_financials.assert_called_once()

    def test_foreign_source_rows_are_never_sent_to_client(self):
        client = MagicMock()
        client.insert_financials.return_value = 0
        client.update_financials.return_value = 0

        row = make_row(company_id="c1")
        existing = {natural_key(row): (999, "finance.naver.com")}
        plan = plan_upsert([row], existing_keys=existing)
        result = execute_upsert(client, plan)

        self.assertEqual(result.skipped_foreign_source, 1)
        client.insert_financials.assert_called_once_with([])
        client.update_financials.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
