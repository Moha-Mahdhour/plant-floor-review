import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plantfloor.project import Project
from plantfloor.prompts import (BAD_JSON, FIRST_CHUNK, NOT_ANNOTATED, NOTHING_OPEN, build_prompts,
                                open_events_text, render_chunk_prompt, template_body)

ROOT = Path(__file__).resolve().parent.parent
CHUNK = {"id": "chunk_0003", "duration": 300.4, "clock_start": "2026-09-02T10:05:00", "file": "chunk_0003__x.mp4"}


class RenderTests(unittest.TestCase):
    def test_bundled_template_renders_every_placeholder(self):
        tmpl = (ROOT / "prompts/chunk_prompt.md").read_text()
        body = render_chunk_prompt(tmpl, CHUNK, fps=2, stations="- press = Press", open_events="- press: queue")
        self.assertNotIn("{{", body)
        self.assertNotIn("<!--", body)
        self.assertIn("CHUNK: chunk_0003", body)
        self.assertIn("2026-09-02 10:05:00  (Wednesday)", body)
        self.assertIn("300 seconds", body)

    def test_unknown_placeholder_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "mystery"):
            render_chunk_prompt("{{chunk_id}} {{mystery}}", CHUNK, fps=2, stations="", open_events="")

    def test_template_without_comment_is_kept_whole(self):
        self.assertEqual(template_body("  plain {{chunk_id}}  "), "plain {{chunk_id}}")


class OpenEventTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(open_events_text(None), NOT_ANNOTATED)
        self.assertEqual(open_events_text("{not json"), BAD_JSON)
        self.assertEqual(open_events_text({"events": [{"station": "qc", "type": "work"}]}), NOTHING_OPEN)

    def test_lists_only_continuing_events(self):
        prev = {"events": [
            {"station": "press_shirt", "type": "queue_buildup", "label": "Backlog", "continues_into_next": True},
            {"station": "qc", "type": "work", "label": "Fine"},
        ]}
        self.assertEqual(open_events_text(prev), "- press_shirt: queue_buildup - Backlog")


class BuildTests(unittest.TestCase):
    def test_writes_prompts_and_batch_with_carry_over(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            shutil.copytree(ROOT / "prompts", root / "prompts")
            (root / "chunks").mkdir()
            chunks = [dict(CHUNK, id="chunk_0000", file="a.mp4"), dict(CHUNK, id="chunk_0001", file="b.mp4")]
            (root / "chunks/manifest.json").write_text(json.dumps({"fps": 2, "chunks": chunks}))
            (root / "annotations").mkdir()
            (root / "annotations/chunk_0000.json").write_text(json.dumps({"events": [
                {"station": "dryers", "type": "machine_stop", "label": "Dryer down", "continues_into_next": True}]}))
            batch = build_prompts(Project.at(root))
            self.assertEqual([b["chunk_id"] for b in batch], ["chunk_0000", "chunk_0001"])
            self.assertIn(FIRST_CHUNK, batch[0]["prompt"])
            self.assertIn("- dryers: machine_stop - Dryer down", batch[1]["prompt"])
            self.assertEqual(batch[1]["video"], "chunks/b.mp4")
            self.assertEqual(batch[0]["schema"]["title"], json.loads((ROOT / "prompts/schema.json").read_text())["title"])
            self.assertTrue((root / "annotations/_prompts/chunk_0001.txt").exists())
            self.assertEqual(len((root / "annotations/_prompts/batch.jsonl").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
