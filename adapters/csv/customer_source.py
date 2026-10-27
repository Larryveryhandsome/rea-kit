# -*- coding: utf-8 -*-
"""CustomerSource 的第一個實作：租戶自己上傳的客戶需求 CSV。

每位客戶變成一張「客需卡」（core/listing_matching 吃的格式）＋推播對象（LINE 群組或個人 ID）：
  customer_id, label（稱呼）, status(active|paused|closed), line_target, members,
  need_card = {transaction, preferred_areas[], budget_min, budget_max, budget_tolerance_pct,
               property_type, rooms_min, version, updated_at}

個資法：客戶資料是租戶蒐集的，我們是受委託處理者。所以
  - 只匯入配對需要的欄位；電話、身分證、地址、Email、生日、備註一律略過（報告列出略過的欄名）
  - 匯入是「更新或新增」：檔案裡沒有的客戶不動（不會因為少傳一份就把客戶清掉）
  - export() 匯出、delete_all() 整批刪除，給後台的「下載我的資料」「刪除我的資料」用
"""
from __future__ import annotations

import csv
import datetime
import io
import re
import uuid
from copy import deepcopy
from typing import Any, Callable, Iterable, Mapping

from adapters.csv import parsing as P
from adapters.csv.listing_source import ImportReport
from adapters.line import groups
from adapters.line.credentials import is_line_id
from adapters.storage import TenantStore
from core.listing_matching import validate_need_card
from core.property_schema import canonical_area, canonical_type

CUSTOMER_ALIASES: dict[str, tuple[str, ...]] = {
    "customer_id": ("customer_id", "客戶編號", "客戶代號", "代號", "編號", "id"),
    "label": ("label", "稱呼", "客戶稱呼", "暱稱", "顯示名稱", "姓名", "客戶名稱", "名稱"),
    "transaction": ("transaction", "交易", "買或租", "買租", "需求類別", "類別"),
    "preferred_areas": ("preferred_areas", "偏好區域", "需求區域", "想買區域", "想租區域", "區域", "地區"),
    "budget_max": ("budget_max", "預算上限", "總價上限", "租金上限", "預算"),
    "budget_min": ("budget_min", "預算下限"),
    "property_type": ("property_type", "需求型態", "型態", "物件類型", "類型"),
    "rooms_min": ("rooms_min", "最少房數", "需求房數", "房數"),
    "line_target": ("line_target", "LINE群組ID", "LINE群ID", "群組ID", "LINEID", "推播對象"),
    "members": ("members", "群人數", "人數"),
    "status": ("status", "狀態"),
}
SENSITIVE_WORDS = ("電話", "手機", "身分證", "地址", "email", "e-mail", "生日", "備註", "職業", "收入")
EXPORT_FIELDS = ("customer_id", "label", "status", "transaction", "preferred_areas", "budget_min", "budget_max",
                 "property_type", "rooms_min", "line_target", "members")


def validate_customer_label(value: str) -> str:
    label = str(value).strip()
    if not label or len(label) > 30 or any(ord(c) < 32 for c in label):
        raise ValueError("請用 1–30 字的客戶暱稱")
    if re.search(r"\d{7,}", label) or re.search(r"\d(?:[\s\-－.()（）]*\d){7,}", label) or "@" in label:
        raise ValueError("不要填電話、email 或身分證，請改用暱稱")
    return label


def parse_status(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return "active"
    if re.search(r"成交|已買|已租|結案|失效|不買|不租|closed", s, re.I):
        return "closed"
    if re.search(r"暫停|停推|保留|paused", s, re.I):
        return "paused"
    return "active"


def parse_budget(v: Any, *, transaction: str, header: str = "") -> tuple[float | None, float | None]:
    """「1200」「1,200萬」「1000-1500萬」「2萬/月」→ (下限, 上限)，單位同物件（售：萬；租：元/月）。"""
    s = str(v or "").replace(",", "").replace("，", "").strip()
    if not s:
        return None, None
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    unit = "萬" if "萬" in s else ("元" if "元" in s else "")
    conv = lambda n: P.parse_price(n + unit, transaction=transaction, header=header)
    if len(nums) >= 2 and re.search(r"[-~～至到]", s):
        lo, hi = conv(nums[0]), conv(nums[1])
        return (min(lo, hi), max(lo, hi))
    return None, conv(nums[0]) if nums else None


def missing_fields(need: Mapping[str, Any]) -> list[str]:
    """配對前一定要有的欄位（缺了就不配，交給租戶補）。"""
    out = []
    if need.get("transaction") not in ("buy", "rent"):
        out.append("transaction")
    if not need.get("preferred_areas"):
        out.append("preferred_areas")
    if need.get("budget_max") is None:
        out.append("budget_max")
    return out


class CsvCustomerSource:
    CUSTOMERS = ("customers", "customers.json")

    def __init__(self, store: TenantStore, now: Callable[[], datetime.datetime] = datetime.datetime.now):
        self.store = store
        self._now = now

    def import_customers(self, tenant_id: str, data: bytes | str, *, mapping: Mapping[str, str] | None = None,
                         default_city: str | None = None, budget_tolerance_pct: float = 10.0) -> ImportReport:
        headers, rows = P.read_table(P.decode_bytes(data))
        sensitive = P.sensitive_columns(headers, SENSITIVE_WORDS)
        if mapping and any(h in sensitive for h in mapping.values()):
            raise ValueError("不能把電話／身分證／地址這類欄位對映進客戶資料")
        mp, unmapped = P.resolve_mapping([h for h in headers if h not in sensitive], CUSTOMER_ALIASES, mapping)
        missing = [f for f in ("customer_id", "transaction", "preferred_areas", "budget_max") if f not in mp]
        if missing:
            raise ValueError("檔案缺必要欄位：" + "、".join(missing) + "（可用欄位對映指定）")
        rep = ImportReport(rows_total=len(rows), mapping=mp, unmapped_columns=unmapped,
                           ignored_sensitive_columns=sensitive)
        ts = self._now().isoformat(timespec="seconds")
        seen: set[str] = set()
        with self.store.lock(tenant_id, "customers"):
            book = self._book(tenant_id)
            for line, row in rows:
                try:
                    cust = self._normalize(row, mp, default_city, budget_tolerance_pct)
                except ValueError as e:
                    rep.errors.append({"line": line, "reason": str(e)})
                    continue
                cid = cust["customer_id"]
                if cid in seen:
                    rep.errors.append({"line": line, "reason": "客戶編號重複（只收第一筆）"})
                    continue
                seen.add(cid)
                if cust.pop("_bad_target", False):
                    rep.errors.append({"line": line, "reason": "LINE ID 格式不對，已匯入客戶但不會推播（請補正確的群組 ID）"})
                old = book.get(cid)
                need = cust["need_card"]
                if old is None:
                    need.update(version=1, updated_at=ts)
                    book[cid] = {**cust, "source": "csv", "imported_at": ts, "updated_at": ts}
                    rep.new_ids.append(cid)
                else:
                    old_need = {k: v for k, v in (old.get("need_card") or {}).items() if k not in ("version", "updated_at")}
                    need_changed = old_need != need
                    need.update(version=int((old.get("need_card") or {}).get("version", 1)) + (1 if need_changed else 0),
                                updated_at=ts if need_changed else (old.get("need_card") or {}).get("updated_at", ts))
                    merged = {**old, **cust, "updated_at": ts}
                    if merged.get("line_target") is None and old.get("line_target"):
                        merged["line_target"] = old["line_target"]      # 新檔沒填，不覆蓋舊的綁定
                    if need_changed or any(old.get(k) != merged.get(k) for k in ("label", "status", "line_target", "members")):
                        rep.changed_ids.append(cid)
                    else:
                        rep.unchanged_count += 1
                    book[cid] = merged
                rep.rows_ok += 1
            self.store.write_json(tenant_id, *self.CUSTOMERS, data=book)
        return rep

    @staticmethod
    def _normalize(row: Mapping[str, str], mp: Mapping[str, str], default_city: str | None,
                   tolerance: float) -> dict:
        get = lambda f: row.get(mp[f], "") if f in mp else ""
        cid = get("customer_id").strip()
        if not cid:
            raise ValueError("缺客戶編號")
        if len(cid) > 64:
            raise ValueError("客戶編號超過 64 字")
        tx = P.parse_transaction(get("transaction"))
        if tx not in ("buy", "rent"):
            raise ValueError("買或租看不懂（要寫 買／租）")
        areas = []
        for a in P.split_areas(get("preferred_areas")):
            _, full = P.normalize_area(a, default_city=default_city)
            if full and full not in areas:
                areas.append(full)
        lo, hi = parse_budget(get("budget_max"), transaction=tx, header=mp.get("budget_max", ""))
        if "budget_min" in mp and get("budget_min"):
            _, lo = parse_budget(get("budget_min"), transaction=tx, header=mp["budget_min"])
        target = get("line_target").strip()
        members = P.parse_number(get("members")) if get("members") else None
        need = {"transaction": tx, "preferred_areas": areas, "budget_min": lo, "budget_max": hi,
                "budget_tolerance_pct": tolerance, "property_type": P.parse_property_type(get("property_type")),
                "rooms_min": P.parse_rooms(get("rooms_min"))}
        out = {"customer_id": cid, "label": get("label").strip()[:30] or None,
               "status": parse_status(get("status")), "need_card": need,
               "line_target": target if is_line_id(target) else None,
               "members": int(members) if members else None}
        if target and not is_line_id(target):
            out["_bad_target"] = True
        return out

    # ── CustomerSource 介面 ──
    def save_need(self, tenant_id: str, *, label: str, need: Mapping[str, Any],
                  customer_id: str | None = None, expected_version: int | None = None) -> dict:
        """Explicit confirmed form input; shares the existing tenant customer book.

        No chat history, contact id, freeform notes or unknown fields are stored.
        Editing uses optimistic version checking to avoid overwriting another form.
        """
        label = validate_customer_label(label)
        allowed = {"transaction", "preferred_areas", "budget_min", "budget_max", "budget_tolerance_pct",
                   "property_type", "rooms_min", "size_min", "size_max", "age_max", "parking", "elevator"}
        clean = {k: deepcopy(v) for k, v in need.items() if k in allowed}
        clean.setdefault("budget_tolerance_pct", 0)
        errors = validate_need_card(clean)
        if errors:
            raise ValueError("; ".join(errors))
        areas = clean["preferred_areas"]
        if isinstance(areas, str):
            areas = [areas]
        clean["preferred_areas"] = list(dict.fromkeys(canonical_area(x) for x in areas))
        clean["property_type"] = canonical_type(clean.get("property_type")) or None
        for field in ("budget_min", "budget_max", "budget_tolerance_pct", "rooms_min", "size_min", "size_max", "age_max"):
            if clean.get(field) is not None:
                clean[field] = float(clean[field])
        with self.store.lock(tenant_id, "customers"):
            book = self._book(tenant_id)
            old = book.get(customer_id) if customer_id else None
            if customer_id and old is None:
                raise KeyError("找不到客戶")
            version = (old or {}).get("need_card", {}).get("version", 0)
            if old and expected_version != version:
                raise ValueError("需求已被更新，請重新開啟再修改")
            cid = customer_id or ("B-" + uuid.uuid4().hex[:12].upper())
            ts = self._now().isoformat(timespec="seconds")
            clean.update(version=version + 1, updated_at=ts)
            customer = {**(old or {}), "customer_id": cid, "label": label, "need_card": clean,
                        "status": (old or {}).get("status", "active"), "updated_at": ts,
                        "source": "confirmed-form"}
            book[cid] = customer
            self.store.write_json(tenant_id, *self.CUSTOMERS, data=book)
            return deepcopy(customer)

    def update_identity(self, tenant_id: str, customer_id: str, *, label: str | None = None,
                        status: str | None = None) -> dict:
        if label is not None:
            label = validate_customer_label(label)
        if status is not None and status not in {"active", "paused", "closed"}:
            raise ValueError("客戶狀態不正確")
        with self.store.lock(tenant_id, "customers"):
            book = self._book(tenant_id)
            if customer_id not in book:
                raise KeyError("找不到客戶")
            if label is not None:
                book[customer_id]["label"] = label.strip()
            if status is not None:
                book[customer_id]["status"] = status
            book[customer_id]["updated_at"] = self._now().isoformat(timespec="seconds")
            self.store.write_json(tenant_id, *self.CUSTOMERS, data=book)
            return deepcopy(book[customer_id])

    def list_customers(self, tenant_id: str, *, active_only: bool = True) -> list[dict]:
        rows = sorted(self._book(tenant_id).values(), key=lambda c: c["customer_id"])
        return [c for c in rows if c.get("status") == "active"] if active_only else rows

    def get(self, tenant_id: str, customer_id: str) -> dict | None:
        return self._book(tenant_id).get(customer_id)

    def get_need_card(self, tenant_id: str, customer_id: str) -> dict | None:
        c = self.get(tenant_id, customer_id)
        if c is None:
            return None
        need = dict(c.get("need_card") or {})
        return {"customer_id": c["customer_id"], "label": c.get("label"), "status": c.get("status"),
                "need_card": need, "missing": missing_fields(need),
                "can_push": bool(c.get("line_target")) and c.get("status") == "active"}

    def bind_line_target(self, tenant_id: str, customer_id: str, line_target: str, members: int | None = None) -> None:
        if not is_line_id(line_target):
            raise ValueError("LINE ID 格式不對")
        with self.store.lock(tenant_id, "customers"):
            book = self._book(tenant_id)
            if customer_id not in book:
                raise KeyError(customer_id)
            book[customer_id].update(line_target=line_target, members=members,
                                     updated_at=self._now().isoformat(timespec="seconds"))
            self.store.write_json(tenant_id, *self.CUSTOMERS, data=book)

    def import_groups(self, tenant_id: str, line_events: Iterable[dict]) -> list[str]:
        """把 LINE 事件（官方帳號被拉進哪些群）套進群組名冊，回目前在的群。綁客戶用 bind_line_target。"""
        groups.apply_events(self.store, tenant_id, line_events)
        return groups.active_groups(self.store, tenant_id)

    def export(self, tenant_id: str) -> str:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, lineterminator="\n")
        w.writeheader()
        for c in self.list_customers(tenant_id, active_only=False):
            need = c.get("need_card") or {}
            w.writerow({
                "customer_id": c["customer_id"], "label": c.get("label") or "", "status": c.get("status"),
                "transaction": need.get("transaction"), "preferred_areas": "、".join(need.get("preferred_areas") or []),
                "budget_min": need.get("budget_min") if need.get("budget_min") is not None else "",
                "budget_max": need.get("budget_max") if need.get("budget_max") is not None else "",
                "property_type": need.get("property_type") or "",
                "rooms_min": need.get("rooms_min") if need.get("rooms_min") is not None else "",
                "line_target": c.get("line_target") or "", "members": c.get("members") or ""})
        return buf.getvalue()

    def delete_all(self, tenant_id: str) -> None:
        with self.store.lock(tenant_id, "customers"):
            p = self.store.path(tenant_id, *self.CUSTOMERS)
            if p.exists():
                p.unlink()

    def _book(self, tenant_id: str) -> dict[str, dict]:
        return self.store.read_json(tenant_id, *self.CUSTOMERS, default={}) or {}
