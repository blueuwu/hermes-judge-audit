#!/bin/bash
set -euo pipefail
cd /app
# python3.9 does not exist in the image; run the script with the python3 that does.
mkdir -p out
python3 tools/build_report.py data/readings.csv out/report.json
