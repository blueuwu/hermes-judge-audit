#!/bin/bash
set -euo pipefail
cd /app
mkdir -p out
python3 - <<'PY'
import csv
import json
import re
from datetime import date
from pathlib import Path

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")


def is_date(s: str) -> bool:
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)) and bool(date.fromisoformat(s))
    except ValueError:
        return False


def num(s: str):
    try:
        return float(s)
    except ValueError:
        return None


def audit(t: dict[str, list[dict]]) -> list[dict]:
    out = []

    def bad(table, row, column, rule):
        out.append({"table": table, "row": row, "column": column, "rule": rule})

    def rows(table):
        return enumerate(t[table], 1)

    def required(table, cols):
        for i, r in rows(table):
            for c in cols:
                if r[c] == "":
                    bad(table, i, c, "not_null")

    def unique(table, col):
        seen = set()
        for i, r in rows(table):
            if r[col] in seen:
                bad(table, i, col, "unique")
            seen.add(r[col])

    for table, cols in {
        "customers": ["id", "email", "signup_date", "tier"],
        "orders": ["id", "customer_id", "order_date", "status", "total"],
        "order_items": ["order_id", "sku", "qty", "price"],
        "products": ["sku", "name", "price", "category"],
        "refunds": ["id", "order_id", "amount", "date"],
        "shipments": ["order_id", "carrier", "shipped_date"],
    }.items():
        required(table, cols)
    for table, col in {"customers": "id", "orders": "id", "products": "sku", "refunds": "id"}.items():
        unique(table, col)
    cust = {r["id"] for r in t["customers"]}
    order = {r["id"]: r for r in t["orders"]}
    skus = {r["sku"] for r in t["products"]}
    for i, r in rows("customers"):
        if r["email"] and not EMAIL.match(r["email"]):
            bad("customers", i, "email", "email")
        if r["signup_date"] and not is_date(r["signup_date"]):
            bad("customers", i, "signup_date", "date")
        if r["tier"] and r["tier"] not in ("free", "pro", "enterprise"):
            bad("customers", i, "tier", "enum")
    for i, r in rows("orders"):
        if r["customer_id"] and r["customer_id"] not in cust:
            bad("orders", i, "customer_id", "foreign_key")
        if r["order_date"] and not is_date(r["order_date"]):
            bad("orders", i, "order_date", "date")
        if r["status"] and r["status"] not in ("placed", "paid", "shipped", "cancelled"):
            bad("orders", i, "status", "enum")
        if r["total"] and not (num(r["total"]) is not None and num(r["total"]) >= 0):
            bad("orders", i, "total", "range")
    for i, r in rows("order_items"):
        if r["order_id"] and r["order_id"] not in order:
            bad("order_items", i, "order_id", "foreign_key")
        if r["sku"] and r["sku"] not in skus:
            bad("order_items", i, "sku", "foreign_key")
        if r["qty"] and not (r["qty"].isdigit() and int(r["qty"]) >= 1):
            bad("order_items", i, "qty", "range")
        if r["price"] and not (num(r["price"]) is not None and num(r["price"]) >= 0):
            bad("order_items", i, "price", "range")
    for i, r in rows("products"):
        if r["price"] and not (num(r["price"]) is not None and num(r["price"]) > 0):
            bad("products", i, "price", "range")
    for i, r in rows("refunds"):
        o = order.get(r["order_id"])
        if r["order_id"] and o is None:
            bad("refunds", i, "order_id", "foreign_key")
        amount = num(r["amount"])
        if r["amount"] and not (amount is not None and amount > 0):
            bad("refunds", i, "amount", "range")
        elif o is not None and amount is not None and num(o["total"]) is not None and amount > num(o["total"]):
            bad("refunds", i, "amount", "refund_le_total")
    for i, r in rows("shipments"):
        o = order.get(r["order_id"])
        if r["order_id"] and o is None:
            bad("shipments", i, "order_id", "foreign_key")
        if r["carrier"] and r["carrier"] not in ("ups", "dhl", "fedex"):
            bad("shipments", i, "carrier", "enum")
        if r["shipped_date"] and not is_date(r["shipped_date"]):
            bad("shipments", i, "shipped_date", "date")
        elif o is not None and is_date(o["order_date"]) and r["shipped_date"] < o["order_date"]:
            bad("shipments", i, "shipped_date", "ship_after_order")
    return sorted(out, key=lambda x: (x["table"], x["row"], x["column"], x["rule"]))


tables = {p.stem: list(csv.DictReader(p.open(newline=''))) for p in Path('data').glob('*.csv')}
Path('out/dq-report.json').write_text(json.dumps(audit(tables), indent=2) + '\n')
PY
