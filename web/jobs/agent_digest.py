# -*- coding: utf-8 -*-
"""給仲介本人的新案摘要（共用通知帳號模式的主角）。

    物件（新上架／指定那幾間）× 他每一位有效客戶的客需卡 → 哪間適合哪些客戶
    → 每間一張卡：標「適合：甲、乙」＋「分享給客戶」鈕 → 通知仲介本人

跟 new_listing_push 的差別：那支是系統直接推進客戶群（要仲介自己的官方帳號＋審核）；
這支只通知仲介，由仲介決定分享給誰——不用審核、客戶群不需要機器人、不需要綁客戶的 LINE。

兩種用法：
  - 排程：run_agent_digest(...) 主動通知（吃共用帳號的額度；同一間物件只通知一次）
  - 隨問隨答：make_reply_handler(...) 掛到 webhook，仲介打「新案」→ 用回覆給（不計額度、不去重）
"""
from __future__ import annotations

import datetime
from typing import Any, Callable, Iterable, Mapping

from adapters.csv.customer_source import CsvCustomerSource, missing_fields
from adapters.csv.listing_source import CsvListingSource
from adapters.line import flex
from adapters.line.push_gate import GateResult
from adapters.storage import TenantStore
from web.jobs.new_listing_push import ACCEPTED, load_matcher, need_of

SENT_BOOK = ("jobs", "agent_digest.json")
ASK_WORDS = {"新案", "今天新案", "新物件", "配對"}


def build_digest(*, tenant_id: str, listings: CsvListingSource, customers: CsvCustomerSource,
                 listing_ids: Iterable[str] | None = None, matcher: Callable | None = None,
                 identify_customers: bool = False
                 ) -> list[tuple[dict, list[str]]]:
    """回 [(物件, [適合的客戶稱呼…])]，適合的客戶越多越前面，同數量新上架的先。只收「可優先」的配對。"""
    match = matcher or load_matcher()
    active = [x for x in listings.list_active(tenant_id) if x.get("url")]
    if listing_ids is not None:
        wanted = set(listing_ids)
        active = [x for x in active if x["id"] in wanted]
    if not active:
        return []
    by_key = {x["id"]: x for x in active}
    fits: dict[str, list[str]] = {}
    for cust in customers.list_customers(tenant_id):
        need = need_of(cust)
        if missing_fields(need):
            continue
        try:
            result = match(need, active)
        except ValueError:
            continue
        for r in result.get("priority", []):
            x = by_key.get(str(r.get("listing_id", "")))
            if x:
                label = cust.get("label") or cust["customer_id"]
                if identify_customers:
                    label = cust["customer_id"] + "｜" + label
                fits.setdefault(x["id"], []).append(label)
    items = [(by_key[lid], names) for lid, names in fits.items()]
    items.sort(key=lambda it: (len(it[1]), str(it[0].get("listed_at") or ""), it[0]["id"]), reverse=True)
    return items


def run_agent_digest(*, tenant_id: str, store: TenantStore, listings: CsvListingSource,
                     customers: CsvCustomerSource, notify: Callable[[str, list[dict]], GateResult],
                     listing_ids: Iterable[str] | None = None, matcher: Callable | None = None,
                     now: Callable[[], datetime.datetime] = datetime.datetime.now) -> dict[str, Any]:
    """主動通知仲介。同一間物件只通知一次（之後要看打「新案」）。回 {state, listing_ids, reason}。"""
    sent = store.read_json(tenant_id, *SENT_BOOK, default={}) or {}
    items = [it for it in build_digest(tenant_id=tenant_id, listings=listings, customers=customers,
                                       listing_ids=listing_ids, matcher=matcher) if it[0]["id"] not in sent]
    if not items:
        return {"state": "nothing", "listing_ids": [], "reason": "沒有新的、適合客戶的物件"}
    messages = flex.agent_digest_messages(items)[:5]
    shown = [x["id"] for x, _ in items[:flex.MAX_CAROUSEL * len(messages)]]
    res = notify(tenant_id, messages)
    if res.state in ACCEPTED:
        ts = now().isoformat(timespec="seconds")
        sent.update({lid: ts for lid in shown})
        store.write_json(tenant_id, *SENT_BOOK, data=sent)
    return {"state": res.state, "listing_ids": shown, "reason": res.reason}


def make_reply_handler(listings: CsvListingSource, customers: CsvCustomerSource,
                       matcher: Callable | None = None) -> Callable:
    """webhook handler：仲介本人一對一打「新案」→ 回覆今天全部的配對（回覆不計額度）。"""
    def handler(ctx: Any) -> None:
        if not ctx.is_owner_dm or ctx.text not in ASK_WORDS:
            return
        items = build_digest(tenant_id=ctx.tenant_id, listings=listings, customers=customers, matcher=matcher)
        msgs = flex.agent_digest_messages(items)[:5]
        ctx.reply(msgs or [{"type": "text", "text": "目前上架中的物件，沒有適合你客戶的 👀\n"
                                                    "可以上傳新的物件 CSV，或檢查客戶的需求卡是否缺區域、預算。"}])
    return handler
