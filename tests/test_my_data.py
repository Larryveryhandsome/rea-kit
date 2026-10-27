"""仲介自己的資料：隱私說明、客人告知範本、匯出、刪除（要確認、10 分鐘內有效、連綁定一起解除）。合成資料、本機假 LINE。"""
import datetime
import json
import unittest

import test_customer_intake as support
from adapters.line import my_data as MD

BUYER = {"transaction": "buy", "preferred_areas": ["台中市西屯區"], "budget_min": 800, "budget_max": 1500,
         "property_type": "公寓"}


class MyDataTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def all_texts(self):
        return [m["text"] for m in self.api.replies[-1]["messages"] if m["type"] == "text"]

    def test_privacy_and_notice(self):
        self.assertIn("只有你本人看得到", self.send("隱私說明")["text"])
        self.send("我的資料")
        self.send("自營／個人工作室")
        self.send("合成林小姐｜示範店")
        self.send("客人告知範本")
        notice = self.all_texts()[1]
        self.assertTrue(notice.startswith("您好，我是合成林小姐｜示範店。"))
        for must in ("只用來替您配對物件", "查詢、更正或刪除", "不會提供給其他人"):
            self.assertIn(must, notice)

    def test_export_only_my_data(self):
        self.customers.save_need("tenant-a", label="合成甲", need=BUYER)
        self.customers.save_need("tenant-b", label="別人的客人", need=BUYER)
        self.send("匯出我的資料")
        texts = self.all_texts()
        self.assertIn("客人 1 位、物件 0 間", texts[0])
        joined = "\n".join(texts)
        self.assertIn("合成甲", joined)
        self.assertNotIn("別人的客人", joined)
        self.assertTrue(any(t.startswith("【客人.csv】\ncustomer_id,") for t in texts))
        self.assertTrue(any(t.startswith("【物件.csv】\nid,transaction") for t in texts))

    def test_long_export_is_split_on_lines_and_capped(self):
        for i in range(400):
            self.customers.save_need("tenant-a", label=f"合成客人{i:03d}號長一點的暱稱", need=BUYER)
        msgs = self.send("匯出我的資料") and self.api.replies[-1]["messages"]
        self.assertLessEqual(len(msgs), 5)
        self.assertIn("完整檔案請跟管理員要", msgs[0]["text"])
        for m in msgs[1:]:
            self.assertLessEqual(len(m["text"]), 5000)
            self.assertTrue(m["text"].endswith("\n"))                       # 照行切，不切半筆

    def test_delete_needs_fresh_confirmation_and_unbinds(self):
        self.customers.save_need("tenant-a", label="合成甲", need=BUYER)
        self.assertIn("先打「刪除我的資料」", self.send("確定刪除我的資料")["text"])
        self.assertTrue(self.store.tenant_dir("tenant-a").exists())
        self.assertIn("客人 1 位", self.send("刪除我的資料")["text"])
        self.dt += datetime.timedelta(minutes=MD.CONFIRM_MINUTES + 1)          # 太久沒確認 → 作廢
        self.assertIn("先打「刪除我的資料」", self.send("確定刪除我的資料")["text"])
        self.send("刪除我的資料")
        self.assertIn("已刪除", self.send("確定刪除我的資料")["text"])
        self.assertFalse(self.store.tenant_dir("tenant-a").exists())
        self.assertIsNone(self.app.registry.user_of("tenant-a"))
        self.assertIn("同意並開始", json.dumps(self.send("客戶清單"), ensure_ascii=False))   # 沒綁定了，只回歡迎卡

    def test_reachable_even_with_open_draft(self):
        self.send("新增買方")                                                 # 草稿進行中
        self.assertIn("只有你本人看得到", self.send("隱私說明")["text"])


if __name__ == "__main__":
    unittest.main()
