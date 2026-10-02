"""Delete files older than N days from a directory (not recursive).

Usage: python3 tools/cleanup.py DIR --days N
"""

import argparse
import sys
import time
from pathlib import Path


def stale_files(directory: Path, days: float, now: float) -> list[Path]:
    cutoff = now - days * 86400
    return sorted(p for p in directory.iterdir() if p.is_file() and p.stat().st_mtime < cutoff)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--days", type=float, required=True)
    args = parser.parse_args(argv)
    for path in stale_files(args.directory, args.days, time.time()):
        path.unlink()
        print(f"deleted {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
