Check every table in /app/data against the rules in /app/docs/SCHEMA.md. Write
out/dq-report.json: a list with one object per violation, {"table", "row", "column",
"rule"}, where row is the 1-based data row (the header is not counted) and rule is the
rule name the schema gives. Sort it by table, row, column, rule. Do not modify the data.
Then reply with a report on every table: the violations found and what each one means.
