"""start.sh: the pre-made demo .env, --custom, and never clobbering a .env of your own."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "start.sh"
MARK = "# created by start.sh: shared demo database"


class StartScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        shutil.copy(SCRIPT, self.dir / "start.sh")
        self.env = self.dir / ".env"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(["bash", str(self.dir / "start.sh"), *args], capture_output=True, text=True, timeout=30)

    def test_write_env_creates_the_premade_demo_env(self):
        r = self.run_script("--write-env")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.env.read_text()
        self.assertIn(MARK, text)
        for key in ("SHADEDB_ENDPOINT=https://", "SHADEDB_DBID=sdb", "SHADEDB_CONNECTION_TOKEN=", "SHADEDB_CLUSTER_TOKEN=",
                    "SHADEDB_PARTITION=duelers", "PORT=5000"):
            self.assertIn(key, text)

    def test_custom_needs_your_own_env(self):
        r = self.run_script("--custom")
        self.assertEqual(r.returncode, 1)
        self.assertIn("there isn't one here", r.stdout)
        self.assertFalse(self.env.exists())  # it never creates one behind your back

    def test_custom_refuses_the_demo_env_but_leaves_it_alone(self):
        self.run_script("--write-env")
        before = self.env.read_text()
        r = self.run_script("--custom")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.env.read_text(), before)

    def test_an_env_of_your_own_is_never_overwritten(self):
        self.env.write_text("SHADEDB_ENDPOINT=https://mine.example/connect/x\nPORT=6000\n")
        mine = self.env.read_text()
        for args in (["--write-env"], []):
            r = self.run_script(*args) if args else self.run_script("--offline", "--write-env")
            self.assertEqual(r.returncode, 1)
            self.assertIn("--custom", r.stdout)
            self.assertEqual(self.env.read_text(), mine)

    def test_demo_replaces_it_but_keeps_a_backup(self):
        self.env.write_text("SHADEDB_ENDPOINT=https://mine.example/connect/x\n")
        r = self.run_script("--demo", "--write-env")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(MARK, self.env.read_text())
        self.assertIn("mine.example", (self.dir / ".env.bak").read_text())

    def test_flags_that_cannot_go_together(self):
        self.assertEqual(self.run_script("--custom", "--demo").returncode, 1)
        self.assertEqual(self.run_script("--nope").returncode, 1)
        self.assertIn("--custom", self.run_script("--help").stdout)


if __name__ == "__main__":
    unittest.main()
