import tempfile
import unittest
from pathlib import Path

from plantfloor.video.ffmpeg import FFmpegError, collect_inputs, parse_signalstats

OUTPUT = """frame:0    pts:0       pts_time:0
lavfi.signalstats.YAVG=0.000
frame:1    pts:2       pts_time:2
lavfi.signalstats.YAVG=5.25
frame:2    pts:4       pts_time:4
some unrelated line
lavfi.signalstats.YAVG=1.5
""".splitlines()


class ParseTests(unittest.TestCase):
    def test_pairs_timestamps_with_values(self):
        self.assertEqual(parse_signalstats(OUTPUT), [(0.0, 0.0), (2.0, 5.25), (4.0, 1.5)])

    def test_value_without_frame_is_ignored(self):
        self.assertEqual(parse_signalstats(["lavfi.signalstats.YAVG=9"]), [])


class CollectInputsTests(unittest.TestCase):
    def test_directory_is_filtered_and_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.mp4", "a.MOV", "notes.txt", "c.dav"):
                Path(d, name).write_bytes(b"")
            self.assertEqual([p.name for p in collect_inputs(d)], ["a.MOV", "b.mp4", "c.dav"])

    def test_single_file_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "x.mp4"); f.write_bytes(b"")
            self.assertEqual(collect_inputs(f), [f])
            with self.assertRaises(FFmpegError):
                collect_inputs(Path(d, "missing.mp4"))
            Path(d, "empty").mkdir()
            with self.assertRaisesRegex(FFmpegError, "no video files"):
                collect_inputs(Path(d, "empty"))


if __name__ == "__main__":
    unittest.main()
