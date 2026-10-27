# -*- coding: utf-8 -*-
"""內政部「地政整合資訊服務共享協作平台」土地標示部查詢（要自己申請金鑰、按筆付費）。

- 平台：https://cop.land.moi.gov.tw/ （申請見 docs/金鑰申請.md）
- 驗證：Client ID＋安全碼 → /cp/getToken 換 access token → LandDescription/1.0/QueryByLandNo
- 每查一筆都收費，所以：
    1. 沒設金鑰就完全不呼叫
    2. 呼叫端要帶 confirm=True（畫面上要按「確認查詢（會收費）」）
    3. 查過的存在 <資料根>/moi/cache.json，同一筆不再收費
    4. 每天最多 REA_MOI_DAILY_LIMIT 筆（預設 20），程式出錯也不會一直扣錢
- 只查「標示部」（面積、使用分區、公告現值等），不查所有權人。
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import pathlib
import re
import threading
import time

from adapters.integration_checks import MOI_BASE, NetError, http
from adapters.storage import DATA_ENV, REPO

SERVICE = "LandDescription/1.0/QueryByLandNo"
_QUERY_LOCK = threading.Lock()          # 同一台主機一次只送一筆收費查詢：連按兩次不會扣兩次


class MoiError(RuntimeError):
    pass


class MoiClient:
    def __init__(self, *, root=None, opener=None, base: str | None = None, env=os.environ,
                 today=lambda: datetime.date.today(), sleep=time.sleep):
        self.dir = pathlib.Path(root or env.get(DATA_ENV) or (REPO / "data")).resolve() / "moi"
        self.opener, self.base, self.env, self.today, self.sleep = opener, base or MOI_BASE, env, today, sleep
        self._token = (None, 0.0)

    # ── 設定 ──
    def enabled(self) -> bool:
        return bool(self.env.get("REA_MOI_CLIENT_ID", "").strip() and self.env.get("REA_MOI_SECRET", "").strip())

    def daily_limit(self) -> int:
        try:
            return max(0, int(self.env.get("REA_MOI_DAILY_LIMIT", "20")))
        except ValueError:
            return 20

    # ── 小檔 ──
    def _read(self, name, default):
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return default

    def _write(self, name, data):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def used_today(self) -> int:
        return self._read("usage.json", {}).get(self.today().isoformat(), 0)

    def _count(self):
        u, k = self._read("usage.json", {}), self.today().isoformat()
        u[k] = u.get(k, 0) + 1
        self._write("usage.json", {d: n for d, n in u.items() if d >= k[:7]})

    # ── 查詢 ──
    @staticmethod
    def normalize(unit: str, sec: str, no: str) -> tuple[str, str, str]:
        unit, sec, no = (unit or "").strip().upper(), (sec or "").strip(), (no or "").strip()
        if not re.fullmatch(r"[A-Z]{2}", unit):
            raise MoiError("地政事務所代碼是 2 個英文字母（例：AA），可在謄本或地政事務所網站查到")
        if not re.fullmatch(r"\d{1,4}", sec):
            raise MoiError("段代碼是 4 位數字（例：0001）")
        m = re.fullmatch(r"(\d{1,4})(?:-(\d{1,4}))?", no)
        if m:
            no = f"{int(m.group(1)):04d}{int(m.group(2) or 0):04d}"
        if not re.fullmatch(r"\d{8}", no):
            raise MoiError("地號請打 123 或 123-4（也可以直接打 8 碼 01230004）")
        return unit, f"{int(sec):04d}", no

    def _get_token(self) -> str:
        tok, at = self._token
        if tok and time.time() - at < 600:
            return tok
        auth = base64.b64encode(f"{self.env['REA_MOI_CLIENT_ID'].strip()}:{self.env['REA_MOI_SECRET'].strip()}".encode()).decode()
        for attempt in range(3):
            try:
                r = http("GET", f"{self.base}/cp/getToken", headers={"Authorization": "Basic " + auth},
                         opener=self.opener, timeout=25)
                tok = r.json().get("access_token") if r.status == 200 else None
                if tok:
                    self._token = (tok, time.time())
                    return tok
            except NetError:
                pass
            self.sleep(2 + attempt * 2)
        raise MoiError("地政平台驗證沒過：請重跑串接精靈的「地政平台」那一步")

    def query(self, unit: str, sec: str, no: str, *, confirm: bool = False) -> dict:
        with _QUERY_LOCK:
            return self._query(unit, sec, no, confirm=confirm)

    def _query(self, unit: str, sec: str, no: str, *, confirm: bool = False) -> dict:
        if not self.enabled():
            raise MoiError("還沒串接地政平台（到串接精靈設定 Client ID 與安全碼）")
        unit, sec, no = self.normalize(unit, sec, no)
        key = f"{unit}-{sec}-{no}"
        hit = self._read("cache.json", {}).get(key)
        if hit:
            return {**hit, "cached": True}
        if not confirm:
            raise MoiError("這筆會向地政平台收費，請按「確認查詢」")
        if self.used_today() >= self.daily_limit():
            raise MoiError(f"今天已查 {self.used_today()} 筆，達到每日上限 {self.daily_limit()}（可在串接精靈調整）")
        tok = self._get_token()
        self._count()                                    # 送出前就算一次：就算逾時，平台也可能已經計費，寧可多算不少算
        try:
            r = http("POST", f"{self.base}/cp/api/{SERVICE}",
                     headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
                     body=json.dumps([{"UNIT": unit, "SEC": sec, "NO": no}]).encode(), opener=self.opener, timeout=25)
        except NetError:
            raise MoiError("連不上地政平台（這筆可能已經計費，今天的用量已先算一筆），晚點再試") from None
        d = r.json()
        if not isinstance(d, dict) or d.get("STATUS") != 1:
            code = (d or {}).get("CODE", "") if isinstance(d, dict) else ""
            raise MoiError(f"平台回覆錯誤 {code}：地所代碼、段代碼或地號可能不對".strip())
        reg = next((x.get("LANDREG") for x in d.get("RESPONSE") or [] if isinstance(x, dict)), None)
        if not isinstance(reg, dict):
            raise MoiError("平台查無這筆土地標示部")
        area = next((float(v) for k, v in reg.items() if "AREA" in str(k).upper() and _is_num(v)), None)
        out = {"key": key, "area_sqm": area, "area_ping": round(area * 0.3025, 2) if area else None,
               "fields": {k: v for k, v in reg.items() if not isinstance(v, (dict, list))},
               "at": self.today().isoformat()}
        c = self._read("cache.json", {})
        c[key] = out
        self._write("cache.json", c)
        return {**out, "cached": False}


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
