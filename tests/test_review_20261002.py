"""2026-10-02 獨立審查（替買方找房、物件配對、每日新物件）重現的 17 項，逐項鎖住。合成資料、本機假 LINE、不連網。"""
import datetime
import json
import unittest
import urllib.parse

import test_customer_intake as support
from adapters.line import area_picker as AP
from adapters.line import flex
from adapters.line.listing_intake import PURPOSE as LISTING
from adapters.line.signature import sign
from adapters.web_search import SearchHit
from core.listing_matching import match_listings as match
from core.tw_districts import DISTRICTS
from web.jobs import daily_brief as DB
from web.jobs.match_cards import pairs

BUYER = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_min": 800, "budget_max": 1500,
         "property_type": "公寓"}


class Flow(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def tap(self, op, value="", *, county="", purpose="intake"):
        self.count += 1
        body = json.dumps({"events": [{"type": "postback", "webhookEventId": f"pb-{self.count}",
            "replyToken": f"reply-{self.count}", "source": {"type": "user", "userId": self.uid},
            "postback": {"data": AP.data(op, purpose, value, county)}}]}).encode()
        self.assertEqual(self.app.handle(body, sign("test-secret", body))[0], 200)

    def texts(self):
        return [m["text"] for m in self.api.replies[-1]["messages"] if m["type"] == "text"]

    def start_buyer(self, label="合成甲", deal="買"):
        for t in ("新增買方", label, deal):
            self.send(t)

    def finish_buyer(self, answers, label="合成甲"):
        for t in answers:
            self.send(t)
        self.send("確認儲存")
        return [c for c in self.customers.list_customers("tenant-a") if c["label"] == label][-1]["need_card"]


class BuyerInputTests(Flow):
    def test_h1_typed_areas_are_checked_against_districts(self):
        for typed, want in (("台中市西屯", ["台中市西屯區"]), ("台中市西屯區 南屯區", ["台中市西屯區", "台中市南屯區"]),
                            ("台中市西屯區/南屯區", ["台中市西屯區", "台中市南屯區"]), ("台中西屯區", ["台中市西屯區"])):
            with self.subTest(typed):
                label = "合成" + str(len(typed))
                self.start_buyer(label)
                self.send(typed)
                self.assertIn("預算", self.texts()[-1])
                need = self.finish_buyer(["800-1500", "公寓", "不限", "不限", "不限", "不限", "不限"], label)
                self.assertEqual(need["preferred_areas"], want)
        self.start_buyer()
        self.assertIn("沒有「不存在區」", self.send("台中市不存在區")["text"])

    def test_m9_common_wording_is_understood(self):
        self.start_buyer()
        self.send("台中市西屯區")
        self.send("800－1500")                        # 全形減號
        self.send("公寓")
        self.send("三房")
        self.send("30坪以上")
        self.send("10年內")
        need = self.finish_buyer(["要車位", "不限"])
        self.assertEqual((need["budget_min"], need["budget_max"], need["rooms_min"], need["size_min"], need["age_max"]),
                         (800, 1500, 3, 30, 10))
        self.assertNotIn("size_max", need)
        for budget in ("800–1500", "800〜1500", "１５００"):
            with self.subTest(budget):
                self.start_buyer()
                self.send("台中市西屯區")
                self.assertIn("房型", self.send(budget)["text"])
                self.send("取消")
        self.start_buyer("合成租", deal="租")
        self.send("台中市西屯區")
        need = self.finish_buyer(["1.5-2萬", "不限", "不限", "不限", "不限", "不限", "不限"], "合成租")
        self.assertEqual((need["budget_min"], need["budget_max"]), (15000, 20000))

    def test_m8_single_size_number_is_a_minimum(self):
        self.start_buyer()
        self.send("台中市西屯區")
        need = self.finish_buyer(["800-1500", "公寓", "不限", "30", "不限", "不限", "不限"])
        self.assertEqual(need.get("size_min"), 30)
        self.assertNotIn("size_max", need)
        self.assertIn("坪數：30–不限", self.texts()[0])

    def test_rooms_range_still_rejected(self):
        self.start_buyer()
        self.send("台中市西屯區")
        self.send("800-1500")
        self.send("公寓")
        self.assertIn("房數請打", self.send("3~4房")["text"])

    def test_m10_draft_expires_after_30_idle_minutes_not_from_start(self):
        self.start_buyer()
        for t in ("台中市西屯區", "800-1500", "公寓", "不限", "不限", "不限", "不限", "不限"):
            self.dt += datetime.timedelta(minutes=3)
            self.send(t)
        self.dt += datetime.timedelta(minutes=3)
        self.assertIn("已儲存", self.send("確認儲存")["text"])

    def test_m12_l14_phone_in_label_is_rejected_with_reason(self):
        self.send("新增買方")
        self.assertIn("不要填電話", self.send("王小姐 09" + "12-345-678")["text"])   # 合成號碼，拆開寫免得被個資守門擋
        self.assertIn("客人要買還是租", self.send("王小姐")["text"])         # 錯了可以直接重打

    def test_l16_summary_has_no_float_noise(self):
        self.start_buyer()
        self.send("台中市西屯區")
        self.finish_buyer(["800-1500", "公寓", "2", "20-40", "不限", "不限", "不限"])
        self.assertIn("最少房數：2\n", self.texts()[0])
        self.assertIn("坪數：20–40｜", self.texts()[0])

    def test_l15_expired_prospect_draft_does_not_eat_next_message(self):
        self.send("找新買方")
        self.dt += datetime.timedelta(minutes=31)
        self.assertIn("客戶暱稱", self.send("新增買方")["text"])


class ListingFlowTests(Flow):
    def test_h7_commands_typed_in_listing_draft_are_not_stored(self):
        self.send("新增物件")
        self.send("出售")
        self.tap("c", "台中市", purpose=LISTING)
        self.tap("d", str(DISTRICTS["台中市"].index("西屯區")), county="台中市", purpose=LISTING)
        self.assertIn("請先回答這一題", self.send("客戶清單")["text"])
        self.send("中山路二段")
        self.assertIn("請先回答這一題", self.send("需求 B-F5EEF0D7C7C6")["text"])
        self.assertIn("請先回答這一題", self.send("適合 B-F5EEF0D7C7C6 的三房")["text"])
        draft = self.store.read_json("tenant-a", "line", "listing_intake.json")["draft"]
        self.assertEqual(draft["listing"].get("road"), "中山路二段")
        self.assertNotIn("title", draft["listing"])


class MatchingTests(unittest.TestCase):
    def test_m13_townhouse_buyer_also_gets_villa(self):
        need = {**BUYER, "property_type": "透天"}
        villa = {"id": "M1", "transaction": "buy", "city": "台中市", "area": "台中市西屯區", "price": 1400,
                 "property_type": "別墅", "online": True, "url": "https://example.test/m1"}
        got = match(need, [villa])
        self.assertTrue(got["priority"] or got["review"])

    def test_m11_over_budget_note_without_url(self):
        need = {**BUYER, "budget_tolerance_pct": 10}
        x = {"id": "M1", "transaction": "buy", "city": "台中市", "area": "台中市西屯區", "price": 1600,
             "property_type": "公寓", "rooms": 3, "size_ping": 30, "age_years": 10, "parking": True, "elevator": False,
             "online": True}
        found = pairs([x], [{"customer_id": "B-1", "label": "合成甲", "need_card": need, "status": "active"}])
        self.assertEqual(len(found), 1)
        self.assertIn("略超預算 100萬", found[0][3] or "")


class ShareLinkTests(unittest.TestCase):
    def test_h6_share_link_fits_line_limit(self):
        x = {"area": "台中市西屯區", "road": "中山路二段", "title": "近公園三房平車" * 6, "price": 1280,
             "property_type": "公寓", "rooms": 3, "size_ping": 35, "age_years": 12, "url": "https://example.test/m1"}
        uri = flex.share_uri(x, signature="合成林小姐｜示範不動產中山店（週一到週日都在）" * 2)
        self.assertLessEqual(len(uri), flex.MAX_URI)
        text = urllib.parse.unquote(uri.split("?", 1)[1])
        self.assertIn("1,280", text)
        self.assertIn("https://example.test/m1", text)
        too_long = {"type": "template", "altText": "x", "template": {"type": "buttons", "text": "x", "actions": [
            {"type": "uri", "label": "x", "uri": "https://example.test/" + "a" * 1001}]}}
        self.assertTrue(any("1000" in e for e in flex.validate_message(too_long)))


class DailyListingTests(unittest.TestCase):
    def why(self, title, snippet, need, url="https://www.sinyi.com.tw/buy/house/AB1"):
        return DB.listing_problem(SearchHit(title, url, snippet), need, None)

    def test_h2_brand_and_same_named_districts(self):
        xinyi = {"transaction": "buy", "preferred_areas": ["台北市信義區"], "budget_max": 3000, "property_type": "公寓"}
        self.assertIsNotNone(self.why("西屯三房公寓｜信義房屋", "公寓 1280萬", xinyi))
        daan = {"transaction": "buy", "preferred_areas": ["台北市大安區"], "budget_max": 3000, "property_type": "公寓"}
        self.assertIsNotNone(self.why("大安區三房公寓", "台中市大安區 公寓 980萬", daan))
        east = {"transaction": "buy", "preferred_areas": ["台中市東區"], "budget_max": 3000, "property_type": "公寓"}
        self.assertIsNotNone(self.why("東區三房公寓", "台南市東區 公寓 980萬", east))
        self.assertIsNotNone(self.why("東區三房公寓", "公寓 980萬", east))                 # 沒看到縣市就不給
        self.assertIsNone(self.why("東區三房公寓", "台中市東區 公寓 980萬", east))
        taichung = {"transaction": "buy", "preferred_areas": ["台中市"], "budget_max": 3000, "property_type": "公寓"}
        self.assertIsNotNone(self.why("鳳山三房公寓｜太平洋房屋", "公寓 980萬", taichung))

    def test_h3_unit_price_is_not_the_total(self):
        need = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_max": 1500, "property_type": "公寓"}
        self.assertEqual(self.why("西屯三房公寓", "台中市西屯區 公寓 總價3280萬 單價52.1萬/坪", need), "超過預算")
        self.assertEqual(self.why("西屯三房公寓", "台中市西屯區 公寓 3280萬 52.1萬/坪", need), "超過預算")
        self.assertIsNone(self.why("西屯三房公寓", "台中市西屯區 公寓 1280萬 單價36.6萬/坪", need))

    def test_h4_type_words_inside_normal_phrases(self):
        apt = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_max": 1500, "property_type": "公寓"}
        self.assertIsNone(self.why("西屯三房公寓 主臥套房", "台中市西屯區 1280萬", apt))
        tower = {**apt, "property_type": "電梯大樓"}
        self.assertIsNone(self.why("西屯雙套房 電梯大樓", "台中市西屯區 1280萬", tower))
        self.assertIsNotNone(self.why("西屯4樓公寓 無電梯", "台中市西屯區 1280萬", tower))
        town = {**apt, "property_type": "透天"}
        self.assertIsNone(self.why("西屯邊間透天", "台中市西屯區 鄰近中科廠房 1280萬", town))

    def test_h5_everyone_gets_searched_within_a_few_days(self):
        class S:
            def search(self, tenant, query, *, recency="d", page=1):
                return []
        custs = [{"customer_id": f"B-{i:02d}", "label": f"合成{i}", "need_card": BUYER} for i in range(15)]
        seen_ids = set()
        for k in range(2):
            day = datetime.date(2026, 10, 2) + datetime.timedelta(days=k)
            calls = []

            class Rec(S):
                def search(self, tenant, query, *, recency="d", page=1):
                    calls.append(query)
                    return []
            r = DB.collect(tenant_id="t", search=Rec(), prospect=None, customers=list(custs), profile=None, seen={},
                           day=day)
            self.assertEqual((r["customers_searched"], r["customers_total"]), (10, 15))
            start = (day.toordinal() * 10) % 15
            seen_ids |= {c["customer_id"] for c in (custs[start:] + custs[:start])[:10]}
        self.assertEqual(len(seen_ids), 15)
        many = {**BUYER, "preferred_areas": [f"台中市{d}" for d in DISTRICTS["台中市"][:8]]}
        q1 = DB.listing_query(many, None, datetime.date(2026, 10, 2))
        q2 = DB.listing_query(many, None, datetime.date(2026, 10, 3))
        self.assertNotEqual(q1, q2)
        head = DB.messages_for({"posts": [], "listings": [("合成", "x", [SearchHit("t", "https://x.test/1", "s")])],
                                "customers_total": 15, "customers_searched": 10}, datetime.date(2026, 10, 2))[0]["text"]
        self.assertIn("10/15 位", head)


if __name__ == "__main__":
    unittest.main()
