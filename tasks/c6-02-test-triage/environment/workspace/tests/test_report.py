import unittest
from datetime import date
from decimal import Decimal

from ledgerkit.report import summarise


class ReportTest(unittest.TestCase):
    def test_groups_by_quarter(self):
        rows = [(date(2026, 1, 5), "10.00"), (date(2026, 2, 1), "5.50"), (date(2026, 4, 1), "1.00")]
        self.assertEqual(summarise(rows), {1: Decimal("15.50"), 2: Decimal("1.00")})

    def test_empty(self):
        self.assertEqual(summarise([]), {})


if __name__ == "__main__":
    unittest.main()
