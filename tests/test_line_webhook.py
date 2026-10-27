"""adapters/line/webhook：多租戶路由、驗簽、事件落檔、內建指令與審核鈕（本機假 LINE，合成資料）。"""
import datetime
import io
import json
import tempfile
import unittest

from adapters.line import flex, groups
from adapters.line.client import LineClient
from adapters.line.credentials import MemoryCredentialStore, TenantLineConfig
from adapters.line.fake_api import FakeLineApi, synthetic_line_id
from adapters.line.push_gate import GatePolicy, PushGate
from adapters.line.signature import sign
from adapters.line.webhook import WebhookApp
from adapters.storage import TenantStore

OWNER = synthetic_line_id("U", "owner")
CUSTOMER = synthetic_line_id("U", "customer")
GROUP = synthetic_line_id("C", "customer-group")
STRANGER = synthetic_line_id("U", "stranger")


def text_event(text, *, user=OWNER, group=None, eid="e1", token="rt-1"):
    src = {"type": "group", "groupId": group, "userId": user} if group else {"type": "user", "userId": user}
    return {"type": "message", "webhookEventId": eid, "replyToken": token, "timestamp": 1790000000000,
            "source": src, "message": {"type": "text", "id": "m1", "text": text}}


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.api = FakeLineApi(member_counts={GROUP: 3}).start()
        self.cfg = TenantLineConfig("t1", "secret-one", "test-token", owner_user_id=OWNER)
        self.other = TenantLineConfig("t2", "secret-two", "test-token", owner_user_id=STRANGER)
        self.now = lambda: datetime.datetime(2026, 10, 1, 10, 0)
        factory = lambda cfg: LineClient(cfg.channel_access_token, api_base=self.api.base_url,
                                         min_interval=0, sleep=lambda s: None)
        self.factory = factory
        self.app = WebhookApp(MemoryCredentialStore([self.cfg, self.other]), self.store,
                              client_factory=factory, now=self.now)

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def post(self, tenant, events, secret="secret-one"):
        body = json.dumps({"destination": "x", "events": events}).encode("utf-8")
        return self.app.handle(tenant, body, sign(secret, body))

    def gate(self):
        return PushGate(self.store, self.cfg, self.factory(self.cfg), now=self.now)

    def test_unknown_or_malformed_tenant_is_404(self):
        self.assertEqual(self.post("nobody", [])[0], 404)
        self.assertEqual(self.post("../t1", [])[0], 404)

    def test_bad_or_missing_signature_is_403_and_nothing_logged(self):
        body = json.dumps({"events": [text_event("hi")]}).encode()
        self.assertEqual(self.app.handle("t1", body, "nope")[0], 403)
        self.assertEqual(self.app.handle("t1", body, "")[0], 403)
        self.assertEqual(self.store.read_jsonl("t1", "line", "events", "2026-10-01.jsonl"), [])
        audit = self.store.read_jsonl("t1", "line", "webhook_audit.jsonl")
        self.assertEqual([a["ev"] for a in audit], ["bad_signature", "bad_signature"])

    def test_other_tenants_secret_cannot_post_into_this_tenant(self):
        self.assertEqual(self.post("t1", [text_event("hi")], secret="secret-two")[0], 403)

    def test_verify_button_empty_events_is_200(self):
        self.assertEqual(self.post("t1", []), (200, "ok"))

    def test_group_message_is_logged_per_conversation_without_reply_token(self):
        self.post("t1", [text_event("想找三房", user=CUSTOMER, group=GROUP)])
        events = self.store.read_jsonl("t1", "line", "events", "2026-10-01.jsonl")
        self.assertEqual(len(events), 1)
        self.assertNotIn("replyToken", events[0])
        msgs = self.store.read_jsonl("t1", "line", "messages", GROUP + ".jsonl")
        self.assertEqual(msgs[0]["text"], "想找三房")
        self.assertEqual(msgs[0]["uid"], CUSTOMER)
        self.assertEqual(self.store.read_jsonl("t2", "line", "messages", GROUP + ".jsonl"), [])

    def test_ping_replies_and_redelivery_is_deduped(self):
        ev = text_event("測試")
        self.post("t1", [ev])
        self.post("t1", [dict(ev, deliveryContext={"isRedelivery": True})])
        self.assertEqual(len(self.api.replies), 1)
        self.assertIn("收到", self.api.replies[0]["messages"][0]["text"])

    def test_join_and_leave_update_group_registry(self):
        join = {"type": "join", "webhookEventId": "j1", "replyToken": "rt", "timestamp": 1,
                "source": {"type": "group", "groupId": GROUP}}
        self.post("t1", [join])
        self.assertEqual(groups.active_groups(self.store, "t1"), [GROUP])
        leave = {"type": "leave", "webhookEventId": "l1", "timestamp": 2, "source": {"type": "group", "groupId": GROUP}}
        self.post("t1", [leave])
        self.assertEqual(groups.active_groups(self.store, "t1"), [])

    def test_owner_pending_command_replies_with_review_cards(self):
        g = self.gate()
        g.submit(to=GROUP, messages=[flex.flex_message("新案", {"type": "bubble", "body": {
            "type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "x"}]}})],
                 level="match", recipient_label="合成客戶群")
        self.post("t1", [text_event("待審", eid="e2", token="rt-2")])
        self.assertEqual(self.api.replies[-1]["replyToken"], "rt-2")
        self.assertEqual(self.api.replies[-1]["messages"][0]["type"], "flex")

    def test_pending_command_from_customer_is_ignored(self):
        self.post("t1", [text_event("待審", user=CUSTOMER, eid="e3")])
        self.assertEqual(self.api.replies, [])

    def test_postback_approve_sends_and_stranger_is_refused(self):
        g = self.gate()
        res = g.submit(to=GROUP, messages=[{"type": "text", "text": "幫您留意到 1 間新上架"}], level="match")
        data = flex.postback_data("approve", res.item_id)
        pb = lambda user, eid: {"type": "postback", "webhookEventId": eid, "replyToken": "rt-" + eid,
                                "timestamp": 1, "source": {"type": "user", "userId": user},
                                "postback": {"data": data}}
        self.post("t1", [pb(STRANGER, "p1")])
        self.assertIn("⛔", self.api.replies[-1]["messages"][0]["text"])
        self.assertFalse(any(p["to"] == GROUP for p in self.api.pushes))
        self.post("t1", [pb(OWNER, "p2")])
        self.assertEqual(self.api.replies[-1]["messages"][0]["text"], "✅ 已送出")
        self.assertTrue(any(p["to"] == GROUP for p in self.api.pushes))

    def test_owed_message_is_repaid_when_customer_speaks(self):
        g = PushGate(self.store, self.cfg, self.factory(self.cfg), policy=GatePolicy.from_dict(
            {"modes": {"match": "auto"}}), now=self.now)
        self.api.quota_exhausted = True
        res = g.submit(to=GROUP, messages=[{"type": "text", "text": "幫您留意到 1 間新上架"}], level="match")
        self.assertEqual(res.state, "deferred")
        self.post("t1", [text_event("請問還有嗎", user=CUSTOMER, group=GROUP, eid="e9", token="rt-9")])
        self.assertEqual(self.api.replies[-1]["replyToken"], "rt-9")
        self.assertIn("新上架", self.api.replies[-1]["messages"][0]["text"])

    def test_wsgi_routing(self):
        body = json.dumps({"events": []}).encode()
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/webhook/t1", "CONTENT_LENGTH": str(len(body)),
               "wsgi.input": io.BytesIO(body), "HTTP_X_LINE_SIGNATURE": sign("secret-one", body)}
        status = {}
        out = self.app.wsgi(env, lambda s, h: status.setdefault("s", s))
        self.assertEqual(status["s"], "200 OK")
        self.assertEqual(b"".join(out), b"ok")
        status.clear()
        self.app.wsgi({"REQUEST_METHOD": "GET", "PATH_INFO": "/admin"}, lambda s, h: status.setdefault("s", s))
        self.assertEqual(status["s"], "404 Not Found")

    def test_tenant_export_and_delete(self):
        self.post("t1", [text_event("hello", user=CUSTOMER, group=GROUP)])
        blob = self.store.export_tenant("t1")
        self.assertGreater(len(blob), 100)
        self.assertTrue(self.store.delete_tenant("t1"))
        self.assertEqual(self.store.read_jsonl("t1", "line", "messages", GROUP + ".jsonl"), [])


if __name__ == "__main__":
    unittest.main()
