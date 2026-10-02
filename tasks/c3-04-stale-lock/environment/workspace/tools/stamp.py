"""Print build metadata for a bundle: its sha256, size and module count."""

import hashlib
import sys
from pathlib import Path

bundle = Path(sys.argv[1])
data = bundle.read_bytes()
modules = data.count(b"/* --- ")
print(f"sha256={hashlib.sha256(data).hexdigest()}")
print(f"bytes={len(data)}")
print(f"modules={modules}")
