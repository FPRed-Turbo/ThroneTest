import json
import tempfile
import unittest
from pathlib import Path

from questlog_tl import scraper
from questlog_tl.datasets import Dataset
from questlog_tl.export import Context, clean_text, export


class FakeClient:
    """Serves a fake list endpoint that, like questlog, caps every query at 25 pages of 40."""

    def __init__(self, rows):
        self.rows = rows

    def call(self, proc, params):
        rows = self.rows
        for key, value in (params.get("facets") or {}).items():
            rows = [r for r in rows if r.get(key) == value]
        for key in ("mainCategory", "subCategory"):
            if key in params:
                rows = [r for r in rows if r.get(key) == params[key]]
        if params.get("sortBy") == "name":
            rows = sorted(rows, key=lambda r: r["name"], reverse=params.get("sortType") == "desc")
        page = params["page"]
        facets = {}
        for key in ("grade", "createdAt"):
            dist = {}
            for r in rows:
                dist[str(r[key])] = dist.get(str(r[key]), 0) + 1
            facets[key] = dist
        visible = rows[: scraper.MAX_PAGES * scraper.PAGE_SIZE]
        start = (page - 1) * scraper.PAGE_SIZE
        return {"pageData": visible[start:start + scraper.PAGE_SIZE] if page <= scraper.MAX_PAGES else [],
                "pageCount": -(-len(rows) // scraper.PAGE_SIZE), "facetDistribution": facets}


class FetchListTest(unittest.TestCase):
    def test_splits_queries_to_get_past_the_1000_row_cap(self):
        rows = [{"id": f"i{n}", "name": f"Item {n:05d}", "grade": [11, 21, 31][n % 3],
                 "createdAt": ["2024-01-01", "2025-01-01"][n % 2], "mainCategory": ["a", "b"][n % 2]}
                for n in range(4500)]
        scraper.log = lambda msg: None
        got = scraper.fetch_list(FakeClient(rows), Dataset("items", "x", "y"), "en")
        self.assertEqual({r["id"] for r in got}, {r["id"] for r in rows})


class FormatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raw = Path(self.tmp.name) / "raw"
        (raw / "builder").mkdir(parents=True)
        (raw / "builder" / "stat-format.json").write_text(json.dumps({
            "debuff_taken_duration_modifier": {"name": "Debuff Duration", "valueFormat": "{0}%", "multiplier": 0.01,
                                               "invert": True},
            "all_critical_attack": {"name": "Critical Hit Chance", "valueFormat": "{0}", "multiplier": 0.1},
            "int": {"name": "Wisdom", "valueFormat": "{0}", "multiplier": 1},
        }))
        (raw / "builder" / "equipment-items.json").write_text(json.dumps({
            "staff_1": {"id": "staff_1", "name": "Test Staff", "grade": 41, "equipmentType": "staff",
                        "itemStats": {"main": {"0": {"mainhand": {"min": 10, "max": 20}}},
                                      "extra": {"0": {"int": 5}},
                                      "traits": {"all_critical_attack": [200, 400, 600, 800]}}}}))
        self.raw = raw

    def tearDown(self):
        self.tmp.cleanup()

    def test_stat_values_are_converted_to_display_values(self):
        ctx = Context(self.raw)
        self.assertEqual(ctx.stat("debuff_taken_duration_modifier", -350), "Debuff Duration -3.5%")
        self.assertEqual(ctx.stat("all_critical_attack", 800), "Critical Hit Chance +80")

    def test_clean_text_strips_html(self):
        self.assertEqual(clean_text('Deals <span style="color:#FEE79E">15%</span> &amp; more'), "Deals 15% & more")

    def test_export_writes_readable_gear_file(self):
        written = export(str(self.raw.parent))
        staff = next(p for p in written if p.name == "gear_weapons_staff.md")
        text = staff.read_text()
        self.assertIn("### Test Staff", text)
        self.assertIn("Critical Hit Chance +80", text)
        self.assertIn("Wisdom +5", text)
        self.assertTrue((self.raw.parent / "knowledge" / "00_START_HERE.md").exists())


if __name__ == "__main__":
    unittest.main()
