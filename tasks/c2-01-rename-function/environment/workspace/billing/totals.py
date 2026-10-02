"""Line-item arithmetic shared by invoices and the CLI."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def calc_total(items: list[dict], tax_rate: str = "0") -> Decimal:
    """Sum quantity * unit_price over items, then add tax, rounded half-up to cents."""
    subtotal = sum(
        (Decimal(str(i["qty"])) * Decimal(str(i["unit_price"])) for i in items), Decimal("0")
    )
    return (subtotal * (1 + Decimal(tax_rate))).quantize(CENT, rounding=ROUND_HALF_UP)
