"""共用通知帳號（adapters/line/shared）＋給仲介的新案摘要（web/jobs/agent_digest）。本機假 LINE、合成資料。"""
import datetime
import io
import json
import pathlib
import tempfile
import unittest

from adapters.csv.customer_source import CsvCustomerSource
from adapters.csv.listing_source import CsvListingSource
from adapters.line import flex
from adapters.line.client import LineClient
from adapters.line.credentials import MemoryCredentialStore
from adapters.line.fake_api import FakeLineApi, synthetic_line_id
from adapters.line.shared import SYS_TENANT, BindingRegistry, SharedChannelConfig, SharedLineApp
from adapters.line.signature import sign
from adapters.line.webhook import WebhookApp
from adapters.storage import TenantStore

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
AGENT1 = synthetic_line_id("U", "agent-1")
AGENT2 = synthetic_line_id("U", "agent-2")
GROUP = synthetic_line_id("C", "some-customer-group")
SECRET = "shared-secret"

try:
    from web.jobs.agent_digest import build_digest, make_reply_handler, run_agent_digest
    from web.jobs.new_listing_push import load_matcher
    load_matcher()
    HAVE_CORE = True
except RuntimeError:
    HAVE_CORE = False


class Clock:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return self.dt


def text(t, user, eid, token=None):
    return {"type": "message", "webhookEventId": eid, "replyToken": token or "rt-" + eid, "timestamp": 1,
            "source": {"type": "user", "userId": user}, "message": {"type": "text", "id": eid, "text": t}}


class SharedChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.clock = Clock(datetime.datetime(2026, 10, 1, 9, 0))
        self.api = FakeLineApi().start()
        self.channel = SharedChannelConfig(SECRET, "test-token", plan_cap=200, per_agent_monthly=30)
        self.app = self.make_app(self.channel)

    def make_app(self, channel, handlers=()):
        return SharedLineApp(self.store, channel, client_factory=lambda tok: LineClient(
            tok, api_base=self.api.base_url, min_interval=0, sleep=lambda s: None), handlers=handlers, now=self.clock)

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def post(self, *events, secret=SECRET, app=None):
        body = json.dumps({"events": list(events)}).encode("utf-8")
        return (app or self.app).handle(body, sign(secret, body))

    def last_reply(self):
        return self.api.replies[-1]["messages"][0].get("text", "")

    def bind(self, tenant, user, eid):
        code = self.app.registry.issue_code(tenant)
        self.post(text(f"綁定 {code}", user, eid))
        return code

    def test_bad_signature(self):
        self.assertEqual(self.post(text("hi", AGENT1, "x"), secret="wrong")[0], 403)

    def test_follow_and_unbound_message_get_onboarding_and_nothing_is_logged(self):
        self.post({"type": "follow", "webhookEventId": "f1", "replyToken": "rt-f1", "timestamp": 1,
                   "source": {"type": "user", "userId": AGENT1}})
        welcome = self.api.replies[-1]["messages"][0]
        self.assertEqual(welcome["type"], "flex")
        self.assertIn("同意並開始", json.dumps(welcome, ensure_ascii=False))       # 2026-10-04 開放：不用綁定碼
        self.post(text("你好", AGENT1, "m1"))
        self.assertIn("同意並開始", json.dumps(self.api.replies[-1]["messages"][0], ensure_ascii=False))
        self.assertFalse((pathlib.Path(self.tmp.name) / "tenants" / "t1").exists())
        self.assertIsNone(self.app.registry.tenant_of(AGENT1))                   # 沒按同意之前什麼都不建

    def test_bind_flow_single_use_and_tenant_logging(self):
        code = self.bind("t1", AGENT1, "b1")
        self.assertIn("綁定完成", self.last_reply())
        self.assertEqual(self.app.registry.tenant_of(AGENT1), "t1")
        self.assertEqual(self.app.registry.user_of("t1"), AGENT1)
        self.post(text(f"綁定 {code}", AGENT2, "b2"))                  # 同一組碼不能再用
        self.assertIn("不對或已過期", self.last_reply())
        self.post(text("測試", AGENT1, "m2"))
        self.assertIn("收到", self.last_reply())
        msgs = self.store.read_jsonl("t1", "line", "messages", AGENT1 + ".jsonl")
        self.assertEqual([m["text"] for m in msgs], ["測試"])
        self.assertNotIn(AGENT1, json.dumps(self.store.read_jsonl(SYS_TENANT, "audit.jsonl")))

    def test_unbound_can_type_bare_digits_and_gets_card_after_binding(self):
        code = self.app.registry.issue_code("t1")
        self.post(text(code, AGENT1, "bare1"))
        msgs = self.api.replies[-1]["messages"]
        self.assertIn("綁定完成", msgs[0]["text"])
        self.assertEqual(msgs[1]["type"], "flex")                      # 綁好立刻附上歡迎卡，不用再打「開始」
        self.assertEqual(self.app.registry.tenant_of(AGENT1), "t1")
        other = self.app.registry.issue_code("t2")
        self.post(text(other, AGENT1, "bare2"))                         # 已綁定的人打 6 位數不會被當成換綁
        self.assertEqual(self.app.registry.tenant_of(AGENT1), "t1")
        self.post(text("123456", AGENT2, "bare3"))                      # 錯的碼照樣受「每小時 5 次」限制
        self.assertIn("不對或已過期", self.last_reply())

    def test_code_expires_and_brute_force_is_throttled(self):
        code = self.app.registry.issue_code("t1")
        self.clock.dt += datetime.timedelta(minutes=16)
        self.post(text(f"綁定 {code}", AGENT1, "e1"))
        self.assertIn("過期", self.last_reply())
        for i in range(5):
            self.post(text("綁定 000000", AGENT2, f"bf{i}"))
        good = self.app.registry.issue_code("t2")
        self.post(text(f"綁定 {good}", AGENT2, "bf-good"))
        self.assertIn("錯太多次", self.last_reply())
        self.assertIsNone(self.app.registry.tenant_of(AGENT2))

    def test_rebinding_moves_line_account_and_unbind(self):
        self.bind("t1", AGENT1, "r1")
        self.bind("t1", AGENT2, "r2")                                  # 同租戶換 LINE 帳號
        self.assertIsNone(self.app.registry.tenant_of(AGENT1))
        self.assertEqual(self.app.registry.user_of("t1"), AGENT2)
        self.post(text("解除綁定", AGENT2, "u1"))
        self.assertIsNone(self.app.registry.user_of("t1"))

    def test_invited_into_group_says_bye_leaves_and_logs_nothing(self):
        self.bind("t1", AGENT1, "g0")
        self.post({"type": "join", "webhookEventId": "j1", "replyToken": "rt-j1", "timestamp": 1,
                   "source": {"type": "group", "groupId": GROUP}})
        self.assertIn("離開群組", self.last_reply())
        self.assertEqual(self.api.leaves, [GROUP])
        self.post({"type": "message", "webhookEventId": "gm", "replyToken": "rt-gm", "timestamp": 2,
                   "source": {"type": "group", "groupId": GROUP, "userId": AGENT1},
                   "message": {"type": "text", "id": "gm", "text": "客人想買三房"}})
        self.assertEqual(self.store.read_jsonl("t1", "line", "messages", GROUP + ".jsonl"), [])

    def test_notify_goes_to_agent_only_with_fair_share_and_repay_by_reply(self):
        app = self.make_app(SharedChannelConfig(SECRET, "test-token", plan_cap=200, per_agent_monthly=1))
        code = app.registry.issue_code("t1")
        self.post(text(f"綁定 {code}", AGENT1, "n0"), app=app)
        card = [flex.flex_message("新案", flex.listing_bubble(
            {"area": "示範市中央區", "title": "合成物件", "price": 1180, "transaction": "buy",
             "url": "https://example.test/l/1"}, for_customers=["合成客戶甲"], share=True))]
        self.assertEqual(app.notify("t1", card).state, "sent")
        self.assertEqual(self.api.pushes[-1]["to"], AGENT1)
        self.clock.dt += datetime.timedelta(days=1)
        self.assertEqual(app.notify("t1", card).state, "deferred")       # 這個月的份額 1 則用完
        self.assertEqual(app.notify("t2", card).state, "skipped")         # t2 沒綁定
        self.post(text("在嗎", AGENT1, "n1", token="rt-owed"), app=app)
        owed = [r for r in self.api.replies if r["replyToken"] == "rt-owed"]
        self.assertEqual(owed[0]["messages"][0]["type"], "flex")         # 欠的那則用回覆補上
        ledger = self.store.read_json(SYS_TENANT, "line", "push_ledger.json")
        self.assertNotIn(AGENT1, json.dumps(ledger))
        self.post(text("額度", AGENT1, "n2"), app=app)
        self.assertIn("1/1", self.last_reply())

    def test_channel_plan_cap_is_shared_by_all_agents(self):
        app = self.make_app(SharedChannelConfig(SECRET, "test-token", plan_cap=1, per_agent_monthly=1))
        for t, u, e in (("t1", AGENT1, "c1"), ("t2", AGENT2, "c2")):
            self.post(text(f"綁定 {app.registry.issue_code(t)}", u, e), app=app)
        msg = [{"type": "text", "text": "今天有新案"}]
        self.assertEqual(app.notify("t1", msg).state, "sent")
        self.assertEqual(app.notify("t2", msg).state, "deferred")

    def test_unbind_tenant_on_account_deletion(self):
        self.bind("t1", AGENT1, "d1")
        self.app.registry.unbind_tenant("t1")
        self.store.delete_tenant("t1")
        self.assertIsNone(self.app.registry.tenant_of(AGENT1))

    def test_reserved_partition_cannot_be_reached_as_tenant(self):
        app = WebhookApp(MemoryCredentialStore(), self.store)
        self.assertEqual(app.handle(SYS_TENANT, b"{}", "x")[0], 404)
        with self.assertRaises(ValueError):
            self.app.registry.issue_code(SYS_TENANT)

    def test_wsgi_path(self):
        body = json.dumps({"events": []}).encode()
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/line-shared/webhook", "CONTENT_LENGTH": str(len(body)),
               "wsgi.input": io.BytesIO(body), "HTTP_X_LINE_SIGNATURE": sign(SECRET, body)}
        status = {}
        self.app.wsgi(env, lambda s, h: status.setdefault("s", s))
        self.assertEqual(status["s"], "200 OK")


@unittest.skipUnless(HAVE_CORE, "core.listing_matching 尚未進版")
class AgentDigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.now = lambda: datetime.datetime(2026, 10, 1, 9, 0)
        self.api = FakeLineApi().start()
        self.listings = CsvListingSource(self.store, now=self.now)
        self.customers = CsvCustomerSource(self.store, now=self.now)
        self.listings.import_csv("t1", (FIX / "listings_synthetic.csv").read_bytes())
        self.customers.import_customers("t1", (FIX / "customers_synthetic.csv").read_bytes(), default_city="示範市")
        handler = make_reply_handler(self.listings, self.customers)
        self.app = SharedLineApp(self.store, SharedChannelConfig(SECRET, "test-token"), handlers=[handler],
                                 client_factory=lambda tok: LineClient(tok, api_base=self.api.base_url,
                                                                       min_interval=0), now=self.now)
        code = self.app.registry.issue_code("t1")
        body = json.dumps({"events": [text(f"綁定 {code}", AGENT1, "b")]}).encode()
        self.app.handle(body, sign(SECRET, body))

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def test_digest_groups_customers_per_listing_without_needing_customer_line_ids(self):
        items = build_digest(tenant_id="t1", listings=self.listings, customers=self.customers)
        got = {x["id"]: names for x, names in items}
        self.assertEqual(got["S-101"], ["合成客戶甲"])
        self.assertEqual(got["S-106"], ["合成客戶甲"])
        self.assertEqual(got["R-201"], ["合成客戶丙"])
        self.assertNotIn("S-104", got)            # 已成交
        self.assertNotIn("S-105", got)            # 沒連結，不能分享

    def test_scheduled_digest_notifies_agent_once_with_share_buttons(self):
        res = run_agent_digest(tenant_id="t1", store=self.store, listings=self.listings, customers=self.customers,
                               notify=self.app.notify, now=self.now)
        self.assertEqual(res["state"], "sent")
        push = self.api.pushes[-1]
        self.assertEqual(push["to"], AGENT1)
        msg = push["messages"][0]
        self.assertEqual(flex.validate_message(msg), [])
        blob = json.dumps(msg, ensure_ascii=False)
        self.assertIn("分享給客戶", blob)
        self.assertIn("適合：合成客戶甲", blob)
        self.assertIn("line.me/R/msg/text/", blob)
        shown_text = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "text":
                    shown_text.append(node["text"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(msg["contents"])
        self.assertFalse([t for t in shown_text if "S-1" in t or "R-2" in t])   # 卡面文字不露內部編號
        self.assertIn("示範市中央區", shown_text)                              # 區域已含縣市，不重複寫
        again = run_agent_digest(tenant_id="t1", store=self.store, listings=self.listings,
                                 customers=self.customers, notify=self.app.notify, now=self.now)
        self.assertEqual(again["state"], "nothing")

    def test_agent_asks_new_listings_and_gets_free_reply(self):
        body = json.dumps({"events": [text("新案", AGENT1, "ask", token="rt-ask")]}).encode()
        self.app.handle(body, sign(SECRET, body))
        r = [x for x in self.api.replies if x["replyToken"] == "rt-ask"][0]
        self.assertEqual(r["messages"][0]["type"], "flex")
        self.assertEqual(self.api.pushes, [])                           # 沒動到推播額度


if __name__ == "__main__":
    unittest.main()
