"""web/mcp_tools：docs/mcp_tools.md 契約的實作（合成資料；配對引擎用替身，另有一支接真的 core）。"""
import datetime
import json
import pathlib
import tempfile
import unittest

from adapters.csv.customer_source import CsvCustomerSource
from adapters.csv.listing_source import CsvListingSource
from adapters.line.client import LineClient
from adapters.line.credentials import TenantLineConfig
from adapters.line.fake_api import FakeLineApi, synthetic_line_id
from adapters.line.push_gate import PushGate
from adapters.storage import TenantStore
from web import mcp_tools as T

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
OWNER = synthetic_line_id("U", "mcp-owner")
GROUP = synthetic_line_id("C", "mcp-a001")


def stub_matcher(need, listings):
    """替身：只看區域與預算；listing_id 故意轉小寫，確認工具會對回原編號。"""
    cap = need["budget_max"] * (1 + need.get("budget_tolerance_pct", 0) / 100)
    out = {"priority": [], "review": [], "rejected": []}
    for x in listings:
        ok = x["area"] in need["preferred_areas"] and x["price"] <= cap and x["transaction"] == need["transaction"]
        bucket = ("priority" if x.get("url") else "review") if ok else "rejected"
        out[bucket].append({"listing_id": x["id"].lower(), "bucket": bucket, "score": 1, "reasons": [], "missing": []})
    return out


class McpToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.now = lambda: datetime.datetime(2026, 10, 1, 11, 0)
        self.api = FakeLineApi(member_counts={GROUP: 3}).start()
        cfg = TenantLineConfig("demo", "s", "test-token", owner_user_id=OWNER)
        client = LineClient("test-token", api_base=self.api.base_url, min_interval=0)
        self.listings = CsvListingSource(self.store, now=self.now)
        self.customers = CsvCustomerSource(self.store, now=self.now)
        self.listings.import_csv("demo", (FIX / "listings_synthetic.csv").read_bytes())
        self.customers.import_customers("demo", (FIX / "customers_synthetic.csv").read_bytes(), default_city="示範市")
        self.customers.bind_line_target("demo", "A001", GROUP, members=3)
        self.ctx = T.ToolContext("demo", self.store, self.listings, self.customers,
                                 gate_factory=lambda: PushGate(self.store, cfg, client, now=self.now),
                                 matcher=stub_matcher, now=self.now)

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def test_every_result_is_json_and_carries_contract_version(self):
        for name, kwargs in (("list_listings", {}), ("get_need_card", {"customer_id": "A001"}),
                             ("match", {"customer_id": "A001"}), ("get_push_quota", {})):
            res = T.TOOLS[name](self.ctx, **kwargs)
            json.dumps(res, ensure_ascii=False)
            self.assertEqual(res.get("contract"), T.CONTRACT_VERSION, name)

    def test_list_listings_filters_and_pages(self):
        res = T.list_listings(self.ctx, transaction="buy", areas=["示範市中央區"], limit=2)
        self.assertEqual([x["id"] for x in res["listings"]], ["S-101", "S-103"])
        self.assertEqual(res["total"], 4)
        page2 = T.list_listings(self.ctx, transaction="buy", areas=["示範市中央區"], limit=2, cursor=res["next_cursor"])
        self.assertEqual([x["id"] for x in page2["listings"]], ["S-105", "S-106"])
        self.assertIsNone(page2["next_cursor"])
        self.assertNotIn("S-104", [x["id"] for x in T.list_listings(self.ctx)["listings"]])     # 已成交下架
        self.assertIn("S-104", [x["id"] for x in T.list_listings(self.ctx, online_only=False)["listings"]])
        self.assertEqual(T.list_listings(self.ctx, transaction="swap")["error"]["code"], "invalid_argument")

    def test_get_need_card(self):
        res = T.get_need_card(self.ctx, customer_id="A001")
        self.assertEqual(res["need_card"]["preferred_areas"], ["示範市中央區"])
        self.assertTrue(res["can_push"])
        self.assertEqual(T.get_need_card(self.ctx, customer_id="nope")["error"]["code"], "not_found")

    def test_match_maps_ids_back_and_attaches_listing(self):
        res = T.match(self.ctx, customer_id="A001")
        self.assertEqual([x["listing_id"] for x in res["priority"]], ["S-101", "S-106"])
        self.assertEqual(res["priority"][0]["listing"]["url"], "https://example.test/l/S-101")
        self.assertEqual([x["listing_id"] for x in res["review"]], ["S-105"])
        self.assertEqual(res["need_card_version"], 1)
        bad = T.match(self.ctx, customer_id="A001", need_card={"transaction": "buy"})
        self.assertEqual(bad["error"]["code"], "invalid_argument")
        adhoc = T.match(self.ctx, need_card={"transaction": "rent", "preferred_areas": ["示範市河濱區"],
                                             "budget_max": 15000})
        self.assertEqual([x["listing_id"] for x in adhoc["priority"]], ["R-201"])

    def test_queue_for_review_goes_through_gate_only(self):
        res = T.queue_for_review(self.ctx, customer_id="A001", listing_ids=["S-101"], note="區域與預算都符合")
        self.assertEqual(res["state"], "held")
        self.assertEqual({p["to"] for p in self.api.pushes}, {OWNER})      # 只有審核卡給本人，客戶沒收到
        self.assertIn("AI 說明", json.dumps(self.api.pushes[0], ensure_ascii=False))
        again = T.queue_for_review(self.ctx, customer_id="A001", listing_ids=["S-101"])
        self.assertEqual(again["state"], "duplicate")
        for kwargs, code in (({"customer_id": "A001", "listing_ids": ["S-105"]}, "invalid_argument"),
                             ({"customer_id": "A001", "listing_ids": ["S-104"]}, "invalid_argument"),
                             ({"customer_id": "A002", "listing_ids": ["S-102"]}, "not_ready"),
                             ({"customer_id": "A001", "listing_ids": ["S-101", "S-103", "S-106", "S-102"]},
                              "invalid_argument")):
            self.assertEqual(T.queue_for_review(self.ctx, **kwargs)["error"]["code"], code, kwargs)

    def test_tenant_without_line_is_not_ready(self):
        ctx = T.ToolContext("demo", self.store, self.listings, self.customers, matcher=stub_matcher, now=self.now)
        self.assertEqual(T.queue_for_review(ctx, customer_id="A001", listing_ids=["S-101"])["error"]["code"],
                         "not_ready")

    def test_line_bind_code(self):
        from adapters.line.shared import BindingRegistry
        self.assertEqual(T.get_line_bind_code(self.ctx)["error"]["code"], "not_ready")
        self.ctx.bind_registry = BindingRegistry(self.store, now=self.now)
        res = T.get_line_bind_code(self.ctx)
        self.assertRegex(res["code"], r"^\d{6}$")
        self.assertIn("綁定 " + res["code"], res["how_to"])
        self.assertFalse(res["already_bound"])

    def test_patrol_posts_is_contract_only_for_now(self):
        res = T.patrol_posts(self.ctx, platforms=["threads"], keywords=["想買房"])
        self.assertEqual(res["error"]["code"], "not_ready")
        self.assertTrue(res["error"]["retryable"])


if __name__ == "__main__":
    unittest.main()
