import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "plantfloor", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"})


class CliTests(unittest.TestCase):
    def test_help_lists_every_step(self):
        r = cli("--help")
        self.assertEqual(r.returncode, 0)
        for step in ("prep", "prompts", "merge", "report", "demo"):
            self.assertIn(step, r.stdout)

    def test_report_on_demo(self):
        r = cli("report", "--events", "demo", "--top", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Shirt press unit", r.stdout)

    def test_missing_events_file_is_a_clean_error(self):
        r = cli("report", "--events", "nowhere.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found", r.stderr)

    def test_demo_then_merge_style_workflow_in_a_scratch_project(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(ROOT / "prompts", Path(d, "prompts"))
            r = cli("demo", "--root", d)
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads(Path(d, "data/events.demo.json").read_text())
            self.assertEqual(len(doc["events"]), 409)
            r = cli("report", "--root", d, "--events", "demo", "--out", "report.md")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("# Bottleneck report", Path(d, "report.md").read_text())

    def test_merge_without_manifest_explains_the_next_step(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(ROOT / "prompts", Path(d, "prompts"))
            r = cli("merge", "--root", d)
            self.assertEqual(r.returncode, 1)
            self.assertIn("run the prep step first", r.stdout)

    def test_prep_without_ffmpeg_on_path_fails_cleanly(self):
        r = cli("prep", "--input", "x.mp4", "--start", "2026-09-01 06:00")   # PATH excludes Homebrew
        if shutil.which("ffmpeg", path="/usr/bin:/bin"):
            self.skipTest("ffmpeg is on the system PATH")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found on PATH", r.stderr)


if __name__ == "__main__":
    unittest.main()
