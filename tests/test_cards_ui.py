"""圖卡點選化（負責人 2026-10-03：「所有東西都要卡片化、圖卡點選化」）：清單是卡片、按鈕直接做事、日期點月曆、預算點區間。"""
import json
import unittest

import test_customer_intake as support
from adapters.line.flex import validate_message
from adapters.line.signature import sign

BUYER = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_min": 800, "budget_max": 1500,
         "property_type": "公寓"}


def bubbles(msg):
    c = msg["contents"]
    return c["contents"] if c["type"] == "carousel" else [c]


def actions(msg):
    return [b["action"] for bub in bubbles(msg) for b in bub["footer"]["contents"]]


class CardTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def all_msgs(self):
        msgs = self.api.replies[-1]["messages"]
        for m in msgs:
            self.assertEqual(validate_message(m), [], m.get("altText"))
        return msgs

    def postback(self, data, params=None):
        self.count += 1
        ev = {"type": "postback", "webhookEventId": f"pb-{self.count}", "replyToken": f"reply-{self.count}",
              "source": {"type": "user", "userId": self.uid}, "postback": {"data": data, **({"params": params} if params else {})}}
        body = json.dumps({"events": [ev]}).encode()
        self.assertEqual(self.app.handle(body, sign("test-secret", body))[0], 200)
        return self.api.replies[-1]["messages"]

    def test_customer_list_is_cards_with_working_buttons(self):
        a = self.customers.save_need("tenant-a", label="合成甲", need=BUYER)
        self.send("客戶清單")
        msgs = self.all_msgs()
        texts = {x["text"] for x in actions(msgs[1])}
        cid = a["customer_id"]
        self.assertEqual(texts, {f"需求 {cid}", f"修改需求 {cid}", f"暫停 {cid}"})
        self.send(f"暫停 {cid}")                                       # 按「暫停配對」
        self.send("客戶清單")
        self.assertIn(f"恢復 {cid}", {x["text"] for x in actions(self.all_msgs()[1])})

    def test_my_listings_are_cards(self):
        self.app.handle  # noqa: B018
        from adapters.csv.listing_source import CsvListingSource
        CsvListingSource(self.store).save_one("tenant-a", {"transaction": "buy", "city": "台中市", "area": "台中市西屯區",
                                                           "title": "合成三房", "price": 1280, "property_type": "公寓",
                                                           "own": True, "listed_at": "2026-10-01"})
        self.send("我的物件")
        texts = {x["text"] for x in actions(self.all_msgs()[1])}
        self.assertEqual(texts, {"配對 M001", "物件 M001", "下架 M001"})

    def test_budget_and_size_are_tappable(self):
        for t in ("新增買方", "合成乙", "租", "台中市西屯區"):
            self.send(t)
        labels = [i["action"]["label"] for i in self.api.replies[-1]["messages"][-1]["quickReply"]["items"]]
        self.assertIn("1.5-2.5萬", labels)
        self.send("1.5-2.5萬")
        for t in ("公寓", "2"):
            self.send(t)
        self.assertIn("30以上", [i["action"]["label"] for i in self.api.replies[-1]["messages"][-1]["quickReply"]["items"]])
        for t in ("30以上", "不限", "不限", "不限", "確認儲存"):
            self.send(t)
        need = [c for c in self.customers.list_customers("tenant-a") if c["label"] == "合成乙"][0]["need_card"]
        self.assertEqual((need["budget_min"], need["budget_max"], need["size_min"]), (15000, 25000, 30))

    def test_more_functions_card(self):
        self.send("更多功能")
        texts = {x["text"] for x in actions(self.all_msgs()[0])}
        for must in ("今日海巡", "客戶清單", "我的物件", "隱私說明"):
            self.assertIn(must, texts)




class TapButtonTests(unittest.TestCase):
    """負責人 2026-10-09：能點的就用點的——回覆裡提到的指令自動變成按鈕。"""

    def test_quoted_commands_become_buttons_on_last_message(self):
        from adapters.line.client import add_tap_buttons
        out = add_tap_buttons([{"type": "text", "text": "已存好；打「客戶清單」看全部，或打「今日報告」馬上找。"}])
        labels = [i["action"]["text"] for i in out[-1]["quickReply"]["items"]]
        self.assertEqual(labels, ["客戶清單", "今日報告"])
        keep = {"type": "text", "text": "打「客戶清單」", "quickReply": {"items": []}}
        self.assertIs(add_tap_buttons([keep])[0], keep)                       # 已經有按鈕就不動
        plain = [{"type": "text", "text": "請打「修改需求 C001」或「不認得的字」"}]
        self.assertNotIn("quickReply", add_tap_buttons(plain)[0])             # 只認固定指令


if __name__ == "__main__":
    unittest.main()
