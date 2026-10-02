#!/bin/bash
set -euo pipefail
cd /app
cat > program.py <<'PY'
"""Python port of src/program.cbl (BOOKFORUM): one book sale per run, fixed-width records."""

from pathlib import Path

APP = Path(__file__).resolve().parent
ACCOUNT, BOOK = 34, 28  # record lengths: id 4 + name 20 + balance 10; id 4 + title 20 + owner 4


def records(path: Path, size: int) -> list[str]:
    text = path.read_text() if path.exists() else ""
    return [text[i : i + size] for i in range(0, len(text), size)]


def main() -> None:
    line = (APP / "src/INPUT.DAT").read_text()
    if not line:
        print("Error: Input file is empty")
        return
    line = line.ljust(22)
    buyer, seller, book_id = line[0:4], line[4:8], line[8:12]
    amount = int(line[12:22]) if line[12:22].strip().isdigit() else 0
    accounts = records(APP / "data/ACCOUNTS.DAT", ACCOUNT)
    books = records(APP / "data/BOOKS.DAT", BOOK)
    ids = {r[:4] for r in accounts}
    book = [r for r in books if r[:4] == book_id]
    valid = buyer in ids and seller in ids and book and any(r[24:28] == seller for r in book)
    print(" ")
    if not valid:
        print("Transaction failed due to validation errors")
        return
    out = []
    for r in accounts:
        balance = int(r[24:34])
        if r[:4] == buyer:
            balance = abs(balance - amount) % 10**10  # PIC 9(10): unsigned, keeps magnitude
        if r[:4] == seller:
            balance = (balance + amount) % 10**10
        out.append(r[:24] + f"{balance:010d}")
    (APP / "data/ACCOUNTS.DAT").write_text("".join(out))
    books = [r[:24] + buyer if r[:4] == book_id else r for r in books]
    (APP / "data/BOOKS.DAT").write_text("".join(books))
    with open(APP / "data/TRANSACTIONS.DAT", "a") as f:
        f.write(f"{book_id}{amount % 10**10:010d}{seller}{buyer}")
    print("Transaction completed successfully")


if __name__ == "__main__":
    main()
PY
python3 check_example.py
