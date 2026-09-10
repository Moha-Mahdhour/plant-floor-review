import unittest
from datetime import datetime
from pathlib import Path

from plantfloor.video.plan import finalize_chunks, lay_out, plan_chunks, windows_from_samples


def samples(active, total=1200, step=2.0, hot=5.0, cold=0.1):
    """Motion samples that are 'hot' inside any of the (start, end) ranges."""
    return [(t, hot if any(a <= t < b for a, b in active) else cold) for t in [i * step for i in range(int(total / step))]]


ONE_FILE = lay_out([("day.mp4", Path("day.mp4"), 5000.0)])


class WindowTests(unittest.TestCase):
    def test_no_motion_means_no_windows(self):
        self.assertEqual(windows_from_samples(samples([]), 1.2, 60, 120), [])

    def test_activity_is_padded(self):
        (a, b), = windows_from_samples(samples([(400, 500)]), 1.2, pad=60, min_gap=120)
        self.assertEqual(a, 340.0)
        self.assertEqual(b, 498 + 2 + 60)

    def test_short_gaps_join_long_gaps_split(self):
        joined = windows_from_samples(samples([(100, 200), (260, 300)]), 1.2, pad=0, min_gap=120)
        self.assertEqual(len(joined), 1)
        split = windows_from_samples(samples([(100, 200), (500, 600)]), 1.2, pad=0, min_gap=120)
        self.assertEqual(len(split), 2)

    def test_padding_overlap_merges_windows(self):
        merged = windows_from_samples(samples([(100, 200), (400, 500)]), 1.2, pad=150, min_gap=120)
        self.assertEqual(len(merged), 1)


class PlanTests(unittest.TestCase):
    def test_window_is_cut_into_fixed_chunks(self):
        chunks = plan_chunks([(0, 700)], 300, ONE_FILE)
        self.assertEqual([(c["abs_start"], c["abs_end"]) for c in chunks], [(0, 300), (300, 600), (600, 700)])
        self.assertEqual([c["id"] for c in chunks], ["chunk_0000", "chunk_0001", "chunk_0002"])

    def test_short_tail_is_folded_into_previous_chunk(self):
        chunks = plan_chunks([(0, 620)], 300, ONE_FILE)
        self.assertEqual([(c["abs_start"], c["abs_end"]) for c in chunks], [(0, 300), (300, 620)])

    def test_source_offset_is_relative_to_the_file(self):
        sources = lay_out([("a.mp4", Path("a"), 1000.0), ("b.mp4", Path("b"), 1000.0)])
        c = plan_chunks([(1200, 1500)], 300, sources)[0]
        self.assertEqual((c["source"], c["source_offset"]), ("b.mp4", 200.0))

    def test_finalize_adds_clock_and_filename(self):
        c = finalize_chunks(plan_chunks([(3600, 3900)], 300, ONE_FILE), datetime(2026, 9, 1, 6))[0]
        self.assertEqual(c["clock_start"], "2026-09-01T07:00:00")
        self.assertEqual(c["file"], "chunk_0000__2026-09-01_070000.mp4")


if __name__ == "__main__":
    unittest.main()


class SourceBoundaryTests(unittest.TestCase):
    TWO = lay_out([("a.mp4", Path("a"), 400.0), ("b.mp4", Path("b"), 400.0)])

    def test_chunk_never_spans_two_files(self):
        chunks = plan_chunks([(300, 500)], 300, self.TWO)
        self.assertEqual([(c["abs_start"], c["abs_end"], c["source"]) for c in chunks],
                         [(300, 400, "a.mp4"), (400, 500, "b.mp4")])
        self.assertEqual(chunks[1]["source_offset"], 0.0)

    def test_every_chunk_fits_inside_its_file(self):
        chunks = plan_chunks([(0, 800)], 300, self.TWO)
        for c in chunks:
            src = next(s for s in self.TWO if s.name == c["source"])
            self.assertLessEqual(c["source_offset"] + c["duration"], src.duration + 1e-6, c)

    def test_padding_past_the_end_of_the_recording_is_clipped(self):
        chunks = plan_chunks([(700, 900)], 300, self.TWO)
        self.assertEqual(chunks[-1]["abs_end"], 800)

    def test_short_tail_is_not_folded_across_a_file_boundary(self):
        chunks = plan_chunks([(100, 420)], 300, self.TWO)
        self.assertTrue(all(c["abs_end"] <= 400 or c["source"] == "b.mp4" for c in chunks), chunks)


class DeadAirTests(unittest.TestCase):
    def test_short_window_is_not_merged_across_a_quiet_gap(self):
        chunks = plan_chunks([(0, 300), (1000, 1030)], 300, ONE_FILE)
        self.assertEqual([(c["abs_start"], c["abs_end"]) for c in chunks], [(0, 300), (1000, 1030)])

    def test_kept_footage_never_exceeds_the_active_windows(self):
        windows = [(0, 300), (900, 940), (2000, 2610)]
        kept = sum(c["duration"] for c in plan_chunks(windows, 300, ONE_FILE))
        self.assertAlmostEqual(kept, sum(b - a for a, b in windows))
