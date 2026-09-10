import unittest

from plantfloor.merge import MIN_DURATION, STITCH_TOLERANCE, lost_hours, merge
from plantfloor.stations import parse_stations

STATIONS = parse_stations([{"id": "press_shirt", "name": "Shirt press"}, {"id": "qc", "name": "QC"}, {"id": "floor"}])


def manifest(n=3, length=300.0, gap=0.0):
    chunks, t = [], 0.0
    for i in range(n):
        chunks.append({"id": f"chunk_{i:04d}", "abs_start": t, "abs_end": t + length, "duration": length})
        t += length + gap
    return {"recording_start": "2026-09-01T06:00:00", "total_seconds": t, "kept_seconds": n * length, "chunks": chunks}


def ev(t0, t1, station="press_shirt", etype="queue_buildup", **kw):
    return {"t_start": t0, "t_end": t1, "station": station, "type": etype, "severity": 3, "confidence": 0.8,
            "label": "x", **kw}


def run(anns, m=None, **kw):
    doc, problems = merge(m or manifest(), anns, STATIONS, generated="fixed", **kw)
    return doc, problems


class MergeTests(unittest.TestCase):
    def test_offsets_become_absolute_time(self):
        doc, _ = run({"chunk_0002": {"events": [ev(10, 70)]}})
        e = doc["events"][0]
        self.assertEqual((e["abs_start"], e["abs_end"], e["duration"]), (610, 670, 60))
        self.assertEqual(e["clock_start"], "2026-09-01T06:10:10")

    def test_times_are_clamped_swapped_and_padded(self):
        doc, _ = run({"chunk_0000": {"events": [ev(999, 250), ev(40, 41)]}})
        a, b = sorted(doc["events"], key=lambda e: e["abs_start"])
        self.assertEqual((a["abs_start"], a["abs_end"]), (40, 40 + MIN_DURATION))
        self.assertEqual((b["abs_start"], b["abs_end"]), (250, 302))

    def test_unknown_station_and_type_are_repaired_and_reported(self):
        doc, problems = run({"chunk_0000": {"events": [ev(0, 30, station="laser_bay", etype="teleport")]}})
        self.assertEqual((doc["events"][0]["station"], doc["events"][0]["type"]), ("floor", "unknown"))
        self.assertEqual(len(problems), 2)

    def test_garbage_severity_and_confidence_fall_back_and_clamp(self):
        doc, _ = run({"chunk_0000": {"events": [ev(0, 30, severity="high", confidence=7)]}})
        self.assertEqual((doc["events"][0]["severity"], doc["events"][0]["confidence"]), (2, 1.0))

    def test_events_without_times_are_rejected(self):
        doc, problems = run({"chunk_0000": {"events": [{"station": "qc", "type": "idle"}]}})
        self.assertEqual(doc["events"], [])
        self.assertIn("no usable t_start", problems[0])

    def test_continuations_are_stitched_across_chunks(self):
        anns = {
            "chunk_0000": {"events": [ev(200, 300, continues_into_next=True, items=9)]},
            "chunk_0001": {"events": [ev(0, 300, continues_from_previous=True, continues_into_next=True, severity=4)]},
            "chunk_0002": {"events": [ev(0, 120, continues_from_previous=True, items=20)]},
        }
        doc, _ = run(anns)
        self.assertEqual(len(doc["events"]), 1)
        e = doc["events"][0]
        self.assertEqual((e["abs_start"], e["abs_end"], e["spans"]), (200, 720, 3))
        self.assertEqual((e["severity"], e["items"]), (4, 20))

    def test_no_stitching_across_a_long_gap(self):
        m = manifest(n=2, gap=STITCH_TOLERANCE + 60)
        anns = {"chunk_0000": {"events": [ev(250, 300, continues_into_next=True)]},
                "chunk_0001": {"events": [ev(0, 60, continues_from_previous=True)]}}
        self.assertEqual(len(run(anns, m)[0]["events"]), 2)

    def test_event_not_re_reported_is_closed(self):
        anns = {"chunk_0000": {"events": [ev(250, 300, continues_into_next=True)]},
                "chunk_0001": {"events": []},
                "chunk_0002": {"events": [ev(0, 60, continues_from_previous=True)]}}
        self.assertEqual(len(run(anns)[0]["events"]), 2)

    def test_confidence_filter(self):
        doc, _ = run({"chunk_0000": {"events": [ev(0, 30, confidence=0.3), ev(40, 90, confidence=0.9)]}},
                     min_confidence=0.5)
        self.assertEqual(len(doc["events"]), 1)

    def test_coverage_and_throughput(self):
        anns = {"chunk_0000": {"coverage": "partial", "events": [], "counts": {"items_in": "4", "items_out": 3}},
                "chunk_0001": "{broken"}
        doc, problems = run(anns)
        self.assertEqual([c["state"] for c in doc["coverage"]], ["partial", "bad_json", "not_annotated"])
        self.assertEqual(doc["throughput"], [{"abs_start": 0.0, "items_in": 4, "items_out": 3, "customers": 0}])
        self.assertEqual(doc["meta"]["chunks_annotated"], 1)
        self.assertIn("invalid JSON", problems[0])

    def test_ids_follow_start_time_and_private_flags_are_removed(self):
        doc, _ = run({"chunk_0001": {"events": [ev(0, 30)]}, "chunk_0000": {"events": [ev(0, 30, station="qc")]}})
        self.assertEqual([e["id"] for e in doc["events"]], ["e00000", "e00001"])
        self.assertEqual(doc["events"][0]["station"], "qc")
        self.assertNotIn("_open", doc["events"][0])

    def test_lost_hours_excludes_necessary_work(self):
        doc, _ = run({"chunk_0000": {"events": [ev(0, 60), ev(60, 120, etype="changeover"), ev(120, 180, etype="work")]}})
        self.assertAlmostEqual(lost_hours(doc), 60 / 3600)


if __name__ == "__main__":
    unittest.main()
