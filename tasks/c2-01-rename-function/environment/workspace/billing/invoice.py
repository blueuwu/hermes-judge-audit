"""Render a plain-text invoice."""

from billing.totals import calc_total


def render(customer: str, items: list[dict], tax_rate: str = "0") -> str:
    lines = [f"Invoice for {customer}"]
    lines += [f"  {i['qty']} x {i['sku']} @ {i['unit_price']}" for i in items]
    lines.append(f"Total: {calc_total(items, tax_rate)}")
    return "\n".join(lines)
