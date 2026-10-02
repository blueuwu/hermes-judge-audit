#!/bin/bash
set -euo pipefail
cd /app
python3 - <<'PY'
import json
import re
from pathlib import Path

def table(path, value):
    return dict(re.findall(rf"^\| (\w+) \| ({value}) \|$", Path(path).read_text(), re.M))

ports = {k: int(v) for k, v in table("docs/PORTS.md", r"\d+").items()}
owners = table("docs/OWNERS.md", r"\S+@\S+")
aliases = {"warning": "warn", "err": "error"}
for path in sorted(Path("configs").glob("*.json")):
    cfg = json.loads(path.read_text())
    name = path.stem
    cfg["name"] = name
    cfg.setdefault("owner", owners[name])
    cfg["port"] = ports[name]
    if "timeout_s" in cfg:
        cfg["timeout_ms"] = int(cfg.pop("timeout_s") * 1000)
    cfg["timeout_ms"] = int(cfg["timeout_ms"])
    cfg["replicas"] = max(cfg["replicas"], 2 if cfg["env"] == "prod" else 1)
    cfg["log_level"] = aliases.get(cfg["log_level"], cfg["log_level"])
    for route in cfg.get("routes", []):
        route["port"] = ports[route["service"]]
    order = ["name", "owner", "env", "port", "replicas", "timeout_ms", "log_level", "routes"]
    cfg = {k: cfg[k] for k in order if k in cfg}
    path.write_text(json.dumps(cfg, indent=2) + "\n")
PY
