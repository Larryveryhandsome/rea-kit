# -*- coding: utf-8 -*-
"""推播預算：把每月主動推播硬性控制在租戶的 LINE 方案額度內，並把額度花在最會成交的地方。

LINE 官方帳號免費方案每月 200 則「推播」；回覆（reply）不計額度、不限量。
所以每個功能都先想「能不能等使用者開口再回」，真的要主動推才來這裡要額度。

三層管法（從實戰帳本學來的）：
  ① 硬上限 plan_cap：等於租戶 LINE 方案的月額度，所有級別加起來都不能超過。
  ② 分級配額：額度先給「最可能促成成交」的（客戶物件配對），不是先搶先贏；
     內部例行日報配額刻意是 0——要看就打字問，回覆不計額度。
  ③ 控制通道保留額 control_reserve：給租戶本人（急事、審核卡）。可裁量的級別再怎麼用，
     都吃不到這塊——否則月中額度被物件卡用光，租戶連「要你審核」的卡都收不到，整個系統卡死。
     控制通道另有「每日斷路器」：失控的迴圈一天內就會被擋下並留紀錄。

計費單位＝收件人數：推一個 5 人群組＝5 則。成本由呼叫端（推播閘）算好傳進來。

單一真相＝帳本 log：每次都從 log 現算用量，沒有另外累加的計數器——
兩份真相一定會打架（曾有第二個寫者拿舊副本把修正過的數字蓋回去）。
只有「真的送出去」才記帳：送失敗也記，等於自己把額度算光、該推的反而推不出去。
"""
from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable

from adapters.storage import TenantStore

FREE_PLAN_CAP = 200

CONTROL_LEVELS = ("owner", "review")

LEVEL_DESC = {
    "owner": "給你本人的急事／系統通知",
    "review": "審核卡（你按送出／不送的地方）",
    "match": "客戶物件配對（會成交的那一類）",
    "greeting": "固定範本問候",
    "announce": "內部低頻公告",
    "internal": "內部例行日報（改成打字才回，回覆不計額度）",
}

# 免費方案預設（可裁量各級加總 = plan_cap - control_reserve = 160）
DEFAULT_LEVEL_QUOTA = {"match": 120, "greeting": 25, "announce": 15, "internal": 0}
DEFAULT_CONTROL_DAILY = {"owner": 3, "review": 5}
DEFAULT_RECIPIENT_DAILY = {"match": 1}      # 同一位客戶一天最多收 1 則物件推播（不洗版）
DEFAULT_RECIPIENT_MONTHLY = {"match": 4}    # 同一位客戶一個月最多收 4 則物件推播（實務經驗：再多客戶就麻木）


@dataclass(frozen=True)
class BudgetPolicy:
    plan_cap: int = FREE_PLAN_CAP
    control_reserve: int = 40
    level_quota: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LEVEL_QUOTA))
    control_daily: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CONTROL_DAILY))
    recipient_daily: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_RECIPIENT_DAILY))
    recipient_monthly: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_RECIPIENT_MONTHLY))
    est_members: int = 3      # 查不到群組人數時的保守估計（客戶群多半是 客戶＋業務＋官方帳號）
    # 同一個收件人一個月最多花掉幾則（0＝不限）。共用通知帳號用它做「每位仲介的公平份額」：
    # 一個帳號的額度大家分，不能讓一位仲介把全部人的額度用光
    recipient_monthly_cap: int = 0

    @classmethod
    def from_dict(cls, d: dict | None) -> "BudgetPolicy":
        d = dict(d or {})
        base = cls()
        return cls(
            plan_cap=int(d.get("plan_cap", base.plan_cap)),
            control_reserve=int(d.get("control_reserve", base.control_reserve)),
            level_quota={**base.level_quota, **{k: int(v) for k, v in (d.get("level_quota") or {}).items()}},
            control_daily={**base.control_daily, **{k: int(v) for k, v in (d.get("control_daily") or {}).items()}},
            recipient_daily={**base.recipient_daily,
                             **{k: int(v) for k, v in (d.get("recipient_daily") or {}).items()}},
            est_members=max(1, int(d.get("est_members", base.est_members))),
            recipient_monthly_cap=max(0, int(d.get("recipient_monthly_cap", base.recipient_monthly_cap))),
            recipient_monthly={**base.recipient_monthly,
                               **{k: int(v) for k, v in (d.get("recipient_monthly") or {}).items()}},
        )

    def validate(self) -> list[str]:
        errs = []
        if self.plan_cap <= 0:
            errs.append("plan_cap 必須大於 0")
        if not 0 <= self.control_reserve <= self.plan_cap:
            errs.append("control_reserve 必須介於 0 與 plan_cap 之間")
        if sum(self.level_quota.values()) > self.plan_cap - self.control_reserve:
            errs.append("各級配額加總超過 plan_cap - control_reserve")
        unknown = set(self.level_quota) - set(LEVEL_DESC)
        if unknown:
            errs.append(f"不認得的級別：{sorted(unknown)}")
        return errs

    def is_known(self, level: str) -> bool:
        return level in CONTROL_LEVELS or level in self.level_quota


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str = ""
    zero_quota: bool = False     # 這一級的配額「結構上」就是 0（不是暫時用完）→ 不該排隊等


def recipient_key(to: str) -> str:
    """帳本不存原始 LINE ID，只存短雜湊：夠查重、夠除錯，外洩也還原不回去。"""
    return hashlib.sha256(str(to or "").encode("utf-8")).hexdigest()[:12]


def cost_of(to: str, members: int | None, est_members: int, n: int = 1) -> int:
    """推 n 則到 to 要花幾則額度。1 對 1（U 開頭）＝1 人；群組／聊天室＝人數。"""
    if str(to or "").startswith("U"):
        return int(n)
    return int(n) * max(1, int(members) if members else est_members)


class PushBudget:
    LEDGER = ("line", "push_ledger.json")
    POLICY = ("line", "push_policy.json")

    def __init__(self, store: TenantStore, tenant_id: str, policy: BudgetPolicy | None = None,
                 now: Callable[[], datetime.datetime] = datetime.datetime.now):
        self.store = store
        self.tenant_id = tenant_id
        self.policy = policy or BudgetPolicy.from_dict(store.read_json(tenant_id, *self.POLICY, default={}))
        errs = self.policy.validate()
        if errs:
            raise ValueError("推播預算設定不合理：" + "；".join(errs))
        self._now = now

    # ── 帳本 ──
    def _month(self) -> str:
        return self._now().strftime("%Y-%m")

    def _load(self) -> dict:
        d = self.store.read_json(self.tenant_id, *self.LEDGER, default={}) or {}
        if d.get("month") != self._month():            # 跨月自動歸零，不必等排程
            d = {"month": self._month(), "log": []}
        d.setdefault("log", [])
        return d

    def _used(self, log: list[dict]) -> dict[str, int]:
        used: dict[str, int] = {}
        for e in log:
            used[e.get("lv", "?")] = used.get(e.get("lv", "?"), 0) + int(e.get("cost", 1))
        return used

    def _used_today(self, log: list[dict], level: str, rkey: str | None = None) -> int:
        today = self._now().date().isoformat()
        return sum(int(e.get("cost", 1)) for e in log
                   if e.get("lv") == level and str(e.get("ts", ""))[:10] == today
                   and (rkey is None or e.get("to") == rkey))

    def _count_today(self, log: list[dict], level: str, rkey: str) -> int:
        today = self._now().date().isoformat()
        return sum(1 for e in log if e.get("lv") == level and e.get("to") == rkey
                   and str(e.get("ts", ""))[:10] == today)

    # ── 問與記 ──
    def check(self, level: str, to: str, cost: int) -> Decision:
        """可不可以推？只問，不記帳。"""
        p = self.policy
        if not p.is_known(level):
            return Decision(False, f"不認得的推播級別：{level}")
        log = self._load()["log"]
        used = self._used(log)
        total = sum(used.values())
        if total + cost > p.plan_cap:
            return Decision(False, f"本月推播會超過 LINE 方案上限（已用 {total}/{p.plan_cap}，這次要 {cost}）")
        if p.recipient_monthly_cap:
            rkey = recipient_key(to)
            mine = sum(int(e.get("cost", 1)) for e in log if e.get("to") == rkey)
            if mine + cost > p.recipient_monthly_cap:
                return Decision(False, f"這位收件人本月已用 {mine}/{p.recipient_monthly_cap} 則（每人公平份額）")
        if level in CONTROL_LEVELS:
            cap = p.control_daily.get(level, 0)
            today = self._used_today(log, level)
            if today + cost > cap:
                return Decision(False, f"{LEVEL_DESC[level]} 今天已用 {today}/{cap} 則（每日斷路器；"
                                       "撞到多半是有東西在重複發）")
            return Decision(True)
        quota = p.level_quota.get(level, 0)
        if quota <= 0:
            return Decision(False, f"{LEVEL_DESC.get(level, level)} 的月配額是 0（刻意的：改成打字才回，不佔額度）",
                            zero_quota=True)
        discretionary = sum(v for k, v in used.items() if k not in CONTROL_LEVELS)
        room = p.plan_cap - p.control_reserve
        if discretionary + cost > room:
            return Decision(False, f"可用於客戶／內部的額度本月已用 {discretionary}/{room}"
                                   f"（另 {p.control_reserve} 則保留給你本人的通知）")
        if used.get(level, 0) + cost > quota:
            return Decision(False, f"{LEVEL_DESC.get(level, level)} 本月配額用完了（{used.get(level, 0)}/{quota}）")
        per = p.recipient_daily.get(level)
        if per and self._count_today(log, level, recipient_key(to)) >= per:
            return Decision(False, f"同一位收件人今天已收過 {per} 則{LEVEL_DESC.get(level, level)}（每日上限）")
        per_month = p.recipient_monthly.get(level)
        rkey = recipient_key(to)
        if per_month and sum(1 for e in log if e.get("lv") == level and e.get("to") == rkey) >= per_month:
            return Decision(False, f"同一位收件人本月已收過 {per_month} 則{LEVEL_DESC.get(level, level)}（每月上限）")
        return Decision(True)

    def charge(self, level: str, to: str, cost: int, note: str = "") -> None:
        """真的送出去之後才呼叫。"""
        d = self._load()
        d["log"].append({"ts": self._now().isoformat(timespec="seconds"), "lv": level, "cost": int(cost),
                         "to": recipient_key(to), "note": str(note)[:60]})
        self.store.write_json(self.tenant_id, *self.LEDGER, data=d)

    def guarded_send(self, level: str, to: str, cost: int, send: Callable[[], Any], note: str = ""):
        """問→送→記，全程持有該租戶帳本的鎖，兩個執行緒不會同時通過同一則剩餘額度。
        回 (Decision, send 的回傳值或 None)。send() 回傳物件要有 .ok；ok 才記帳。"""
        with self.store.lock(self.tenant_id, "push_ledger"):
            dec = self.check(level, to, cost)
            if not dec.ok:
                return dec, None
            result = send()
            if getattr(result, "ok", False):
                self.charge(level, to, cost, note)
            return dec, result

    # ── 給後台／MCP 看的 ──
    def recipient_used(self, to: str) -> int:
        rkey = recipient_key(to)
        return sum(int(e.get("cost", 1)) for e in self._load()["log"] if e.get("to") == rkey)

    def summary(self) -> dict:
        p = self.policy
        log = self._load()["log"]
        used = self._used(log)
        total = sum(used.values())
        levels = {}
        for lv in (*CONTROL_LEVELS, *p.level_quota):
            if lv in CONTROL_LEVELS:
                levels[lv] = {"desc": LEVEL_DESC[lv], "used_month": used.get(lv, 0),
                              "daily_cap": p.control_daily.get(lv, 0),
                              "used_today": self._used_today(log, lv)}
            else:
                levels[lv] = {"desc": LEVEL_DESC.get(lv, lv), "used_month": used.get(lv, 0),
                              "quota": p.level_quota[lv]}
        return {"month": self._month(), "plan_cap": p.plan_cap, "used": total,
                "remaining": max(0, p.plan_cap - total), "control_reserve": p.control_reserve,
                "levels": levels}
