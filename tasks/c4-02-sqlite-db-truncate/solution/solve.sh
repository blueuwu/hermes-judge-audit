#!/bin/bash
set -euo pipefail
cd /app
# The header page is gone, so sqlite cannot open the file. Parse the surviving table-leaf
# cells directly: each is (payload length, rowid, header, NULL id, text word, number).
python3 - <<'PY'
import json
import re
import struct

data = open("trunc.db", "rb").read()


def varint(buf, i):
    n = 0
    for k in range(9):
        b = buf[i + k]
        if k == 8:
            return (n << 8) | b, i + 9
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            return n, i + k + 1


def value(kind, buf, i):
    sizes = {1: 1, 2: 2, 3: 3, 4: 4, 5: 6, 6: 8}
    if kind in (8, 9):
        return kind - 8
    if kind == 7:
        return struct.unpack(">d", buf[i : i + 8])[0]
    raw = buf[i : i + sizes[kind]]
    return int.from_bytes(raw, "big", signed=True)


rows = {}
for m in re.finditer(rb"testword\d\d", data):
    start = m.start()
    # header: [len=4][col0 type][text type][value type] sits right before the text
    header = data[start - 4 : start]
    if header[0] != 4:
        continue
    kind = header[3]
    if kind not in (1, 2, 3, 4, 5, 6, 7, 8, 9):
        continue
    word = m.group().decode()
    text_len = (header[2] - 13) // 2
    rows[word] = value(kind, data, start + text_len)
out = [{"word": w, "value": v} for w, v in sorted(rows.items())]
json.dump(out, open("recover.json", "w"), indent=2)
PY
python3 check_format.py
