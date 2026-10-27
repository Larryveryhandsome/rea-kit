"""配對錯配回歸測試：實務上配對稽核找到的根因，改寫成通用規則（合成資料，不含任何真實客戶）。

只收對本產品適用的：本產品的需求是結構化欄位（不從群名、自由文字猜），所以「群名編號被當預算」
「排除語意反向」這類解析錯誤不會發生；適用的是排序、身分鍵、髒值、賣方、缺區域。
"""
import unittest

import test_customer_intake as support
from core.listing_matching import match_listings
from web.jobs.match_cards import pairs

NEED = {"transaction": "buy", "preferred_areas": ["台中市"], "budget_max": 800, "budget_tolerance_pct": 10}


def L(lid, price, **kw):
    return {"id": lid, "transaction": "buy", "area": "台中市西屯區", "price": price,
            "url": f"https://example.test/{lid}", **kw}


class MatchingRegressionTests(unittest.TestCase):
    def test_over_budget_never_ranks_first(self):
        """根因：容忍 5–10% 的超預算物件，常被其他加分推到第一名，理由還印成「838萬≤800」。"""
        out = match_listings(NEED, [L("over", 838), L("in1", 798), L("in2", 760)])
        order = [r["listing_id"] for r in out["priority"]]
        self.assertEqual(order[-1], "over")
        self.assertIn("over budget by 38", out["priority"][-1]["reasons"])
        self.assertNotIn("over budget by", " ".join(out["priority"][0]["reasons"]))

    def test_ties_have_a_fixed_useful_order(self):
        """根因：同分只靠編號排，某些物件天天排最後、永遠推不到。改成新上架先、屋齡新的先。"""
        rows = [L("a", 700, listed_at="2026-09-01", age_years=30), L("b", 700, listed_at="2026-09-20", age_years=30),
                L("c", 700, listed_at="2026-09-20", age_years=5), L("d", 700)]
        order = [r["listing_id"] for r in match_listings(NEED, rows)["priority"]]
        self.assertEqual(order, ["c", "b", "a", "d"])

    def test_cards_say_over_budget_in_plain_words(self):
        rows = [{"customer_id": "B-1", "label": "合成甲", "status": "active", "need_card": NEED}]
        found = pairs([L("over", 838)], rows)
        self.assertEqual(found[0][3], "略超預算 38萬")

    def test_same_nickname_two_customers_stay_separate(self):
        """根因：用姓名當去重鍵，8 位沒暱稱的客戶共用一份「已推過」，互相把物件燒掉。"""
        rows = [{"customer_id": "B-1", "label": "王先生", "status": "active", "need_card": NEED},
                {"customer_id": "B-2", "label": "王先生", "status": "active", "need_card": NEED}]
        self.assertEqual(len(pairs([L("x", 700)], rows)), 2)

    def test_need_without_area_is_not_matched(self):
        """根因：沒寫區域＝完全不過濾，八成客戶收到同一張全縣廣告單，還推到外縣市。"""
        rows = [{"customer_id": "B-1", "label": "缺區域", "status": "active",
                 "need_card": {"transaction": "buy", "budget_max": 800}}]
        self.assertEqual(pairs([L("x", 700)], rows), [])
        with self.assertRaises(ValueError):
            match_listings({"transaction": "buy", "budget_max": 800}, [L("x", 700)])

    def test_other_county_never_matches(self):
        out = match_listings({**NEED, "preferred_areas": ["台中市"]},
                             [L("tc", 700, area="台中市西屯區"), L("tp", 700, area="台北市中正區")])
        self.assertEqual([r["listing_id"] for r in out["priority"]], ["tc"])

    def test_seller_or_unknown_deal_is_not_matched(self):
        """根因：賣方（屋主）被當買方配對，差點把別人的房子推進屋主的群。"""
        for deal in ("sell", None, ""):
            rows = [{"customer_id": "B-1", "label": "屋主", "status": "active",
                     "need_card": {**NEED, "transaction": deal}}]
            self.assertEqual(pairs([L("x", 700)], rows), [])


class IntakeDirtyValueTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def step(self):
        return self.store.read_json("tenant-a", "line", "customer_intake.json")["draft"]["step"]

    def test_rooms_like_34_are_rejected(self):
        """根因：「3~4 房」存成 34 房，九成物件被濾掉、畫面不報錯。"""
        for text in ["新增買方", "合成甲", "買", "台中市", "800-1500", "公寓"]:
            self.send(text)
        self.assertIn("房數請打 0–10", self.send("34")["text"])
        self.assertEqual(self.step(), "rooms")
        self.send("3")
        self.assertEqual(self.step(), "size")

    def test_budget_units_are_checked(self):
        """根因：買方被當租客，500 萬變成月租 500 萬元；或把萬當元打。"""
        for text in ["新增買方", "合成乙", "租", "台中市"]:
            self.send(text)
        self.assertIn("月租單位是元", self.send("5000000")["text"])
        self.assertIn("月租單位是元", self.send("2.5")["text"])
        self.send("15000-25000")
        self.assertEqual(self.step(), "type")
        self.send("取消")
        for text in ["新增買方", "合成丙", "買", "台中市"]:
            self.send(text)
        self.assertIn("總價單位是萬元", self.send("8000000")["text"])
        self.send("800-1500")
        self.assertEqual(self.step(), "type")


if __name__ == "__main__":
    unittest.main()
