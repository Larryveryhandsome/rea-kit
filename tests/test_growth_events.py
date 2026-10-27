import unittest

from core.growth_events import make_event


class GrowthEventTests(unittest.TestCase):
    def test_event_has_contract(self):
        event = make_event("first_result", session_id="session-001", surface="plugin", metadata={"count": 3})
        self.assertEqual(event["event"], "first_result")
        self.assertEqual(event["metadata"]["count"], 3)
        self.assertTrue(event["occurred_at"].endswith("+00:00"))

    def test_unknown_event_fails(self):
        with self.assertRaises(ValueError):
            make_event("customer_message", session_id="session-001", surface="plugin")

    def test_sensitive_metadata_fails(self):
        with self.assertRaises(ValueError):
            make_event("sample_imported", session_id="session-001", surface="web", metadata={"address": "redacted"})


if __name__ == "__main__":
    unittest.main()
