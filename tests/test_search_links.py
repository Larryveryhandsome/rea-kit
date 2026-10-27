"""每位買方的找房連結：591 原生連結（實際操作讀到的格式）＋其他平台 Google 限站近一週；避開自己品牌。"""
import json
import unittest
import urllib.parse

import test_customer_intake as support
from adapters.line.flex import validate_message
from core.search_links import PLATFORMS, links_for

NEED = {"transaction": "buy", "preferred_areas": ["台中市西屯區", "台中市南屯區"], "budget_min": 800,
        "budget_max": 1500, "property_type": "公寓", "rooms_min": 3}


def query(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


class SearchLinksTests(unittest.TestCase):
    def test_591_native_link_matches_observed_format(self):
        label, url = links_for(NEED)[0]
        self.assertEqual(label, "591 最新")
        self.assertTrue(url.startswith("https://sale.591.com.tw/?"))
        self.assertEqual(query(url), {"regionid": "8", "shType": "list", "order": "posttime_desc",
                                      "price": "800_1500", "shape": "1", "pattern": "3"})

    def test_other_platforms_are_site_limited_recent_searches(self):
        links = dict(links_for(NEED))
        q = query(links["信義房屋（近一週）"])
        self.assertEqual(q["tbs"], "qdr:w")
        self.assertEqual(q["q"], "site:sinyi.com.tw 西屯區 南屯區 公寓 出售")
        self.assertIn("全網搜尋（近一週）", links)
        self.assertIn("800-1500萬", query(links["全網搜尋（近一週）"])["q"])
        self.assertEqual(len(links), 1 + len(PLATFORMS) - 1 + 1)

    def test_own_brand_hidden_unless_opted_in(self):
        names = [l for l, _ in links_for(NEED, {"brand": "信義房屋", "include_own_brand": False})]
        self.assertNotIn("信義房屋（近一週）", names)
        names = [l for l, _ in links_for(NEED, {"brand": "信義房屋", "include_own_brand": True})]
        self.assertIn("信義房屋（近一週）", names)
        names = [l for l, _ in links_for(NEED, {"brand": "合成房屋", "include_own_brand": False})]
        self.assertEqual(len(names), len(links_for(NEED)))           # 清單外品牌：不影響

    def test_rent_and_multi_county(self):
        need = {"transaction": "rent", "preferred_areas": ["彰化縣", "台中市西屯區"], "budget_max": 25000}
        links = dict(links_for(need))
        self.assertNotIn("591 最新", links)                           # 租屋格式沒看過，不猜
        self.assertIn("site:rent.591.com.tw 彰化縣 西屯區 出租", query(links["591（近一週）"])["q"])
        self.assertIn("25000元以內", query(links["全網搜尋（近一週）"])["q"])
        buy = dict(links_for({**need, "transaction": "buy", "budget_max": 1500}))
        self.assertIn("591 最新・彰化", buy)
        self.assertIn("591 最新・台中", buy)

    def test_labels_and_urls_fit_line(self):
        for label, url in links_for(NEED, {}):
            self.assertLessEqual(len(label), 20)
            self.assertTrue(url.startswith("https://"))
            self.assertLess(len(url), 1000)


class SearchCardFlowTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def test_need_command_returns_links_card_with_brand_note(self):
        c = self.customers.save_need("tenant-a", label="合成甲", need=NEED)
        self.send(f"找房 {c['customer_id']}")
        msgs = self.api.replies[-1]["messages"]
        self.assertIn("合成甲", msgs[0]["text"])
        card = msgs[1]
        self.assertEqual(validate_message(card), [])
        flat = json.dumps(card, ensure_ascii=False)
        self.assertIn("還沒設定你的品牌", flat)
        self.assertIn("信義房屋（近一週）", flat)
        for text in ["我的資料", "信義房屋", "避開我的品牌", "略過"]:
            self.send(text)
        self.send(f"需求 {c['customer_id']}")
        flat = json.dumps(self.api.replies[-1]["messages"][1], ensure_ascii=False)
        self.assertIn("已避開你的品牌：信義房屋", flat)
        self.assertNotIn("信義房屋（近一週）", flat)

    def test_saved_buyer_reply_ends_with_links_card(self):
        for text in ["新增買方", "合成乙", "買", "台中市西屯區", "800-1500", "公寓", "2", "不限", "不限", "不限", "不限",
                     "確認儲存"]:
            self.send(text)
        msgs = self.api.replies[-1]["messages"]
        self.assertIn("已儲存", msgs[0]["text"])
        self.assertIn("找房連結：合成乙", msgs[-1]["altText"])
        self.assertLessEqual(len(msgs), 5)


if __name__ == "__main__":
    unittest.main()
