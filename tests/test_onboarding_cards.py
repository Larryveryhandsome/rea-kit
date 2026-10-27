import json
import unittest
import test_customer_intake as support
from adapters.line.onboarding import PROFILE, welcome
from adapters.line.fake_api import synthetic_line_id
from adapters.line.signature import sign


class OnboardingTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def test_consent_clear_and_no_push(self):
        self.assertEqual(self.send("新手體驗")["type"], "flex")
        self.assertIsNone(self.store.read_json("tenant-a", *PROFILE, default=None))
        self.send("退出新手體驗")
        self.assertIsNone(self.store.read_json("tenant-a", *PROFILE, default=None))
        self.send("確認合成檔案")
        first = self.store.read_json("tenant-a", *PROFILE)
        self.send("確認合成檔案")
        self.assertEqual(first, self.store.read_json("tenant-a", *PROFILE))
        self.assertIsNone(self.store.read_json("tenant-b", *PROFILE, default=None))
        self.send("地號查增值稅說明")
        self.send("清除合成檔案")
        self.assertIsNone(self.store.read_json("tenant-a", *PROFILE, default=None))
        self.assertEqual(self.api.pushes, [])

    def test_follow_automatically_returns_card_without_signup(self):
        uid = synthetic_line_id("U", "newcomer")
        for user, bound in [(uid, False), (self.uid, True)]:
            body = json.dumps({"events": [{"type": "follow", "replyToken": "follow-token",
                "source": {"type": "user", "userId": user}}]}).encode()
            self.assertEqual(self.app.handle(body, sign("test-secret", body))[0], 200)
            self.assertEqual(self.api.replies[-1]["messages"][0], welcome(bound))
        self.assertIsNone(self.app.registry.tenant_of(uid))
        self.send("確認合成檔案", user=uid)
        self.assertIsNone(self.app.registry.tenant_of(uid))

    def test_button_limits_and_real_branch(self):
        for text in ["新手體驗", "確認合成檔案", "地號查增值稅說明"]:
            msg = self.send(text)
            self.assertLessEqual(len(msg["altText"]), 400)
            for button in msg["contents"]["footer"]["contents"]:
                self.assertLessEqual(len(button["action"]["label"]), 20)
        self.assertIn("選服務縣市", self.send("找新買方")["altText"])
        self.send("取消")
        self.assertIn("客戶暱稱", self.send("新增買方")["text"])
