import tempfile
import unittest
from pathlib import Path

from plantfloor.stations import StationError, load_stations, parse_stations

ROOT = Path(__file__).resolve().parent.parent


class StationTests(unittest.TestCase):
    def test_bundled_catalog_is_valid_and_ordered(self):
        stations = load_stations(ROOT / "prompts/stations.json")
        self.assertEqual(stations[0].id, "counter")
        self.assertEqual(stations[-1].id, "floor")
        self.assertEqual([s.order for s in stations], sorted(s.order for s in stations))

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(StationError, "duplicate"):
            parse_stations([{"id": "a", "name": "A"}, {"id": "a", "name": "B"}, {"id": "floor"}])

    def test_fallback_station_required(self):
        with self.assertRaisesRegex(StationError, "floor"):
            parse_stations([{"id": "press", "name": "Press"}])

    def test_bad_id_and_kind_rejected(self):
        with self.assertRaises(StationError):
            parse_stations([{"id": "Shirt Press"}, {"id": "floor"}])
        with self.assertRaisesRegex(StationError, "kind"):
            parse_stations([{"id": "a", "kind": "robot"}, {"id": "floor"}])

    def test_missing_file_is_a_station_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(StationError):
                load_stations(Path(d, "nope.json"))

    def test_defaults_fill_name_order_kind(self):
        s = parse_stations([{"id": "floor"}])[0]
        self.assertEqual((s.name, s.order, s.kind), ("floor", 99, "other"))


if __name__ == "__main__":
    unittest.main()
