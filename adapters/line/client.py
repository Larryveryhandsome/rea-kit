# -*- coding: utf-8 -*-
"""LINE Messaging API 出口（每租戶一個 client，用該租戶自己的 token）。

這裡只管「怎麼送」：節流、限流退避、月額度用罄短路、冪等重試。
「該不該送、算不算額度」是 push_gate／push_budget 的事——任何主動推播都要經過它們，
不要直接拿 client.push 去推客戶（測試與推播閘內部除外）。

LINE 的兩種 429 要分開處理：
  - 打太快（rate limit）→ 退避後重試
  - 本月額度用完（訊息含 monthly limit）→ 重試必死，立刻回 quota_exhausted，交給上層排隊
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from adapters.line.credentials import is_line_id

DEFAULT_API_BASE = "https://api.line.me"
API_BASE_ENV = "REA_LINE_API_BASE"      # 只給開發／測試指向本機假 API 用
DRY_RUN_ENV = "REA_PUSH_DRY_RUN"        # 設成 1：主動推播只模擬（寫進 simulated、印一行紀錄），不連 LINE、不耗額度
PUSH_PATH = "/v2/bot/message/push"
REPLY_PATH = "/v2/bot/message/reply"
MAX_MESSAGES = 5                         # LINE 一次最多 5 則 message 物件
# 負責人 2026-10-09：「一律能夠用點擊的就用點擊的，能不要打字就不要打字」。
# 回覆裡寫了 打「客戶清單」這類指令、最後一則又沒有按鈕 → 自動在最後一則加上那幾個按鈕（LINE 的快速回覆）。
TAP_COMMANDS = ("今日報告", "今日海巡", "海巡狀態", "找新買方", "客戶清單", "我的物件", "新增買方", "新增物件", "新案",
                "設定我的資料", "我的資料",
                "隱私說明", "客人告知範本", "匯出我的資料", "刪除我的資料", "確定刪除我的資料", "更多功能", "取消",
                "同意並開始", "開始新手體驗", "新手體驗", "待審")
_QUOTED = __import__("re").compile(r"「([^「」]{1,12})」")


def add_tap_buttons(messages: list[dict]) -> list[dict]:
    """文字裡提到的指令變成最後一則的按鈕（最後一則已經有按鈕就不動）。"""
    if not messages or "quickReply" in messages[-1]:
        return messages
    found: list[str] = []
    for m in messages:
        if m.get("type") == "text":
            for w in _QUOTED.findall(str(m.get("text") or "")):
                if w in TAP_COMMANDS and w not in found:
                    found.append(w)
    if not found:
        return messages
    last = dict(messages[-1])
    last["quickReply"] = {"items": [{"type": "action", "action": {"type": "message", "label": w, "text": w}}
                                    for w in found[:13]]}
    return messages[:-1] + [last]


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status: int = 0
    error: str = ""
    quota_exhausted: bool = False


def _check_api_base(api_base: str) -> str:
    """token 只准送去 LINE 官方或本機假 API，免得設定錯把金鑰送到別人的伺服器。"""
    u = urllib.parse.urlparse(api_base)
    if u.scheme == "https":
        return api_base.rstrip("/")
    if u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"):
        return api_base.rstrip("/")
    raise ValueError("LINE API base 只能是 https，或本機 http（測試用）")


class LineClient:
    def __init__(self, channel_access_token: str, *, api_base: str | None = None,
                 min_interval: float = 0.35, max_tries: int = 3, timeout: float = 15.0,
                 sleep: Callable[[float], None] = time.sleep):
        if not channel_access_token:
            raise ValueError("缺 channel access token")
        self._token = channel_access_token
        self.api_base = _check_api_base(api_base or os.environ.get(API_BASE_ENV) or DEFAULT_API_BASE)
        self.min_interval = min_interval
        self.max_tries = max(1, max_tries)
        self.timeout = timeout
        self._sleep = sleep
        self._last = 0.0
        self._lock = threading.Lock()
        self.dry_run = os.environ.get(DRY_RUN_ENV, "").strip().lower() in ("1", "true", "yes", "on")
        self.simulated: list[dict] = []          # 只模擬時，「本來會推出去」的內容

    def __repr__(self) -> str:
        return f"LineClient(api_base={self.api_base!r})"     # 不印 token

    # ── 送訊息 ──
    def reply(self, reply_token: str, messages: list[dict]) -> SendResult:
        """回覆：不計月額度、不限量（所以產品「回覆為主、推播為輔」）。reply token 只能用一次、約一分鐘內有效。"""
        if not reply_token:
            return SendResult(False, error="沒有 reply token")
        return self._post(REPLY_PATH, {"replyToken": reply_token, "messages": self._msgs(messages)})

    def push(self, to: str, messages: list[dict], *, retry_key: str | None = None) -> SendResult:
        """主動推播：計月額度。帶 X-Line-Retry-Key，網路斷掉重送時 LINE 不會送兩次。"""
        if not is_line_id(to):
            return SendResult(False, error="收件 ID 格式不對")
        if self.dry_run:                          # 只模擬不送出：整條流程照跑，唯獨不連 LINE
            msgs = self._msgs(messages)
            self.simulated.append({"to": to, "messages": msgs})
            print(f"[dry-run] 本來會推播給 {to[:3]}…{to[-4:]}：{len(msgs)} 則（未送出）", flush=True)
            return SendResult(True, 0, "dry-run：未送出")
        headers = {"X-Line-Retry-Key": retry_key or str(uuid.uuid4())}
        return self._post(PUSH_PATH, {"to": to, "messages": self._msgs(messages)}, headers)

    def leave_chat(self, chat_id: str) -> SendResult:
        """官方帳號自己退出群組／聊天室（不計額度）。"""
        if not is_line_id(chat_id) or chat_id[0] == "U":
            return SendResult(False, error="只能退出群組或聊天室")
        kind = "group" if chat_id[0] == "C" else "room"
        return self._post(f"/v2/bot/{kind}/{chat_id}/leave", {})

    def quota(self) -> dict | None:
        """官方帳號的月額度（只讀）：{"type": "limited", "value": 200} 或 {"type": "none"}。查不到回 None。"""
        try:
            return self._get("/v2/bot/message/quota")
        except Exception:
            return None

    def bot_info_status(self) -> int:
        """GET /v2/bot/info 的 HTTP 狀態碼（200＝token 有效、401＝失效、0＝連不上）。"""
        try:
            self._get("/v2/bot/info")
            return 200
        except urllib.error.HTTPError as e:
            e.close()
            return e.code
        except Exception:
            return 0

    def group_member_count(self, group_id: str) -> int | None:
        """群組人數（不含官方帳號本身）。推群組是按人頭計費，配額閘靠它估成本；查不到回 None。"""
        if not is_line_id(group_id) or group_id[0] == "U":
            return None
        kind = "group" if group_id[0] == "C" else "room"
        try:
            data = self._get(f"/v2/bot/{kind}/{group_id}/members/count")
            return int(data.get("count"))
        except Exception:
            return None

    # ── 底層 ──
    @staticmethod
    def _msgs(messages: list[dict]) -> list[dict]:
        if not messages:
            raise ValueError("至少要一則訊息")
        if len(messages) > MAX_MESSAGES:
            raise ValueError(f"LINE 一次最多 {MAX_MESSAGES} 則")
        return add_tap_buttons(list(messages))

    def _throttle(self) -> None:
        with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.min_interval:
                self._sleep(self.min_interval - gap)
            self._last = time.monotonic()

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Content-Type": "application/json", "Authorization": "Bearer " + self._token}
        h.update(extra or {})
        return h

    def _get(self, path: str) -> Any:
        self._throttle()
        req = urllib.request.Request(self.api_base + path, headers=self._headers(), method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def _post(self, path: str, payload: dict, headers: dict | None = None) -> SendResult:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last = SendResult(False, error="未送出")
        for attempt in range(self.max_tries):
            self._throttle()
            req = urllib.request.Request(self.api_base + path, data=body,
                                         headers=self._headers(headers), method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return SendResult(200 <= r.status < 300, r.status)
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                finally:
                    e.close()
                if e.code == 429 and "monthly limit" in detail.lower():
                    return SendResult(False, 429, "本月推播額度已用完", quota_exhausted=True)
                # 409＝同一個 retry key 已經送過（前一次其實成功了）→ 當成功
                if e.code == 409 and path == PUSH_PATH:
                    return SendResult(True, 409, "已送過（冪等）")
                last = SendResult(False, e.code, f"HTTP {e.code}: {detail[:120]}")
                if e.code == 429 or e.code >= 500:
                    if attempt < self.max_tries - 1:
                        self._sleep(2 ** attempt + 1)
                        continue
                return last
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = SendResult(False, 0, f"{type(e).__name__}: {str(e)[:80]}")
                if attempt < self.max_tries - 1:
                    self._sleep(2 ** attempt + 1)
                    continue
        return last
