# -*- coding: utf-8 -*-
"""全市場新物件盤點（負責人 2026-10-03：「你必須知道哪個品牌今天上架了甚麼房子」）。

  每個地區（例：宜蘭縣宜蘭市）每天一次，對每個品牌／平台網站各查一次「最近一天搜尋引擎新收錄的物件頁」；
  第一次盤點這個地區時多查「最近一週」當基準。讀出品牌、地區、總價、型態（core/market_sources.py），
  存進系統分區的物件池：只存整理過的欄位與網址，不存摘要原文、不存電話。
  同一個地區今天掃過，別位仲介直接用（搜尋用量記在 sys-market，有自己的每日上限）。

  今日報告：仲介地區裡「今天第一次看到」的物件，依品牌分卡；編號比這個網站在這區以前看過的都大 → 標 🆕（新刊登），
  其他是搜尋引擎今天才收錄的（可能刊登幾天了）。同一批物件也拿來幫買方配對（core/listing_matching.py 同一套規則）。
只用搜尋服務 API 回來的標題、摘要、網址；不打開、不轉存原頁。結果只給仲介本人。
"""
from __future__ import annotations

import datetime
import json
import os
import re
from collections import Counter
from typing import Any

from adapters.line import flex
from adapters.web_search import BudgetedSearch, SearchError, SearchHit
from core import market_sources as MS
from core import patrol_keywords as PK
from core.listing_matching import match_listings
from core.tw_districts import COUNTIES, DISTRICTS

SYS = "sys-line-shared"
POOL = ("market", "pool.json")
SCANS = ("market", "scans.json")
SEARCH_TENANT = "sys-market"                 # 搜尋用量記在這個代號（跟仲介自己的上限分開）
MARKET_CAP = int(os.environ.get("REA_MARKET_DAILY_CAP", "80"))
KEEP_DAYS = 45
MAX_AREAS = 3                                # 每位仲介每天最多盤點幾個地區（多的輪流）
MAX_PAGES = 2
ROWS = 6                                     # 一張卡列幾間
MAX_BYTES = 45_000                           # 一則 carousel 的大小（LINE 上限 50KB，留餘裕）
MATCH_DAYS = 3                               # 配對看最近幾天進池的物件（報告漏一天也補得到）
OPTIONAL = {"price", "rooms", "size_ping", "age_years", "parking", "elevator"}   # 缺了還是給（卡片註明），型態缺不給
NOT_HOME = {"農地", "土地", "廠房", "辦公", "車位", "農舍"}                       # 客人沒指定型態時不給這些

_catalog: dict[str, Any] = {}


def catalog() -> MS.Catalog:
    """預設清單＋執行資料夾設定檔（REA_MARKET_SOURCES；檔案改了下次自動重讀）。"""
    path = os.environ.get("REA_MARKET_SOURCES", "").strip()
    try:
        mtime = os.path.getmtime(path) if path else None
    except OSError:
        mtime = None
    if _catalog.get("key") != (path, mtime):
        _catalog.update(key=(path, mtime), value=MS.load_catalog(path or None))
    return _catalog["value"]


def query_term(county: str, district: str | None) -> str:
    if not district:
        return PK.county_term(county)
    term = PK.district_term(county, district)
    if term == PK.county_term(county):
        return district                                   # 宜蘭市→「宜蘭市」，不是整個宜蘭
    if term in PK.ambiguous_terms() or district in PK._GENERIC:
        return f"{PK.county_term(county)} {term}"         # 同名的區（中山、信義）帶縣市
    return term


def area_key(county: str, district: str | None) -> str:
    return county + (district or "")


def area_name(areas: list[tuple[str, str | None]]) -> str:
    names = [d or c for c, d in areas]
    return "、".join(names[:3]) + ("等" if len(names) > 3 else "")


def tenant_areas(prospect: dict | None, customers: list[dict] = ()) -> list[tuple[str, str | None]]:
    """仲介的地區：海巡設定的地區；沒設定就用買方要的地區。"""
    out: list[tuple[str, str | None]] = []
    p = prospect or {}
    areas = p.get("areas") or {}
    for county in list(p.get("cities") or []) + [c for c in areas if c not in (p.get("cities") or [])]:
        ds = [d for d in areas.get(county) or [] if d in DISTRICTS.get(county, ())]
        out += [(county, d) for d in ds] if ds else [(county, None)]
    if not out:
        from core.search_links import _split
        for cust in customers:
            for a in (cust.get("need_card") or {}).get("preferred_areas") or []:
                c, d = _split(a)
                if c:
                    out.append((c, d))
    return [a for a in dict.fromkeys(out) if a[0] in COUNTIES]


def in_areas(item: dict, areas: list[tuple[str, str | None]]) -> bool:
    return any(item.get("county") == c and (d is None or item.get("district") == d) for c, d in areas)


def _budget(search: BudgetedSearch) -> BudgetedSearch:
    return BudgetedSearch(search.provider, search.store, now=search.now, daily_cap=search.daily_cap,
                          tenant_cap=MARKET_CAP, cache_ttl=getattr(search, "cache_ttl", None))


def _series(key: str) -> str:
    """編號序列：同一個網站、同一種開頭字母的編號才比大小（住商 XS／WS／c 是不同序列）。"""
    family, _, oid = key.partition(":")
    return family + ":" + re.match(r"[A-Z]*", oid).group(0)


def scan_area(search: BudgetedSearch, store, county: str, district: str | None, *, day: datetime.date,
              cat: MS.Catalog | None = None) -> dict:
    """掃一個地區（今天掃過就直接回上次的紀錄）。呼叫端要拿著 market-scan 鎖。"""
    cat = cat or catalog()
    d = day.isoformat()
    key = area_key(county, district)
    scans = store.read_json(SYS, *SCANS, default={}) or {}
    rec = scans.get(key) or {}
    if rec.get("day") == d:
        return rec
    baseline = not rec
    term = query_term(county, district)
    found: dict[str, dict] = {}
    queries, errors, dropped = 0, [], Counter()
    try:
        for src in cat.sources:
            q = f"site:{src.site} {term}" + (f" {src.terms}" if src.terms else "")
            for recency in (("d", "w") if baseline else ("d",)):
                for page in range(1, MAX_PAGES + 1):
                    hits = search.search(SEARCH_TENANT, q, recency=recency, page=page) if page > 1 else \
                        search.search(SEARCH_TENANT, q, recency=recency)
                    queries += 1
                    for hit in hits:
                        item, why = MS.parse(hit, src, cat, hint_county=county)
                        if not item:
                            dropped[why] += 1
                        else:
                            found[item["key"]] = MS.merge(found[item["key"]], item) if item["key"] in found else item
                    if len(hits) < 10:
                        break
    except SearchError as e:                       # 額度用完／被限速／金鑰錯：今天就停在這裡，已經找到的照樣存
        errors.append(str(e))
    maxes = rec.get("max") or {}
    new_max, new = dict(maxes), 0
    cutoff = (day - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    with store.lock(SYS, "market-pool"):
        pool = store.read_json(SYS, *POOL, default={}) or {}
        for k, it in found.items():
            series = _series(k)
            if k in pool:
                pool[k] = {**MS.merge(pool[k], it), "last_seen": d}
            else:
                fresh = not baseline and it.get("num") is not None and series in maxes and it["num"] > maxes[series]
                pool[k] = {**it, "first_seen": d, "last_seen": d, "fresh": fresh, "found_in": key}
                new += 1
            if it.get("num") is not None:
                new_max[series] = max(new_max.get(series, 0), it["num"])
        pool = {k: v for k, v in pool.items() if v.get("last_seen", "") >= cutoff}
        store.write_json(SYS, *POOL, data=pool)
    rec = {"day": d, "first_day": rec.get("first_day") or d, "queries": queries, "found": len(found), "new": new,
           "errors": errors, "max": new_max, "dropped": dict(dropped)}
    with store.lock(SYS, "market-scans"):
        scans = store.read_json(SYS, *SCANS, default={}) or {}
        scans[key] = rec
        store.write_json(SYS, *SCANS, data=scans)
    return rec


def ensure(search: BudgetedSearch, store, areas: list[tuple[str, str | None]], *, day: datetime.date) -> list[dict]:
    """把這些地區今天都掃過（別位仲介掃過的直接用）。一次一個地區排隊，不會兩個人同時掃同一區多花錢。"""
    if not search.available or not areas:
        return []
    if len(areas) > MAX_AREAS:                     # 地區多：每天輪一批
        start = (day.toordinal() * MAX_AREAS) % len(areas)
        areas = (areas[start:] + areas[:start])[:MAX_AREAS]
    budget = _budget(search)
    out = []
    for county, district in areas:
        with store.lock(SYS, "market-scan", timeout=300):
            out.append(scan_area(budget, store, county, district, day=day))
    return out


def board(store, areas: list[tuple[str, str | None]], day: datetime.date) -> dict:
    """今天在仲介地區第一次看到的物件（＋同縣市別鄉鎮的，當「附近」）。"""
    d = day.isoformat()
    pool = store.read_json(SYS, *POOL, default={}) or {}
    scans = store.read_json(SYS, *SCANS, default={}) or {}
    todays = [i for i in pool.values() if i.get("first_seen") == d]
    counties = {c for c, _ in areas}
    recs = [scans.get(area_key(c, dd)) or {} for c, dd in areas]
    return {"areas": areas, "items": [i for i in todays if in_areas(i, areas)],
            "nearby": [i for i in todays if i.get("county") in counties and not in_areas(i, areas)],
            "baseline": any(r.get("first_day") == d for r in recs),
            "scanned": bool(areas) and all(r.get("day") == d for r in recs),
            "errors": sorted({e for r in recs if r.get("day") == d for e in r.get("errors") or []})}


def brand_of(item: dict) -> str:
    return item.get("brand") or item.get("site") or "其他"


def _order(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda i: (not i.get("fresh"), -(i.get("num") or 0)))


def head_line(b: dict) -> str | None:
    if not b.get("areas"):
        return None
    where = area_name(b["areas"])
    items = b["items"]
    if not b["scanned"] and not items:
        return f"市場：{where}今天還沒盤點" + (f"（{b['errors'][0]}）" if b.get("errors") else "")
    if not items:
        return f"市場：{where}今天各品牌沒有新收錄的物件" + (f"（附近鄉鎮 {len(b['nearby'])} 筆）" if b["nearby"] else "")
    counts = Counter(brand_of(i) for i in items).most_common()
    brands = "、".join(f"{name} {n}" for name, n in counts[:6]) + ("…" if len(counts) > 6 else "")
    fresh = sum(1 for i in items if i.get("fresh"))
    if b["baseline"]:
        return f"市場：第一次盤點{where}，最近一週各品牌 {len(items)} 筆（{brands}）；之後每天只報新的"
    return (f"市場：{where}今天各品牌新出現 {len(items)} 筆（{brands}）"
            + (f"，其中 🆕 {fresh} 筆是新刊登" if fresh else ""))


def _row(item: dict) -> dict:
    title = ("🆕 " if item.get("fresh") else "") + (item.get("title") or "物件")
    return {"type": "box", "layout": "vertical", "paddingTop": "6px", "paddingBottom": "6px",
            "action": {"type": "uri", "label": "看物件", "uri": item["url"]},
            "contents": [{"type": "text", "text": title[:60], "size": "sm", "weight": "bold", "color": flex.INK1,
                          "wrap": True, "maxLines": 2},
                         {"type": "text", "text": MS.label(item) or " ", "size": "xs", "color": flex.INK2, "wrap": True}]}


def _bubble(title: str, items: list[dict]) -> dict:
    c = flex.LISTING
    rows: list[dict] = []
    for i, it in enumerate(items):
        if i:
            rows.append({"type": "separator"})
        rows.append(_row(it))
    return {"type": "bubble", "size": "mega",
            "header": {"type": "box", "layout": "vertical", "backgroundColor": c["bar"], "paddingAll": "12px",
                       "contents": [flex._txt(title, size="md", color="#FFFFFF", weight="bold")]},
            "body": {"type": "box", "layout": "vertical", "spacing": "none", "paddingAll": "12px",
                     "contents": rows + [flex._txt("點物件直接開那個網站", size="xxs", color=flex.INK2)]}}


def messages(b: dict) -> list[dict]:
    """依品牌分卡（多的品牌排前面），每張最多 6 間；最多 12 張，留一張給附近鄉鎮。"""
    groups: dict[str, list[dict]] = {}
    for it in _order(b.get("items") or []):
        groups.setdefault(brand_of(it), []).append(it)
    bubbles: list[dict] = []
    room = flex.MAX_CAROUSEL - (1 if b.get("nearby") else 0)
    for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        for start in range(0, len(items), ROWS):
            if len(bubbles) >= room:
                break
            part = items[start:start + ROWS]
            more = "（續）" if start else ""
            bubbles.append(_bubble(f"{name}{more}｜{len(items)} 筆", part))
    if b.get("nearby") and len(bubbles) < flex.MAX_CAROUSEL:
        near = _order(b["nearby"])
        bubbles.append(_bubble(f"附近鄉鎮｜{len(near)} 筆", near[:ROWS]))
    if not bubbles:
        return []
    n = len(b.get("items") or [])
    while True:                                    # LINE 一則 carousel 上限 50KB；網址長的日子少放幾張，不要整則被拒
        msg = flex.flex_message(f"今日市場：各品牌新物件 {n} 筆", flex.carousel(bubbles))
        if len(json.dumps(msg, ensure_ascii=False).encode("utf-8")) <= MAX_BYTES or len(bubbles) == 1:
            return [msg]
        bubbles.pop()


# ── 買方配對：物件池裡最近幾天的物件，用跟上架配對同一套規則篩 ─────────────────────────

def _own_brand(item: dict, profile: dict | None) -> bool:
    mine = (profile or {}).get("brand")
    if not mine or (profile or {}).get("include_own_brand"):
        return False
    theirs = item.get("brand") or ""
    return bool(theirs) and (mine in theirs or theirs in mine)


def pool_matches(store, need: dict, profile: dict | None, day: datetime.date, *, limit: int = 5) -> list[SearchHit]:
    """回 SearchHit（標題寫品牌；摘要是讀出來的欄位），讓今日報告的客人卡片直接用。"""
    if need.get("transaction") != "buy" or not need.get("preferred_areas"):
        return []
    since = (day - datetime.timedelta(days=MATCH_DAYS)).isoformat()
    pool = store.read_json(SYS, *POOL, default={}) or {}
    kind = need.get("property_type")
    items = {k: v for k, v in pool.items() if v.get("first_seen", "") >= since and not _own_brand(v, profile)
             and (kind or v.get("kind") not in NOT_HOME)}
    listings = [{"id": k, "transaction": "buy", "area": f"{v['county']}{v['district']}", "price": v.get("price"),
                 "property_type": v.get("kind"), "rooms": v.get("rooms"), "size_ping": v.get("ping"),
                 "url": v.get("url")} for k, v in items.items()]
    try:
        res = match_listings(need, listings)
    except ValueError:
        return []
    ok = [r for r in res["priority"]] + [r for r in res["review"] if set(r["missing"]) <= OPTIONAL]
    ok.sort(key=lambda r: (r["bucket"] != "priority", -r["score"], -(items[r["listing_id"]].get("num") or 0)))
    out = []
    for r in ok[:limit]:
        it = items[r["listing_id"]]
        note = "（價格未標）" if "price" in r["missing"] else ""
        out.append(SearchHit(f"{brand_of(it)}｜{it.get('title') or '物件'}", it["url"], MS.label(it) + note))
    return out
