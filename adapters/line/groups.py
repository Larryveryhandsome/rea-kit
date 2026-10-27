# -*- coding: utf-8 -*-
"""租戶的 LINE 群組名冊：官方帳號被拉進哪些群、何時離開、人數有沒有變。

來源只有 LINE 事件（join／leave／memberJoined／memberLeft），所以 webhook 收到就更新；
客戶匯入（CustomerSource.import_groups）也可以把歷史事件重放進來補名冊。
群組「名稱」不在這裡抓：群名常含客戶稱呼，需要時由功能自己向 LINE 查、用完不落檔。
"""
from __future__ import annotations

from typing import Iterable

from adapters.storage import TenantStore

GROUPS = ("line", "groups.json")


def _source_id(ev: dict) -> str:
    src = ev.get("source") or {}
    return src.get("groupId") or src.get("roomId") or ""


def apply_events(store: TenantStore, tenant_id: str, events: Iterable[dict]) -> dict:
    """把一串 LINE 事件套進名冊，回傳更新後的名冊。重放同一批事件結果不變（冪等）。"""
    with store.lock(tenant_id, "groups"):
        reg = store.read_json(tenant_id, *GROUPS, default={}) or {}
        changed = False
        for ev in events:
            gid = _source_id(ev)
            if not gid:
                continue
            ts = int(ev.get("timestamp") or 0)
            g = reg.setdefault(gid, {"type": (ev.get("source") or {}).get("type", "group"),
                                     "joined_at": None, "left_at": None, "last_event_ts": 0})
            if ts and ts < g.get("last_event_ts", 0) and ev.get("type") in ("join", "leave"):
                continue          # 舊事件不能蓋掉新狀態
            t = ev.get("type")
            if t == "join":
                g["joined_at"], g["left_at"] = ts or g.get("joined_at"), None
            elif t == "leave":
                g["left_at"] = ts or g.get("left_at") or 1
            elif t in ("memberJoined", "memberLeft"):
                g["members_changed_ts"] = ts      # 人數變了：推播閘的人數快取隔天自然重查
            g["last_event_ts"] = max(g.get("last_event_ts", 0), ts)
            changed = True
        if changed:
            store.write_json(tenant_id, *GROUPS, data=reg)
        return reg


def active_groups(store: TenantStore, tenant_id: str) -> list[str]:
    reg = store.read_json(tenant_id, *GROUPS, default={}) or {}
    return sorted(gid for gid, g in reg.items() if not g.get("left_at"))
