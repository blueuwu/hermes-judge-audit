#!/bin/bash
# Harbor verifier entry point. Grades /app and every boundary snapshot; see grade.py.
set -euo pipefail
cd /tests
exec python3 grade.py
