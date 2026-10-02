import unittest
from decimal import Decimal

from ledgerkit.fx import convert

RATES = {"USD": Decimal("1"), "EUR": Decimal("0.92"), "JPY": Decimal("149.5")}


class FxTest(unittest.TestCase):
    def test_same_currency(self):
        self.assertEqual(convert(Decimal("5.00"), "EUR", "EUR", RATES), Decimal("5.00"))

    def test_usd_to_eur(self):
        self.assertEqual(convert(Decimal("100.00"), "USD", "EUR", RATES), Decimal("92.00"))

    def test_unknown_currency(self):
        with self.assertRaises(KeyError):
            convert(Decimal("1"), "USD", "GBP", RATES)


if __name__ == "__main__":
    unittest.main()
