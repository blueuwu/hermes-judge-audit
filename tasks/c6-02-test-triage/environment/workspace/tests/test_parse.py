import unittest
from decimal import Decimal

from ledgerkit.parse import parse_amount


class ParseTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_amount("12.50"), Decimal("12.50"))

    def test_thousands_separator(self):
        self.assertEqual(parse_amount("1,234.50"), Decimal("1234.50"))

    def test_currency_symbol(self):
        self.assertEqual(parse_amount("$99.00"), Decimal("99.00"))

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            parse_amount("twelve")


if __name__ == "__main__":
    unittest.main()
