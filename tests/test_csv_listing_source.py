import unittest

from adapters.csv_listing_source import diff_listings, load_csv, normalize_listing
from core.listing_matching import match_listings


CSV = """id,transaction,area,price,property_type,rooms,url,listed_at,size_ping,age_years,source
L-001,buy,中央區,1180,Apartment,2,https://example.test/L-001,2026-10-01,28,8,synthetic
L-002,buy,中央區,1350,公寓,3,https://example.test/L-002,2026-10-01,36,12,synthetic
"""


class CsvListingSourceTests(unittest.TestCase):
    def test_load_normalizes_types_and_case(self):
        listings = load_csv(CSV, source="fixture")
        self.assertEqual(listings[0]["property_type"], "公寓")
        self.assertEqual(listings[0]["price"], 1180.0)
        self.assertEqual(listings[0]["source"], "synthetic")

    def test_diff_marks_new_changed_unchanged_and_removed(self):
        previous = load_csv(CSV)
        current = load_csv(CSV.replace("1180", "1190").replace("L-002", "L-003"))
        delta = diff_listings(previous, current)
        self.assertEqual([row["id"] for row in delta.new], ["L-003"])
        self.assertEqual([row["id"] for row in delta.changed], ["L-001"])
        self.assertEqual(delta.unchanged, ())
        self.assertEqual(delta.removed_ids, ("L-002",))

    def test_missing_required_field_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_listing({"id": "L-004", "transaction": "buy"})

    def test_unknown_transaction_fails_closed(self):
        row = {"id": "L-005", "transaction": "swap", "area": "中央區", "price": "1000",
               "property_type": "公寓", "rooms": "2", "url": "https://example.test/L-005",
               "listed_at": "2026-10-01"}
        with self.assertRaises(ValueError):
            normalize_listing(row)

    def test_csv_to_matching_vertical_slice(self):
        listings = load_csv(CSV, source="fixture")
        need = {
            "transaction": "buy",
            "preferred_areas": ["中央區"],
            "budget_max": 1200,
            "budget_tolerance_pct": 10,
            "property_type": "公寓",
            "rooms_min": 2,
        }
        result = match_listings(need, listings)
        self.assertEqual([item["listing_id"] for item in result["priority"]], ["L-001"])
        self.assertEqual([item["listing_id"] for item in result["rejected"]], ["L-002"])


if __name__ == "__main__":
    unittest.main()
