# -*- coding: utf-8 -*-
"""免費功能①：新案件自動推播（W1 版骨架；W4 補齊排程、日報）。

    新物件（CSV 匯入的 new／changed）→ 每位有效客戶的客需卡配對（core/listing_matching）
    → 只取「可優先」的、沒推過給這位客戶的，最多 max_per_push 間做成一則 Flex
    → 交給推播閘（預設先送審核卡給租戶本人；租戶可設成自動）

推播閘會管：額度、每位客戶每天最多一則、審核、沒額度時改用回覆補送。這支不直接碰 LINE。
同一間物件推過（或已排隊等審）給同一位客戶就不再推，紀錄在租戶資料夾 jobs/new_listing_push.json。
"""
from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Mapping

from adapters.csv.customer_source import CsvCustomerSource, missing_fields
from adapters.csv.listing_source import CsvListingSource
from adapters.line import flex
from adapters.line.flex import format_price
from adapters.line.push_gate import PushGate
from adapters.storage import TenantStore

SENT_BOOK = ("jobs", "new_listing_push.json")
ACCEPTED = ("sent", "held", "deferred", "duplicate")
# 配對引擎看得懂的全部條件。少給一個＝那個條件被當成「不限」（例：要電梯的客人配到公寓），所以要全給。
NEED_KEYS = ("transaction", "preferred_areas", "budget_min", "budget_max", "budget_tolerance_pct", "property_type",
             "rooms_min", "size_min", "size_max", "age_max", "parking", "elevator")


def load_matcher() -> Callable[[Mapping[str, Any], list[Mapping[str, Any]]], dict]:
    try:
        from core.listing_matching import match_listings
    except ImportError as e:            # core/ 還沒進版時講清楚，不要默默跳過
        raise RuntimeError("找不到 core.listing_matching（配對引擎）") from e
    return match_listings


def need_of(cust: Mapping[str, Any]) -> dict:
    """客戶 → 配對引擎吃的客需卡。沒填的欄位整個拿掉（交給引擎的預設），不傳 None。"""
    card = cust.get("need_card") or {}
    return {k: card[k] for k in NEED_KEYS if card.get(k) is not None}


@dataclass
class PushRunReport:
    pushed: list[dict] = field(default_factory=list)       # 每位客戶一筆：送出／排隊等審／延後
    skipped: list[dict] = field(default_factory=list)      # 沒推的客戶與原因
    needs_data: list[dict] = field(default_factory=list)   # 有配到、但物件缺資料（例如沒連結）不能推的

    def as_dict(self) -> dict:
        return asdict(self)


def run_new_listing_push(*, tenant_id: str, store: TenantStore, listings: CsvListingSource,
                         customers: CsvCustomerSource, gate: PushGate, listing_ids: Iterable[str] | None = None,
                         max_per_push: int = 3, matcher: Callable | None = None,
                         now: Callable[[], datetime.datetime] = datetime.datetime.now) -> PushRunReport:
    match = matcher or load_matcher()
    rep = PushRunReport()
    active = listings.list_active(tenant_id)
    if listing_ids is not None:
        wanted = set(listing_ids)
        active = [x for x in active if x["id"] in wanted]
    if not active:
        return rep
    # 配對引擎回傳的 listing_id 可能被轉成小寫：一律用 casefold 對回原物件
    by_key = {x["id"].casefold(): x for x in active}
    book = store.read_json(tenant_id, *SENT_BOOK, default={}) or {}

    for cust in customers.list_customers(tenant_id):
        cid = cust["customer_id"]
        need = need_of(cust)
        lack = missing_fields(need)
        if lack:
            rep.skipped.append({"customer_id": cid, "reason": "客需卡缺：" + "、".join(lack)})
            continue
        if not cust.get("line_target"):
            rep.skipped.append({"customer_id": cid, "reason": "還沒綁 LINE 群組／好友，配到也推不出去"})
            continue
        try:
            result = match(need, active)
        except ValueError as e:
            rep.skipped.append({"customer_id": cid, "reason": f"客需卡不合格：{e}"})
            continue
        done = book.get(cid, {})
        picks = []
        for r in result.get("priority", []):
            x = by_key.get(str(r.get("listing_id", "")).casefold())
            if x and x["id"] not in done and x.get("url"):
                picks.append(x)
        for r in result.get("review", []):
            x = by_key.get(str(r.get("listing_id", "")).casefold())
            if x:
                rep.needs_data.append({"customer_id": cid, "listing_id": x["id"], "missing": r.get("missing", [])})
        if not picks:
            continue
        picks = picks[:max_per_push]
        msg = flex.listing_message(picks, intro="幫您留意到符合需求的新物件")
        label = cust.get("label") or cid
        first = picks[0]
        summary = f"{label}：{len(picks)} 間符合（{first.get('area') or ''} {first.get('title') or ''} {format_price(first)}" \
                  + (" 等" if len(picks) > 1 else "") + "）"
        ids = [x["id"] for x in picks]
        res = gate.submit(to=cust["line_target"], messages=[msg], level="match", kind="new_listing_match",
                          recipient_label=label, summary=summary, members=cust.get("members"),
                          dedup_key=cid + "|" + ",".join(ids))
        rep.pushed.append({"customer_id": cid, "listing_ids": ids, "state": res.state, "item_id": res.item_id,
                           "reason": res.reason})
        if res.state in ACCEPTED:
            ts = now().isoformat(timespec="seconds")
            book.setdefault(cid, {}).update({i: ts for i in ids})

    store.write_json(tenant_id, *SENT_BOOK, data=book)
    return rep
