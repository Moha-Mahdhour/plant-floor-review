import json
import unittest
from pathlib import Path

from plantfloor.demo import generate
from plantfloor.stations import load_stations
from plantfloor.taxonomy import EVENT_TYPES

ROOT = Path(__file__).resolve().parent.parent
STATIONS = load_stations(ROOT / "prompts/stations.json")


class DemoTests(unittest.TestCase):
    def test_bundled_demo_data_matches_the_generator(self):
        committed = json.loads((ROOT / "data/events.demo.json").read_text())
        fresh = generate(STATIONS, generated=committed["meta"]["generated"])
        self.assertEqual(fresh, committed)

    def test_script_version_matches_the_json(self):
        js = (ROOT / "data/events.demo.js").read_text()
        self.assertTrue(js.startswith("window.DEMO_DATA = ") and js.endswith(";"))
        self.assertEqual(json.loads(js[len("window.DEMO_DATA = "):-1]),
                         json.loads((ROOT / "data/events.demo.json").read_text()))

    def test_same_seed_same_data(self):
        self.assertEqual(generate(STATIONS, generated="x"), generate(STATIONS, generated="x"))
        self.assertNotEqual(generate(STATIONS, seed=8, generated="x")["events"], generate(STATIONS, generated="x")["events"])

    def test_every_event_is_valid(self):
        ids = {s.id for s in STATIONS}
        for e in generate(STATIONS, generated="x")["events"]:
            self.assertIn(e["station"], ids)
            self.assertIn(e["type"], EVENT_TYPES)
            self.assertLess(e["abs_start"], e["abs_end"])


if __name__ == "__main__":
    unittest.main()
