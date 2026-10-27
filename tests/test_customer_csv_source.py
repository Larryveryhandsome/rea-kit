import unittest

from adapters.customer_csv_source import active_need_cards, load_csv, normalize_need_card

CSV = """customer_id,transaction,preferred_areas,budget_max,updated_at,property_type,rooms_min,consent_status
C-001,buy,中央區;東區,1500,2026-10-01,apartment,2,tenant-confirmed
C-002,rent,北區,30,2026-10-01,apartment,1,revoked
"""


class CustomerCsvSourceTests(unittest.TestCase):
    def test_loads_need_cards_without_message_content(self):
        cards = load_csv(CSV, source="fixture")
        self.assertEqual(cards[0]["preferred_areas"], ["中央區", "東區"])
        self.assertEqual(cards[0]["source"], "fixture")
        self.assertNotIn("message", cards[0])

    def test_revoked_cards_are_excluded(self):
        cards = load_csv(CSV)
        self.assertEqual([card["customer_id"] for card in active_need_cards(cards)], ["C-001"])

    def test_invalid_transaction_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_need_card({"customer_id": "C-003", "transaction": "swap",
                                 "preferred_areas": "中央區", "budget_max": "1000",
                                 "updated_at": "2026-10-01"})
