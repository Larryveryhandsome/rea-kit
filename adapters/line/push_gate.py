# -*- coding: utf-8 -*-
"""推播閘：要主動推給客戶的東西，先給租戶本人看過、他按「送出」才送。

為什麼做成閘門而不是靠每支功能自己記得問：會推播的功能只會越來越多，
只要有一支忘了問，訊息就出去了、收不回來。所以所有主動推播一律走 submit()，誰都繞不過去，
新寫的功能也自動被保護。

不擋什麼（刻意的）：
  · 給租戶本人／審核群的訊息——那是他自己的遙控器。閘門若連「要他審核的卡」都攔，
    他得先按 OK 才收得到「要他按 OK 的東西」，系統就轉不動了。
  · 回覆（reply）——他（或客戶）先開口才答，不經過這裡，也不計額度。
  · 他按過「以後這類都可以」的固定範本（問候、公告）。物件配對內容每次不同，一律逐則審，
    除非租戶在設定裡把物件推播改成自動（policy.modes["match"] = "auto"）。

狀態：wait（等審）→ sent／rejected／deferred（核准了但額度不夠，等額度或等對方開口用回覆補送）
      ／failed（LINE 拒收）／expired（放太久失去時效，留痕不默默丟）
配額結構上是 0 的級別（例如內部日報）根本不排隊：問一件註定送不出去的事，是在浪費他唯一的注意力。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from adapters.line import flex
from adapters.line.client import LineClient, SendResult
from adapters.line.credentials import TenantLineConfig
from adapters.line.push_budget import CONTROL_LEVELS, LEVEL_DESC, PushBudget, cost_of
from adapters.storage import TenantStore

DEFAULT_MODES = {"match": "review", "greeting": "template", "announce": "template", "internal": "auto"}
CUSTOMER_FACING = {"match", "greeting"}


@dataclass(frozen=True)
class GatePolicy:
    modes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODES))
    review_ttl_days: int = 3       # 等審超過幾天作廢（物件可能已經賣掉了）
    match_review_ttl_hours: int = 24   # 物件推播等審超過 24 小時作廢（物件時效短；實務規則）
    deferred_ttl_days: int = 7     # 核准但沒額度，放超過幾天作廢

    @classmethod
    def from_dict(cls, d: dict | None) -> "GatePolicy":
        d = dict(d or {})
        modes = {**DEFAULT_MODES, **(d.get("modes") or {})}
        bad = {k: v for k, v in modes.items() if v not in ("review", "template", "auto")}
        if bad:
            raise ValueError(f"推播模式只能是 review／template／auto：{bad}")
        return cls(modes=modes, review_ttl_days=int(d.get("review_ttl_days", 3)),
                   deferred_ttl_days=int(d.get("deferred_ttl_days", 7)),
                   match_review_ttl_hours=int(d.get("match_review_ttl_hours", 24)))

    def mode(self, level: str) -> str:
        if level in CONTROL_LEVELS:
            return "auto"
        return self.modes.get(level, "review")       # 沒設定的新級別：保守，逐則審


@dataclass(frozen=True)
class GateResult:
    state: str            # sent | held | duplicate | deferred | skipped | failed | rejected | refused
    item_id: str = ""
    reason: str = ""


def _skeleton(text: str) -> str:
    """訊息「骨架」：拿掉數字、英文名、括號補充、標點，只留開頭那句話的樣子。
    「今天有 3 件到期」和「今天有 7 件到期」是同一個範本；換了值班人名也還是同一個範本。"""
    first = str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""
    first = re.sub(r"\d+", "", first)
    first = re.sub(r"[A-Za-z]{2,}", "", first)
    first = re.sub(r"[（(【\[].*?[）)】\]]", "", first)
    first = re.sub(r"[\s　·・、，,。:：\-—/|｜]+", "", first)
    return first[:16]


def template_key(to: str, messages: list[dict]) -> str:
    """「以後這類都可以」記的是【送到哪 × 哪一種訊息】，不是這一則。按群分開記：
    客戶群的東西不會因為批准了內部公告就一起放行。"""
    head = _text_of(messages)
    core = _skeleton(head) or hashlib.sha1(head.encode("utf-8")).hexdigest()[:12]
    return "t:" + hashlib.sha1(f"{to}|{core}".encode("utf-8")).hexdigest()[:12]


def _text_of(messages: list[dict]) -> str:
    m = messages[0] if messages else {}
    return str(m.get("altText") or m.get("text") or "")


def _content_sig(to: str, messages: list[dict]) -> str:
    blob = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(f"{to}|{blob}".encode("utf-8")).hexdigest()[:12]


class PushGate:
    QUEUE = ("line", "push_queue.jsonl")
    REJECTED = ("line", "push_rejected.json")      # 按過「不送」的：同一則永遠不再送（不是 7 天後再問一次）
    TEMPLATES = ("line", "push_templates.json")
    MEMBERS = ("line", "group_members.json")
    POLICY = ("line", "gate_policy.json")

    def __init__(self, store: TenantStore, config: TenantLineConfig, client: LineClient,
                 budget: PushBudget | None = None, policy: GatePolicy | None = None,
                 now: Callable[[], datetime.datetime] = datetime.datetime.now):
        self.store = store
        self.cfg = config
        self.tenant_id = config.tenant_id
        self.client = client
        self._now = now
        self.budget = budget or PushBudget(store, self.tenant_id, now=now)
        self.policy = policy or GatePolicy.from_dict(store.read_json(self.tenant_id, *self.POLICY, default={}))

    # ── 對外：送出請求 ──
    def submit(self, *, to: str, messages: list[dict], level: str, kind: str = "",
               recipient_label: str = "", summary: str = "", members: int | None = None,
               dedup_key: str | None = None, keep_payload: bool = True) -> GateResult:
        """keep_payload=False：佇列紀錄不存訊息內容（例：今日報告含別人的貼文摘要）；送不出去就不補送。"""
        if not 1 <= len(messages or []) <= 5:
            return GateResult("failed", reason="一次要送 1–5 則訊息")
        errs = [e for m in messages for e in flex.validate_message(m)]
        if errs:
            return GateResult("failed", reason="訊息格式不合 LINE 規定：" + "；".join(errs[:3]))
        if not self.budget.policy.is_known(level):
            return GateResult("failed", reason=f"不認得的推播級別：{level}")
        if level not in CONTROL_LEVELS and self.budget.policy.level_quota.get(level, 0) <= 0:
            self._log("skip_zero_quota", level=level, kind=kind)
            return GateResult("skipped", reason=f"{LEVEL_DESC.get(level, level)} 的月配額是 0：不主動推，要看就打字問")
        item = {"id": self._new_id(to, messages), "to": to, "level": level, "kind": kind,
                "recipient_label": recipient_label, "summary": summary or _text_of(messages)[:200],
                "messages": messages, "members": members, "retry_key": str(uuid.uuid4()),
                "key": f"{to}|{dedup_key or _content_sig(to, messages)}",
                "ts": self._now().isoformat(timespec="seconds"), "keep": keep_payload}
        if not keep_payload and not (to in self.cfg.control_targets() or level in CONTROL_LEVELS
                                     or self.policy.mode(level) == "auto"):
            return GateResult("failed", reason="不保留內容的訊息不能排隊等審")
        if item["key"] in (self.store.read_json(self.tenant_id, *self.REJECTED, default={}) or {}):
            self._log("skip_rejected", level=level, kind=kind)
            return GateResult("skipped", reason="這則之前你按過不送，不會再送")
        if to in self.cfg.control_targets() or level in CONTROL_LEVELS:
            return self._send(item, record=True)
        mode = self.policy.mode(level)
        if mode == "auto":
            return self._send(item, record=True)
        if mode == "template" and template_key(to, messages) in self._templates():
            return self._send(item, record=True, why="範本已核准（以後這類都可以）")
        return self._hold(item, allow_always=(mode == "template"))

    # ── 審核 ──
    def approve(self, item_id: str, *, actor: str, always: bool = False) -> GateResult:
        if not self.cfg.can_review(actor):
            return GateResult("refused", item_id, "只有租戶本人（或指定審核人）可以按送出")
        with self.store.lock(self.tenant_id, "push_queue"):
            item = self.get(item_id)
            if not item:
                return GateResult("failed", item_id, "找不到這一筆（可能已處理或已過期）")
            if item.get("state") not in ("wait", "deferred"):
                return GateResult(item["state"], item_id, f"這筆已經是「{item['state']}」了")
            if always and self.policy.mode(item["level"]) == "template":
                tpl = self._templates()
                tpl[template_key(item["to"], item["messages"])] = {
                    "ts": self._now().isoformat(timespec="seconds"), "kind": item.get("kind"),
                    "sample": item.get("summary", "")[:80]}
                self.store.write_json(self.tenant_id, *self.TEMPLATES, data=tpl)
            return self._send(item, record=False)

    def reject(self, item_id: str, *, actor: str) -> GateResult:
        if not self.cfg.can_review(actor):
            return GateResult("refused", item_id, "只有租戶本人（或指定審核人）可以按不送")
        with self.store.lock(self.tenant_id, "push_queue"):
            item = self.get(item_id)
            if not item:
                return GateResult("failed", item_id, "找不到這一筆")
            if item.get("state") not in ("wait", "deferred"):
                return GateResult(item["state"], item_id, f"這筆已經是「{item['state']}」了")
            self._mark(item_id, "rejected", why=f"{actor[:6]}… 按了不送")
            rejected = self.store.read_json(self.tenant_id, *self.REJECTED, default={}) or {}
            rejected[item["key"]] = self._now().isoformat(timespec="seconds")
            self.store.write_json(self.tenant_id, *self.REJECTED, data=rejected)
            return GateResult("rejected", item_id, "不送了；同一則以後也不會再送")

    # ── 查詢 ──
    def _all(self) -> list[dict]:
        merged: dict[str, dict] = {}
        for r in self.store.read_jsonl(self.tenant_id, *self.QUEUE):
            rid = r.get("id")
            if rid:
                merged[rid] = {**merged.get(rid, {}), **r}
        return list(merged.values())

    def get(self, item_id: str) -> dict | None:
        return next((r for r in self._all() if r.get("id") == item_id), None)

    def pending(self) -> list[dict]:
        """等審的，客戶看得到的排前面（同級舊的先）。"""
        rank = {"match": 0, "greeting": 2}
        rows = [r for r in self._all() if r.get("state") == "wait"]
        return sorted(rows, key=lambda r: (rank.get(r.get("level"), 1), str(r.get("ts"))))

    def deferred(self, to: str | None = None) -> list[dict]:
        rows = [r for r in self._all() if r.get("state") == "deferred" and (to is None or r.get("to") == to)]
        return sorted(rows, key=lambda r: str(r.get("ts")))

    def review_messages(self, limit: int = 5) -> list[dict]:
        """「待審」指令用：把等審的卡做成訊息，走回覆（不計額度）送給本人。"""
        out = []
        for item in self.pending()[:limit]:
            out.append(flex.flex_message("待審：" + item.get("summary", "")[:60], self._review_bubble(item)))
        return out

    # ── 補送與清理 ──
    def retry_deferred(self, limit: int = 20) -> list[GateResult]:
        """核准了但當時沒額度的，額度恢復後補送。額度又死了就停，不要一直白敲 429。"""
        out = []
        for item in self.deferred()[:limit]:
            with self.store.lock(self.tenant_id, "push_queue"):
                cur = self.get(item["id"])
                if not cur or cur.get("state") != "deferred":
                    continue
                res = self._send(cur, record=False)
            out.append(res)
            if res.state == "deferred":
                break
        return out

    def take_for_reply(self, to: str, limit: int = 4) -> list[dict]:
        """對方剛開口（有 reply token）→ 把欠他的訊息改用回覆補送：不計額度。
        回傳要附在回覆裡的 messages，並把那幾筆標成 sent_by_reply。"""
        msgs: list[dict] = []
        with self.store.lock(self.tenant_id, "push_queue"):
            for item in self.deferred(to):
                if len(msgs) + len(item["messages"]) > limit:
                    break
                msgs.extend(item["messages"])
                self._mark(item["id"], "sent_by_reply", why="對方開口，改用回覆補送（不計額度）")
        return msgs

    def expire_stale(self) -> list[str]:
        now = self._now()
        gone = []
        for item in self._all():
            st = item.get("state")
            ttl = self.policy.review_ttl_days if st == "wait" else (
                self.policy.deferred_ttl_days if st == "deferred" else None)
            if ttl is None:
                continue
            try:
                elapsed = now - datetime.datetime.fromisoformat(str(item.get("ts"))[:19])
                age = elapsed.days
            except ValueError:
                elapsed, age = None, ttl
            if st == "wait" and item.get("level") == "match" and elapsed is not None                     and elapsed >= datetime.timedelta(hours=self.policy.match_review_ttl_hours):
                age = ttl                                  # 物件推播：24 小時就作廢
            if age >= ttl:
                self._mark(item["id"], "expired", why=f"{'等審' if st == 'wait' else '等額度'} {age} 天，已失去時效")
                gone.append(item["id"])
        return gone

    # ── 內部 ──
    def _new_id(self, to: str, messages: list[dict]) -> str:
        # 編號要含「送到哪」：同一則內容同一秒送去兩個群，只用內容雜湊會撞號
        return self._now().strftime("%m%d%H%M%S") + "-" + _content_sig(to, messages)[:6]

    def _templates(self) -> dict:
        return self.store.read_json(self.tenant_id, *self.TEMPLATES, default={}) or {}

    def _log(self, ev: str, **kw: Any) -> None:
        self.store.append_jsonl(self.tenant_id, "line", "gate_log.jsonl",
                                record={"ts": self._now().isoformat(timespec="seconds"), "ev": ev, **kw})

    def _mark(self, item_id: str, state: str, **extra: Any) -> None:
        self.store.append_jsonl(self.tenant_id, *self.QUEUE, record={
            "id": item_id, "state": state, "decided": self._now().isoformat(timespec="seconds"), **extra})

    def _members(self, to: str, given: int | None) -> int | None:
        if given:
            return int(given)
        if to.startswith("U"):
            return 1
        cache = self.store.read_json(self.tenant_id, *self.MEMBERS, default={}) or {}
        hit = cache.get(to)
        today = self._now().date().isoformat()
        if hit and hit.get("date") == today:
            return int(hit["count"])
        n = self.client.group_member_count(to)
        if n:
            cache[to] = {"count": n, "date": today}
            self.store.write_json(self.tenant_id, *self.MEMBERS, data=cache)
        return n

    def _send(self, item: dict, *, record: bool, why: str = "") -> GateResult:
        keep = item.get("keep", True)
        if record:
            saved = item if keep else {**item, "messages": [], "summary": f"（不保留內容，{len(item['messages'])} 則）"}
            self.store.append_jsonl(self.tenant_id, *self.QUEUE, record={**saved, "state": "sending"})
        to, level = item["to"], item["level"]
        cost = cost_of(to, self._members(to, item.get("members")), self.budget.policy.est_members)
        dec, res = self.budget.guarded_send(
            level, to, cost, lambda: self.client.push(to, item["messages"], retry_key=item.get("retry_key")),
            note=item.get("kind", ""))
        # 審核卡沒推出去不排補送：「待審」指令隨時能用回覆重新產生，補送舊卡只會洗版；不保留內容的也沒得補
        no_retry = dec.zero_quota or item.get("kind") == "review_card" or not keep
        if not dec.ok:
            if no_retry:
                self._mark(item["id"], "skipped", why=dec.reason)
                return GateResult("skipped", item["id"], dec.reason)
            self._mark(item["id"], "deferred", why=dec.reason)
            return GateResult("deferred", item["id"], dec.reason + "；等額度恢復或對方開口時用回覆補送")
        assert isinstance(res, SendResult)
        if res.ok:
            self._mark(item["id"], "sent", why=why or "已送出", cost=cost)
            return GateResult("sent", item["id"], why or "已送出")
        if res.quota_exhausted and no_retry:
            self._mark(item["id"], "skipped", why=res.error)
            return GateResult("skipped", item["id"], res.error)
        if res.quota_exhausted:
            self._mark(item["id"], "deferred", why=res.error)
            return GateResult("deferred", item["id"], "LINE 回本月額度已用完；等額度恢復或對方開口時用回覆補送")
        self._mark(item["id"], "failed", why=res.error)
        return GateResult("failed", item["id"], res.error)

    def _review_bubble(self, item: dict) -> dict:
        return flex.review_bubble(item_id=item["id"], recipient_label=item.get("recipient_label", ""),
                                  summary=item.get("summary", ""),
                                  level_desc=LEVEL_DESC.get(item["level"], item["level"]),
                                  allow_always=self.policy.mode(item["level"]) == "template")

    def _hold(self, item: dict, *, allow_always: bool) -> GateResult:
        with self.store.lock(self.tenant_id, "push_queue"):
            for r in self._all():
                if r.get("key") == item["key"] and r.get("state") in ("wait", "deferred"):
                    return GateResult("duplicate", r["id"], "同一則已經在等你審核")
            self.store.append_jsonl(self.tenant_id, *self.QUEUE, record={**item, "state": "wait"})
        review_to = self.cfg.review_to
        if not review_to:
            return GateResult("held", item["id"], "已排隊等審；還沒設定你本人的 LINE ID，請到後台看待審清單")
        # 預覽＋審核卡放同一個 push：LINE 按「收件人×次」計費，一次最多 5 則訊息，合在一起只算 1 則
        preview = item["messages"][:3]
        card = flex.flex_message("要送嗎？" + item.get("summary", "")[:40], self._review_bubble(item))
        res = self.submit(to=review_to, messages=[*preview, card], level="review",
                          kind="review_card", recipient_label="你本人")
        if res.state != "sent":
            return GateResult("held", item["id"], f"已排隊等審，但審核卡沒推出去（{res.reason}）；"
                                                  "在 LINE 對官方帳號打「待審」就會用回覆叫出來（不計額度）")
        return GateResult("held", item["id"], "已排隊等審，審核卡已送到你的 LINE")
