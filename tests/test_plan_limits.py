import unittest
from datetime import datetime, timedelta, timezone

from core.plan_limits import FREE_MONITOR_DAYS, FREE_PAIRING_LIMIT, FreePlanUsage


class PlanLimitTests(unittest.TestCase):
    def test_unique_pairings_have_one_hundred_free(self):
        usage = FreePlanUsage()
        for index in range(FREE_PAIRING_LIMIT):
            self.assertTrue(usage.record_pairing(f"L-{index}"))
        self.assertFalse(usage.record_pairing("L-over"))

    def test_repeating_same_listing_does_not_consume_again(self):
        usage = FreePlanUsage()
        self.assertTrue(usage.record_pairing("L-001"))
        for index in range(FREE_PAIRING_LIMIT):
            usage.record_pairing(f"L-{index + 100}")
        self.assertTrue(usage.can_pair("L-001"))

    def test_monitor_is_free_for_seven_days(self):
        started = datetime(2026, 10, 1, tzinfo=timezone.utc)
        usage = FreePlanUsage()
        usage.start_monitor(now=started)
        self.assertTrue(usage.monitor_active(now=started + timedelta(days=FREE_MONITOR_DAYS) - timedelta(seconds=1)))
        self.assertFalse(usage.monitor_active(now=started + timedelta(days=FREE_MONITOR_DAYS)))

    def test_usage_round_trips(self):
        started = datetime(2026, 10, 1, tzinfo=timezone.utc)
        restored = FreePlanUsage.from_mapping(FreePlanUsage({"L-002"}, started).to_mapping())
        self.assertEqual(restored.pairing_listing_ids, {"L-002"})
        self.assertEqual(restored.monitor_started_at, started)
