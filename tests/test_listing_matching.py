import unittest

from core.listing_matching import match_listings, validate_need_card


NEED = {
    "transaction": "buy",
    "preferred_areas": ["中央區"],
    "budget_max": 1200,
    "budget_tolerance_pct": 10,
    "property_type": "公寓",
    "rooms_min": 2,
}


class ListingMatchingTests(unittest.TestCase):
    def test_valid_need_card(self):
        self.assertEqual(validate_need_card(NEED), ())

    def test_priority_listing_is_explainable(self):
        result = match_listings(NEED, [{
            "id": "L-001", "transaction": "buy", "area": "中央區",
            "price": 1180, "property_type": "公寓", "rooms": 2,
            "url": "https://example.test/listing/L-001",
        }])
        self.assertEqual(result["priority"][0]["listing_id"], "L-001")
        self.assertIn("preferred area", result["priority"][0]["reasons"])

    def test_over_budget_is_rejected(self):
        result = match_listings(NEED, [{
            "id": "L-002", "transaction": "buy", "area": "中央區",
            "price": 1350, "property_type": "公寓", "rooms": 3,
            "url": "https://example.test/listing/L-002",
        }])
        self.assertEqual(result["rejected"][0]["reasons"], ["over budget tolerance"])

    def test_missing_url_is_review_not_ready(self):
        result = match_listings(NEED, [{
            "id": "L-003", "transaction": "buy", "area": "中央區",
            "price": 1100, "property_type": "公寓", "rooms": 2,
        }])
        self.assertEqual(result["review"][0]["missing"], ["url"])
        self.assertFalse(result["priority"])

    def test_missing_evidence_is_review(self):
        result = match_listings(NEED, [{
            "id": "L-004", "transaction": "buy", "area": "中央區",
            "price": 1100, "rooms": 2, "url": "https://example.test/listing/L-004",
        }])
        self.assertEqual(result["review"][0]["missing"], ["property_type"])

    def test_need_card_conflict_fails_closed(self):
        with self.assertRaises(ValueError):
            match_listings({"transaction": "buy", "preferred_areas": ["中央區"]}, [])


if __name__ == "__main__":
    unittest.main()
