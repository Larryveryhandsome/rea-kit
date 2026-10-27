"""管理員面板（負責人 2026-10-09：「要像我另一套營運系統那樣，有一個管理員面板」）。
LINE 拿一次性登入連結、只有設定的管理員拿得到；頁面要登入；動作要表單驗證碼；不顯示客人暱稱。合成資料、本機假 LINE。"""
import io
import json
import os
import unittest
import unittest.mock
import urllib.parse

import test_customer_intake as support
from adapters.line.fake_api import synthetic_line_id
from web.admin_app import make_admin_app
from web.line_app import create_app

STRANGER = synthetic_line_id("U", "not-admin")


class AdminPanelTests(unittest.TestCase):
    send = support.CustomerIntakeTests.send
    tearDown = support.CustomerIntakeTests.tearDown

    def setUp(self):
        support.CustomerIntakeTests.setUp(self)
        self.app = create_app(store=self.store, channel=self.cfg, client_factory=self.factory, now=self.now,
                              public_base="https://example.test")
        self.send("綁定 " + self.app.registry.issue_code("tenant-a"))
        self.customers.save_need("tenant-a", label="合成客人甲", need={
            "transaction": "buy", "preferred_areas": ["宜蘭縣宜蘭市"], "budget_max": 1000, "property_type": "公寓"})
        self.env = unittest.mock.patch.dict(os.environ, {"REA_ADMIN_USERS": self.uid})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.web = make_admin_app(self.app, self.app.admin_auth)

    def call(self, path, *, cookie=None, method="GET", form=None):
        body = urllib.parse.urlencode(form or {}).encode()
        path, _, query = path.partition("?")
        env = {"PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": method, "HTTP_COOKIE": cookie or "",
               "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
        got = {}
        out = b"".join(self.web(env, lambda s, h: got.update(status=s, headers=dict(h))))
        return got["status"], got["headers"], out.decode("utf-8")

    def login(self):
        card = self.send("管理員面板")
        url = card["contents"]["footer"]["contents"][0]["action"]["uri"]
        self.assertTrue(url.startswith("https://example.test/admin/login?t="))
        status, headers, _ = self.call(url.replace("https://example.test", ""))
        self.assertEqual(status, "302 Found")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("Secure", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";")[0], url

    def test_only_admins_get_a_link_and_links_are_one_time(self):
        reply = self.send("管理員面板", user=STRANGER)
        self.assertNotIn("admin/login", json.dumps(reply, ensure_ascii=False))     # 一般人只看到歡迎卡
        cookie, url = self.login()
        self.assertTrue(self.call(url.replace("https://example.test", ""))[0].startswith("403"))   # 用過不能再用
        self.assertTrue(self.call("/admin/")[0].startswith("401"))                                 # 沒登入
        self.dt = self.dt.replace(year=2026, month=12)                                              # 30 天後失效
        self.assertTrue(self.call("/admin/", cookie=cookie)[0].startswith("401"))

    def test_pages_render_without_customer_names(self):
        cookie, _ = self.login()
        for path in ("/admin/", "/admin/agents", "/admin/patrol", "/admin/patrol?all=1", "/admin/market"):
            with self.subTest(path):
                status, _h, page = self.call(path, cookie=cookie)
                self.assertEqual(status, "200 OK")
                self.assertNotIn("合成客人甲", page)
                self.assertIn("noindex", page)
        page = self.call("/admin/agents", cookie=cookie)[2]
        self.assertIn("tenant-a", page)
        self.assertIn("買方 1", page)

    def test_actions_need_csrf_and_switch_my_line(self):
        cookie, _ = self.login()
        page = self.call("/admin/", cookie=cookie)[2]
        csrf = page.split("name='csrf' value='")[1].split("'")[0]
        self.assertTrue(self.call("/admin/act", cookie=cookie, method="POST", form={"do": "me_fresh", "csrf": "x"})[0]
                        .startswith("403"))
        self.call("/admin/act", cookie=cookie, method="POST", form={"do": "me_fresh", "csrf": csrf})
        self.assertIsNone(self.app.registry.tenant_of(self.uid))                     # 變成新客人
        self.assertIn("同意並開始", json.dumps(self.send("你好"), ensure_ascii=False))
        self.call("/admin/act", cookie=cookie, method="POST", form={"do": "bind_me", "tenant": "tenant-a", "csrf": csrf})
        self.assertEqual(self.app.registry.tenant_of(self.uid), "tenant-a")         # 一鍵接回
        page = self.call("/admin/act", cookie=cookie, method="POST",
                         form={"do": "bind_code", "tenant": "tenant-a", "csrf": csrf})[2]
        self.assertRegex(page, r"class='code'>\d{6}<")
        bad = self.call("/admin/act", cookie=cookie, method="POST", form={"do": "bind_me", "tenant": "nope", "csrf": csrf})[2]
        self.assertIn("看不懂", bad)

    def test_admin_button_only_in_admins_more_card(self):
        self.assertIn("管理員面板", json.dumps(self.send("更多功能"), ensure_ascii=False))
        other = synthetic_line_id("U", "plain-agent")
        self.send("綁定 " + self.app.registry.issue_code("tenant-b"), user=other)
        self.assertNotIn("管理員面板", json.dumps(self.send("更多功能", user=other), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
