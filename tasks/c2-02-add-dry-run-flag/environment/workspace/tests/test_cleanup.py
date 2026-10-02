import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "cleanup.py"


def make(directory: Path, name: str, age_days: float) -> Path:
    path = directory / name
    path.write_text(name)
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))
    return path


class CleanupTest(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(TOOL), *args], capture_output=True, text=True, check=True
        )

    def test_deletes_only_old_files(self):
        with tempfile.TemporaryDirectory() as d:
            old = make(Path(d), "old.log", 10)
            new = make(Path(d), "new.log", 1)
            out = self.run_tool(d, "--days", "7").stdout
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())
            self.assertIn("deleted", out)

    def test_leaves_subdirectories(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "keep"
            sub.mkdir()
            make(sub, "old.log", 30)
            self.run_tool(d, "--days", "7")
            self.assertTrue((sub / "old.log").exists())


if __name__ == "__main__":
    unittest.main()
