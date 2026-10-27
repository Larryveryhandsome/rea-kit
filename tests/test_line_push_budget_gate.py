"""adapters/line：推播預算、推播閘、Flex、API 出口（全部打本機假 LINE，合成資料）。"""
import datetime
import tempfile
import unittest

from adapters.line import flex
from adapters.line.client import LineClient
from adapters.line.credentials import TenantLineConfig
from adapters.line.fake_api import FakeLineApi, synthetic_line_id
from adapters.line.push_budget import BudgetPolicy, PushBudget, cost_of
from adapters.line.push_gate import GatePolicy, PushGate, template_key
from adapters.storage import TenantStore

OWNER = synthetic_line_id("U", "owner")
CUSTOMER_GROUP = synthetic_line_id("C", "customer-group-1")
INTERNAL_GROUP = synthetic_line_id("C", "internal-group")


class Clock:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return self.dt


def listing(i=1, **kw):
    base = {"id": f"L-{i:03d}", "transaction": "buy", "city": "示範市", "area": "中央區",
            "title": f"合成物件 {i}", "price": 1180, "property_type": "電梯大樓", "rooms": 3,
            "size_ping": 32.5, "age_years": 8, "url": f"https://example.test/listing/{i}",
            "photo_url": f"https://example.test/photo/{i}.jpg"}
    base.update(kw)
    return base


class FlexTests(unittest.TestCase):
    def test_listing_card_has_no_internal_id_and_passes_validation(self):
        msg = flex.listing_message([listing(1), listing(2, photo_url=None)])
        self.assertEqual(flex.validate_message(msg), [])
        self.assertNotIn("L-001", str(msg["contents"]))
        self.assertEqual(msg["contents"]["type"], "carousel")
        self.assertIn("1,180 萬", str(msg))

    def test_rent_price_unit(self):
        self.assertEqual(flex.format_price({"transaction": "rent", "price": 18000}), "18,000 元/月")

    def test_listing_without_link_cannot_become_customer_card(self):
        with self.assertRaises(ValueError):
            flex.listing_bubble(listing(url=""))

    def test_non_https_photo_falls_back_to_block(self):
        b = flex.listing_bubble(listing(photo_url="http://example.test/p.jpg"))
        self.assertEqual(b["hero"]["type"], "box")

    def test_validate_catches_bad_uri_and_long_alt(self):
        bad = flex.flex_message("x", flex.listing_bubble(listing()))
        bad["altText"] = "長" * 401
        bad["contents"]["footer"]["contents"][0]["action"]["uri"] = "javascript:alert(1)"
        errs = flex.validate_message(bad)
        self.assertTrue(any("altText" in e for e in errs))
        self.assertTrue(any("http" in e for e in errs))

    def test_postback_roundtrip(self):
        self.assertEqual(flex.parse_postback(flex.postback_data("approve", "1001-abc")),
                         {"gate": "approve", "id": "1001-abc"})


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.clock = Clock(datetime.datetime(2026, 10, 1, 10, 0))

    def tearDown(self):
        self.tmp.cleanup()

    def budget(self, **policy):
        return PushBudget(self.store, "t1", BudgetPolicy.from_dict(policy), now=self.clock)

    def test_group_cost_is_per_recipient(self):
        self.assertEqual(cost_of(OWNER, None, 3), 1)
        self.assertEqual(cost_of(CUSTOMER_GROUP, 5, 3), 5)
        self.assertEqual(cost_of(CUSTOMER_GROUP, None, 3), 3)

    def test_default_policy_fits_free_plan(self):
        p = BudgetPolicy()
        self.assertEqual(p.plan_cap, 200)
        self.assertEqual(p.validate(), [])

    def test_policy_over_plan_is_rejected(self):
        with self.assertRaises(ValueError):
            self.budget(level_quota={"match": 500})

    def test_zero_quota_level_is_structural(self):
        d = self.budget().check("internal", INTERNAL_GROUP, 3)
        self.assertFalse(d.ok)
        self.assertTrue(d.zero_quota)

    def test_control_reserve_cannot_be_eaten_by_customer_pushes(self):
        b = self.budget(plan_cap=10, control_reserve=4, level_quota={"match": 6, "greeting": 0, "announce": 0},
                        recipient_daily={"match": 99})
        b.charge("match", CUSTOMER_GROUP, 6)
        self.assertFalse(b.check("match", CUSTOMER_GROUP, 1).ok)
        self.assertTrue(b.check("owner", OWNER, 1).ok)

    def test_control_daily_breaker_and_month_rollover(self):
        b = self.budget()
        for _ in range(3):
            b.charge("owner", OWNER, 1)
        self.assertFalse(b.check("owner", OWNER, 1).ok)
        self.clock.dt = datetime.datetime(2026, 10, 2, 9, 0)
        self.assertTrue(b.check("owner", OWNER, 1).ok)
        self.clock.dt = datetime.datetime(2026, 11, 1, 9, 0)
        self.assertEqual(b.summary()["used"], 0)

    def test_one_match_push_per_recipient_per_day(self):
        b = self.budget()
        b.charge("match", CUSTOMER_GROUP, 3)
        self.assertFalse(b.check("match", CUSTOMER_GROUP, 3).ok)
        self.assertTrue(b.check("match", synthetic_line_id("C", "other"), 3).ok)

    def test_ledger_does_not_store_raw_line_ids(self):
        self.budget().charge("match", CUSTOMER_GROUP, 3)
        raw = (self.store.path("t1", "line", "push_ledger.json")).read_text(encoding="utf-8")
        self.assertNotIn(CUSTOMER_GROUP, raw)

    def test_failed_send_is_not_charged(self):
        b = self.budget()

        class R:
            ok = False
        b.guarded_send("match", CUSTOMER_GROUP, 3, lambda: R())
        self.assertEqual(b.summary()["used"], 0)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.clock = Clock(datetime.datetime(2026, 10, 1, 10, 0))
        self.api = FakeLineApi(member_counts={CUSTOMER_GROUP: 3}).start()
        self.cfg = TenantLineConfig("t1", "secret", "test-token", owner_user_id=OWNER)
        self.client = LineClient("test-token", api_base=self.api.base_url, min_interval=0, sleep=lambda s: None)

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def gate(self, modes=None, budget_policy=None):
        budget = PushBudget(self.store, "t1", BudgetPolicy.from_dict(budget_policy), now=self.clock)
        return PushGate(self.store, self.cfg, self.client, budget,
                        GatePolicy.from_dict({"modes": modes or {}}), now=self.clock)

    def card(self, i=1):
        return [flex.listing_message([listing(i)])]

    def test_customer_push_is_held_and_review_card_goes_to_owner(self):
        g = self.gate()
        res = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match", recipient_label="王先生群")
        self.assertEqual(res.state, "held")
        self.assertEqual(len(self.api.pushes), 1)
        self.assertEqual(self.api.pushes[0]["to"], OWNER)
        self.assertEqual(len(self.api.pushes[0]["messages"]), 2)       # 預覽＋審核卡，同一則計費
        self.assertEqual(g.budget.summary()["levels"]["review"]["used_today"], 1)

    def test_duplicate_submit_does_not_queue_twice(self):
        g = self.gate()
        first = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match", dedup_key="cust1|L-001")
        again = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match", dedup_key="cust1|L-001")
        self.assertEqual(again.state, "duplicate")
        self.assertEqual(again.item_id, first.item_id)

    def test_only_owner_can_approve(self):
        g = self.gate()
        res = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match")
        stranger = synthetic_line_id("U", "stranger")
        self.assertEqual(g.approve(res.item_id, actor=stranger).state, "refused")
        ok = g.approve(res.item_id, actor=OWNER)
        self.assertEqual(ok.state, "sent")
        self.assertEqual(self.api.pushes[-1]["to"], CUSTOMER_GROUP)
        self.assertEqual(g.budget.summary()["levels"]["match"]["used_month"], 3)   # 3 人群組
        self.assertEqual(g.approve(res.item_id, actor=OWNER).state, "sent")         # 第二次按不重送
        self.assertEqual(len([p for p in self.api.pushes if p["to"] == CUSTOMER_GROUP]), 1)

    def test_reject(self):
        g = self.gate()
        res = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match")
        self.assertEqual(g.reject(res.item_id, actor=OWNER).state, "rejected")
        self.assertEqual(g.pending(), [])
        again = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match")       # 同一則再送一次
        self.assertEqual(again.state, "skipped")                                   # 按過不送 → 永遠不再送
        self.assertIn("按過不送", again.reason)

    def test_match_review_expires_after_24_hours(self):
        g = self.gate()
        res = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match")
        self.clock.dt = datetime.datetime(2026, 10, 2, 9, 59)
        self.assertEqual(g.expire_stale(), [])                                     # 23 小時 59 分：還在
        self.clock.dt = datetime.datetime(2026, 10, 2, 10, 0)
        self.assertEqual(g.expire_stale(), [res.item_id])                          # 滿 24 小時：作廢

    def test_owner_messages_skip_review(self):
        g = self.gate()
        res = g.submit(to=OWNER, messages=[{"type": "text", "text": "今天有 2 件新案"}], level="owner")
        self.assertEqual(res.state, "sent")

    def test_zero_quota_level_is_not_queued(self):
        g = self.gate()
        res = g.submit(to=INTERNAL_GROUP, messages=[{"type": "text", "text": "內部日報"}], level="internal")
        self.assertEqual(res.state, "skipped")
        self.assertEqual(g.pending(), [])
        self.assertEqual(self.api.pushes, [])

    def test_template_always_then_auto(self):
        g = self.gate()
        msg = lambda n: [{"type": "text", "text": f"週二問候：本週有 {n} 件新上架，有需要跟我說"}]
        first = g.submit(to=CUSTOMER_GROUP, messages=msg(3), level="greeting")
        self.assertEqual(first.state, "held")
        self.assertEqual(g.approve(first.item_id, actor=OWNER, always=True).state, "sent")
        self.clock.dt = datetime.datetime(2026, 10, 8, 10, 0)
        second = g.submit(to=CUSTOMER_GROUP, messages=msg(5), level="greeting")
        self.assertEqual(second.state, "sent")
        self.assertEqual(template_key(CUSTOMER_GROUP, msg(3)), template_key(CUSTOMER_GROUP, msg(5)))

    def test_match_mode_auto_sends_without_review(self):
        g = self.gate(modes={"match": "auto"})
        self.assertEqual(g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match").state, "sent")

    def test_quota_exhausted_defers_then_repaid_by_reply(self):
        g = self.gate(modes={"match": "auto"})
        self.api.quota_exhausted = True
        res = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match")
        self.assertEqual(res.state, "deferred")
        self.assertEqual(g.budget.summary()["used"], 0)
        owed = g.take_for_reply(CUSTOMER_GROUP)
        self.assertEqual(len(owed), 1)
        self.assertEqual(g.get(res.item_id)["state"], "sent_by_reply")
        self.assertEqual(g.take_for_reply(CUSTOMER_GROUP), [])

    def test_retry_deferred_after_quota_recovers(self):
        g = self.gate(modes={"match": "auto"})
        self.api.quota_exhausted = True
        res = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match")
        self.api.quota_exhausted = False
        out = g.retry_deferred()
        self.assertEqual([r.state for r in out], ["sent"])
        self.assertEqual(g.get(res.item_id)["state"], "sent")

    def test_stale_review_items_expire(self):
        g = self.gate()
        res = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match")
        self.clock.dt = datetime.datetime(2026, 10, 5, 10, 0)
        self.assertEqual(g.expire_stale(), [res.item_id])
        self.assertEqual(g.get(res.item_id)["state"], "expired")

    def test_review_card_falls_back_when_review_budget_is_out(self):
        g = self.gate(budget_policy={"control_daily": {"review": 0}})
        res = g.submit(to=CUSTOMER_GROUP, messages=self.card(), level="match")
        self.assertEqual(res.state, "held")
        self.assertIn("待審", res.reason)
        self.assertEqual(len(g.review_messages()), 1)

    def test_invalid_message_is_refused_before_queueing(self):
        g = self.gate()
        res = g.submit(to=CUSTOMER_GROUP, messages=[{"type": "text", "text": "  "}], level="match")
        self.assertEqual(res.state, "failed")


class ClientTests(unittest.TestCase):
    def test_rejects_non_local_http_base(self):
        with self.assertRaises(ValueError):
            LineClient("tok", api_base="http://example.test")

    def test_wrong_token_is_reported(self):
        with FakeLineApi(token="right") as api:
            c = LineClient("wrong", api_base=api.base_url, min_interval=0, max_tries=1)
            res = c.push(OWNER, [{"type": "text", "text": "hi"}])
            self.assertFalse(res.ok)
            self.assertEqual(res.status, 401)

    def test_wrong_token_is_reported_when_body_arrives_late(self):
        # 假 API 若先回 401 才讀 body，晚到的 body 會讓連線被 RST，客戶端拿到 0 而不是 401
        import http.client
        import time
        from unittest import mock
        send = http.client.HTTPConnection.send

        def late_body(conn, data):
            if not data.startswith(b"POST"):
                time.sleep(0.05)
            return send(conn, data)
        with FakeLineApi(token="right") as api, mock.patch.object(http.client.HTTPConnection, "send", late_body):
            c = LineClient("wrong", api_base=api.base_url, min_interval=0, max_tries=1)
            self.assertEqual(c.push(OWNER, [{"type": "text", "text": "hi"}]).status, 401)

    def test_bad_recipient_id_is_not_sent(self):
        with FakeLineApi() as api:
            c = LineClient("test-token", api_base=api.base_url, min_interval=0)
            self.assertFalse(c.push("not-an-id", [{"type": "text", "text": "hi"}]).ok)
            self.assertEqual(api.pushes, [])

    def test_same_retry_key_is_idempotent(self):
        with FakeLineApi() as api:
            c = LineClient("test-token", api_base=api.base_url, min_interval=0)
            self.assertTrue(c.push(OWNER, [{"type": "text", "text": "hi"}], retry_key="k1").ok)
            self.assertTrue(c.push(OWNER, [{"type": "text", "text": "hi"}], retry_key="k1").ok)
            self.assertEqual(len(api.pushes), 1)


if __name__ == "__main__":
    unittest.main()


class SourceLessonGateTests(unittest.TestCase):
    """實務規則（2026-10-02 移植）：物件推播待審 24 小時作廢、按過不送永不再送、每位客戶每月 4 則。"""

    def setUp(self):
        import tempfile
        from adapters.line.push_budget import BudgetPolicy, PushBudget
        from adapters.line.shared import SharedChannelConfig
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.dt = datetime.datetime(2026, 10, 2, 9)
        self.BudgetPolicy, self.PushBudget, self.Shared = BudgetPolicy, PushBudget, SharedChannelConfig

    def tearDown(self):
        self.tmp.cleanup()

    def test_customer_monthly_cap_four(self):
        b = self.PushBudget(self.store, "t1", self.BudgetPolicy(), now=lambda: self.dt)
        to = "C" + "a" * 32
        for day in range(4):
            self.dt = datetime.datetime(2026, 10, 2 + day, 9)
            self.assertTrue(b.check("match", to, 1).ok)
            b.charge("match", to, 1)
        self.dt = datetime.datetime(2026, 10, 9, 9)
        dec = b.check("match", to, 1)
        self.assertFalse(dec.ok)
        self.assertIn("每月上限", dec.reason)
        self.dt = datetime.datetime(2026, 11, 1, 9)
        self.assertTrue(b.check("match", to, 1).ok)                      # 跨月重置

    def test_shared_account_agent_digest_not_capped_monthly(self):
        policy = self.Shared("s", "t").budget_policy()
        self.assertEqual(policy.recipient_monthly, {})
