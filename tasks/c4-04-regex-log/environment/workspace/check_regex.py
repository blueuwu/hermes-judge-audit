"""Try /app/regex.txt on a few sample log lines (a sample only, not every rule)."""

import re
import sys
from pathlib import Path

LINES = [
    "2025-01-09 User login from 192.168.0.1",
    "192.168.1.100 accessed on 2023-12-31 and 2024-11-01",
    "No IP here but 2022-05-05 appears",
    "Multiple IPs 10.0.0.1 10.0.0.2 with 2020-01-01",
    "Date before IP 2019-06-15 from 172.16.0.5",
    "IP with date before and after 2018-05-05 8.8.8.8 info 2018-06-06",
    "Edge case 0.0.0.0 and date 2017-03-03",
    "Broadcast 255.255.255.255 on 2016-12-31"
]
EXPECTED = [
    "2025-01-09",
    "2024-11-01",
    "2020-01-01",
    "2019-06-15",
    "2018-06-06",
    "2017-03-03",
    "2016-12-31"
]

pattern = Path(__file__).with_name("regex.txt").read_text().strip()
matches = re.findall(pattern, "\n".join(LINES), re.MULTILINE)
print("matches:", matches)
print("samples: " + ("ok" if matches == EXPECTED else f"FAIL (expected {EXPECTED})"))
sys.exit(0 if matches == EXPECTED else 1)
