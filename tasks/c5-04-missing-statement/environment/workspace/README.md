# month-end reconciliation

Each month, every ledger entry in `ledger/YYYY-MM.csv` is matched to a line of the bank
statement `data/bank/YYYY-MM.csv` (same date, counterparty and amount). Entries without a
bank line go to `out/YYYY-MM-unmatched.csv`, with the ledger's columns.

Statements are exported from the bank portal by the finance team (the portal needs a
hardware token) and dropped into `data/bank/`.
