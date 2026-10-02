#!/bin/bash
set -euo pipefail
cd /app
mkdir -p out
python3 - <<'PY'
import json
import re
from pathlib import Path


def v(s):
    return tuple(int(x) for x in s.split("."))


def hit(version, spec):
    for part in spec.split(","):
        op, bound = re.match(r"(>=|<=|<|>)(.+)", part).groups()
        a, b = v(version), v(bound)
        if not {"<": a < b, ">": a > b, ">=": a >= b, "<=": a <= b}[op]:
            return False
    return True


advisories = json.loads(Path("security/advisories.json").read_text())
index = {p: vs for p, *vs in (line.split() for line in Path("security/index.txt").read_text().splitlines())}
out, audit = [], []
for line in Path("requirements.txt").read_text().splitlines():
    m = re.match(r"^([A-Za-z0-9_.-]+)(\[[^\]]*\])?==(\S+)$", line)
    if not m:
        out.append(line)
        continue
    name, extras, version = m.group(1), m.group(2) or "", m.group(3)
    hits = [a for a in advisories if a["package"] == name and hit(version, a["affected"])]
    if hits:
        need = max(v(a["fixed_in"]) for a in hits)
        new = min((x for x in index[name] if v(x) >= need), key=v)
        audit.append({"package": name, "from": version, "to": new, "advisories": [a["id"] for a in hits]})
        version = new
    out.append(f"{name}{extras}=={version}")
Path("requirements.txt").write_text("\n".join(out) + "\n")
Path("out/audit.json").write_text(json.dumps(audit, indent=2) + "\n")
PY
