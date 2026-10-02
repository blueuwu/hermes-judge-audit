#!/bin/bash
set -euo pipefail
cd /app
python3 - <<'PY'
from pathlib import Path

FIXES = {
    "index.md": {
        "guide/install.md": "setup/install.md",
        "guide/config.md#tls-settings": "guide/config.md#tls--certificates-v2"
    },
    "guide/config.md": {
        "../reference/env.md": "../reference/environment.md",
        "#env-vars": "#environment-variables"
    },
    "guide/deploy.md": {
        "install.md": "../setup/install.md",
        "config.md#tls-settings": "config.md#tls--certificates-v2"
    },
    "reference/cli.md": {
        "#build": "#build-command"
    },
    "ops/runbook.md": {
        "../guide/deploy.md#rollback": "../guide/deploy.md#rolling-back",
        "../reference/env.md#proxy": "../reference/environment.md#proxy"
    },
    "faq.md": {
        "guide/install.md#prerequisites": "setup/install.md#prerequisites"
    }
}
for path, fixes in FIXES.items():
    doc = Path('docs') / path
    text = doc.read_text()
    for old, new in fixes.items():
        assert f'({old})' in text, (path, old)
        text = text.replace(f'({old})', f'({new})')
    doc.write_text(text)
PY
