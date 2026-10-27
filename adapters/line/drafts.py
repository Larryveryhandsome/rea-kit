"""各個點選流程的草稿：同一時間只做一件事，避免兩個流程搶同一句回答。"""
from __future__ import annotations

import re

FLOWS = {
    "prospect": (("line", "prospect_setup.json"), "找新買方的設定"),
    "intake": (("line", "customer_intake.json"), "買方需求草稿"),
    "listing": (("line", "listing_intake.json"), "新增物件草稿"),
    "profile": (("line", "agent_profile.json"), "個人資料設定"),
}
TTL = 1800                       # 草稿 30 分鐘沒動就作廢


def busy(store, tenant_id: str, now_ts: float, *, exclude: str) -> str | None:
    """別的流程還有沒過期的草稿 → 回它的中文名；沒有回 None。只讀不寫。"""
    for name, (path, label) in FLOWS.items():
        if name == exclude:
            continue
        draft = (store.read_json(tenant_id, *path, default={}) or {}).get("draft")
        if draft and now_ts - draft.get("started", 0) <= TTL:
            return label
    return None


# 打在草稿裡、看起來是指令的字（審查：新增物件時打「需求 B-…」「客戶清單」會被存成物件內容、跟著分享出去）
COMMAND_RE = re.compile(
    r"^(客戶清單|找客戶|需求|找房|找房連結|改名|暫停|恢復|修改需求|新增買方|找新買方|新增物件|加物件|我的物件|物件清單|"
    r"今日報告|今日海巡|立即海巡|自動海巡|海巡狀態|海巡設定|我的資料|設定我的資料|修改我的資料|隱私說明|匯出我的資料|"
    r"刪除我的資料|確定刪除我的資料|客人告知範本|新案|今天新案|新物件|配對|下架|上架|新手體驗)(\s|$)")
CUSTOMER_ID_RE = re.compile(r"\bB-[0-9A-F]{6,}\b", re.I)


def looks_like_command(text: str) -> bool:
    t = str(text or "").strip()
    return bool(COMMAND_RE.match(t) or CUSTOMER_ID_RE.search(t))
