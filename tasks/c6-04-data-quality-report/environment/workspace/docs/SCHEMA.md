# Warehouse extract: data-quality rules

Every column listed for a table is required (`not_null`: an empty value violates it).

| Table | Columns | Rules |
|---|---|---|
| customers | id, email, signup_date, tier | `id` unique; `email` is `local@domain.tld` (rule `email`, tld lower-case letters, at least 2); `signup_date` a real YYYY-MM-DD date (`date`); `tier` one of free, pro, enterprise (`enum`) |
| orders | id, customer_id, order_date, status, total | `id` unique; `customer_id` exists in customers (`foreign_key`); `order_date` a real YYYY-MM-DD date (`date`); `status` one of placed, paid, shipped, cancelled (`enum`); `total` a number ≥ 0 (`range`) |
| order_items | order_id, sku, qty, price | `order_id` exists in orders and `sku` in products (`foreign_key`); `qty` an integer ≥ 1 (`range`); `price` a number ≥ 0 (`range`) |
| products | sku, name, price, category | `sku` unique; `price` a number > 0 (`range`) |
| refunds | id, order_id, amount, date | `id` unique; `order_id` exists in orders (`foreign_key`); `amount` a number > 0 (`range`) and at most the order's total (`refund_le_total`) |
| shipments | order_id, carrier, shipped_date | `order_id` exists in orders (`foreign_key`); `carrier` one of ups, dhl, fedex (`enum`); `shipped_date` a real YYYY-MM-DD date (`date`) not before the order's order_date (`ship_after_order`) |

A duplicate is reported on each later occurrence, not the first. `refund_le_total` and
`ship_after_order` apply only when the row passes its own `range` or `date` rule and the
referenced order exists with a valid value.
