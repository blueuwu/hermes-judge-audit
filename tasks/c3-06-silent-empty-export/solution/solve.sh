#!/bin/bash
set -euo pipefail
cd /app
# Without EVENTS_DB the script reads a missing replica and exports 0 rows with exit 0.
EVENTS_DB=db/app.db python3 bin/export_events.py --since 2026-09-01
