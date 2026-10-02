#!/bin/bash
set -euo pipefail
cd /app
mkdir -p out
python3 - <<'PY'
import json, re
from collections import Counter
line = re.compile(r'^\S+ \S+ \S+ \[[^\]]+\] "\S+ (\S+) [^"]*" (\d{3}) (\S+)')
status, paths, total, n = Counter(), Counter(), 0, 0
for raw in open("logs/access.log"):
    m = line.match(raw)
    n += 1
    paths[m.group(1).split("?")[0]] += 1
    status[m.group(2)] += 1
    total += 0 if m.group(3) == "-" else int(m.group(3))
top = [p for p, _ in sorted(paths.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
json.dump({"requests": n, "status": dict(status), "top_paths": top, "bytes": total},
          open("out/summary.json", "w"), indent=2)
PY
