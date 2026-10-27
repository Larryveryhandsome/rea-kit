import datetime
import io
import json
import tempfile
import unittest

from adapters.csv.customer_source import CsvCustomerSource
from adapters.line.client import LineClient
from adapters.line.fake_api import FakeLineApi, synthetic_line_id
from adapters.line.shared import SharedChannelConfig
from adapters.line.signature import sign
from adapters.storage import TenantStore
from web.line_app import create_app, LazyApplication
from web.jobs.agent_digest import build_digest
from adapters.ephemeral_listing_source import EphemeralListingSource

NEED = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_min": 800,
        "budget_max": 1500, "property_type": "公寓", "parking": "preferred", "elevator": "any"}


class CustomerIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.dt = datetime.datetime(2026, 10, 1, 9)
        self.now = lambda: self.dt
        self.customers = CsvCustomerSource(self.store, now=self.now)
        self.api = FakeLineApi().start()
        self.cfg = SharedChannelConfig("test-secret", "test-token")
        self.factory = lambda token: LineClient(token, api_base=self.api.base_url, min_interval=0)
        self.app = create_app(store=self.store, channel=self.cfg, client_factory=self.factory, now=self.now)
        self.uid = synthetic_line_id("U", "intake-test")
        self.count = 0
        self.send("綁定 " + self.app.registry.issue_code("tenant-a"))

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def send(self, text, *, eid=None, user=None):
        self.count += 1
        eid = eid or f"event-{self.count}"
        body = json.dumps({"events": [{"type": "message", "webhookEventId": eid,
            "replyToken": f"reply-{self.count}", "source": {"type": "user", "userId": user or self.uid},
            "message": {"type": "text", "text": text}}]}).encode()
        self.assertEqual(self.app.handle(body, sign("test-secret", body))[0], 200)
        return self.api.replies[-1]["messages"][0]

    def draft(self):
        for text in ["新增買方", "合成客戶甲", "買", "臺中市西屯區", "800-1500", "公寓", "2", "20-40", "20", "偏好", "不限"]:
            reply = self.send(text)
        return reply

    def test_full_click_input_confirm_then_rename(self):
        reply = self.draft()
        self.assertIn("確認儲存", reply["text"])
        self.assertEqual(self.customers.list_customers("tenant-a"), [])
        self.send("確認儲存")
        cust = self.customers.list_customers("tenant-a")[0]
        self.assertEqual(cust["need_card"]["parking"], "preferred")
        self.assertEqual(cust["need_card"]["preferred_areas"], ["台中市西屯區"])
        self.assertEqual(cust["need_card"]["budget_tolerance_pct"], 0)
        self.send(f"改名 {cust['customer_id']} 合成客戶乙")
        self.assertEqual(self.customers.get("tenant-a", cust["customer_id"])["label"], "合成客戶乙")
        self.assertEqual(self.api.pushes, [])
        self.assertFalse(self.store.path("tenant-a", "line", "messages").exists())
        self.assertFalse(self.store.path("tenant-a", "line", "events").exists())

    def test_cancel_never_creates_customer(self):
        self.draft()
        self.send("取消")
        self.send("確認儲存")
        self.assertEqual(self.customers.list_customers("tenant-a"), [])

    def test_invalid_budget_does_not_advance(self):
        for text in ["新增買方", "合成甲", "買", "台中市"]:
            self.send(text)
        self.send("1500-800")
        state = self.store.read_json("tenant-a", "line", "customer_intake.json")
        self.assertEqual(state["draft"]["step"], "budget")

    def test_draft_expires(self):
        self.draft()
        self.dt += datetime.timedelta(minutes=31)
        self.send("確認儲存")
        self.assertEqual(self.customers.list_customers("tenant-a"), [])

    def test_restart_duplicate_confirmation_not_duplicate_customer(self):
        self.draft()
        self.send("確認儲存", eid="confirm-once")
        self.app = create_app(store=self.store, channel=self.cfg, client_factory=self.factory, now=self.now)
        self.send("確認儲存", eid="confirm-once")
        self.assertEqual(len(self.customers.list_customers("tenant-a")), 1)

    def test_100_customers_pages_and_no_tenant_leak(self):
        for i in range(100):
            self.customers.save_need("tenant-a", label=f"合成客戶{i}", need=NEED)
        self.assertIn("共100組", self.send("客戶清單")["text"])
        self.assertIn("第10/10頁", self.send("客戶清單 10")["text"])
        private = self.customers.save_need("tenant-b", label="另一租戶", need=NEED)
        self.send(f"改名 {private['customer_id']} 不應成功")
        self.assertEqual(self.customers.get("tenant-b", private["customer_id"])["label"], "另一租戶")
        self.assertEqual(len(self.customers.list_customers("tenant-b")), 1)

    def test_pause_resume_and_need_edit(self):
        c = self.customers.save_need("tenant-a", label="合成甲", need=NEED)
        cid = c["customer_id"]
        self.send(f"暫停 {cid}")
        self.assertEqual(self.customers.list_customers("tenant-a"), [])
        self.send(f"恢復 {cid}")
        self.assertEqual(len(self.customers.list_customers("tenant-a")), 1)
        for text in [f"修改需求 {cid}", "租", "台北市", "15000-25000", "不限", "不限", "不限", "不限", "不限", "不限", "確認儲存"]:
            self.send(text)
        need = self.customers.get("tenant-a", cid)["need_card"]
        self.assertEqual(need["budget_max"], 25000)
        self.assertEqual(need["version"], 2)

    def test_edit_conflict_is_not_overwritten(self):
        c = self.customers.save_need("tenant-a", label="合成甲", need=NEED)
        with self.assertRaises(ValueError):
            self.customers.save_need("tenant-a", label="合成乙", need=NEED, customer_id=c["customer_id"], expected_version=0)

    def test_unknown_person_cannot_create_customer(self):
        other = synthetic_line_id("U", "not-bound")
        self.send("新增買方", user=other)
        self.assertEqual(self.customers.list_customers("tenant-a"), [])

    def test_no_source_is_reported_honestly(self):
        self.assertIn("尚未接通", self.send("新案")["text"])

    def test_end_to_end_demo_is_executable(self):
        from tools.demo_line_intake import main
        self.assertEqual(main(), 0)

    def test_quick_reply_limit(self):
        self.send("新增買方")
        for text in ["合成甲", "買", "台中市"]:
            self.send(text)
        reply = self.send("1000")
        self.assertEqual(len(reply["quickReply"]["items"]), 13)

    def test_weekly_memory_match_identifies_customer_without_listing_db(self):
        c = self.customers.save_need("tenant-a", label="合成甲", need=NEED)
        source = EphemeralListingSource("tenant-a", [{"id": "Ab-C", "transaction": "buy",
            "area": "台中市西屯區", "price": 1200, "property_type": "公寓", "rooms": 2,
            "url": "https://example.test/a", "listed_at": "2026-10-01"}], today=self.dt.date())
        digest = build_digest(tenant_id="tenant-a", listings=source, customers=self.customers, identify_customers=True)
        self.assertEqual(digest[0][1], [c["customer_id"] + "｜合成甲"])
        self.assertFalse(self.store.path("tenant-a", "listings").exists())

    def test_health_never_creates_line_client(self):
        app = LazyApplication()
        status = []
        self.assertEqual(app({"PATH_INFO": "/healthz", "REQUEST_METHOD": "GET"}, lambda s, h: status.append(s)), [b"ok"])
        self.assertIsNone(app.app)

    def test_malformed_payload_and_negative_length_rejected(self):
        raw = b"[]"
        self.assertEqual(self.app.handle(raw, sign("test-secret", raw))[0], 400)
        status = []
        self.app.wsgi({"PATH_INFO": "/line-shared/webhook", "REQUEST_METHOD": "POST", "CONTENT_LENGTH": "-1",
                       "wsgi.input": io.BytesIO()}, lambda s, h: status.append(s))
        self.assertEqual(status, ["400 Bad Request"])
