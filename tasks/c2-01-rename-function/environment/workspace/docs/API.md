# billing API

## `billing.totals.calc_total(items, tax_rate="0")`

Returns the invoice total as a `Decimal`: the sum of `qty * unit_price` over `items`, plus
tax, rounded half-up to cents. `tax_rate` is a decimal string such as `"0.2"`.

## `billing.invoice.render(customer, items, tax_rate="0")`

Plain-text invoice ending in a `Total:` line computed with `calc_total`.
