"""Currency conversion with rates quoted per 1 USD."""

from decimal import Decimal


def convert(amount: Decimal, src: str, dst: str, rates: dict[str, Decimal]) -> Decimal:
    """Convert amount from src to dst; rates[c] is the price of 1 USD in currency c."""
    usd = amount * rates[src]
    return (usd / rates[dst]).quantize(Decimal("0.01"))
