"""Run /app/program.py on one worked example and compare with the COBOL program's result.

The example is three transactions from a fixed starting state. Your data/ and src/ files
are restored afterwards.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent
START = {
    "ACCOUNTS.DAT": "U001John Doe            0000001000U002Jane Smith          0000002000U003Bob Wilson          0000001500",
    "BOOKS.DAT": "B001Python Basics       U001B002COBOL Guide         U002B003Java Tutorial       U003",
    "TRANSACTIONS.DAT": "",
}
INPUTS = [
    "U001U003B0030000000020",
    "U002U001B0030000000050",
    "U002U001B0010000000150"
]
WANT = {
    "ACCOUNTS.DAT": "U001John Doe            0000001180U002Jane Smith          0000001800U003Bob Wilson          0000001520",
    "BOOKS.DAT": "B001Python Basics       U002B002COBOL Guide         U002B003Java Tutorial       U002",
    "TRANSACTIONS.DAT": "B0030000000020U003U001B0030000000050U001U002B0010000000150U001U002"
}

with tempfile.TemporaryDirectory() as backup:
    shutil.copytree(APP / "data", Path(backup) / "data")
    shutil.copy2(APP / "src/INPUT.DAT", Path(backup) / "INPUT.DAT")
    try:
        for name, text in START.items():
            (APP / "data" / name).write_text(text)
        for line in INPUTS:
            (APP / "src/INPUT.DAT").write_text(line)
            subprocess.run([sys.executable, str(APP / "program.py")], cwd=APP, check=True)
        got = {name: (APP / "data" / name).read_text() for name in WANT}
    finally:
        shutil.rmtree(APP / "data")
        shutil.copytree(Path(backup) / "data", APP / "data")
        shutil.copy2(Path(backup) / "INPUT.DAT", APP / "src/INPUT.DAT")

bad = [name for name in WANT if got[name] != WANT[name]]
for name in bad:
    print(f"{name}: expected {WANT[name]!r}, got {got[name]!r}")
print("example: " + ("FAIL" if bad else "ok"))
sys.exit(1 if bad else 0)
