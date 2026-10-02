#!/usr/bin/env python3.9
"""Build the daily sensor report: per-sensor stats and anomalous readings.

A reading is anomalous when it is more than THRESHOLD robust z-scores from its sensor's
median, using the median absolute deviation (scaled by 1.4826) as the spread.
"""

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

THRESHOLD = 4.5


def build(readings: Path) -> dict:
    by_sensor = defaultdict(list)
    with readings.open(newline="") as f:
        for row in csv.DictReader(f):
            by_sensor[row["sensor"]].append((row["ts"], float(row["celsius"])))
    report = {"sensors": {}, "anomalies": []}
    for sensor, rows in sorted(by_sensor.items()):
        values = [v for _, v in rows]
        median = statistics.median(values)
        mad = statistics.median(abs(v - median) for v in values) * 1.4826
        report["sensors"][sensor] = {
            "n": len(values),
            "median": round(median, 2),
            "min": min(values),
            "max": max(values),
        }
        for ts, v in rows:
            if mad and abs(v - median) / mad > THRESHOLD:
                report["anomalies"].append({"sensor": sensor, "ts": ts, "celsius": v})
    return report


if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(src), indent=2) + "\n")
