#!/bin/bash
set -euo pipefail
mkdir -p /app/report
cp "$(dirname "$0")/incident.json" /app/report/incident.json
