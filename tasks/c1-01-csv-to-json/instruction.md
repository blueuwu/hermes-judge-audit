In /app, convert data/orders.csv into out/orders.json and write out/totals.json.

- out/orders.json is a JSON array with one object per order, sorted by order_id ascending. Each
  object has exactly these keys: order_id (integer), customer (string), amount (number) and
  shipped (boolean; the CSV uses yes/no). Drop the notes column.
- out/totals.json is an object: {"orders": <number of orders>, "shipped_amount": <sum of amount
  over shipped orders, rounded to 2 decimals>}.
- Do not modify data/orders.csv.
