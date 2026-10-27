import datetime
import unittest
from unittest.mock import patch

from adapters.public_page_collector import CollectionStopped, fetch_public_page
from adapters.public_source_registry import load_registry, runnable_sources
from adapters.ephemeral_listing_source import EphemeralListingSource
from core.listing_diff import diff_listings
from core.listing_matching import match_listings, validate_need_card
from pathlib import Path

NEED = {"transaction": "buy", "preferred_areas": ["臺中市"], "budget_max": 1500, "property_type": "公寓"}
ROW = {"id": "Ab-C", "transaction": "buy", "area": "台中市西屯區", "price": 1200,
       "property_type": "apartment", "rooms": 2, "url": "https://example.test/a", "listed_at": "2026-10-01"}


class HandoffRegressions(unittest.TestCase):
    def test_city_alias_type_and_identity(self):
        self.assertEqual(match_listings(NEED, [ROW])["priority"][0]["listing_id"], "Ab-C")

    def test_no_cross_city_district_match(self):
        self.assertTrue(match_listings({**NEED, "preferred_areas": ["台北市中正區"]}, [ROW])["rejected"])

    def test_nonfinite_and_negative_budget_rejected(self):
        for value in [float("nan"), float("inf"), -1, 0, True]:
            self.assertTrue(validate_need_card({**NEED, "budget_max": value}))

    def test_unknown_feature_not_guessed(self):
        self.assertEqual(match_listings({**NEED, "parking": "required"}, [ROW])["review"][0]["missing"], ["parking"])

    def test_false_required_rejected_but_preference_not_exclusion(self):
        row = {**ROW, "parking": False}
        self.assertTrue(match_listings({**NEED, "parking": "required"}, [row])["rejected"])
        self.assertTrue(match_listings({**NEED, "parking": "preferred"}, [row])["priority"])

    def test_size_age_and_budget_lower_bound(self):
        for need, row in [({"size_min": 30}, {"size_ping": 20}), ({"age_max": 10}, {"age_years": 15}),
                          ({"budget_min": 1300}, {})]:
            self.assertTrue(match_listings({**NEED, **need}, [{**ROW, **row}])["rejected"])

    def test_id_and_transaction_missing_go_to_review(self):
        row = {**ROW, "id": None, "transaction": None}
        self.assertEqual(match_listings(NEED, [row])["review"][0]["missing"], ["id", "transaction"])

    def test_timestamp_only_change_is_not_an_alert(self):
        self.assertEqual(len(diff_listings([ROW], [{**ROW, "listed_at": "2026-10-02"}]).unchanged), 1)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            diff_listings([], [ROW, ROW])

    def test_no_network_can_be_enabled_by_registry(self):
        with patch("urllib.request.urlopen") as network:
            with self.assertRaises(CollectionStopped):
                fetch_public_page("https://example.test/a")
            network.assert_not_called()
        self.assertEqual(runnable_sources([{"status": "verified"}]), [])
        rows = load_registry(Path(__file__).resolve().parents[1] / "sources/public_sources.json")
        self.assertFalse([r for r in rows if r["status"] == "verified"])

    def test_seven_days_does_not_use_first_seen(self):
        rows = [ROW, {**ROW, "id": "boundary", "listed_at": "2026-09-25"},
                {**ROW, "id": "old", "listed_at": "2026-09-24"},
                {**ROW, "id": "future", "listed_at": "2026-10-02"},
                {**ROW, "id": "unknown", "listed_at": None, "first_seen": "2026-10-01"}]
        source = EphemeralListingSource("t1", rows, today=datetime.date(2026, 10, 1))
        self.assertEqual([r["id"] for r in source.list_active("t1")], ["Ab-C", "boundary"])
        self.assertEqual(source.list_active("t2"), [])
