# -*- coding: utf-8 -*-
"""本機假 LINE Messaging API（只聽 127.0.0.1）：單元測試、E2E、示範都用它，不碰真的 LINE。

    with FakeLineApi(token="test-token") as api:
        client = LineClient("test-token", api_base=api.base_url)
        ...
        api.pushes   # 收到的每一個 push：{"to":..., "messages":[...], "retry_key":...}

可模擬：月額度用罄（quota_exhausted=True → 429 monthly limit）、群組人數（member_counts）。
同一個 X-Line-Retry-Key 重送會回 409，跟真的 LINE 一樣。
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def synthetic_line_id(kind: str, seed: str) -> str:
    """合成的 LINE ID（U 個人／C 群組／R 聊天室）：格式對、但不屬於任何真人。
    測試與示範一律用這個在執行時產生，原始碼裡不出現任何 32 碼 ID。"""
    if kind not in ("U", "C", "R"):
        raise ValueError("kind 只能是 U／C／R")
    return kind + hashlib.md5(("rea-kit-synthetic:" + seed).encode("utf-8")).hexdigest()


class FakeLineApi:
    def __init__(self, token: str = "test-token", member_counts: dict[str, int] | None = None):
        self.token = token
        self.member_counts = dict(member_counts or {})
        self.quota_exhausted = False
        self.pushes: list[dict[str, Any]] = []
        self.replies: list[dict[str, Any]] = []
        self.leaves: list[str] = []
        self._retry_keys: set[str] = set()
        self._lock = threading.Lock()
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._srv, "先 start()"
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    def start(self) -> "FakeLineApi":
        api = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, code: int, obj: dict) -> None:
                b = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _authed(self) -> bool:
                if self.headers.get("Authorization") != f"Bearer {api.token}":
                    self._send(401, {"message": "Authentication failed"})
                    return False
                return True

            def do_GET(self) -> None:
                if not self._authed():
                    return
                m = re.match(r"^/v2/bot/(group|room)/([^/]+)/members/count$", self.path)
                if m and m.group(2) in api.member_counts:
                    return self._send(200, {"count": api.member_counts[m.group(2)]})
                self._send(404, {"message": "Not found"})

            def do_POST(self) -> None:
                # 先把 body 讀完再回應（連 401 也是）：沒讀完就關連線，Windows 會送 RST，
                # 客戶端還沒讀到的回應被整個丟掉，變成 ConnectionAbortedError 而不是 401。
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                if not self._authed():
                    return
                body = json.loads(raw.decode("utf-8") or "{}")
                m = re.match(r"^/v2/bot/(group|room)/([^/]+)/leave$", self.path)
                if m:
                    with api._lock:
                        api.leaves.append(m.group(2))
                    return self._send(200, {})
                if self.path == "/v2/bot/message/reply":
                    with api._lock:
                        api.replies.append(body)
                    return self._send(200, {})
                if self.path == "/v2/bot/message/push":
                    if api.quota_exhausted:
                        return self._send(429, {"message": "You have reached your monthly limit."})
                    key = self.headers.get("X-Line-Retry-Key", "")
                    with api._lock:
                        if key and key in api._retry_keys:
                            return self._send(409, {"message": "The retry key is already accepted"})
                        if key:
                            api._retry_keys.add(key)
                        api.pushes.append({**body, "retry_key": key})
                    return self._send(200, {})
                self._send(404, {"message": "Not found"})

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._thread = threading.Thread(target=self._srv.serve_forever, kwargs={"poll_interval": 0.02},
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    def __enter__(self) -> "FakeLineApi":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()
