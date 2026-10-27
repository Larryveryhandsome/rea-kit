import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebEntrypointTests(unittest.TestCase):
    def test_static_entrypoint_has_product_flow(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for required in ("免費配對", "新案", "買方需求卡", "csv-file", "result-list", "資料邊界"):
            self.assertIn(required, html)

    def test_client_demo_has_privacy_and_events(self):
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("local-file", js)
        self.assertIn("CustomEvent", js)
        self.assertIn("first_result", js)


if __name__ == "__main__":
    unittest.main()
