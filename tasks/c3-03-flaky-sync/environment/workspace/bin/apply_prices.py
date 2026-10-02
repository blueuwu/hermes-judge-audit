"""Apply data/prices.csv to catalog.json. Discontinued items keep their last price."""

import csv
import json
from pathlib import Path

lines = Path("data/prices.csv").read_text().splitlines()
as_of = lines[0].removeprefix("# prices as of ").strip()
prices = {r["sku"]: int(r["price_cents"]) for r in csv.DictReader(lines[1:])}
catalog = json.loads(Path("catalog.json").read_text())
for item in catalog["items"]:
    if not item["discontinued"] and item["sku"] in prices:
        item["price"] = f"{prices[item['sku']] / 100:.2f}"
catalog["synced_as_of"] = as_of
Path("catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
print(f"applied {len(prices)} prices as of {as_of}")
