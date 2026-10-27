"""審查者補的回歸測試（2026-10-01，commit 7d180b8）：共用 LINE 入口的租戶隔離與不落原始對話。全合成。"""
import datetime
import json
import pathlib
import tempfile
import unittest

from adapters.csv.customer_source import CsvCustomerSource
from adapters.line.client import LineClient
from adapters.line.fake_api import FakeLineApi, synthetic_line_id
from adapters.line.shared import SYS_TENANT, SharedChannelConfig
from adapters.line.signature import sign
from adapters.storage import TenantStore
from web.line_app import create_app

A = synthetic_line_id("U", "review-agent-a")
B = synthetic_line_id("U", "review-agent-b")
STRANGER = synthetic_line_id("U", "review-stranger")
GROUP = synthetic_line_id("C", "review-group")
FLOW = ["新增買方", "合成甲", "買", "台中市西屯區", "800-1500", "公寓", "2", "不限", "不限", "不限", "不限", "確認儲存"]


class SharedIntakeIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.store = TenantStore(self.tmp.name)
        self.now = lambda: datetime.datetime(2026, 10, 2, 9)
        self.api = FakeLineApi().start()
        self.app = create_app(store=self.store, channel=SharedChannelConfig("s", "test-token"),
                              client_factory=lambda t: LineClient(t, api_base=self.api.base_url, min_interval=0),
                              now=self.now)
        self.n = 0
        self.send(A, "綁定 " + self.app.registry.issue_code("tenant-a"))
        self.send(B, "綁定 " + self.app.registry.issue_code("tenant-b"))
        self.customers = CsvCustomerSource(self.store, now=self.now)

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def send(self, user, text, *, group=None, with_id=True):
        self.n += 1
        src = {"type": "group", "groupId": group, "userId": user} if group else {"type": "user", "userId": user}
        ev = {"type": "message", "replyToken": f"r{self.n}", "source": src, "message": {"type": "text", "text": text}}
        if with_id:
            ev["webhookEventId"] = f"e{self.n}"
        body = json.dumps({"events": [ev]}).encode()
        self.assertEqual(self.app.handle(body, sign("s", body))[0], 200)
        r = [x for x in self.api.replies if x["replyToken"] == f"r{self.n}"]
        return r[0]["messages"][0].get("text", "") if r else None

    def make_customer(self, user):
        for t in FLOW:
            self.send(user, t)

    def test_other_tenant_cannot_touch_customer_by_id(self):
        self.make_customer(A)
        a_id = self.customers.list_customers("tenant-a")[0]["customer_id"]
        before = json.dumps(self.customers.get("tenant-a", a_id), ensure_ascii=False, sort_keys=True)
        for cmd in (f"需求 {a_id}", f"修改需求 {a_id}", f"改名 {a_id} 偷改", f"暫停 {a_id}", f"恢復 {a_id}"):
            reply = self.send(B, cmd) or ""
            self.assertNotIn("合成甲", reply, cmd)
        self.assertEqual(before, json.dumps(self.customers.get("tenant-a", a_id), ensure_ascii=False, sort_keys=True))
        self.assertEqual(self.customers.list_customers("tenant-b", active_only=False), [])
        self.assertNotIn(a_id, self.send(B, "客戶清單"))
        self.assertIn("找不到符合的客人", self.send(B, "找客戶 合成"))

    def test_rebinding_leaves_old_tenant_unreachable_and_untouched(self):
        self.make_customer(A)
        self.send(A, "綁定 " + self.app.registry.issue_code("tenant-c"))
        self.assertEqual(self.app.registry.tenant_of(A), "tenant-c")
        self.assertIn("還沒有客人", self.send(A, "客戶清單"))
        self.assertEqual(len(self.customers.list_customers("tenant-a")), 1)

    def test_unbound_user_and_group_context_cannot_operate(self):
        self.assertEqual(self.send(STRANGER, "新增買方"), "")                    # 只回歡迎卡（要先按同意並開始）
        self.assertIsNone(self.app.registry.tenant_of(STRANGER))
        self.assertIsNone(self.send(A, "新增買方", group=GROUP))
        self.assertFalse((self.root / "tenants" / "tenant-a" / "customers").exists())

    def test_shared_mode_keeps_no_raw_chat_and_audit_has_no_line_ids(self):
        self.make_customer(A)
        files = [p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()]
        self.assertFalse([f for f in files if "/messages/" in f or "/events/" in f], files)
        audit = (self.root / "tenants" / SYS_TENANT / "audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(A, audit)
        self.assertNotIn(B, audit)

    def test_repeated_confirm_without_event_id_creates_one_customer(self):
        for t in FLOW[:-1]:
            self.send(A, t)
        self.send(A, "確認儲存", with_id=False)
        self.send(A, "確認儲存", with_id=False)
        self.assertEqual(len(self.customers.list_customers("tenant-a")), 1)


if __name__ == "__main__":
    unittest.main()
