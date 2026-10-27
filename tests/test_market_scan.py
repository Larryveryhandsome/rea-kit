import unittest

from adapters.csv_listing_source import load_csv
from core.market_scan import MarketScanCriteria, build_alert_queue, match_alert_queue, scan_snapshot


BASE = """id,transaction,area,price,property_type,rooms,url,listed_at,size_ping,age_years,source
L-001,buy,中央區,1100,公寓,2,https://example.test/L-001,2026-10-01,28,8,synthetic
L-002,buy,東區,1050,公寓,2,https://example.test/L-002,2026-10-01,28,8,synthetic
L-003,buy,中央區,1500,公寓,3,https://example.test/L-003,2026-10-01,42,18,synthetic
"""


class MarketScanTests(unittest.TestCase):
    def setUp(self):
        self.criteria = MarketScanCriteria(
            area="中央區", transaction="buy", property_type="公寓",
            price_max=1200, size_min=20, size_max=35, age_max=12,
        )

    def test_region_and_scope_filters(self):
        result = scan_snapshot(load_csv(BASE), self.criteria)
        self.assertEqual([item["listing"]["id"] for item in result["candidates"]], ["L-001"])
        self.assertIn("area mismatch", result["excluded"][0]["reasons"])

    def test_new_and_changed_only_enter_queue(self):
        current = BASE.replace("L-002,buy,東區,1050", "L-004,buy,中央區,1050").replace("1100,公寓", "1150,公寓")
        result = build_alert_queue(load_csv(BASE), load_csv(current), self.criteria)
        self.assertEqual({item["listing"]["id"] for item in result["queue"]}, {"L-001", "L-004"})
        self.assertEqual(result["unchanged_count"], 1)
        self.assertEqual(result["removed_ids"], ["L-002"])

    def test_incomplete_filter_field_goes_to_review(self):
        row = BASE.replace(",1100,公寓,2,", ",,公寓,2,")
        # The CSV adapter rejects missing required price before scan, so use a normalized row.
        listing = load_csv(BASE)[0]
        listing["price"] = None
        result = scan_snapshot([listing], self.criteria)
        self.assertEqual(result["review"][0]["reasons"], ["missing price"])

    def test_alert_queue_flows_into_buyer_matching(self):
        current = BASE.replace("L-002,buy,東區,1050", "L-004,buy,中央區,1050").replace("1100,公寓", "1150,公寓")
        alerts = build_alert_queue(load_csv(BASE), load_csv(current), self.criteria)
        need = {
            "transaction": "buy", "preferred_areas": ["中央區"],
            "budget_max": 1200, "budget_tolerance_pct": 0,
            "property_type": "公寓", "rooms_min": 2,
        }
        matched = match_alert_queue(alerts, need)
        self.assertEqual({item["listing_id"] for item in matched["priority"]}, {"L-001", "L-004"})


if __name__ == "__main__":
    unittest.main()
