import unittest
from datetime import datetime

from plantfloor.timecode import at, clip_stamp, iso, parse_start


class TimecodeTests(unittest.TestCase):
    def test_parses_all_supported_forms(self):
        expected = datetime(2026, 9, 1, 6, 0, 0)
        for text in ("2026-09-01 06:00:00", "2026-09-01 06:00", "2026-09-01T06:00:00", " 2026-09-01T06:00 "):
            self.assertEqual(parse_start(text), expected, text)

    def test_rejects_other_formats(self):
        for text in ("09/01/2026 06:00", "06:00", ""):
            with self.assertRaises(ValueError):
                parse_start(text)

    def test_offsets_and_formatting(self):
        start = datetime(2026, 9, 1, 23, 59, 30)
        self.assertEqual(iso(at(start, 45)), "2026-09-02T00:00:15")
        self.assertEqual(clip_stamp(at(start, 45)), "2026-09-02_000015")


if __name__ == "__main__":
    unittest.main()
