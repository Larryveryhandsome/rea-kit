"""搜尋引擎 API（自動海巡、各平台新物件都用它）。只用搜尋服務的官方 API，不直接抓任何網站。

為什麼走搜尋 API（2026-10-02，詳見 docs/法遵/自動海巡與新物件搜尋_檢視_20261002.md）：
  - 各物件平台條款禁止爬蟲（591 依刊登物件數計賠、樂屋有擋機器人）；Threads 官方關鍵字搜尋要 Meta 審查。
  - 搜尋服務本來就索引這些公開頁面，用它的 API 查「最近一天新出現的頁面」是它允許的用法；
    我們只拿標題、摘要、網址，不打開、不轉存原頁內容，使用者點連結回原站看。
供應商（環境變數 REA_SEARCH_PROVIDER、REA_SEARCH_KEY；金鑰只放本機加密保險箱）：
  serper：Google 結果，註冊送 2,500 次；brave：自有索引，每月送 5 美元額度。
花費保護：全站每天上限（REA_SEARCH_DAILY_CAP，預設 200 次；2026-10-03 加全市場盤點，從 120 調高）、每位仲介每天上限（預設 40 次）；
  額度用完／金鑰錯誤／被限速 → 當天停用，不重試轟炸。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

SYS = "sys-line-shared"
USAGE = ("search", "usage.json")
CACHE = ("search", "cache.json")       # 同樣的查詢幾小時內共用結果（同區的仲介查的字一樣，不用每人各搜一次）


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


class SearchError(Exception):
    """kind：quota（額度用完／被限速）／auth（金鑰錯）／unavailable（服務暫時不通）／off（沒設定或當天已停用）。"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟轉址：轉址會把金鑰標頭一起帶到新位址（可能是別的主機或 http）。"""

    def redirect_request(self, *args, **kwargs):
        return None


SAFE_OPEN = urllib.request.build_opener(_NoRedirect).open


def _call(req: urllib.request.Request, opener, timeout: float) -> dict:
    try:
        with (opener or SAFE_OPEN)(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 422):                 # Brave 金鑰錯回 422 SUBSCRIPTION_TOKEN_INVALID
            raise SearchError("auth", "搜尋服務金鑰不對或已停用") from None
        if e.code in (402, 429):
            raise SearchError("quota", "搜尋服務額度用完或被限速") from None
        raise SearchError("unavailable", f"搜尋服務回應 {e.code}") from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
        raise SearchError("unavailable", "搜尋服務連不上") from None
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        raise SearchError("unavailable", "搜尋服務回應看不懂") from None
    return data if isinstance(data, dict) else {}


@dataclass
class SerperSearch:
    key: str = field(repr=False)
    opener: object = None
    timeout: float = 10.0
    name = "serper"

    def search(self, query: str, *, recency: str = "d", count: int = 10, page: int = 1) -> list[SearchHit]:
        # num 只能 10（2026-10-02 實測 20 回 400）；要更多就翻頁
        body = {"q": query, "gl": "tw", "hl": "zh-tw", "num": min(count, 10), "tbs": f"qdr:{recency}", "page": page}
        req = urllib.request.Request("https://google.serper.dev/search", data=json.dumps(body).encode("utf-8"),
                                     headers={"X-API-KEY": self.key, "Content-Type": "application/json"}, method="POST")
        data = _call(req, self.opener, self.timeout)
        return [SearchHit(str(r.get("title") or ""), str(r.get("link") or ""), str(r.get("snippet") or ""))
                for r in data.get("organic") or [] if isinstance(r, dict) and r.get("link")]


@dataclass
class BraveSearch:
    key: str = field(repr=False)
    opener: object = None
    timeout: float = 10.0
    name = "brave"

    def search(self, query: str, *, recency: str = "d", count: int = 10, page: int = 1) -> list[SearchHit]:
        q = urllib.parse.urlencode({"q": query, "country": "TW", "search_lang": "zh-hant", "count": min(count, 20),
                                    "offset": max(page - 1, 0), "freshness": {"d": "pd", "w": "pw"}.get(recency, "pd")})
        req = urllib.request.Request("https://api.search.brave.com/res/v1/web/search?" + q,
                                     headers={"X-Subscription-Token": self.key, "Accept": "application/json"})
        data = _call(req, self.opener, self.timeout)
        rows = (data.get("web") or {}).get("results") or []
        return [SearchHit(str(r.get("title") or ""), str(r.get("url") or ""), str(r.get("description") or ""))
                for r in rows if isinstance(r, dict) and r.get("url")]


PROVIDERS = {"serper": SerperSearch, "brave": BraveSearch}


def provider_from_env(env=os.environ, **kw):
    kind, key = env.get("REA_SEARCH_PROVIDER", "").strip().lower(), env.get("REA_SEARCH_KEY", "").strip()
    if kind not in PROVIDERS or not key:
        return None
    return PROVIDERS[kind](key, **kw)


class BudgetedSearch:
    """包一層用量控管：每天全站上限、每位仲介上限；出錯（額度／金鑰）當天停用。用量記在系統分區。"""

    def __init__(self, provider, store, *, now=datetime.datetime.now, daily_cap: int | None = None,
                 tenant_cap: int = 40, cache_ttl: datetime.timedelta | None = None):
        self.provider, self.store, self.now = provider, store, now
        self.daily_cap = daily_cap if daily_cap is not None else int(os.environ.get("REA_SEARCH_DAILY_CAP", "200"))
        self.tenant_cap = tenant_cap
        self.cache_ttl = cache_ttl             # 2026-10-04 開放給大家：同區仲介共用結果；命中不算用量

    def _cache_key(self, query: str, recency: str, count: int, page: int) -> str:
        raw = f"{getattr(self.provider, 'name', '')}|{query}|{recency}|{count}|{page}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cached(self, key: str) -> list[SearchHit] | None:
        rec = (self.store.read_json(SYS, *CACHE, default={}) or {}).get(key)
        if not rec or rec.get("at", "") < (self.now() - self.cache_ttl).isoformat():
            return None
        return [SearchHit(*h) for h in rec.get("hits") or []]

    def _remember(self, key: str, hits: list[SearchHit]) -> None:
        cutoff = (self.now() - self.cache_ttl).isoformat()
        with self.store.lock(SYS, "search-cache"):
            cache = {k: v for k, v in (self.store.read_json(SYS, *CACHE, default={}) or {}).items()
                     if v.get("at", "") >= cutoff}
            cache[key] = {"at": self.now().isoformat(timespec="seconds"),
                          "hits": [[h.title, h.url, h.snippet] for h in hits]}
            self.store.write_json(SYS, *CACHE, data=cache)

    @property
    def available(self) -> bool:
        return self.provider is not None

    def _book(self) -> dict:
        today = self.now().date().isoformat()
        book = self.store.read_json(SYS, *USAGE, default={}) or {}
        return book if book.get("day") == today else {"day": today, "total": 0, "tenants": {}, "off": None}

    def remaining(self, tenant_id: str) -> int:
        book = self._book()
        if book.get("off") or not self.provider:
            return 0
        return max(0, min(self.daily_cap - book["total"], self.tenant_cap - book["tenants"].get(tenant_id, 0)))

    def search(self, tenant_id: str, query: str, *, recency: str = "d", count: int = 10, page: int = 1) -> list[SearchHit]:
        if not self.provider:
            raise SearchError("off", "自動搜尋還沒接上搜尋服務")
        key = self._cache_key(query, recency, count, page) if self.cache_ttl else None
        if key:
            hit = self._cached(key)
            if hit is not None:
                return hit
        with self.store.lock(SYS, "search-usage"):
            book = self._book()
            if book.get("off"):
                raise SearchError("off", "搜尋服務今天已停用：" + book["off"])
            if book["total"] >= self.daily_cap or book["tenants"].get(tenant_id, 0) >= self.tenant_cap:
                raise SearchError("quota", "今天的自動搜尋次數到上限了")
            book["total"] += 1
            book["tenants"][tenant_id] = book["tenants"].get(tenant_id, 0) + 1
            self.store.write_json(SYS, *USAGE, data=book)
        try:
            hits = self.provider.search(query, recency=recency, count=count, page=page)
            if key:
                self._remember(key, hits)
            self._health(True, "")
            return hits
        except SearchError as e:
            if e.kind in ("quota", "auth"):
                with self.store.lock(SYS, "search-usage"):
                    book = self._book()
                    book["off"] = str(e)
                    self.store.write_json(SYS, *USAGE, data=book)
                self._health(False, ("搜尋服務金鑰不對或已停用，請到串接精靈重貼" if e.kind == "auth"
                                     else "搜尋服務額度用完或被限速，今天先停用，明天自動恢復"))
            raise

    def _health(self, ok: bool, msg: str) -> None:
        try:
            from adapters import integration_status
            from adapters.settings_store import SettingsStore
            integration_status.record("search", ok, msg, settings=SettingsStore(self.store.root), now=self.now)
        except Exception:
            pass
