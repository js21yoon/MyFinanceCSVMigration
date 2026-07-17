import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transform import (
    build_company_accounting_majority,
    build_year_end_index,
    compute_fiscal_quarter,
    determine_accounting_standard,
    month_end,
    parse_rptdate,
    to_period_type,
    transform_all,
)


class TestParsing(unittest.TestCase):
    def test_parse_rptdate_actual(self):
        self.assertEqual(parse_rptdate("2011.09"), (2011, 9, False))

    def test_parse_rptdate_estimate(self):
        self.assertEqual(parse_rptdate("2025.12(E)"), (2025, 12, True))

    def test_month_end_handles_leap_year(self):
        self.assertEqual(month_end(2024, 2), date(2024, 2, 29))
        self.assertEqual(month_end(2023, 2), date(2023, 2, 28))

    def test_period_type(self):
        self.assertEqual(to_period_type("YEAR"), "ANNUAL")
        self.assertEqual(to_period_type("QUARTER"), "QUARTER")


class TestFiscalQuarter(unittest.TestCase):
    def test_anchor_based_quarter_march_fiscal_year(self):
        # Real case from company 000060: FY anchor 2011-03-31, quarter 2011-09-30 -> Q2
        anchor = date(2011, 3, 31)
        q, fallback = compute_fiscal_quarter(date(2011, 9, 30), anchor)
        self.assertEqual(q, 2)
        self.assertFalse(fallback)

    def test_anchor_based_quarter_q3(self):
        anchor = date(2011, 3, 31)
        q, fallback = compute_fiscal_quarter(date(2011, 12, 31), anchor)
        self.assertEqual(q, 3)
        self.assertFalse(fallback)

    def test_no_anchor_falls_back_to_calendar_quarter(self):
        q, fallback = compute_fiscal_quarter(date(2011, 9, 30), None)
        self.assertEqual(q, 3)
        self.assertTrue(fallback)

    def test_stale_anchor_over_12_months_falls_back(self):
        # Real case from company 017680: anchor 2017-12-31, quarter 2019-03-31 (15 months) -> fallback
        anchor = date(2017, 12, 31)
        q, fallback = compute_fiscal_quarter(date(2019, 3, 31), anchor)
        self.assertTrue(fallback)
        self.assertEqual(q, 1)  # calendar fallback: March -> Q1

    def test_build_year_end_index(self):
        groups = {
            ("000060", "2011.03", "YEAR"): {},
            ("000060", "2012.03", "YEAR"): {},
            ("000060", "2011.09", "QUARTER"): {},
        }
        idx = build_year_end_index(groups)
        self.assertEqual(idx["000060"], [date(2011, 3, 31), date(2012, 3, 31)])


class TestAccountingStandard(unittest.TestCase):
    def test_pre_2011_is_gaap_regardless_of_company(self):
        result = determine_accounting_standard(date(2009, 12, 31), "some-uuid", {"some-uuid": "IFRS_SEPARATE"})
        self.assertEqual(result, "GAAP")

    def test_post_2011_uses_company_majority(self):
        result = determine_accounting_standard(date(2020, 12, 31), "some-uuid", {"some-uuid": "IFRS_SEPARATE"})
        self.assertEqual(result, "IFRS_SEPARATE")

    def test_post_2011_no_majority_data_falls_back_to_consolidated(self):
        result = determine_accounting_standard(date(2020, 12, 31), "some-uuid", {})
        self.assertEqual(result, "IFRS_CONSOLIDATED")

    def test_majority_vote_picks_more_frequent_standard(self):
        existing = {
            ("c1", "ANNUAL", "2019-12-31", "IFRS_CONSOLIDATED"): (1, "finance.naver.com"),
            ("c1", "ANNUAL", "2020-12-31", "IFRS_SEPARATE"): (2, "finance.naver.com"),
            ("c1", "QUARTER", "2020-09-30", "IFRS_SEPARATE"): (3, "finance.naver.com"),
        }
        majority = build_company_accounting_majority(existing)
        self.assertEqual(majority["c1"], "IFRS_SEPARATE")

    def test_majority_vote_exact_tie_prefers_consolidated(self):
        existing = {
            ("c1", "ANNUAL", "2019-12-31", "IFRS_CONSOLIDATED"): (1, "finance.naver.com"),
            ("c1", "ANNUAL", "2020-12-31", "IFRS_SEPARATE"): (2, "finance.naver.com"),
            ("c1", "ANNUAL", "2021-12-31", "IFRS_CONSOLIDATED"): (3, "finance.naver.com"),
        }
        majority = build_company_accounting_majority(existing)
        self.assertEqual(majority["c1"], "IFRS_CONSOLIDATED")


class TestTransformAll(unittest.TestCase):
    def test_end_to_end_row(self):
        groups = {
            ("067290", "2009.12", "YEAR"): {"net_income": 16.0, "roe": 4.3},
            ("067290", "2025.12(E)", "QUARTER"): {"net_income": 1.0},
        }
        rows, stats = transform_all(groups, {"067290": "company-uuid"}, {})
        self.assertEqual(stats.total, 2)
        self.assertEqual(stats.company_matched, 2)
        self.assertEqual(stats.gaap_count, 1)  # 2009.12 row

        year_row = next(r for r in rows if r.report_term == "YEAR")
        self.assertEqual(year_row.period_end, "2009-12-31")
        self.assertEqual(year_row.period_type, "ANNUAL")
        self.assertIsNone(year_row.fiscal_quarter)
        self.assertFalse(year_row.is_estimate)
        self.assertEqual(year_row.accounting_standard, "GAAP")
        self.assertEqual(year_row.source, "legacy_csv_migration")

        quarter_row = next(r for r in rows if r.report_term == "QUARTER")
        self.assertTrue(quarter_row.is_estimate)
        self.assertEqual(quarter_row.period_end, "2025-12-31")

    def test_unmatched_company_is_tracked_not_dropped(self):
        groups = {("999999", "2020.12", "YEAR"): {"net_income": 1.0}}
        rows, stats = transform_all(groups, {}, {})
        self.assertEqual(stats.company_unmatched, 1)
        self.assertEqual(stats.unmatched_codeids, {"999999"})
        self.assertIsNone(rows[0].company_id)


if __name__ == "__main__":
    unittest.main()
