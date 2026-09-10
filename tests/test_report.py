import json
import unittest
from pathlib import Path

from plantfloor.metrics import summarize
from plantfloor.report import fmt_minutes, render_markdown

ROOT = Path(__file__).resolve().parent.parent
DEMO = json.loads((ROOT / "data/events.demo.json").read_text())


class ReportTests(unittest.TestCase):
    def test_minute_formatting_matches_the_dashboard(self):
        self.assertEqual(fmt_minutes(45), "45 min")
        self.assertEqual(fmt_minutes(294), "4.9 h")
        self.assertEqual(fmt_minutes(1668), "28 h")

    def test_demo_report_tells_the_planted_story(self):
        md = render_markdown(DEMO, summarize(DEMO))
        self.assertIn("| Likely constraint | Shirt press unit: 5.8 h of queue build-up |", md)
        self.assertIn("| Costliest station | Shirt press unit: 7.3 h lost |", md)
        self.assertIn("| Biggest single cause | press backlog: 13 h lost |", md)
        self.assertIn("| Worst hour | Wed 02 Sep 11:00: 4.9 h lost |", md)
        self.assertIn("| Shirt press unit | 7.3 h |", md)
        self.assertIn("account for 80%", md)

    def test_top_events_are_limited_and_ranked(self):
        md = render_markdown(DEMO, summarize(DEMO), top_events=3)
        section = md.split("## Highest-impact events")[1]
        rows = [l for l in section.splitlines() if l.startswith("| ") and "When" not in l]
        self.assertEqual(len(rows), 3)
        self.assertIn("Dryer 2 down", rows[0])

    def test_empty_timeline_renders(self):
        doc = {"meta": {"recording_start": "2026-01-01T00:00:00", "total_seconds": 3600, "site": "Empty"},
               "stations": [], "events": []}
        md = render_markdown(doc, summarize(doc))
        self.assertIn("no queue build-up recorded", md)
        self.assertNotIn("## Causes", md)


if __name__ == "__main__":
    unittest.main()
