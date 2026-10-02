#!/bin/bash
set -euo pipefail
cd /app
sed -i 's/^version = "1.4.2"/version = "1.5.0"/' pyproject.toml
sed -i 's/^__version__ = "1.4.2"/__version__ = "1.5.0"/' src/fluxq/__init__.py
sed -i 's/^version = "1.4"/version = "1.5"/; s/^release = "1.4.2"/release = "1.5.0"/' docs/conf.py
sed -i 's#badge/version-1.4.2-blue#badge/version-1.5.0-blue#' README.md
sed -i 's/^## Unreleased$/## Unreleased\n\n## 1.5.0 - 2026-10-02/' CHANGELOG.md
