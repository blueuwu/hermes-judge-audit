#!/bin/bash
set -euo pipefail
cd /app
python3 - <<'PY'
from pathlib import Path


def patch(path, old, new):
    p = Path(path)
    text = p.read_text()
    assert old in text, (path, old)
    p.write_text(text.replace(old, new))


# float round() is banker's rounding on binary floats: quantize the Decimal instead.
patch("ledgerkit/money.py",
      '    return Decimal(str(round(float(amount), 2))).quantize(Decimal("0.01"))',
      '    return amount.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")')
# December has no month 13: roll over to January of the next year.
patch("ledgerkit/dates.py",
      "    first_next = date(day.year, day.month + 1, 1)",
      "    first_next = date(day.year + day.month // 12, day.month % 12 + 1, 1)")
# Thousands separators, and accounting negatives in parentheses.
patch("ledgerkit/parse.py",
      '    cleaned = re.sub(r"[$\\s]", "", text)\n',
      '    cleaned = re.sub(r"[$\\s]", "", text)\n'
      '    negative = cleaned.startswith("(") and cleaned.endswith(")")\n'
      '    if negative:\n'
      '        cleaned = cleaned[1:-1].lstrip("$")\n'
      '    if not re.fullmatch(r"\\d{1,3}(,\\d{3})*(\\.\\d+)?|\\d+(\\.\\d+)?", cleaned):\n'
      '        raise ValueError(f"not an amount: {text!r}")\n'
      '    cleaned = cleaned.replace(",", "")\n')
patch("ledgerkit/parse.py",
      "        return Decimal(cleaned)\n",
      "        return -Decimal(cleaned) if negative else Decimal(cleaned)\n")
# Rates are per 1 USD: divide to get USD, multiply to get the target currency.
patch("ledgerkit/fx.py",
      "    usd = amount * rates[src]\n    return (usd / rates[dst])",
      "    usd = amount / rates[src]\n    return (usd * rates[dst])")
PY
