import unittest
from datetime import date

from ledgerkit.dates import month_end, quarter


class DatesTest(unittest.TestCase):
    def test_month_end_february_leap(self):
        self.assertEqual(month_end(date(2028, 2, 10)), date(2028, 2, 29))

    def test_month_end_december(self):
        self.assertEqual(month_end(date(2026, 12, 3)), date(2026, 12, 31))

    def test_quarter(self):
        self.assertEqual([quarter(date(2026, m, 1)) for m in (1, 3, 4, 12)], [1, 1, 2, 4])


if __name__ == "__main__":
    unittest.main()
