import json
import re
import unittest
from pathlib import Path

from plantfloor.taxonomy import COVERAGE_STATES, EVENT_TYPES, LOSS_TYPES, category, is_loss

ROOT = Path(__file__).resolve().parent.parent


class TaxonomyTests(unittest.TestCase):
    def test_schema_enum_matches_taxonomy(self):
        schema = json.loads((ROOT / "prompts/schema.json").read_text())
        enum = schema["properties"]["events"]["items"]["properties"]["type"]["enum"]
        self.assertEqual(set(enum), set(EVENT_TYPES))
        self.assertEqual(tuple(schema["properties"]["coverage"]["enum"]), COVERAGE_STATES)

    def test_dashboard_categories_match_taxonomy(self):
        html = (ROOT / "app/index.html").read_text()
        table = dict(re.findall(r"^\s*(\w+):\s*\{c:'#[0-9A-Fa-f]{6}',\s*label:'[^']*',\s*cat:'(\w+)'\}", html, re.M))
        self.assertEqual(table, EVENT_TYPES)

    def test_changeovers_and_transport_are_not_losses(self):
        self.assertFalse(is_loss("changeover"))
        self.assertFalse(is_loss("transport"))
        self.assertFalse(is_loss("break"))
        self.assertTrue(is_loss("blockage"))

    def test_unknown_types_count_as_loss(self):
        self.assertEqual(category("teleport"), "loss")
        self.assertIn("unknown", LOSS_TYPES)


if __name__ == "__main__":
    unittest.main()
