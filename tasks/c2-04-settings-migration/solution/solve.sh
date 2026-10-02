#!/bin/bash
set -euo pipefail
cd /app
python3 - <<'PY'
import configparser
import json
import re

REMOVED = {("server", "legacy_mode"), ("cache", "legacy_keys")}
ini = configparser.ConfigParser()
ini.read("config/settings.ini")
out = {"schema_version": 2}
for section in ini.sections():
    obj = {}
    for key, value in ini[section].items():
        if (section, key) in REMOVED:
            continue
        if key == "timeout":
            obj["timeout_ms"] = round(float(value) * 1000)
        elif value in ("yes", "no"):
            obj[key] = value == "yes"
        elif re.fullmatch(r"-?\d+", value):
            obj[key] = int(value)
        else:
            obj[key] = value
    out[section] = obj
with open("config/settings.json", "w") as f:
    json.dump(out, f, indent=2)
PY
