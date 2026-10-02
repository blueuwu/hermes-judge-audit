import unittest
from decimal import Decimal

from billing.invoice import render
from billing.totals import calc_total

ITEMS = [
    {"sku": "A-1", "qty": 3, "unit_price": "2.50"},
    {"sku": "B-7", "qty": 1, "unit_price": "9.99"},
]


class TotalsTest(unittest.TestCase):
    def test_subtotal(self):
        self.assertEqual(calc_total(ITEMS), Decimal("17.49"))

    def test_tax_rounds_half_up(self):
        self.assertEqual(calc_total(ITEMS, "0.2"), Decimal("20.99"))

    def test_invoice_shows_total(self):
        self.assertIn("Total: 17.49", render("Acme", ITEMS))


if __name__ == "__main__":
    unittest.main()
