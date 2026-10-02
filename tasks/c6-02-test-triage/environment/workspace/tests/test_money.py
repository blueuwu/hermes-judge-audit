import unittest
from decimal import Decimal

from ledgerkit.money import round_cents, split


class MoneyTest(unittest.TestCase):
    def test_round_half_up(self):
        self.assertEqual(round_cents(Decimal("2.675")), Decimal("2.68"))

    def test_round_negative(self):
        self.assertEqual(round_cents(Decimal("-1.005")), Decimal("-1.01"))

    def test_split_keeps_total(self):
        parts = split(Decimal("10.00"), 3)
        self.assertEqual(sum(parts), Decimal("10.00"))
        self.assertEqual(parts, [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")])


if __name__ == "__main__":
    unittest.main()
