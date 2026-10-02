"""Concatenate src/ modules in src/manifest.txt order into one bundle, dropping comments."""

import sys
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
order = [
    line.strip()
    for line in (src / "manifest.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]
parts = ["/* app bundle: " + ", ".join(order) + " */"]
for name in order:
    body = [
        line
        for line in (src / name).read_text().splitlines()
        if not line.lstrip().startswith("//") and not line.startswith("import ")
    ]
    parts.append(f"/* --- {name} --- */")
    parts.extend(line.replace("export ", "") for line in body)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(parts) + "\n", newline="\n")
