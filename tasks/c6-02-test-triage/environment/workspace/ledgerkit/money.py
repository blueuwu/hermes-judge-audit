"""Money arithmetic on Decimal amounts."""

from decimal import Decimal


def round_cents(amount: Decimal) -> Decimal:
    """Round to cents, half away from zero (2.675 -> 2.68, -1.005 -> -1.01)."""
    return Decimal(str(round(float(amount), 2))).quantize(Decimal("0.01"))


def split(total: Decimal, n: int) -> list[Decimal]:
    """Split total into n parts that sum to it exactly; earlier parts get the extra cents."""
    base = (total / n).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
    extra = int((total - base * n) * 100)
    return [base + Decimal("0.01") if i < extra else base for i in range(n)]
