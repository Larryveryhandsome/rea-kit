# -*- coding: utf-8 -*-
"""串接的「執行期健康狀態」：設定時測過不代表之後一直好（token 被重發、試算表被取消共用、搜尋額度用完）。

排程與各轉接器出事時記一筆，串接精靈打開就看得到紅字＋怎麼修（因為 LINE 金鑰壞掉時，沒辦法用 LINE 通知你）。
檔案：<資料根>/settings/integration_status.json；只存「哪個串接、好不好、白話原因、時間」，不存金鑰與個資。
"""
from __future__ import annotations

import datetime
import json
import threading

from adapters.settings_store import SettingsStore

_LOCK = threading.Lock()
NAMES = ("line", "gsheet_customers", "gsheet_listings", "search", "moi")


def _path(settings: SettingsStore | None):
    return (settings or SettingsStore()).path.with_name("integration_status.json")


def load(settings: SettingsStore | None = None) -> dict:
    try:
        data = json.loads(_path(settings).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(name: str, ok: bool, msg: str = "", *, settings: SettingsStore | None = None, now=None) -> None:
    if name not in NAMES:
        raise ValueError(name)
    ts = (now or datetime.datetime.now)().isoformat(timespec="seconds")
    with _LOCK:
        data = load(settings)
        old = data.get(name) or {}
        if old.get("ok") == ok and old.get("msg") == msg:
            if (old.get("checked") or "")[:10] == ts[:10]:
                return                                     # 狀態沒變、今天記過：不再寫檔（搜尋每次成功都會叫到這裡）
            old["checked"] = ts
            data[name] = old
        else:
            data[name] = {"ok": bool(ok), "msg": str(msg)[:200], "since": ts, "checked": ts}
        p = _path(settings)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
