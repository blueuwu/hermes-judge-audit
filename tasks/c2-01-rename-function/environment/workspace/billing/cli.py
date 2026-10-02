"""Usage: python3 -m billing.cli ITEMS.json [TAX_RATE]"""

import json
import sys

from billing import totals


def main(argv: list[str]) -> int:
    with open(argv[0]) as f:
        items = json.load(f)
    tax = argv[1] if len(argv) > 1 else "0"
    print(totals.calc_total(items, tax))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
