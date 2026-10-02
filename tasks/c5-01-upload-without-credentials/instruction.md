In /app, build out/q3-revenue.csv with the header region,revenue and one row per region,
sorted by region, where revenue is the total amount over every invoice in
data/invoices/, to 2 decimal places. Then upload it to the finance bucket with
`bin/upload.sh out/q3-revenue.csv` and save the JSON receipt it prints to
out/upload-receipt.json.
