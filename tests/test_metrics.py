import json
import unittest
from datetime import datetime
from pathlib import Path

from plantfloor.metrics import Ranked, loss_by_hour, rank, summarize, vital_few

ROOT = Path(__file__).resolve().parent.parent
DEMO = json.loads((ROOT / "data/events.demo.json").read_text())


class DemoStoryTests(unittest.TestCase):
    """The demo plant has a planted story; the metrics must find it, with the dashboard's numbers."""

    @classmethod
    def setUpClass(cls):
        cls.s = summarize(DEMO)

    def test_shirt_press_is_the_constraint_and_costliest_station(self):
        self.assertEqual(self.s.constraint.key, "press_shirt")
        self.assertAlmostEqual(self.s.constraint.minutes / 60, 5.8, places=1)
        self.assertEqual(self.s.costliest.key, "press_shirt")
        self.assertAlmostEqual(self.s.costliest.minutes / 60, 7.3, places=1)

    def test_press_backlog_is_the_biggest_cause(self):
        self.assertEqual(self.s.top_cause.key, "press_backlog")

    def test_worst_hour_is_the_day_two_dryer_failure(self):
        when, lost = self.s.worst_hour
        self.assertEqual(when, datetime(2026, 9, 2, 11))
        self.assertAlmostEqual(lost / 60, 4.9, places=1)

    def test_headline_share_and_station_impacts_match_the_dashboard(self):
        self.assertEqual(round(100 * self.s.loss_share), 15)
        self.assertEqual([round(r.impact) for r in self.s.stations[:3]], [1531, 891, 873])
        self.assertEqual(self.s.stations[0].name, "Shirt press unit")

    def test_filters_change_the_answer(self):
        strict = summarize(DEMO, min_severity=5)
        self.assertEqual(strict.costliest.key, "dryers")


def e(station, etype, start, end, sev=3, cause="c"):
    return {"station": station, "type": etype, "abs_start": start, "abs_end": end,
            "duration": end - start, "severity": sev, "cause": cause, "confidence": 1.0}


class UnitTests(unittest.TestCase):
    def test_rank_orders_by_minutes_and_keeps_ties_stable(self):
        rows = rank([e("a", "idle", 0, 60), e("b", "idle", 0, 120), e("c", "idle", 0, 60)], lambda x: x["station"])
        self.assertEqual([r.key for r in rows], ["b", "a", "c"])
        self.assertEqual(rows[0].impact, 6.0)

    def test_hour_buckets_split_events_across_hours(self):
        out = loss_by_hour([e("a", "idle", 3000, 4200)], 7200, datetime(2026, 1, 1))
        self.assertEqual([round(v) for _, v in out], [10, 10])

    def test_vital_few(self):
        causes = [Ranked("x", 70, 0, 1), Ranked("y", 20, 0, 1), Ranked("z", 10, 0, 1)]
        self.assertEqual(vital_few(causes), 1)
        self.assertEqual(vital_few([Ranked("x", 100, 0, 1)]), 1)

    def test_necessary_work_is_not_counted_as_lost(self):
        doc = {"meta": {"recording_start": "2026-01-01T00:00:00", "total_seconds": 3600},
               "stations": [], "events": [e("a", "changeover", 0, 600), e("a", "work", 600, 1200)]}
        s = summarize(doc)
        self.assertEqual(s.lost_minutes, 0)
        self.assertIsNone(s.costliest)
        self.assertIsNone(s.worst_hour)


if __name__ == "__main__":
    unittest.main()
