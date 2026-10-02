"""Quarterly totals."""

from collections import defaultdict
from decimal import Decimal

from ledgerkit.dates import quarter
from ledgerkit.parse import parse_amount


def summarise(rows) -> dict[int, Decimal]:
    totals = defaultdict(Decimal)
    for day, amount in rows:
        totals[quarter(day)] += parse_amount(amount)
    return dict(totals)
