"""新增物件 → 比對自己的買方 → 配對卡（推給誰＋分享鈕）；基本資料（品牌、署名）。合成資料、本機假 LINE。"""
import json
import unittest
import urllib.parse

import test_customer_intake as support
from adapters.line import area_picker as AP
from adapters.line.agent_profile import STATE as PROFILE_STATE
from adapters.line.flex import unit_price, validate_message
from adapters.line.listing_intake import PURPOSE, STATE
from adapters.line.signature import sign
from core.tw_districts import DISTRICTS
from web.jobs.match_cards import pairs

BUYER = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_min": 800, "budget_max": 1500,
         "property_type": "公寓"}
ANSWERS = ["中山路二段", "合成三房平車", "1280", "公寓", "3", "35", "12", "有車位", "沒有電梯",
           "https://example.test/m1"]


class ListingMatchFlowTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def tap(self, op, value="", *, county="", purpose=PURPOSE):
        self.count += 1
        body = json.dumps({"events": [{"type": "postback", "webhookEventId": f"pb-{self.count}",
            "replyToken": f"reply-{self.count}", "source": {"type": "user", "userId": self.uid},
            "postback": {"data": AP.data(op, purpose, value, county)}}]}).encode()
        self.assertEqual(self.app.handle(body, sign("test-secret", body))[0], 200)
        hit = [r for r in self.api.replies if r["replyToken"] == f"reply-{self.count}"]
        return hit[0]["messages"] if hit else []

    def last(self):
        return self.api.replies[-1]["messages"]

    def add_listing(self, answers=ANSWERS, county="台中市", district="西屯區"):
        self.send("新增物件")
        card = self.send("出售")
        self.assertIn("物件在哪個縣市", card["altText"])
        self.assertIn("在哪一區", self.tap("c", county)[-1]["altText"])
        self.assertIn("在哪條路", self.tap("d", str(DISTRICTS[county].index(district)), county=county)[-1]["text"])
        for text in answers:
            self.send(text)
        self.assertIn("確認儲存", self.last()[0]["text"])
        self.send("確認儲存")
        return self.last()

    def cards(self, messages):
        return [b for m in messages if m["type"] == "flex"
                for b in (m["contents"]["contents"] if m["contents"]["type"] == "carousel" else [m["contents"]])]

    def share_text(self, bubble):
        uri = [b["action"]["uri"] for b in bubble["footer"]["contents"] if "分享" in b["action"]["label"]][0]
        return urllib.parse.unquote(uri.split("?", 1)[1])

    def test_profile_brand_signature(self):
        self.assertIn("哪個品牌", self.send("我的資料")["text"])
        self.assertIn("自己品牌", self.send("信義房屋")["text"])
        self.send("避開我的品牌")
        self.assertIn("已保存", self.send("合成林小姐｜示範店")["text"])
        profile = self.store.read_json("tenant-a", *PROFILE_STATE)["profile"]
        self.assertEqual((profile["brand"], profile["include_own_brand"], profile["signature"]),
                         ("信義房屋", False, "合成林小姐｜示範店"))
        self.assertIn("品牌：信義房屋", self.send("我的資料")["text"])
        self.send("修改我的資料")
        self.send("其他（自己打）")
        self.send("合成房屋")
        self.send("我的品牌也要")
        self.send("略過")
        profile = self.store.read_json("tenant-a", *PROFILE_STATE)["profile"]
        self.assertEqual((profile["brand"], profile["include_own_brand"], profile["signature"]), ("合成房屋", True, None))
        self.assertIsNone(self.store.read_json("tenant-b", *PROFILE_STATE, default=None))

    def test_new_listing_matches_my_buyers_with_share_card(self):
        self.send("我的資料")
        self.send("自營／個人工作室")
        self.send("合成林小姐")
        a = self.customers.save_need("tenant-a", label="合成甲", need=BUYER)
        self.customers.save_need("tenant-a", label="合成乙", need={**BUYER, "preferred_areas": ["台北市"]})
        self.customers.save_need("tenant-b", label="別人的客人", need=BUYER)          # 別的仲介
        msgs = self.add_listing()
        self.assertIn("已存成 M001", msgs[0]["text"])
        self.assertIn("1 位可能適合", msgs[0]["text"])
        cards = self.cards(msgs)
        self.assertEqual(len(cards), 1)
        flat = json.dumps(cards[0], ensure_ascii=False)
        self.assertIn("推給：合成甲", flat)
        self.assertIn("需求：買｜台中市西屯區｜800–1500萬｜公寓", flat)
        self.assertIn("台中市西屯區・中山路二段", flat)
        self.assertIn("每坪約 36.6 萬", flat)
        self.assertNotIn("別人的客人", flat)
        self.assertNotIn("合成乙", flat)
        text = self.share_text(cards[0])
        for leak in ("合成甲", "M001", "推給", "需求", a["customer_id"]):
            self.assertNotIn(leak, text)
        self.assertIn("https://example.test/m1", text)
        self.assertTrue(text.endswith("合成林小姐"))
        for m in msgs:
            self.assertEqual(validate_message(m), [])
        saved = self.store.read_json("tenant-a", "listings", "snapshot.json")["M001"]
        self.assertEqual((saved["area"], saved["road"], saved["parking"], saved["elevator"], saved["own"]),
                         ("台中市西屯區", "中山路二段", True, False, True))
        self.assertIsNone(self.store.read_json("tenant-b", "listings", "snapshot.json", default=None))

    def test_buyer_conditions_are_all_used(self):
        """回歸：以前 need_of 只給配對引擎 6 個欄位，要電梯的客人會配到沒電梯的物件。"""
        self.customers.save_need("tenant-a", label="要電梯", need={**BUYER, "elevator": "required"})
        self.customers.save_need("tenant-a", label="要新屋", need={**BUYER, "age_max": 5})
        self.customers.save_need("tenant-a", label="都可以", need=BUYER)
        flat = json.dumps(self.cards(self.add_listing()), ensure_ascii=False)
        self.assertIn("推給：都可以", flat)
        self.assertNotIn("推給：要電梯", flat)                      # 物件「沒有電梯」
        self.assertNotIn("推給：要新屋", flat)                      # 屋齡 12 年

    def test_unknown_field_listed_as_to_confirm(self):
        self.customers.save_need("tenant-a", label="要電梯", need={**BUYER, "elevator": "required"})
        answers = ANSWERS[:8] + ["略過", "略過"]                   # 電梯略過、沒有網址
        cards = self.cards(self.add_listing(answers))
        flat = json.dumps(cards, ensure_ascii=False)
        self.assertIn("要確認：電梯", flat)
        self.assertNotIn("看物件", json.dumps(cards[0]["footer"], ensure_ascii=False))   # 沒網址就只有分享鈕
        self.assertIn("分享", json.dumps(cards[0]["footer"], ensure_ascii=False))

    def test_new_buyer_gets_matching_listings(self):
        self.add_listing()
        for text in ["新增買方", "合成丙", "買"]:
            self.send(text)
        self.tap("c", "台中市", purpose="intake")
        self.tap("next", purpose="intake")
        self.tap("d", "*", county="台中市", purpose="intake")
        for text in ["800-1500", "公寓", "2", "不限", "不限", "不限", "不限", "確認儲存"]:
            self.send(text)
        msgs = self.last()
        self.assertIn("已儲存", msgs[0]["text"])
        self.assertIn("1 間可能適合 合成丙", msgs[1]["text"])
        self.assertIn("推給：合成丙", json.dumps(self.cards(msgs), ensure_ascii=False))

    def test_digest_list_and_online_toggle(self):
        self.assertIn("尚未接通", self.send("新案")["text"])         # 沒物件：講實話
        self.customers.save_need("tenant-a", label="合成甲", need=BUYER)
        self.add_listing()
        self.add_listing(county="台中市", district="南屯區")
        self.assertIn("M001", self.send("我的物件")["text"])
        self.assertIn("共 1 組配對", self.send("新案")["text"])     # 南屯那間不適合
        self.send("下架 M001")
        self.assertIn("目前都沒有適合", self.send("新案")["text"])
        self.assertIn("已下架", self.send("配對 M001")["text"])
        self.send("上架 M001")
        self.assertIn("1 位買方可能適合", self.send("配對 m001")["text"])
        self.assertIn("找不到 M099", self.send("物件 M099")["text"])

    def test_privacy_validation(self):
        self.send("新增物件")
        self.send("出售")
        self.tap("c", "台中市")
        self.tap("d", "0", county="台中市")
        self.assertIn("不要寫門牌", self.send("中山路二段12號")["text"])
        fake_phone = "09" + "1" * 8                               # 合成；拆開寫免得 pii_scan 誤擋
        self.assertIn("不要放電話", self.send(fake_phone)["text"])
        self.send("中山路二段")
        self.assertIn("不要放電話", self.send(f"屋主{fake_phone[:4]}-{fake_phone[4:7]}-{fake_phone[7:]}")["text"])
        self.send("略過")
        self.assertIn("請打數字", self.send("很便宜")["text"])
        draft = self.store.read_json("tenant-a", *STATE)["draft"]
        self.assertEqual((draft["step"], draft["listing"]["road"]), ("price", "中山路二段"))
        self.assertNotIn("title", draft["listing"])

    def test_typed_area_and_cancel(self):
        self.send("新增物件")
        self.send("出租")
        self.assertIn("在哪條路", self.send("臺中市西屯區")["text"])
        self.send("取消")
        self.assertIsNone(self.store.read_json("tenant-a", *STATE)["draft"])
        self.assertEqual(self.store.read_json("tenant-a", "listings", "snapshot.json", default=None), None)

    def test_one_flow_at_a_time(self):
        self.send("新增買方")
        self.assertIn("買方需求草稿沒完成", self.send("新增物件")["text"])
        self.send("取消")
        self.send("新增物件")
        self.assertIn("你正在新增物件", self.send("新增買方")["text"])
        self.assertIn("新增物件草稿沒完成", self.send("我的資料")["text"])

    def test_stale_listing_card(self):
        self.assertIn("已經用過了", self.tap("c", "台中市")[0]["text"])

    def test_unit_price_and_many_buyers_paginate(self):
        self.assertEqual(unit_price({"transaction": "buy", "price": 1000, "size_ping": 40}), "每坪約 25.0 萬")
        self.assertIsNone(unit_price({"transaction": "rent", "price": 18000, "size_ping": 40}))
        self.assertIsNone(unit_price({"transaction": "buy", "price": 1000}))
        for i in range(30):
            self.customers.save_need("tenant-a", label=f"合成客{i:02d}", need=BUYER)
        msgs = self.add_listing()
        cards = [m for m in msgs if m["type"] == "flex"]
        self.assertEqual(len(cards), 3)                              # 30 位 → 12＋12＋6
        self.assertLessEqual(len(msgs), 5)
        for m in msgs:
            self.assertEqual(validate_message(m), [])

    def test_pairs_ignores_paused_and_incomplete(self):
        listing = {"id": "X1", "transaction": "buy", "area": "台中市西屯區", "price": 1000, "property_type": "公寓",
                   "url": "https://example.test/x", "online": True}
        rows = [{"customer_id": "B-1", "label": "停", "status": "paused", "need_card": BUYER},
                {"customer_id": "B-2", "label": "缺", "status": "active", "need_card": {"transaction": "buy"}},
                {"customer_id": "B-3", "label": "好", "status": "active", "need_card": BUYER}]
        self.assertEqual([p[1] for p in pairs([listing], rows)], ["好"])


if __name__ == "__main__":
    unittest.main()
