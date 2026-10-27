"""擴展性與漏洞檢視（docs/擴展性與漏洞檢視.md）裡 🔴🟠 問題的回歸測試。全部合成資料、假網路。"""
import datetime
import io
import json
import os
import tempfile
import threading
import unittest
import unittest.mock
import urllib.parse

import test_customer_intake as support
import test_setup_wizard as W
from adapters import integration_status
from adapters.line.fake_api import synthetic_line_id
from adapters.line.shared import INVITE_ONLY
from adapters.settings_store import FIELDS, SettingsStore
from web.admin_app import _safe_url, act

STRANGER = synthetic_line_id("U", "stranger")
ADMIN = synthetic_line_id("U", "hardening-admin")


class InviteOnlyTests(unittest.TestCase):
    """擴展性：自架預設只限受邀；管理員按一下「邀請新成員」就能加同事，每人資料分開。"""
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def env(self, **kw):
        p = unittest.mock.patch.dict(os.environ, kw)
        p.start()
        self.addCleanup(p.stop)

    def test_stranger_cannot_sign_up_when_admin_exists(self):
        self.env(REA_ADMIN_USERS=ADMIN, REA_SIGNUP_MODE="")
        self.assertEqual(self.send("同意並開始", user=STRANGER)["text"], INVITE_ONLY)
        self.assertIsNone(self.app.registry.tenant_of(STRANGER))
        self.send("同意並開始", user=ADMIN)                                     # 管理員自己可以
        self.assertIsNotNone(self.app.registry.tenant_of(ADMIN))

    def test_open_mode_lets_anyone_in(self):
        self.env(REA_ADMIN_USERS=ADMIN, REA_SIGNUP_MODE="open")
        self.send("同意並開始", user=STRANGER)
        self.assertIsNotNone(self.app.registry.tenant_of(STRANGER))

    def test_admin_invites_new_member_with_separate_data(self):
        self.env(REA_ADMIN_USERS=ADMIN, REA_SIGNUP_MODE="invite")
        sess = {"user": ADMIN, "csrf": "x"}
        page = act(self.app, sess, {"do": "invite"}).decode("utf-8")
        code = page.split("<div class='code'>")[1].split("</div>")[0]
        self.send(code, user=STRANGER)
        member = self.app.registry.tenant_of(STRANGER)
        self.assertTrue(member.startswith("m"))
        self.assertNotEqual(member, "tenant-a")
        self.customers.save_need("tenant-a", label="合成甲的客人", need=support.NEED)
        self.assertEqual(self.customers.list_customers(member), [])            # 新成員看不到別人的客人
        self.assertNotIn("合成甲的客人", json.dumps(self.send("客戶清單", user=STRANGER), ensure_ascii=False))

    def test_admin_bind_me_does_not_kick_the_agent_off(self):
        self.env(REA_ADMIN_USERS=ADMIN)
        sess = {"user": ADMIN, "csrf": "x"}
        page = act(self.app, sess, {"do": "bind_me", "tenant": "tenant-a"}).decode("utf-8")
        self.assertIn("沒有接上", page)
        self.assertEqual(self.app.registry.tenant_of(self.uid), "tenant-a")    # 原本的仲介還在


class AdminXssTests(unittest.TestCase):
    def test_only_http_links(self):
        self.assertEqual(_safe_url("javascript:alert(1)"), "#")
        self.assertEqual(_safe_url(" JaVaScRiPt:alert(1)"), "#")
        self.assertEqual(_safe_url("https://www.threads.com/@x/post/1"), "https://www.threads.com/@x/post/1")


class BadSignatureFloodTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    send = support.CustomerIntakeTests.send
    tearDown = support.CustomerIntakeTests.tearDown

    def test_flood_writes_one_audit_line_per_minute(self):
        for _ in range(200):
            self.assertEqual(self.app.handle(b'{"events":[]}', "bad")[0], 403)
        audit = (self.store.tenant_dir("sys-line-shared") / "audit.jsonl").read_text(encoding="utf-8")
        self.assertEqual(audit.count("bad_signature"), 1)
        self.dt += datetime.timedelta(minutes=1)
        self.app.handle(b'{"events":[]}', "bad")
        audit = (self.store.tenant_dir("sys-line-shared") / "audit.jsonl").read_text(encoding="utf-8")
        self.assertEqual(audit.count("bad_signature"), 2)


class WizardHardeningTests(unittest.TestCase):
    """沿用精靈走查的假網路與服務（只借 setUp 與小工具，不重跑那邊的測試）。"""
    setUp = W.WizardFlowTests.setUp
    call = W.WizardFlowTests.call
    login = W.WizardFlowTests.login
    line_say = W.WizardFlowTests.line_say

    def test_failed_webhook_test_does_not_touch_line_setting(self):
        self.login()
        self.assertTrue(self.call("/setup/api/line/keys", {"secret": W.SECRET, "token": W.TOKEN})[2]["ok"])
        self.net.endpoint = "https://old.example.com/line-shared/webhook"                # 原本能用的設定
        self.net.line_secret = W.WRONG_SECRET                                              # 新服務簽章對不上
        _, _, r = self.call("/setup/api/line/webhook", {"public_base": "https://new.example.com"})
        self.assertFalse(r["ok"])
        self.assertEqual(self.net.endpoint, "https://old.example.com/line-shared/webhook")  # 沒被改掉
        self.assertEqual(self.settings.get("REA_PUBLIC_BASE"), "")

    def test_wrong_host_header_is_rejected(self):
        self.assertTrue(self.call("/setup?k=" + "t" * 40, headers={"HTTP_HOST": "evil.example:8080"})[0].startswith("403"))
        self.assertTrue(self.call("/setup?k=" + "t" * 40, headers={"HTTP_HOST": "127.0.0.1:8080"})[0].startswith("303"))

    def test_signup_mode_switch(self):
        self.login()
        _, _, r = self.call("/setup/api/line/signup", {"mode": "open"})
        self.assertTrue(r["ok"])
        self.assertEqual(os.environ["REA_SIGNUP_MODE"], "open")
        self.assertEqual(self.call("/setup/api/status")[2]["signup_mode"], "open")
        self.assertFalse(self.call("/setup/api/line/signup", {"mode": "x"})[2]["ok"])

    def test_health_banner_data(self):
        self.login()
        integration_status.record("gsheet_customers", False, "Google 不讓我們讀這份試算表", settings=self.settings)
        h = self.call("/setup/api/status")[2]["health"]
        self.assertFalse(h["gsheet_customers"]["ok"])
        self.assertNotIn("http", json.dumps(h))

    def test_new_search_key_lifts_todays_stop(self):
        self.login()
        self.store.write_json("sys-line-shared", "search", "usage.json",
                              data={"day": "x", "total": 0, "tenants": {}, "off": "搜尋服務金鑰不對或已停用"})
        self.assertTrue(self.call("/setup/api/search/check", {"provider": "brave", "key": "brave-synthetic"})[2]["ok"])
        self.assertNotIn("off", self.store.read_json("sys-line-shared", "search", "usage.json"))

    def test_moi_timeout_still_counts_and_double_click_charges_once(self):
        self.login()
        self.call("/setup/api/moi/check", {"client_id": "cid-synthetic", "secret": "sec-synthetic", "daily_limit": "5"})
        from adapters.moi_cop import MoiClient
        client = MoiClient(root=self.tmp.name, opener=self.net, sleep=lambda s: None)
        real = self.net.__call__

        def timeout_on_query(req, timeout=None):
            if "/cp/api/" in req.full_url:
                from adapters.integration_checks import NetError
                raise NetError("timed out")
            return real(req, timeout)
        client.opener = timeout_on_query
        with self.assertRaises(Exception):
            client.query("AA", "1", "9", confirm=True)
        self.assertEqual(client.used_today(), 1)                                            # 逾時也先算一筆
        client.opener = self.net
        results = []
        ts = [threading.Thread(target=lambda: results.append(client.query("AA", "1", "10", confirm=True)))
              for _ in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(self.net.moi_queries, 1)                                           # 連按三次只查一次
        self.assertEqual(sorted(r["cached"] for r in results), [False, True, True])


class SchedulerHealthTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    send = support.CustomerIntakeTests.send
    tearDown = support.CustomerIntakeTests.tearDown

    def test_revoked_line_token_shows_in_wizard_health(self):
        from web.scheduler import DailyScheduler
        sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now)
        self.app._client = type("C", (), {"bot_info_status": lambda self: 401})()
        self.assertFalse(sched.check_line_auth())
        h = integration_status.load(SettingsStore(self.store.root))
        self.assertFalse(h["line"]["ok"])
        self.assertIn("重貼", h["line"]["msg"])
        self.app._client = type("C", (), {"bot_info_status": lambda self: 200})()
        self.assertTrue(sched.check_line_auth())
        self.assertTrue(integration_status.load(SettingsStore(self.store.root))["line"]["ok"])

    def test_stop_waits_for_running_round(self):
        from web.scheduler import DailyScheduler
        started, release = threading.Event(), threading.Event()
        sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now, interval=0.01)
        sched.tick = lambda: (started.set(), release.wait(2))
        sched.start()
        self.assertTrue(started.wait(2))
        threading.Timer(0.2, release.set).start()
        sched.stop()
        self.assertFalse(sched._thread.is_alive())                                          # 舊的那一輪收完才回來

    def test_tenants_take_turns_first(self):
        from web.scheduler import DailyScheduler
        order = []
        self.app.search.provider = object()                                                  # 假裝有搜尋服務
        type(self.app.search)  # noqa: B018
        with unittest.mock.patch.object(type(self.app.search), "available", new_callable=unittest.mock.PropertyMock,
                                        return_value=True), \
                unittest.mock.patch.object(type(self.app.registry), "tenants", return_value=["t1", "t2", "t3"]), \
                unittest.mock.patch("web.jobs.daily_brief.due", side_effect=lambda store, t, now: order.append(t) or False), \
                unittest.mock.patch("web.jobs.daily_brief.due_extra", return_value=None):
            sched = DailyScheduler(self.app, self.app.search, self.app.customers, now=self.now)
            sched._quota_day = sched._sheet_day = self.dt.date()
            sched.tick()
            first = order[0]
            order.clear()
            self.dt += datetime.timedelta(days=1)
            sched._quota_day = sched._sheet_day = self.dt.date()
            sched.tick()
            self.assertNotEqual(order[0], first)


class SearchHealthTests(unittest.TestCase):
    def test_bad_search_key_recorded(self):
        from adapters.storage import TenantStore
        from adapters.web_search import BudgetedSearch, SearchError
        with tempfile.TemporaryDirectory() as tmp:
            class Bad:
                name = "brave"

                def search(self, *a, **k):
                    raise SearchError("auth", "搜尋服務金鑰不對或已停用")
            s = BudgetedSearch(Bad(), TenantStore(tmp))
            with self.assertRaises(SearchError):
                s.search("tenant-a", "q")
            h = integration_status.load(SettingsStore(tmp))
            self.assertFalse(h["search"]["ok"])


if __name__ == "__main__":
    unittest.main()
