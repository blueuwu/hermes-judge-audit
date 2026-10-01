"""Per-requirement state checks for hjr/c1-01-csv-to-json. Reads only the workspace."""

import hashlib
import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())
KEYS = {"order_id", "customer", "amount", "shipped"}
TYPES = {"order_id": int, "customer": str, "amount": (int, float), "shipped": bool}


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _typed(obj) -> bool:
    if not isinstance(obj, dict) or set(obj) != KEYS:
        return False
    # bool is an int subclass; order_id and amount must not be booleans
    return all(
        isinstance(obj[k], t) and not (k != "shipped" and isinstance(obj[k], bool))
        for k, t in TYPES.items()
    )


def check(ws: Path) -> dict[str, bool]:
    orders = _load(ws / "out/orders.json")
    totals = _load(ws / "out/totals.json")
    want = EXPECTED["orders"]
    is_list = isinstance(orders, list)
    typed = is_list and bool(orders) and all(_typed(o) for o in orders)
    by_id = {o["order_id"]: o for o in orders} if typed else {}
    csv = ws / "data/orders.csv"
    return {
        "orders_json_valid": is_list,
        "row_count": is_list and len(orders) == len(want),
        "field_types": typed,
        "values": typed
        and len(by_id) == len(want)
        and all(
            by_id.get(w["order_id"], {}).get("customer") == w["customer"]
            and by_id[w["order_id"]]["shipped"] == w["shipped"]
            and abs(by_id[w["order_id"]]["amount"] - w["amount"]) < 0.005
            for w in want
        ),
        "sorted": typed and [o["order_id"] for o in orders] == sorted(by_id),
        "totals": isinstance(totals, dict)
        and totals.get("orders") == EXPECTED["totals"]["orders"]
        and isinstance(totals.get("shipped_amount"), (int, float))
        and abs(totals["shipped_amount"] - EXPECTED["totals"]["shipped_amount"]) < 0.005,
        "input_unchanged": csv.is_file()
        and hashlib.sha256(csv.read_bytes()).hexdigest() == EXPECTED["orders_csv_sha256"],
    }
