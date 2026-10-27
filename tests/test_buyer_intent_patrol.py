import unittest

from core.buyer_intent_patrol import classify_posts


class BuyerIntentPatrolTests(unittest.TestCase):
    def test_buyer_intent_is_review_only(self):
        result = classify_posts([{"post_id": "P-001", "text": "想找房，自住預算1500萬，請問有推薦嗎？"}])[0]
        self.assertEqual(result["category"], "buyer-intent")
        self.assertTrue(result["requires_human_review"])
        self.assertEqual(result["external_action"], "none")

    def test_agent_and_ad_are_not_buyer_leads(self):
        results = classify_posts([
            {"post_id": "P-002", "text": "我是房仲，有物件出售"},
            {"post_id": "P-003", "text": "限時優惠招商活動"},
        ])
        self.assertEqual([item["category"] for item in results], ["industry", "advertisement"])
