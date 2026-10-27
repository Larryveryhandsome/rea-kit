"""服務本體的「換心臟」：串接精靈存了新金鑰 → reload() 重新組裝 LINE 服務，不用重開程式。

還沒串接 LINE 時服務照樣能開（精靈要用），只是 /line-shared/webhook 回 503「還沒設定」。
"""
from __future__ import annotations

import os
import threading


class AppHolder:
    def __init__(self, factory=None, *, start_scheduler: bool = True):
        self._factory = factory
        self.start_scheduler = start_scheduler
        self.app = None
        self.error = ""
        self.scheduler = None
        self._lock = threading.Lock()

    def _build(self):
        if self._factory:
            return self._factory()
        from web.line_app import create_app
        return create_app()

    def reload(self) -> bool:
        with self._lock:
            if self.scheduler is not None:
                self.scheduler.stop()
                self.scheduler = None
            try:
                app = self._build()
            except RuntimeError as e:                   # 缺 LINE 金鑰：等精靈設定
                self.app, self.error = None, str(e)
                return False
            self.app, self.error = app, ""
            if self.start_scheduler:
                from web.scheduler import DailyScheduler
                self.scheduler = DailyScheduler(app, app.search, app.customers).start()
            return True

    def admin_tenant(self) -> str | None:
        """管理員（串接精靈綁定的那個 LINE 帳號）的資料夾代號；還沒按「同意並開始」就是 None。"""
        if self.app is None:
            return None
        for user in [u.strip() for u in os.environ.get("REA_ADMIN_USERS", "").split(",") if u.strip()]:
            tenant = self.app.registry.tenant_of(user)
            if tenant:
                return tenant
        return None

    def wsgi(self, environ, start_response):
        app = self.app
        if app is None:
            body = "還沒串接 LINE：請在架設的電腦上開串接精靈（雙擊「開始設定.vbs」）".encode("utf-8")
            start_response("503 Service Unavailable", [("Content-Type", "text/plain; charset=utf-8"),
                                                       ("Content-Length", str(len(body)))])
            return [body]
        return app.wsgi(environ, start_response)
