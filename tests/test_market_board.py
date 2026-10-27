"""全市場新物件盤點（負責人 2026-10-03：「你必須知道哪個品牌今天上架了甚麼房子」）。
搜尋結果全部是合成的（網址樣式照 2026-10-03 實際搜尋結果的格式），不連網。"""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

import test_customer_intake as support
from adapters.line.flex import validate_message
from adapters.storage import TenantStore
from adapters.web_search import BudgetedSearch, SearchError, SearchHit
from core import market_sources as MS
from core import post_triage
from core.post_facts import TW
from web.jobs import daily_brief as DB
from web.jobs import market_board as MB
from web.line_app import create_app
from web.scheduler import DailyScheduler

DAY = datetime.date(2026, 10, 3)
PHONE = "09" + "12" + "345678"                       # 拆開寫：測試資料不放完整電話樣式


def H(url, title, snippet=""):
    return SearchHit(title, url, snippet)


# 宜蘭市一天的市場（各網站的網址、摘要長相照實際搜尋結果）
DAY1 = {
    "sinyi.com.tw": [
        H("https://www.sinyi.com.tw/buy/house/XS100200HB?breadcrumb=list", "宜市大坡路住家華廈",
          "宜市大坡路住家華廈位於宜蘭縣宜蘭市大坡路一段，2房2廳2衛總價688萬，格局方正"),
        H("https://www.sinyi.com.tw/buy/house/500300CT", "員山市中心商業區透天",
          "員山市中心商業區透天位於宜蘭縣員山鄉員山路1段，3房2廳3衛總價958萬"),
        H("https://www.sinyi.com.tw/buy/list/Yilan-county/index/1", "宜蘭縣全區買房", "列表頁"),
    ],
    "hbhousing.com.tw": [
        H("https://www.hbhousing.com.tw/detail/?sn=XS100200", "宜蘭縣宜蘭市宜市大坡路住家華廈",
          "位於宜蘭縣宜蘭市大坡路一段出售華廈，格局2房(室)2廳2衛"),
    ],
    "twhg.com.tw/buy": [
        H("https://www.twhg.com.tw/buy/TG00000101-print", "市區學區華廈｜宜蘭縣宜蘭市住宅出售",
          f"宜蘭縣羅東鎮中正路1號. 王小明. {PHONE}. TG00000101. $1200 萬. 市區學區華廈. 宜蘭縣宜蘭市示範路二段. "
          "類型. 華廈. 格局. 2房1廳2衛. 建坪. 65.94坪."),
        H("https://store.twhg.com.tw/TG31", "宜蘭特許加盟店", "本店近期成交紀錄"),
    ],
    "etwarm.com.tw": [
        H("https://www.etwarm.com.tw/print.php?id=700100", "列印畫面- 宜市轉運站透天",
          "物件編號︱A1. 總價︱1,780 萬. 地址︱. 宜蘭縣宜蘭市陽明二路 ; 類型︱透天 ; 4房2廳3衛"),
        H("https://store.etwarm.com.tw/A1/houses/buy/700200", "板橋大觀路一樓出售",
          "宜蘭縣宜蘭市示範路三段1號1樓. 撥打電話. 地址. 新北市板橋區大觀路二段. 類型. 公寓/ 住家用. 總價. 850 萬"),
    ],
    "591.com.tw": [
        H("https://land.591.com.tw/sale/20000100", "宜蘭市環市東路農地-某某出售",
          "宜蘭縣宜蘭市農地出售，總價1033萬，面積625坪"),
        H("https://m.591.com.tw/v2/sale/20000200", "宜蘭市高樓層三房",
          "所屬公司群義房屋-宜蘭加盟店 經紀業名稱某某不動產有限公司"),
        H("https://market.591.com.tw/9000001", "合成社區", "社區行情"),
    ],
    "buy.housefun.com.tw/buy/house": [
        H("https://buy.housefun.com.tw/buy/house/7000100", "羅東夜市超低總價電梯套房",
          "地址宜蘭縣羅東鎮興東路 · 單價 30萬/坪 · 每月應付 20,000元 · 格局. 1房(室)"),
    ],
}


class FakeMarket:
    name = "fake"

    def __init__(self, data=None):
        self.data, self.calls = dict(data or DAY1), []

    def search(self, query, *, recency="d", count=10, page=1):
        self.calls.append((query, recency, page))
        if page > 1:
            return []
        for site, hits in self.data.items():
            if query.startswith(f"site:{site}"):
                return list(hits)
        return []


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.cat = MS.Catalog()

    def parse(self, hit, hint="宜蘭縣"):
        for src in self.cat.sources:
            item, why = MS.parse(hit, src, self.cat, hint_county=hint)
            if item or why != "不是物件頁":
                return item, why
        return None, "不是物件頁"

    def test_partner_listing_on_sinyi_goes_to_real_brand_and_dedupes(self):
        a, _ = self.parse(DAY1["sinyi.com.tw"][0])
        b, _ = self.parse(DAY1["hbhousing.com.tw"][0])
        self.assertEqual((a["brand"], a["key"]), ("住商不動產", "hb:XS100200"))
        self.assertEqual(a["key"], b["key"])                                   # 兩個網站同一間只算一次
        self.assertEqual(a["url"], "https://www.sinyi.com.tw/buy/house/XS100200HB")   # 拿掉追蹤參數
        c, _ = self.parse(DAY1["sinyi.com.tw"][1])
        self.assertEqual((c["brand"], c["district"]), ("中信房屋", "員山鄉"))

    def test_store_address_and_phone_are_skipped(self):
        item, _ = self.parse(DAY1["twhg.com.tw/buy"][0])
        self.assertEqual((item["district"], item["price"], item["kind"], item["rooms"]), ("宜蘭市", 1200.0, "華廈", 2))
        self.assertEqual(item["url"], "https://www.twhg.com.tw/buy/TG00000101")
        self.assertNotIn(PHONE, json.dumps(item, ensure_ascii=False))
        self.assertNotIn("王小明", json.dumps(item, ensure_ascii=False))         # 摘要原文不留
        self.assertEqual(self.parse(DAY1["twhg.com.tw/buy"][1]), (None, "不是物件頁"))

    def test_object_address_wins_over_store_address(self):
        item, _ = self.parse(DAY1["etwarm.com.tw"][1])
        self.assertEqual((item["county"], item["district"]), ("新北市", "板橋區"))
        print_page, _ = self.parse(DAY1["etwarm.com.tw"][0])
        self.assertEqual(print_page["url"], "https://www.etwarm.com.tw/houses/buy/700100")
        self.assertEqual(print_page["title"], "宜市轉運站透天")

    def test_platform_brand_from_text(self):
        item, _ = self.parse(DAY1["591.com.tw"][1])
        self.assertEqual(item["brand"], "群義房屋")
        owner, _ = self.parse(DAY1["591.com.tw"][0])
        self.assertIsNone(owner["brand"])                                       # 沒寫品牌 → 顯示網站名
        self.assertEqual(MB.brand_of(owner), "591")
        self.assertEqual(owner["title"], "宜蘭市環市東路農地")                  # 「-某某出售」是人名，拿掉

    def test_kind_reads_the_end_of_the_title(self):
        self.assertEqual(MS.find_kind("礁溪市區農舍林立環境優美足坪農地", ""), "農地")
        self.assertEqual(MS.find_kind("羅東夜市超低總價168電梯套房", ""), "套房")
        self.assertEqual(MS.find_kind("一樓三房車位電梯華廈", ""), "華廈")
        self.assertEqual(MS.find_kind("頭城企業主大宅", "8房全部獨立套房"), None)    # 摘要的套房是房間
        self.assertEqual(MS.find_kind("三房美宅", "類型. 華廈. 格局"), "華廈")

    def test_price_ignores_unit_and_monthly(self):
        self.assertIsNone(MS.find_price("單價 44.28萬/坪 · 每月應付 101,645元"))
        self.assertEqual(MS.find_price("3,280萬. 37.95萬/坪. 47,833/月"), 3280.0)
        self.assertEqual(MS.find_price("總價︱4,980 萬"), 4980.0)
        self.assertIsNone(MS.find_price("宜蘭縣宜蘭市住宅出售：總價?萬，面積?坪"))

    def test_short_district_name_only_inside_the_scanned_county(self):
        self.assertEqual(MS.find_area("礁溪460老農地", "近交流道", "宜蘭縣"), ("宜蘭縣", "礁溪鄉"))
        self.assertEqual(MS.find_area("宜蘭運動公園旁農地", "", "宜蘭縣"), None)   # 「宜蘭」是縣，不猜宜蘭市
        self.assertIsNone(MS.find_area("礁溪460老農地", "", None))

    def test_runtime_catalog_adds_sources_and_brands(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            path.write_text(json.dumps({
                "brands": {"示範": "示範房屋"}, "prefix_brands": {"DM": "示範加盟"},
                "sources": [{"key": "dm", "name": "示範房屋", "brand": "示範房屋", "site": "buy.demo-realty.test/house",
                             "pattern": r"^https://buy\.demo-realty\.test/house/(\d+)", "family": "dm",
                             "brand_from_text": True},
                            {"key": "bad", "name": "x", "site": "x", "pattern": "http://insecure/(\\d+)"},
                            {"key": "broken", "name": "y", "site": "y", "pattern": "^https://y/("}]}),
                encoding="utf-8")
            cat = MS.load_catalog(path)
        self.assertEqual([s.key for s in cat.sources][-1], "dm")
        self.assertEqual(len(cat.sources), len(MS.SOURCES) + 1)                   # 不安全、壞掉的跳過
        item, _ = MS.parse(H("https://buy.demo-realty.test/house/123456", "宜蘭市三房華廈",
                             "(DM1234567) 宜蘭縣宜蘭市"), cat.sources[-1], cat)
        self.assertEqual(item["brand"], "示範加盟")
        self.assertEqual(MS.load_catalog(Path("does-not-exist.json")).sources, MS.SOURCES)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.fake = FakeMarket()
        self.dt = datetime.datetime(2026, 10, 3, 9, 0)
        self.search = BudgetedSearch(self.fake, self.store, now=lambda: self.dt)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_scan_is_baseline_then_daily_only_new(self):
        recs = MB.ensure(self.search, self.store, [("宜蘭縣", "宜蘭市")], day=DAY)
        self.assertEqual({r for _, r, _ in self.fake.calls}, {"d", "w"})            # 第一次：最近一天＋一週當基準
        self.assertEqual(recs[0]["first_day"], DAY.isoformat())
        b = MB.board(self.store, [("宜蘭縣", "宜蘭市")], DAY)
        self.assertTrue(b["baseline"])
        brands = {MB.brand_of(i) for i in b["items"]}
        self.assertEqual(brands, {"住商不動產", "台灣房屋", "東森房屋", "591", "群義房屋"})
        self.assertEqual(len([i for i in b["items"] if i["key"] == "hb:XS100200"]), 1)
        self.assertEqual({i["district"] for i in b["nearby"]}, {"員山鄉", "羅東鎮"})   # 同縣市別鄉鎮另外列
        self.assertNotIn("板橋區", json.dumps(b, ensure_ascii=False))
        # 同一天第二位仲介：不再搜
        n = len(self.fake.calls)
        MB.ensure(self.search, self.store, [("宜蘭縣", "宜蘭市")], day=DAY)
        self.assertEqual(len(self.fake.calls), n)
        # 隔天：只查最近一天；新編號 → 🆕，舊編號第一次出現 → 搜尋引擎才收錄
        self.dt += datetime.timedelta(days=1)
        self.fake.data["twhg.com.tw/buy"] = [
            H("https://www.twhg.com.tw/buy/TG00000150", "宜市新上架三房華廈", "宜蘭縣宜蘭市. $900 萬. 類型. 華廈. 3房"),
            H("https://www.twhg.com.tw/buy/TG00000050", "宜市老物件公寓", "宜蘭縣宜蘭市. $600 萬. 類型. 公寓")]
        self.fake.calls.clear()
        MB.ensure(self.search, self.store, [("宜蘭縣", "宜蘭市")], day=DAY + datetime.timedelta(days=1))
        self.assertEqual({r for _, r, _ in self.fake.calls}, {"d"})
        b2 = MB.board(self.store, [("宜蘭縣", "宜蘭市")], DAY + datetime.timedelta(days=1))
        self.assertFalse(b2["baseline"])
        fresh = {i["title"]: i["fresh"] for i in b2["items"]}
        self.assertEqual(fresh, {"宜市新上架三房華廈": True, "宜市老物件公寓": False})
        self.assertIn("🆕 1 筆是新刊登", MB.head_line(b2))

    def test_quota_error_keeps_what_was_found(self):
        class Quota(FakeMarket):
            def search(self, query, **kw):
                if "etwarm" in query:
                    raise SearchError("quota", "搜尋服務額度用完或被限速")
                return super().search(query, **kw)
        search = BudgetedSearch(Quota(), self.store, now=lambda: self.dt)
        rec = MB.ensure(search, self.store, [("宜蘭縣", "宜蘭市")], day=DAY)[0]
        self.assertTrue(rec["errors"])
        self.assertGreater(rec["found"], 0)

    def test_market_has_its_own_daily_cap(self):
        MB.ensure(self.search, self.store, [("宜蘭縣", "宜蘭市")], day=DAY)
        usage = self.store.read_json(MB.SYS, "search", "usage.json")
        self.assertIn(MB.SEARCH_TENANT, usage["tenants"])
        self.assertNotIn("tenant-a", usage["tenants"])

    def test_cards_group_by_brand_and_pass_line_checks(self):
        MB.ensure(self.search, self.store, [("宜蘭縣", "宜蘭市")], day=DAY)
        b = MB.board(self.store, [("宜蘭縣", "宜蘭市")], DAY)
        msgs = MB.messages(b)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(validate_message(msgs[0]), [])
        bubbles = msgs[0]["contents"]["contents"]
        heads = [bb["header"]["contents"][0]["text"] for bb in bubbles]
        self.assertTrue(heads[-1].startswith("附近鄉鎮"))
        uris = [row["action"]["uri"] for bb in bubbles for row in bb["body"]["contents"] if row.get("action")]
        self.assertTrue(all(u.startswith("https://") for u in uris))
        self.assertIn("第一次盤點宜蘭市", MB.head_line(b))

    def test_many_items_stay_within_twelve_cards(self):
        hits = [H(f"https://www.twhg.com.tw/buy/TG{100000 + i:08d}", f"宜市三房華廈{i}", "宜蘭縣宜蘭市. 類型. 華廈")
                for i in range(80)]
        self.fake.data = {"twhg.com.tw/buy": hits}
        MB.ensure(self.search, self.store, [("宜蘭縣", "宜蘭市")], day=DAY)
        msgs = MB.messages(MB.board(self.store, [("宜蘭縣", "宜蘭市")], DAY))
        self.assertEqual(len(msgs[0]["contents"]["contents"]), 12)
        self.assertEqual(validate_message(msgs[0]), [])

    def test_long_urls_drop_cards_instead_of_exceeding_line_size(self):
        items = [{"key": f"x:{i}", "brand": f"品牌{i % 4}", "site": "s", "url": "https://buy.example.test/h/" + "q" * 700,
                  "title": "合成" * 30, "county": "宜蘭縣", "district": "宜蘭市", "num": i} for i in range(90)]
        msg = MB.messages({"areas": [("宜蘭縣", "宜蘭市")], "items": items, "nearby": [], "baseline": False,
                           "scanned": True, "errors": []})[0]
        self.assertLessEqual(len(json.dumps(msg, ensure_ascii=False).encode()), MB.MAX_BYTES)
        self.assertGreater(len(msg["contents"]["contents"]), 1)


class PoolMatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        search = BudgetedSearch(FakeMarket(), self.store, now=lambda: datetime.datetime(2026, 10, 3, 9))
        MB.ensure(search, self.store, [("宜蘭縣", "宜蘭市")], day=DAY)

    def tearDown(self):
        self.tmp.cleanup()

    def need(self, **kw):
        return {"transaction": "buy", "preferred_areas": ["宜蘭縣宜蘭市"], "budget_max": 1300,
                "property_type": "華廈", **kw}

    def test_matches_type_area_budget(self):
        hits = MB.pool_matches(self.store, self.need(), None, DAY)
        self.assertEqual(sorted(h.url for h in hits), ["https://www.sinyi.com.tw/buy/house/XS100200HB",
                                                       "https://www.twhg.com.tw/buy/TG00000101"])
        self.assertTrue(all("｜" in h.title for h in hits))                       # 標題帶品牌
        self.assertEqual(MB.pool_matches(self.store, self.need(budget_max=700), None, DAY)[0].title[:5], "住商不動產")

    def test_own_brand_hidden_and_no_type_means_homes_only(self):
        hits = MB.pool_matches(self.store, self.need(), {"brand": "台灣房屋"}, DAY)
        self.assertNotIn("twhg", " ".join(h.url for h in hits))
        anything = MB.pool_matches(self.store, self.need(property_type=None, budget_max=5000), None, DAY)
        self.assertFalse(any("land.591" in h.url for h in anything))                # 沒指定型態不給農地

    def test_rent_and_old_items_not_matched(self):
        self.assertEqual(MB.pool_matches(self.store, self.need(transaction="rent"), None, DAY), [])
        later = DAY + datetime.timedelta(days=MB.MATCH_DAYS + 1)
        self.assertEqual(MB.pool_matches(self.store, self.need(), None, later), [])


class BriefIntegrationTests(unittest.TestCase):
    send = support.CustomerIntakeTests.send
    tearDown = support.CustomerIntakeTests.tearDown

    def setUp(self):
        support.CustomerIntakeTests.setUp(self)
        self.fake = FakeMarket()
        self.app = create_app(store=self.store, channel=self.cfg, client_factory=self.factory,
                              search_provider=self.fake, now=self.now)
        self.send("綁定 " + self.app.registry.issue_code("tenant-a"))
        self.store.write_json("tenant-a", "line", "prospect_setup.json", data={"profile": {
            "cities": ["宜蘭縣"], "areas": {"宜蘭縣": ["宜蘭市"]}, "transaction": "買", "kind": "住宅",
            "keywords": ["買房"], "time": "09:00"}})

    def test_report_without_buyers_still_shows_the_market(self):
        """負責人截圖：沒有買方 → 新物件 0。現在不用先有買方，每天直接報各品牌新物件。"""
        sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now)
        self.dt = self.dt.replace(hour=9, minute=1)
        self.assertEqual(sched.tick()[0], ("tenant-a", "sent"))
        msgs = self.api.pushes[-1]["messages"]
        self.assertIn("市場：第一次盤點宜蘭市", msgs[0]["text"])
        self.assertIn("還沒有買方", msgs[0]["text"])
        self.assertTrue(any(m.get("altText", "").startswith("今日市場") for m in msgs))
        for m in msgs:
            self.assertEqual(validate_message(m), [])

    def test_buyer_gets_market_matches_before_extra_searches(self):
        self.customers.save_need("tenant-a", label="合成甲", need={
            "transaction": "buy", "preferred_areas": ["宜蘭縣宜蘭市"], "budget_max": 1300, "property_type": "華廈"})
        sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now)
        self.dt = self.dt.replace(hour=9, minute=1)
        sched.tick()
        msgs = self.api.pushes[-1]["messages"]
        self.assertIn("幫買方配對：1 位客人", msgs[0]["text"])
        flat = json.dumps(msgs[-1], ensure_ascii=False)
        self.assertIn("住商不動產｜", flat)

    def test_command_does_not_scan_synchronously(self):
        self.send("今日報告")
        self.assertFalse(any("hbhousing" in q for q, _, _ in self.fake.calls))


class MediaAccountTests(unittest.TestCase):
    def test_platform_news_post_is_not_a_buyer(self):
        now = datetime.datetime(2026, 10, 3, 9, tzinfo=TW)
        text = "到宜蘭買房，真準備好了？央行鬆綁管制，減輕了建商的資金壓力，專家提醒切勿過度擴張槓桿"
        args = dict(county="宜蘭縣", area_term="宜蘭市", intent="buy", posted_at=now, now=now)
        self.assertEqual(post_triage.judge(text, handle="demo_official", **args).reason, "媒體／官方帳號")
        self.assertEqual(post_triage.judge(text, handle="someone", **args).reason, "新聞／行情文，不是買賣方")
        self.assertTrue(post_triage.judge("請問宜蘭市哪裡有透天要賣的？", handle="someone", **args).keep)


if __name__ == "__main__":
    unittest.main()
