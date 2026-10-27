"""今日報告（自動海巡＋各平台新物件）：搜尋 API 轉接器、用量上限、篩選、去重、排程。全部用假搜尋服務，不連網。"""
import datetime
import io
import json
import unittest
import urllib.error

import test_customer_intake as support
from adapters.line.flex import validate_message
from adapters.web_search import (BraveSearch, BudgetedSearch, SearchError, SearchHit, SerperSearch,
                                 provider_from_env)
from web.jobs import daily_brief as DB
from web.line_app import create_app
from web.scheduler import DailyScheduler

from core.post_facts import TW, code_for

T0 = datetime.datetime(2026, 10, 1, 7, 0, tzinfo=TW)          # 測試時鐘 10/1 09:00 的 2 小時前發文


def post(handle, seq, when=T0):
    return f"https://www.threads.com/@{handle}/post/{code_for(when, seq)}"


PROSPECT = {"cities": ["彰化縣"], "areas": {"彰化縣": ["*"]}, "transaction": "買", "kind": "住宅",
            "keywords": ["買房", "找房"], "time": "09:00"}
NEED = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_max": 1500, "property_type": "公寓"}


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = []

    def search(self, query, *, recency="d", count=10, page=1):
        self.calls.append(query)
        if "threads.com" in query:
            return [SearchHit("想在彰化買房", post("buyer_a", 1), "請問彰化有推薦的社區嗎？預算一千萬"),
                    SearchHit("專任委託出售", post("agent_x", 2), "彰化三房，歡迎洽詢，帶看預約"),
                    SearchHit("個人頁", "https://www.threads.com/@buyer_b", "不是貼文"),
                    SearchHit("想找房", post("buyer_c", 3), "彰化員林想買透天，有人知道哪裡好嗎")]
        return [SearchHit("西屯三房公寓 1280萬", "https://sale.591.com.tw/home/house/detail/2/1001.html", "近捷運"),
                SearchHit("西屯豪宅 3200萬", "https://sale.591.com.tw/home/house/detail/2/1002.html", "景觀"),
                SearchHit("西屯公寓列表", "https://sale.591.com.tw/?regionid=8&section=104", "列表頁"),
                SearchHit("信義房屋 西屯", "https://www.sinyi.com.tw/buy/house/77AB", "1180萬 三房公寓"),
                SearchHit("不相干網站", "https://example.test/x", "1000萬")]


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SearchAdapterTests(unittest.TestCase):
    def test_serper_request_and_parse(self):
        seen = {}

        def opener(req, timeout=None):
            seen.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data))
            return Resp(json.dumps({"organic": [{"title": "t", "link": "https://x.test/a", "snippet": "s"}]}).encode())
        hits = SerperSearch("synthetic-key", opener=opener).search("彰化 買房")
        self.assertEqual(hits, [SearchHit("t", "https://x.test/a", "s")])
        self.assertEqual(seen["url"], "https://google.serper.dev/search")
        self.assertEqual(seen["headers"]["X-api-key"], "synthetic-key")
        self.assertEqual((seen["body"]["gl"], seen["body"]["hl"], seen["body"]["tbs"]), ("tw", "zh-tw", "qdr:d"))

    def test_brave_request_and_parse(self):
        seen = {}

        def opener(req, timeout=None):
            seen.update(url=req.full_url, headers=dict(req.header_items()))
            return Resp(json.dumps({"web": {"results": [{"title": "t", "url": "https://x.test/b",
                                                        "description": "d"}]}}).encode())
        hits = BraveSearch("synthetic-key", opener=opener).search("彰化 買房", recency="w")
        self.assertEqual(hits[0].url, "https://x.test/b")
        self.assertIn("freshness=pw", seen["url"])
        self.assertIn("country=TW", seen["url"])
        self.assertEqual(seen["headers"]["X-subscription-token"], "synthetic-key")

    def test_http_errors_map_to_kinds(self):
        for code, kind in ((401, "auth"), (402, "quota"), (429, "quota"), (500, "unavailable")):
            def opener(req, timeout=None, code=code):
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b"{}"))
            with self.assertRaises(SearchError) as ctx:
                SerperSearch("k", opener=opener).search("q")
            self.assertEqual(ctx.exception.kind, kind)

    def test_provider_from_env(self):
        self.assertIsInstance(provider_from_env({"REA_SEARCH_PROVIDER": "Serper", "REA_SEARCH_KEY": "k"}), SerperSearch)
        self.assertIsInstance(provider_from_env({"REA_SEARCH_PROVIDER": "brave", "REA_SEARCH_KEY": "k"}), BraveSearch)
        self.assertIsNone(provider_from_env({"REA_SEARCH_PROVIDER": "serper"}))
        self.assertIsNone(provider_from_env({"REA_SEARCH_PROVIDER": "other", "REA_SEARCH_KEY": "k"}))


class BudgetTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def test_caps_and_disable_on_auth_error(self):
        fake = FakeProvider()
        s = BudgetedSearch(fake, self.store, now=self.now, daily_cap=3, tenant_cap=2)
        s.search("t1", "q")
        s.search("t1", "q")
        with self.assertRaises(SearchError):
            s.search("t1", "q")                                       # 每位仲介上限
        s.search("t2", "q")
        with self.assertRaises(SearchError):
            s.search("t3", "q")                                       # 全站上限
        self.assertEqual(len(fake.calls), 3)
        self.dt += datetime.timedelta(days=1)                         # 隔天重置
        self.assertEqual(s.remaining("t1"), 2)

        class Broken:
            def search(self, *a, **k):
                raise SearchError("auth", "金鑰錯")
        b = BudgetedSearch(Broken(), self.store, now=self.now, daily_cap=50)
        with self.assertRaises(SearchError):
            b.search("t1", "q")
        with self.assertRaises(SearchError) as ctx:
            b.search("t1", "q")
        self.assertEqual(ctx.exception.kind, "off")                    # 當天停用，不再打

    def test_no_provider(self):
        s = BudgetedSearch(None, self.store, now=self.now)
        self.assertFalse(s.available)
        with self.assertRaises(SearchError):
            s.search("t1", "q")


class CollectTests(unittest.TestCase):
    def test_queries(self):
        g = DB.PK.build_groups(PROSPECT["areas"], ["buy"], ["住宅"], PROSPECT["keywords"])[0]
        self.assertEqual(DB.patrol_query(g), "site:threads.com 彰化 (買房 OR 找房) " + DB.NOT_LISTING)
        self.assertIn("-開價", DB.NOT_LISTING)                                 # 搜尋就先排掉刊登文
        q = DB.listing_query(NEED, {"brand": "信義房屋", "include_own_brand": False})
        self.assertIn("site:sale.591.com.tw", q)
        self.assertNotIn("sinyi", q)                                  # 避開自己品牌
        self.assertTrue(q.endswith("西屯 公寓 出售"))
        self.assertIn("site:sale.591.com.tw/home/house/detail", q)               # 限定物件詳情頁
        self.assertIn("site:rent.591.com.tw", DB.listing_query({**NEED, "transaction": "rent"}, None))
        self.assertIsNone(DB.listing_query({"transaction": "buy"}, None))

    def test_filters_dedupe_and_messages(self):
        class S:
            calls = 0

            def search(self, tenant, query, *, recency="d", page=1):
                S.calls += 1
                return FakeProvider().search(query)
        seen = {}
        day = datetime.date(2026, 10, 2)
        cust = [{"customer_id": "B-1", "label": "合成甲", "need_card": NEED}]
        r = DB.collect(tenant_id="t", search=S(), prospect=PROSPECT, customers=cust, profile=None, seen=seen, day=day)
        self.assertEqual([h.url.split("@")[1].split("/")[0] for _, h, _v in r["posts"]], ["buyer_a", "buyer_c"])
        urls = [h.url for h in r["listings"][0][2]]
        self.assertEqual(urls, ["https://sale.591.com.tw/home/house/detail/2/1001.html",
                                "https://www.sinyi.com.tw/buy/house/77AB"])                  # 超預算、列表頁、他站去掉
        msgs = DB.messages_for(r, day)
        self.assertLessEqual(len(msgs), 5)
        for m in msgs:
            self.assertEqual(validate_message(m), [])
        again = DB.collect(tenant_id="t", search=S(), prospect=PROSPECT, customers=cust, profile=None, seen=seen,
                           day=day)
        self.assertEqual((again["posts"], again["listings"]), ([], []))          # 看過的不再給
        self.assertEqual(DB.messages_for(again, day), [])


class ReviewFixTests(unittest.TestCase):
    def test_post_cap_does_not_burn_extra_posts(self):
        class Many:
            def search(self, tenant, query, *, recency="d", page=1):
                return [SearchHit("想買", post(f"b{i}", i), "想在彰化買房") for i in range(30)]
        seen = {}
        r = DB.collect(tenant_id="t", search=Many(), prospect=PROSPECT, customers=[], profile=None, seen=seen,
                       day=datetime.date(2026, 10, 2))
        self.assertEqual(len(r["posts"]), DB.MAX_POSTS)
        self.assertEqual(len(seen), DB.MAX_POSTS)                     # 沒給的不標成看過

    def test_buyer_phrases_are_not_seller(self):
        self.assertFalse(DB._seller_like("想在彰化買房，請房仲帶看也可以"))
        self.assertTrue(DB._seller_like("專任委託出售，歡迎洽詢"))
        self.assertTrue(DB._seller_like("我的客戶在找彰化透天"))               # 同業找物件：外觀最像買方
        self.assertTrue(DB._seller_like("物件編號 A12 三房"))                  # 強訊號一個就算
        self.assertFalse(DB._seller_like("想找可養寵物的整層，出租的也可以"))   # 弱訊號只有一個

    def test_do_not_contact_posts_are_skipped(self):
        class S:
            def search(self, tenant, query, *, recency="d", page=1):
                return [SearchHit("想買房", post("a", 1), "彰化想買透天，房仲勿擾"),
                        SearchHit("想買房", post("b", 2), "彰化想買透天，謝絕仲介"),
                        SearchHit("想買房", post("c", 3), "彰化想買透天，有推薦的嗎")]
        r = DB.collect(tenant_id="t", search=S(), prospect=PROSPECT, customers=[], profile=None, seen={},
                       day=datetime.date(2026, 10, 2))
        self.assertEqual([h.url.split("@")[1].split("/")[0] for _, h, _v in r["posts"]], ["c"])


class BriefFlowTests(unittest.TestCase):
    send = support.CustomerIntakeTests.send
    tearDown = support.CustomerIntakeTests.tearDown

    def setUp(self):
        support.CustomerIntakeTests.setUp(self)
        self.fake = FakeProvider()
        self.app = create_app(store=self.store, channel=self.cfg, client_factory=self.factory,
                              search_provider=self.fake, now=self.now)
        self.send("綁定 " + self.app.registry.issue_code("tenant-a"))
        self.store.write_json("tenant-a", "line", "prospect_setup.json", data={"profile": PROSPECT})
        self.customers.save_need("tenant-a", label="合成甲", need=NEED)

    def test_command_replies_with_cards(self):
        self.assertIn("今日報告", self.send("今日報告")["text"])
        msgs = self.api.replies[-1]["messages"]
        self.assertEqual([m["type"] for m in msgs], ["text", "flex", "flex"])
        self.assertIn("沒有新的結果", self.send("今日報告")["text"])
        self.assertEqual(self.api.pushes, [])                                     # 指令走回覆，不吃推播額度

    def test_patrol_command_gives_the_posts_themselves(self):
        """負責人 2026-10-02：搜尋關鍵字大家都會，要直接給那一篇想買房的文章。"""
        self.assertIn("今日海巡", self.send("今日海巡")["text"])
        msgs = self.api.replies[-1]["messages"]
        uris = [b["action"]["uri"] for bub in msgs[1]["contents"]["contents"] for b in bub["footer"]["contents"]]
        self.assertEqual(len(uris), 2)
        self.assertTrue(all("/post/" in u for u in uris))
        self.assertFalse(any("/search?" in u for u in uris))
        self.assertIn("沒找到新的", self.send("今日海巡")["text"])                  # 看過的不重複給
        self.assertIn("每天自動找", self.send("海巡狀態")["text"])

    def test_scheduler_pushes_once_at_time(self):
        sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now)
        self.dt = self.dt.replace(hour=8, minute=59)
        self.assertEqual(sched.tick(), [])                                        # 還沒到 09:00
        self.dt = self.dt.replace(hour=9, minute=1)
        self.assertEqual(sched.tick()[0][0], "tenant-a")
        self.assertEqual(len(self.api.pushes), 1)
        self.assertEqual(sched.tick(), [])                                        # 同一天不重跑
        runs = self.store.read_json("tenant-a", *DB.RUNS)
        self.assertEqual((runs["posts"], runs["listings"]), (2, 2))
        self.dt += datetime.timedelta(days=1)
        self.assertEqual(sched.tick()[0][1], "nothing")                           # 隔天都看過了 → 不推
        self.assertEqual(len(self.api.pushes), 1)

    def test_failed_push_does_not_mark_seen_and_queue_keeps_no_content(self):
        sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now)
        real_notify = self.app.notify
        self.app.notify = lambda *a, **k: type("R", (), {"state": "failed"})()
        sched.tick()
        self.assertEqual(self.store.read_json("tenant-a", *DB.SEEN, default={}), {})   # 沒送到 → 不記看過
        self.app.notify = real_notify
        self.dt += datetime.timedelta(days=1)
        sched.tick()
        self.assertEqual(len(self.api.pushes), 1)
        queue = self.store.path("tenant-a", "line", "push_queue.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("threads.com", queue)                                    # 推播紀錄不留別人的貼文
        self.assertNotIn("西屯兩房", queue)

    def test_scheduler_loop_survives_errors(self):
        sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now, interval=0.01)
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("corrupt bindings")
        sched.tick = boom
        sched.start()
        import time
        time.sleep(0.1)
        sched.stop()
        self.assertGreater(len(calls), 1)                                         # 出錯後還在跑

    def test_without_search_service(self):
        app = create_app(store=self.store, channel=self.cfg, client_factory=self.factory, now=self.now)
        self.assertFalse(app.search.available)
        self.assertEqual(DailyScheduler(app, app.search, app.customers, now=self.now).tick(), [])


if __name__ == "__main__":
    unittest.main()


class PostFactsTests(unittest.TestCase):
    """負責人 2026-10-02：推給仲介要說清楚這是誰、幾點幾分發文、要找哪裡。"""

    def test_who_when_where(self):
        from core import post_facts as PF
        now = datetime.datetime(2026, 10, 2, 18, 0, tzinfo=PF.TW)
        url = "https://www.threads.com/@buyer_a/post/DNG2tXiBAAA"
        when = PF.posted_at(url)
        self.assertEqual((when.year, when.month, when.day), (2025, 8, 9))      # 網址代碼解出的發文時間
        lines = PF.describe(url, "合成名 (@buyer_a)", "想在宜蘭礁溪或羅東買透天，預算1500萬以內", now=now,
                            prefer_county="宜蘭縣")
        self.assertEqual(lines[0], "👤 @buyer_a（合成名）")
        self.assertTrue(lines[1].startswith("🕒 8/9 04:16 發文"))
        self.assertEqual(lines[2], "📍 想找：礁溪、羅東｜透天｜預算約 1500萬")
        self.assertIsNone(PF.posted_at("https://www.threads.com/@x"))
        self.assertEqual(PF.wants("台中西屯找整層，月租 25000 可養寵物", rent=True, prefer_county="台中市"),
                         "西屯｜整層｜月租約 25000 元")

    def test_cards_show_facts_newest_first(self):
        old = SearchHit("想買", "https://www.threads.com/@old/post/DNG2tXiBAAA", "宜蘭想買房")
        new = SearchHit("想買", "https://www.threads.com/@new/post/DPAAAAAAAAA", "宜蘭礁溪想買透天")
        g = DB.PK.build_groups({"宜蘭縣": ["*"]}, ["buy"], ["住宅"], ["買房"])[0]
        from core.post_triage import Verdict
        ok = Verdict(True, "想買")
        msgs = DB.messages_for({"posts": [(g, old, ok), (g, new, ok)], "listings": []}, datetime.date(2026, 10, 2),
                               patrol_only=True, now=datetime.datetime(2026, 10, 2, 18, 0, tzinfo=DB.post_facts.TW))
        flat = json.dumps(msgs[1], ensure_ascii=False)
        self.assertLess(flat.index("@new"), flat.index("@old"))                    # 新的在前
        self.assertIn("🕒", flat)
        self.assertIn("📍 想找：礁溪｜透天", flat)
        self.assertEqual(validate_message(msgs[1]), [])


class OwnerReportedNoiseTests(unittest.TestCase):
    """負責人 2026-10-02 截圖：宜蘭買住宅的海巡混進感情文、彰化政治、宜蘭租屋、同業標籤、成交文、房價心得、股票。"""

    def run_one(self, text, *, hours_ago=5, intent="buy"):
        from core.post_triage import judge
        now = datetime.datetime(2026, 10, 2, 18, 0, tzinfo=TW)
        return judge(text, county="宜蘭縣", area_term="宜蘭", intent=intent,
                     posted_at=now - datetime.timedelta(hours=hours_ago), now=now)

    def test_noise_is_dropped(self):
        noise = {
            "感情文": "我家的租客，變成了我的老婆—— 大二那年，我們在一堂外系選修課認識，常常約在咖啡廳討論",
            "外縣市政治": "彰化那麼爛連議員都在罵好嗎自己派系搞不定",
            "租屋": "宜蘭市能租到2萬以內的透天嗎？有剛好1房、2房想要轉租的！",
            "同業標籤": "宜蘭房仲#宜蘭在地房仲#宜蘭買房#宜蘭賣房#宜蘭房屋買賣#宜蘭首購",
            "成交文": "從看屋、議價、簽約，到今天順利交屋，很開心不只是促成一筆交易，而是陪著買方把買房變成一個家",
            "房價心得": "以前覺得台北生活貴，回宜蘭之後才發現房價、物價根本沒有哪裡真的便宜。",
            "股票": "0056 第四季配息有新進度！最新預估每單位配發1.72 元，預計10/22 除息。",
            "刊登文": "798萬買頭城海景透天！看得到龜山島。我們這間透天裡面完全不用整理，總共有6個房間，自然採光非常充足",
            "通勤閒聊": "體感宜蘭沒有內湖潮濕，公司有人住在宜蘭每天從宜蘭來內湖，太佩服",
        }
        for name, text in noise.items():
            with self.subTest(name):
                self.assertFalse(self.run_one(text).keep, name)

    def test_real_buyers_and_seller_leads_kept(self):
        for text in ("想在宜蘭礁溪或羅東買透天，預算1500萬以內，有推薦的社區嗎？", "準備在羅東買房了，第一次買房好緊張",
                     "宜蘭買透天好還是買大樓好？", "請問羅東哪裡有透天要賣的？"):
            with self.subTest(text):
                self.assertTrue(self.run_one(text).keep)
        self.assertFalse(self.run_one("我們也在宜蘭買房了～超開心").keep)                 # 已經買好的不是買方
        reply = self.run_one("一樓比較少見，我們也為了貓咪在宜蘭買房了～希望你早日找到合適的房子")
        self.assertEqual((reply.keep, reply.reason), (True, "留言提到有人在找房（點進去看原文）"))
        lead = self.run_one("我想要賣一間在蘇澳的透天房子，請問有推薦的房仲嗎？")
        self.assertTrue(lead.keep)
        self.assertIn("屋主想賣", lead.reason)
        self.assertTrue(self.run_one("想在宜蘭租整層，月租2萬內", intent="rent").keep)

    def test_three_day_lock(self):
        self.assertTrue(self.run_one("想在宜蘭買透天", hours_ago=71).keep)
        v = self.run_one("想在宜蘭買透天", hours_ago=73)
        self.assertEqual((v.keep, v.reason), (False, "超過 3 天"))

    def test_archive_keeps_every_candidate_once(self):
        import tempfile
        from adapters.storage import TenantStore
        with tempfile.TemporaryDirectory() as tmp:
            store = TenantStore(tmp)
            now = datetime.datetime(2026, 10, 2, 18, 0, tzinfo=TW)
            rec = {"url": post("x", 1), "keep": False, "reason": "跟房子無關"}
            self.assertEqual(DB.save_archive(store, [rec, rec], now), 1)
            self.assertEqual(DB.save_archive(store, [rec], now), 0)
            rows = store.read_jsonl(DB.SYS_PARTITION, *DB.ARCHIVE)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["first_seen"], "2026-10-02T18:00+08:00")


def bubbles(msg):
    c = msg["contents"]
    return c["contents"] if c["type"] == "carousel" else [c]


def ptt_url(when, board="home-sale"):
    return f"https://www.ptt.cc/bbs/{board}/M.{int(when.timestamp())}.A.1F3.html"


class PttSourceTests(unittest.TestCase):
    """負責人 2026-10-02「繞過那個限制」：不登入、不抓 Threads 頁面；多一個 PTT 房屋買賣板來源（網址就是發文時間）。"""

    def test_ptt_time_board_and_card_lines(self):
        from core import post_facts as PF
        when = datetime.datetime(2026, 10, 1, 21, 5, tzinfo=TW)
        url = ptt_url(when)
        self.assertEqual(PF.posted_at(url), when)
        self.assertEqual(PF.source_of(url), "ptt")
        lines = PF.describe(url, "[請益] 羅東買透天 預算1500萬 - 看板 home-sale - 批踢踢實業坊", "想在羅東買透天",
                            now=when + datetime.timedelta(hours=3), prefer_county="宜蘭縣")
        self.assertEqual(lines[0], "👤 PTT home-sale 板：[請益] 羅東買透天 預算1500萬")
        self.assertEqual(lines[1], "🕒 10/1 21:05 發文（約 3 小時前）")
        self.assertIsNone(PF.posted_at("https://www.ptt.cc/bbs/home-sale/index.html"))
        self.assertIsNone(PF.source_of("https://example.test/a"))

    def test_ptt_query_only_for_buyers(self):
        g = DB.PK.build_groups(PROSPECT["areas"], ["buy"], ["住宅"], PROSPECT["keywords"])[0]
        self.assertEqual(DB.ptt_query(g), "site:ptt.cc/bbs/home-sale 彰化 (買房 OR 找房 OR 請益)")
        rent = DB.PK.build_groups(PROSPECT["areas"], ["rent"], ["住宅"], None)[0]
        self.assertIsNone(DB.ptt_query(rent))
        self.assertEqual([(r, n) for _q, _p, r, n in DB.patrol_sources(g)], [("w", 2), ("w", 1)])
        self.assertEqual([(r, n) for _q, _p, r, n in DB.patrol_sources(g, quick=True)], [("d", 1), ("d", 1)])

    def test_collect_keeps_fresh_ptt_buyer_and_card_opens_ptt(self):
        now = datetime.datetime(2026, 10, 2, 9, 0, tzinfo=TW)
        good = ptt_url(now - datetime.timedelta(hours=5))
        old = ptt_url(now - datetime.timedelta(days=4))

        class S:
            def search(self, tenant, query, *, recency="d", page=1):
                if "ptt.cc" not in query:
                    return []
                return [SearchHit("[請益] 彰化員林買透天 - 看板 home-sale - 批踢踢實業坊", good, "想在彰化員林買透天，預算1200萬"),
                        SearchHit("[請益] 彰化買房 - 看板 home-sale", old, "想在彰化買房"),
                        SearchHit("Threads 混進 PTT 查詢", post("x", 9), "想在彰化買房")]
        r = DB.collect(tenant_id="t", search=S(), prospect=PROSPECT, customers=[], profile=None, seen={},
                       day=now.date(), now=now)
        self.assertEqual([h.url for _g, h, _v in r["posts"]], [good])
        self.assertEqual(r["dropped"], {"超過 3 天": 1})
        msgs = DB.messages_for(r, now.date(), patrol_only=True, now=now)
        for m in msgs:
            self.assertEqual(validate_message(m), [])
        action = bubbles(msgs[1])[0]["footer"]["contents"][0]["action"]
        self.assertEqual((action["label"], action["uri"]), ("開 PTT 看原文", good))


class ExtraPatrolRunTests(unittest.TestCase):
    """報告之後 13:00、19:00 再巡一次：搜尋引擎晚收錄的新貼文當天就給，不用等明天。"""
    send = support.CustomerIntakeTests.send
    tearDown = support.CustomerIntakeTests.tearDown

    def setUp(self):
        support.CustomerIntakeTests.setUp(self)
        test = self

        class Growing:
            name = "fake"

            def __init__(self):
                self.calls = []

            def search(self, query, *, recency="d", count=10, page=1):
                self.calls.append((test.dt.hour, recency, page))
                if "threads.com" not in query:
                    return []
                hits = [SearchHit("想買", post("early", 1), "想在彰化買透天")]
                if test.dt.hour >= 13:              # 中午之後搜尋引擎才收錄的新貼文
                    noon = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=TW)
                    hits.append(SearchHit("想買", post("noon", 2, when=noon), "彰化員林想買房，有推薦的嗎"))
                return hits
        self.fake = Growing()
        self.app = create_app(store=self.store, channel=self.cfg, client_factory=self.factory,
                              search_provider=self.fake, now=self.now)
        self.send("綁定 " + self.app.registry.issue_code("tenant-a"))
        self.sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now)

    def at(self, hh, mm, prospect=PROSPECT):
        self.store.write_json("tenant-a", "line", "prospect_setup.json", data={"profile": prospect})
        self.dt = self.dt.replace(hour=hh, minute=mm)
        return self.sched.tick()

    def test_two_extra_runs_push_only_new_posts(self):
        self.assertEqual(self.at(9, 1)[0][1], "sent")                           # 早上報告
        self.assertEqual(self.at(12, 59), [])
        self.assertEqual(self.at(13, 1), [("tenant-a", "sent")])               # 加報：中午的新貼文
        push = self.api.pushes[-1]["messages"]
        self.assertIn("海巡加報", push[0]["text"])
        self.assertEqual(len(bubbles(push[1])), 1)                               # 早上給過的不重給
        self.assertTrue(all(r == "d" and p == 1 for h, r, p in self.fake.calls if h >= 13))
        self.assertEqual(self.at(13, 30), [])
        self.assertEqual(self.at(19, 5), [("tenant-a", "nothing")])            # 沒有新的 → 不推
        self.assertEqual(len(self.api.pushes), 2)
        self.assertEqual(self.store.read_json("tenant-a", *DB.EXTRA)["slots"], ["13:00", "19:00"])
        self.assertEqual(self.at(21, 0), [])

    def test_waits_two_hours_after_a_late_report(self):
        late = {**PROSPECT, "time": "12:00"}
        self.assertEqual(self.at(12, 1, late)[0][1], "sent")
        self.assertEqual(self.at(13, 1, late), [])                              # 才隔 1 小時
        self.assertEqual(len(self.at(14, 2, late)), 1)
        self.assertEqual(self.at(16, 0, late), [])
        self.assertEqual(len(self.at(19, 1, late)), 1)

    def test_missed_slots_run_once(self):
        self.at(9, 1)
        self.assertEqual(len(self.at(20, 0)), 1)                                # 服務停到晚上：只補一次
        self.assertEqual(self.store.read_json("tenant-a", *DB.EXTRA)["slots"], ["13:00", "19:00"])
        self.assertEqual(self.at(20, 30), [])


class ListingQualityTests(unittest.TestCase):
    """2026-10-02 模擬一整天（真的搜尋服務）抓到的錯：店頭頁、別的縣市、套房給要公寓的人、售屋頁給租屋客人。"""
    BUY = {"transaction": "buy", "preferred_areas": ["宜蘭縣礁溪鄉", "宜蘭縣羅東鎮"], "budget_min": 1200,
           "budget_max": 1800, "property_type": "透天"}
    RENT = {"transaction": "rent", "preferred_areas": ["宜蘭縣宜蘭市"], "budget_min": 15000, "budget_max": 25000,
            "property_type": "公寓"}

    def why(self, title, url, snippet, need):
        return DB.listing_problem(SearchHit(title, url, snippet), need, None)

    def test_real_noise_is_dropped(self):
        cases = [
            ("羅東合成特許加盟店", "https://store.twhg.com.tw/TG21", "近羅運低總價美透天 宜蘭縣羅東鎮", self.BUY),
            ("買房- 21世紀不動產", "https://century21.com.tw/buy?order=newly&page=8", "精選房屋物件推薦", self.BUY),
            ("羅東透天 2600萬", "https://www.sinyi.com.tw/buy/house/AB1", "羅東 透天 2600萬", self.BUY),
            ("健身公寓！高CP值質感分租套房", "https://rent.591.com.tw/90000001", "宜蘭市 公寓 型態：獨立分租套房", self.RENT),
            ("合成店三星百坪田園農舍", "https://www.etwarm.com.tw/index.php/houses/buy/700001", "宜蘭市 農舍",
             self.RENT),
            ("麥寮鄉橋頭村套房出租", "https://rent.591.com.tw/90000002", "每月租金5500元", self.RENT),
            ("合成家園社區租金行情", "https://rent.591.com.tw/market/community?community_id=1", "宜蘭市 公寓", self.RENT),
            ("宜蘭市大公寓", "https://rent.591.com.tw/90000003", "宜蘭市 公寓 月租 32,000 元", self.RENT),
            ("宜蘭 公寓出租", "https://rent.591.com.tw/90000004", "宜蘭縣冬山鄉 公寓", self.RENT),
        ]
        for title, url, snippet, need in cases:
            with self.subTest(title):
                self.assertIsNotNone(self.why(title, url, snippet, need))

    def test_good_listings_kept(self):
        self.assertIsNone(self.why("礁溪合成全新透天A", "https://www.sinyi.com.tw/buy/house/XS1", "宜蘭縣礁溪鄉 1288萬", self.BUY))
        self.assertIsNone(self.why("東區學區稀有2樓公寓出租", "https://rent.591.com.tw/90000005",
                                   "宜蘭市 公寓 月租 18,000 元", self.RENT))

    def test_query_uses_full_name_when_district_equals_county(self):
        self.assertIn(" 宜蘭市 公寓 出租", DB.listing_query(self.RENT, None))


class ListingSweepRegressionTests(unittest.TestCase):
    """2026-10-02 全台抽查（8 種需求、76 筆真實結果）抓到的：路名當地區、標題寫店面、平台自己寫的型態。"""
    TAIPEI_RENT = {"transaction": "rent", "preferred_areas": ["台北市中山區"], "budget_max": 35000,
                   "property_type": "電梯大樓"}
    YILAN = {"transaction": "buy", "preferred_areas": ["宜蘭縣"], "budget_max": 2000, "property_type": "透天"}
    TAICHUNG = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_max": 1500, "property_type": "公寓"}
    ZHONGLI = {"transaction": "rent", "preferred_areas": ["桃園市中壢區"], "budget_max": 10000, "property_type": "套房"}

    def why(self, title, url, snippet, need):
        return DB.listing_problem(SearchHit(title, url, snippet), need, None)

    def test_road_name_or_other_county_is_not_the_area(self):
        self.assertIsNotNone(self.why("新北市永和區中山路一段比漾商圈電梯大樓", "https://rent.591.com.tw/90000006",
                                      "電梯大樓 35,000 元/月", self.TAIPEI_RENT))
        self.assertIsNotNone(self.why("中山路電梯大樓出租", "https://rent.591.com.tw/90000007", "電梯 30,000 元/月",
                                      self.TAIPEI_RENT))
        self.assertIsNone(self.why("中山國小站、新裝潢2房、電梯大樓", "https://rent.591.com.tw/90000008",
                                   "台北市 近捷運 有電梯", self.TAIPEI_RENT))
        # 中山區台北、基隆都有：沒看到縣市就不給（寧可少給）
        self.assertIsNotNone(self.why("中山國小站、新裝潢2房、電梯大樓", "https://rent.591.com.tw/90000009",
                                      "近捷運 有電梯", self.TAIPEI_RENT))

    def test_title_and_declared_type_win(self):
        self.assertIsNotNone(self.why("宜大蘭女旁店面｜宜蘭縣宜蘭市店面出售", "https://www.twhg.com.tw/buy/TG00000011",
                                      "宜蘭縣宜蘭市 透天 $1900 萬", self.YILAN))
        self.assertIsNotNone(self.why("合成大樓24樓3房高樓層B2平面車位", "https://www.rakuya.com.tw/sell_item/info?ehid=1",
                                      "位於台中市西屯區台灣大道三段，總價1388萬，房屋類型為電梯大廈，格局為3房", self.TAICHUNG))
        self.assertIsNone(self.why("文華高中捷運旁低總價健身三房", "https://www.twhg.com.tw/buy/TB00000012",
                                   "台中市西屯區漢成六街. 類型. 公寓. 格局. 3房2廳1衛", self.TAICHUNG))
        self.assertIsNone(self.why("合成步道旁透天｜宜蘭縣羅東鎮住宅出售", "https://www.twhg.com.tw/buy/TG00000013",
                                   "詳細資料 ; 類型. 透天別墅 ; 格局. 4房3廳4衛", self.YILAN))

    def test_suite_renter_cares_about_the_room_not_the_building(self):
        self.assertIsNone(self.why("中壢合成公園優質套房", "https://rent.591.com.tw/90000010",
                                   "用途：分租套房 型態：透天 住址：桃園市中壢區龍東十二街 租金：5300", self.ZHONGLI))


class ListingTitleWinsTests(unittest.TestCase):
    """第二次全台抽查：摘要混著店家地址或同頁別的物件，標題寫的區和型態才是這間。"""

    def why(self, title, snippet, need):
        return DB.listing_problem(SearchHit(title, "https://www.twhg.com.tw/buy/TB00000014", snippet), need, None)

    def test_title_district_wins_over_snippet(self):
        need = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_max": 1500, "property_type": "公寓"}
        self.assertEqual(self.why("合成公園旁活路低總價可改套公寓｜台中市北區住宅出售", "台中市西屯區漢成六街 公寓 $698 萬", need),
                         "講的是同縣市的別區")
        tainan = {"transaction": "buy", "preferred_areas": ["台南市東區"], "budget_max": 1200, "property_type": "華廈"}
        self.assertEqual(self.why("近探索公園明亮整新三房｜台南市永康區住宅出售", "台南合成特許加盟店 台南市東區 華廈", tainan),
                         "講的是同縣市的別區")
        whole = {"transaction": "buy", "preferred_areas": ["宜蘭縣"], "budget_max": 2000, "property_type": "透天"}
        self.assertIsNone(self.why("三星合成山莊透天別墅｜宜蘭縣三星鄉住宅出售", "類型. 透天別墅", whole))   # 整個縣都要

    def test_title_kind_wins_over_declared_type_of_other_listing(self):
        whole = {"transaction": "buy", "preferred_areas": ["宜蘭縣"], "budget_max": 2000, "property_type": "透天"}
        self.assertEqual(self.why("宜大蘭女旁店面｜宜蘭縣宜蘭市店面出售", "宜蘭縣宜蘭市 $1900 萬 類型. 透天別墅", whole),
                         "型態不符（標題寫的是別的型態）")
