"""W1 完成判準（全合成資料、本機假 LINE）：
CSV 上傳物件 → 配對（core/listing_matching）→ 走推播閘與配額 → 租戶本人審核 → 客戶群收到一張 Flex 卡。
"""
import datetime
import json
import pathlib
import tempfile
import unittest

from adapters.csv.customer_source import CsvCustomerSource
from adapters.csv.listing_source import CsvListingSource
from adapters.line.client import LineClient
from adapters.line.credentials import MemoryCredentialStore, TenantLineConfig
from adapters.line.fake_api import FakeLineApi, synthetic_line_id
from adapters.line.flex import postback_data, validate_message
from adapters.line.push_gate import PushGate
from adapters.line.signature import sign
from adapters.line.webhook import WebhookApp
from adapters.storage import TenantStore

try:
    from web.jobs.new_listing_push import load_matcher, run_new_listing_push
    load_matcher()
    HAVE_CORE = True
except RuntimeError:
    HAVE_CORE = False

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
OWNER = synthetic_line_id("U", "e2e-owner")
GROUP_A001 = synthetic_line_id("C", "e2e-a001")
FRIEND_A003 = synthetic_line_id("U", "e2e-a003")


@unittest.skipUnless(HAVE_CORE, "core.listing_matching 尚未進版")
class W1ListingPushE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.now = lambda: datetime.datetime(2026, 10, 1, 10, 0)
        self.api = FakeLineApi(member_counts={GROUP_A001: 3}).start()
        self.cfg = TenantLineConfig("demo", "demo-secret", "test-token", owner_user_id=OWNER)
        self.client_factory = lambda cfg: LineClient(cfg.channel_access_token, api_base=self.api.base_url,
                                                     min_interval=0, sleep=lambda s: None)
        self.listings = CsvListingSource(self.store, now=self.now)
        self.customers = CsvCustomerSource(self.store, now=self.now)

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def run_job(self, listing_ids=None):
        gate = PushGate(self.store, self.cfg, self.client_factory(self.cfg), now=self.now)
        return run_new_listing_push(tenant_id="demo", store=self.store, listings=self.listings,
                                    customers=self.customers, gate=gate, listing_ids=listing_ids, now=self.now)

    def test_csv_to_match_to_gate_to_flex_card(self):
        # ① 租戶上傳物件與客戶 CSV，把兩位客戶綁上 LINE（一個 3 人群、一個 1 對 1 好友）
        rep = self.listings.import_csv("demo", (FIX / "listings_synthetic.csv").read_bytes())
        self.customers.import_customers("demo", (FIX / "customers_synthetic.csv").read_bytes(), default_city="示範市")
        self.customers.bind_line_target("demo", "A001", GROUP_A001, members=3)
        self.customers.bind_line_target("demo", "A003", FRIEND_A003)

        # ② 配對 → 推播閘：客戶面的推播先排隊，審核卡（含預覽）推給租戶本人
        run = self.run_job(listing_ids=rep.new_ids)
        by_cust = {p["customer_id"]: p for p in run.pushed}
        self.assertEqual(by_cust["A001"]["listing_ids"], ["S-106", "S-101"])   # 同分新上架先；S-103 超預算、S-105 沒連結、S-104 已成交
        self.assertEqual(by_cust["A001"]["state"], "held")
        self.assertEqual(by_cust["A003"]["listing_ids"], ["R-201"])
        skipped = {s["customer_id"]: s["reason"] for s in run.skipped}
        self.assertIn("還沒綁 LINE", skipped["A002"])
        self.assertIn("preferred_areas", skipped["A005"])
        self.assertNotIn("A004", by_cust)                                       # 已成交客戶不推
        self.assertIn({"customer_id": "A001", "listing_id": "S-105", "missing": ["url"]}, run.needs_data)
        self.assertEqual({p["to"] for p in self.api.pushes}, {OWNER})            # 客戶還沒收到任何東西

        # ③ 租戶本人在 LINE 按「送出」（webhook 收到 postback）
        app = WebhookApp(MemoryCredentialStore([self.cfg]), self.store, client_factory=self.client_factory,
                         now=self.now)
        body = json.dumps({"events": [{
            "type": "postback", "webhookEventId": "pb-1", "replyToken": "rt-1", "timestamp": 1,
            "source": {"type": "user", "userId": OWNER},
            "postback": {"data": postback_data("approve", by_cust["A001"]["item_id"])}}]}).encode("utf-8")
        self.assertEqual(app.handle("demo", body, sign("demo-secret", body)), (200, "ok"))
        self.assertEqual(self.api.replies[-1]["messages"][0]["text"], "✅ 已送出")

        # ④ 客戶群收到一張 Flex 卡：兩間物件、可點連結、沒有內部編號
        to_group = [p for p in self.api.pushes if p["to"] == GROUP_A001]
        self.assertEqual(len(to_group), 1)
        msg = to_group[0]["messages"][0]
        self.assertEqual(msg["type"], "flex")
        self.assertEqual(validate_message(msg), [])
        self.assertEqual(msg["contents"]["type"], "carousel")
        blob = json.dumps(msg, ensure_ascii=False)
        self.assertIn("https://example.test/l/S-101", blob)
        self.assertIn("https://example.test/l/S-106", blob)
        self.assertNotIn('"S-101"', blob)
        self.assertIn("1,180 萬", blob)

        # ⑤ 額度照人頭記帳：審核卡 2 則（A001、A003 各一張）＋ 客戶群 3 人
        s = PushGate(self.store, self.cfg, self.client_factory(self.cfg), now=self.now).budget.summary()
        self.assertEqual(s["levels"]["review"]["used_today"], 2)
        self.assertEqual(s["levels"]["match"]["used_month"], 3)
        self.assertEqual(s["used"], 5)

        # ⑥ 重跑不重推：同一批物件已推／已排隊給同一位客戶
        again = self.run_job(listing_ids=rep.new_ids)
        self.assertEqual(again.pushed, [])

    def test_auto_mode_pushes_straight_to_customer(self):
        self.store.write_json("demo", "line", "gate_policy.json", data={"modes": {"match": "auto"}})
        self.listings.import_csv("demo", (FIX / "listings_synthetic.csv").read_bytes())
        self.customers.import_customers("demo", (FIX / "customers_synthetic.csv").read_bytes(), default_city="示範市")
        self.customers.bind_line_target("demo", "A001", GROUP_A001, members=3)
        run = self.run_job()
        self.assertEqual([p["state"] for p in run.pushed], ["sent"])
        self.assertEqual([p["to"] for p in self.api.pushes], [GROUP_A001])


if __name__ == "__main__":
    unittest.main()
