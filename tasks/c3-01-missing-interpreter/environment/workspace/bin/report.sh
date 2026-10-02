#!/bin/sh
# Build out/report.json from today's readings.
set -e
cd "$(dirname "$0")/.."
./tools/build_report.py data/readings.csv out/report.json
echo "wrote out/report.json"
