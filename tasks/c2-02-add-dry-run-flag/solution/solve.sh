#!/bin/bash
set -euo pipefail
cd /app
python3 - <<'PY'
from pathlib import Path

tool = Path("tools/cleanup.py")
src = tool.read_text()
src = src.replace(
    "Usage: python3 tools/cleanup.py DIR --days N",
    "Usage: python3 tools/cleanup.py DIR --days N [--dry-run]",
)
src = src.replace(
    '    parser.add_argument("--days", type=float, required=True)\n',
    '    parser.add_argument("--days", type=float, required=True)\n'
    '    parser.add_argument("--dry-run", action="store_true", help="list files, delete nothing")\n',
)
src = src.replace(
    '        path.unlink()\n        print(f"deleted {path}")\n',
    '        if args.dry_run:\n'
    '            print(f"would delete {path}")\n'
    '            continue\n'
    '        path.unlink()\n'
    '        print(f"deleted {path}")\n',
)
tool.write_text(src)

readme = Path("README.md")
text = readme.read_text()
text = text.replace(
    "python3 tools/cleanup.py DIR --days N\n```",
    "python3 tools/cleanup.py DIR --days N [--dry-run]\n```",
)
text = text.replace(
    "printing `deleted <path>` for each one.\n",
    "printing `deleted <path>` for each one. With `--dry-run` it prints\n"
    "`would delete <path>` for each file instead and deletes nothing.\n",
)
readme.write_text(text)

test = Path("tests/test_cleanup.py")
text = test.read_text()
text = text.replace(
    '\n\nif __name__ == "__main__":',
    '''

    def test_dry_run_lists_and_keeps_files(self):
        with tempfile.TemporaryDirectory() as d:
            old = make(Path(d), "old.log", 10)
            out = self.run_tool(d, "--days", "7", "--dry-run").stdout
            self.assertTrue(old.exists())
            self.assertEqual(out.strip(), f"would delete {old}")


if __name__ == "__main__":''',
)
test.write_text(text)
PY
