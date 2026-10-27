"""替買方找房：區域這題改成點選卡（跟找新買方同一套），打字照樣可以。合成資料、本機假 LINE。"""
import json
import unittest

import test_customer_intake as support
from adapters.line import area_picker as AP
from adapters.line.customer_intake import PURPOSE, STATE
from adapters.line.signature import sign
from core.tw_districts import COUNTIES, DISTRICTS, WHOLE

REST = ["800-1500", "公寓", "2", "不限", "不限", "不限", "不限"]


class IntakeAreaPickerTests(unittest.TestCase):
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

    def draft(self):
        return (self.store.read_json("tenant-a", *STATE, default={}) or {}).get("draft")

    def start(self):
        self.send("新增買方")
        self.send("合成客戶甲")
        card = self.send("買")
        self.assertEqual(card["type"], "flex")
        self.assertIn("客人想找哪些縣市", card["altText"])

    def finish(self):
        for text in REST:
            self.send(text)
        self.assertIn("確認儲存", self.api.replies[-1]["messages"][0]["text"])
        self.send("確認儲存")
        return self.customers.list_customers("tenant-a")[0]["need_card"]

    def test_tap_two_counties_and_districts(self):
        self.start()
        self.tap("c", "台中市")
        self.tap("c", "彰化縣")
        self.tap("next")
        self.tap("d", str(DISTRICTS["台中市"].index("西屯區")), county="台中市")
        self.tap("d", str(DISTRICTS["台中市"].index("南屯區")), county="台中市")
        self.assertIn("彰化縣：選區域", self.tap("done", county="台中市")[-1]["altText"])
        replies = self.tap("d", WHOLE, county="彰化縣")
        self.assertIn("✓ 彰化縣：全區", replies[0]["text"])
        self.assertIn("預算", replies[-1]["text"])                     # 選完直接到預算題
        need = self.finish()
        self.assertEqual(need["preferred_areas"], ["台中市西屯區", "台中市南屯區", "彰化縣"])

    def test_whole_taiwan(self):
        self.start()
        self.assertIn("預算", self.tap("all")[-1]["text"])
        self.assertEqual(self.finish()["preferred_areas"], list(COUNTIES))

    def test_typing_still_works(self):
        self.start()
        self.assertIn("預算", self.send("台中市西屯區、台中市南屯區")["text"])
        self.assertNotIn("pick", self.draft())
        self.assertEqual(self.finish()["preferred_areas"], ["台中市西屯區", "台中市南屯區"])

    def test_quick_reply_text_whole_advances(self):
        self.start()
        self.tap("c", "宜蘭縣")
        self.tap("next")
        self.send("全區")
        self.assertEqual(self.draft()["step"], "budget")
        self.assertEqual(self.draft()["need"]["preferred_areas"], ["宜蘭縣"])

    def test_stale_card_and_other_purpose(self):
        self.start()
        self.tap("all")
        self.assertIn("已經用過了", self.tap("c", "台中市")[0]["text"])      # 已經過了區域題
        self.assertEqual(self.draft()["step"], "budget")
        self.assertIn("已經用過了", self.tap("c", "台中市", purpose="prospect")[0]["text"])   # 找新買方的舊卡
        self.assertEqual(self.draft()["step"], "budget")
        self.send("取消")
        self.assertIn("已經用過了", self.tap("c", "台中市")[0]["text"])      # 沒有草稿
        self.assertEqual(self.customers.list_customers("tenant-a"), [])

    def test_bad_typing_at_area_step_reshows_card(self):
        self.start()
        self.send("隨便打的")
        msgs = self.api.replies[-1]["messages"]
        self.assertIn("請照題目重填", msgs[0]["text"])
        self.assertEqual(msgs[1]["type"], "flex")
        self.assertEqual(self.draft()["step"], "area")

    def test_edit_need_uses_picker(self):
        self.start()
        self.tap("all")
        cid = self.finish() and self.customers.list_customers("tenant-a")[0]["customer_id"]
        self.send(f"修改需求 {cid}")
        self.assertEqual(self.send("買")["type"], "flex")
        self.tap("c", "台南市")
        self.tap("next")
        self.tap("d", str(DISTRICTS["台南市"].index("東區")), county="台南市")
        self.tap("done", county="台南市")
        need = self.finish()
        self.assertEqual(need["preferred_areas"], ["台南市東區"])
        self.assertEqual(need["version"], 2)


if __name__ == "__main__":
    unittest.main()
