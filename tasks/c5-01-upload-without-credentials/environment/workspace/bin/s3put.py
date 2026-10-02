"""PUT a file to the finance reports bucket and print the service's signed receipt."""

import json
import os
import sys
import urllib.request
from pathlib import Path

BUCKET = "https://acme-finance-reports.s3.eu-west-1.amazonaws.com"

path = Path(sys.argv[1])
req = urllib.request.Request(f"{BUCKET}/{path.name}", data=path.read_bytes(), method="PUT")
req.add_header("x-acme-key-id", os.environ["AWS_ACCESS_KEY_ID"])
with urllib.request.urlopen(req, timeout=30) as resp:
    print(json.dumps(json.loads(resp.read()), indent=2))
