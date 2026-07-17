import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from csv_pivot import pivot_csv

HEADER = '"RPTDATE","REPORT_TERM","CODEID","KEYDATA","VALDATA","REPORTSEQ","EVENTTIME","DATASOURCE","VALDATAUNIT"'


def make_csv(rows: list[str]) -> io.StringIO:
    return io.StringIO("\n".join([HEADER, *rows]))


class TestCsvPivot(unittest.TestCase):
    def test_groups_two_periods_of_one_company(self):
        csv = make_csv(
            [
                '"2009.12","YEAR","067290","NetIncome",16,2,13/01/28,"Naver","mil"',
                '"2011.09","QUARTER","067290","NetIncome",15,2,13/01/28,"Naver","mil"',
                '"2009.12","YEAR","067290","OperationIncomeRate",7.05,3,13/01/28,"Naver","mil"',
                '"2011.09","QUARTER","067290","OperationIncomeRate",13.29,3,13/01/28,"Naver","mil"',
                '"2009.12","YEAR","067290","NetIncomeRate",2.49,4,13/01/28,"Naver","mil"',
                '"2009.12","YEAR","067290","ROE",4.3,5,13/01/28,"Naver","mil"',
            ]
        )
        groups, stats = pivot_csv(csv, chunksize=3, warn=lambda _msg: None)

        self.assertEqual(stats.row_count, 6)
        self.assertEqual(stats.group_count, 2)
        self.assertEqual(stats.unknown_keydata, set())
        self.assertEqual(stats.duplicate_keydata_in_group, 0)

        self.assertEqual(
            groups[("067290", "2009.12", "YEAR")],
            {"net_income": 16.0, "operating_margin": 7.05, "net_margin": 2.49, "roe": 4.3},
        )
        self.assertEqual(
            groups[("067290", "2011.09", "QUARTER")],
            {"net_income": 15.0, "operating_margin": 13.29},
        )

    def test_group_spans_across_chunk_boundary(self):
        # chunksize=1 forces every row into its own chunk; the two rows below
        # belong to the same group and must still be merged correctly.
        csv = make_csv(
            [
                '"2020.12","YEAR","005930","Sales",1000,0,13/01/28,"Naver","mil"',
                '"2020.12","YEAR","005930","NetIncome",100,2,13/01/28,"Naver","mil"',
            ]
        )
        groups, stats = pivot_csv(csv, chunksize=1, warn=lambda _msg: None)
        self.assertEqual(stats.group_count, 1)
        self.assertEqual(groups[("005930", "2020.12", "YEAR")], {"revenue": 1000.0, "net_income": 100.0})

    def test_unknown_keydata_is_skipped_not_fatal(self):
        csv = make_csv(
            [
                '"2020.12","YEAR","005930","Sales",1000,0,13/01/28,"Naver","mil"',
                '"2020.12","YEAR","005930","SomeFutureField",1,99,13/01/28,"Naver","mil"',
            ]
        )
        warnings = []
        groups, stats = pivot_csv(csv, chunksize=100, warn=warnings.append)
        self.assertEqual(stats.unknown_keydata, {"SomeFutureField"})
        self.assertEqual(groups[("005930", "2020.12", "YEAR")], {"revenue": 1000.0})
        self.assertTrue(any("SomeFutureField" in w for w in warnings))

    def test_duplicate_keydata_in_same_group_is_flagged(self):
        csv = make_csv(
            [
                '"2020.12","YEAR","005930","Sales",1000,0,13/01/28,"Naver","mil"',
                '"2020.12","YEAR","005930","Sales",2000,0,13/01/28,"Naver","mil"',
            ]
        )
        groups, stats = pivot_csv(csv, chunksize=100, warn=lambda _msg: None)
        self.assertEqual(stats.duplicate_keydata_in_group, 1)
        self.assertEqual(groups[("005930", "2020.12", "YEAR")]["revenue"], 2000.0)


if __name__ == "__main__":
    unittest.main()
