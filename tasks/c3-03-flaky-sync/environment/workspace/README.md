# catalog

Price updates: `bin/sync.sh` fetches the current list from the pricing mirror into
`data/prices.csv`, then `python3 bin/apply_prices.py` applies it to `catalog.json`.
