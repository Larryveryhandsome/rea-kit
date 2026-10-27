# -*- coding: utf-8 -*-
"""今日報告（全自動）：海巡想買／想租的人＋各平台可能的新物件 → 每天一則推給仲介本人。

  海巡：今天輪到的最多 3 組（地區×需求詞）→ 每組搜「site:threads.com 地區 (詞1 OR 詞2 …)」；
        買方組另外搜 PTT 房屋買賣板（網址就是發文時間）→ 只留貼文網址、鎖 3 天內、內容判斷（post_triage）
        → 卡片：誰、幾點發文、想找哪裡＋「開 Threads 回覆」／「開 PTT 看原文」
  加報：報告跑完後，13:00、19:00 再巡一次（只巡貼文、最近一天、1 頁）；有新的才推（搜尋引擎陸續收錄，不用等明天）
  新物件：每位有效買方 1 次搜尋「(site:各平台…) 區域 型態 出售／出租」最近一天（避開仲介自己品牌）
        → 只留平台網域、去掉列表頁、標題摘要裡的總價明顯超過預算的不要 → 每位客人一張卡、最多 5 個連結
  同一個網址 30 天內只給一次。什麼都沒找到就不推（省推播額度）。
只用搜尋服務 API 回來的標題、摘要、網址；不打開、不轉存原頁。結果只給仲介本人，不自動傳給客人。
"""
from __future__ import annotations

import datetime
import hashlib
import re
import urllib.parse
from typing import Any

from adapters.line import flex
from adapters.line.customer_intake import message
from adapters.web_search import BudgetedSearch, SearchError
from core import patrol_keywords as PK
from core import post_facts, post_triage
from core.search_links import PLATFORMS, _split, own_brand_hidden
from core.tw_districts import COUNTIES, DISTRICTS
from web.jobs import market_board
from web.jobs.match_cards import need_line

SEEN = ("jobs", "daily_brief_seen.json")
SYS_PARTITION = "sys-line-shared"
RUNS = ("jobs", "daily_brief_runs.json")
SEEN_DAYS = 30
MAX_POSTS = 10
MAX_CUSTOMERS = 10
MAX_CUSTOMERS_COMMAND = 5
LINKS_PER_CUSTOMER = 5
MAX_QUERY_AREAS = 4
POST_RE = re.compile(r"^https://(www\.)?threads\.(com|net)/@[\w.]+/post/[\w-]+", re.I)
PTT_POST_RE = re.compile(r"^https://(www\.)?ptt\.cc/bbs/[\w-]+/M\.\d{9,10}\.A\.[0-9A-F]{1,4}\.html$", re.I)
PTT_BOARDS = {"buy": "home-sale"}          # PTT 房屋買賣板；租屋板依縣市分散，先不搜
EXTRA_SLOTS = ("13:00", "19:00")           # 加報時段（報告之後）
EXTRA_GAP = datetime.timedelta(hours=2)    # 跟上一次巡的間隔至少 2 小時（服務晚開也不會連著巡）
EXTRA = ("jobs", "patrol_extra_runs.json")
PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*萬")
# 搜尋引擎收錄的多半是列表頁（2026-10-02 實測信義幾乎全是 /buy/list/…）；已知物件詳情頁路徑的平台，查詢直接限定在詳情頁
DETAIL_PATHS = {"sale.591.com.tw": "/home/house/detail", "rakuya.com.tw": "/sell_item", "sinyi.com.tw": "/buy/house"}
LIST_HINTS = ("/list", "search", "?keyword", "regionid=", "page=", "order=", "/market/", "/community", "/store")
# ↑ 搜尋／列表／社區行情／店頭頁，不是單一物件（2026-10-02 模擬：買透天的客人拿到一排「特許加盟店」頁）
TYPE_WORDS = {"透天": ("透天", "別墅"), "別墅": ("別墅", "透天"), "公寓": ("公寓",),
              "電梯大樓": ("大樓", "電梯", "華廈", "社區"), "華廈": ("華廈", "電梯", "大樓"), "套房": ("套房",),
              "店面": ("店面", "店鋪", "店舖", "金店"), "辦公": ("辦公", "商辦"), "廠房": ("廠房", "廠辦", "工廠"),
              "土地": ("土地", "建地"), "農地": ("農地", "農舍"), "車位": ("車位",)}
CONFLICT_WORDS = ("套房", "雅房", "農舍", "農地", "辦公", "廠房")     # 出現了就不是一般住家（客人要的不是這種就不給）
TITLE_KINDS = ("店面", "套房", "雅房", "農地", "農舍", "土地", "建地", "廠房", "工廠", "辦公", "車位")  # 標題直接寫的型態
# 平台摘要裡物件自己寫的型態（樂屋「房屋類型為電梯大廈」、住商「類型. 透天別墅」、591「型態：透天」）比猜關鍵字準
# 品牌、店名裡的地名不算地區（審查：「信義房屋」被當成信義區、「太平洋房屋」被當成台中太平）
BRAND_WORDS = ("信義房屋", "住商不動產", "中信房屋", "東森房屋", "台灣房屋", "21世紀", "太平洋房屋", "群義房屋",
               "大家房屋", "春耕不動產", "力爭房屋", "全國不動產", "僑福房屋")   # 只列名字裡帶地名、會被誤認的
# 不是型態的講法（審查：「主臥套房」「雙套房」當成套房；「無電梯」當成有電梯；「鄰近中科廠房」當成廠房）
NOT_TYPE = re.compile(r"(主臥|雙|三|四|全室|大|衛浴)套房|套房式|(無|沒有|沒|不含)電梯|(鄰)?近\S{0,8}?(廠房|工業區|辦公大樓|商辦)")
UNIT_WORDS = re.compile(r"(分租|獨立)套房|雅房")                     # 出現就是一個房間，不是整戶
NEED_CONFLICTS = {"電梯大樓": ("公寓", "透天"), "華廈": ("公寓", "透天"), "公寓": ("大樓", "大廈", "透天")}
UNIT_PRICE = re.compile(r"(單價|每坪)[^\d]{0,6}[\d,.]+\s*萬(元)?(\s*/\s*坪)?|[\d,.]+\s*萬(元)?\s*/\s*坪|每月應付[^\d]{0,4}[\d,]+\s*元?")
TOTAL_PRICE = re.compile(r"(?:總價|售價|開價)[^\d]{0,4}([\d,]+(?:\.\d+)?)\s*萬")
DECLARED_TYPE = re.compile(r"(?:房屋類型為|類型[.．:：]\s*|型態[:：]\s*)([^\s，,。；;|｜]{2,8})")
STORE_TITLE = re.compile(r"(加盟店|直營店|分店|門市)\s*$")
RENT_PRICE = re.compile(r"(?:租金|月租)[^\d]{0,6}(\d{1,3}(?:,\d{3})+|\d{4,6})")


def _h(url: str) -> str:
    return hashlib.sha256(url.split("#")[0].encode()).hexdigest()[:24]


# 搜尋就先排掉刊登文常見的字（2026-10-08 複查：搜「宜蘭 買房」回來的幾乎都是房仲刊登，真的買方被擠出前兩頁）
NOT_LISTING = "-開價 -售價 -總價 -經紀人 -加盟店 -專任 -賞屋 -詳情私訊"


def patrol_query(group: PK.PatrolGroup) -> str:
    words = [q.split(" ", 1)[1] for q in group.queries(limit=10)]          # 一次查詢用 OR 把詞全部帶上
    return f'site:threads.com {group.area_term} ({" OR ".join(words)}) {NOT_LISTING}'


def ptt_query(group: PK.PatrolGroup) -> str | None:
    board = PTT_BOARDS.get(group.intent)
    if not board:
        return None
    words = [q.split(" ", 1)[1] for q in group.queries(limit=10)] + ["請益"]   # PTT 買方多半發 [請益]
    return f'site:ptt.cc/bbs/{board} {group.area_term} ({" OR ".join(words)})'


def patrol_sources(group: PK.PatrolGroup, quick: bool = False) -> list[tuple[str, re.Pattern, str, int]]:
    """[(查詢, 收哪種網址, 時間範圍, 頁數)]。平常查一週兩頁再用 3 天鎖；加報只查最近一天一頁。"""
    out = [(patrol_query(group), POST_RE, "d" if quick else "w", 1 if quick or group.intent == "sell" else 2)]
    q = ptt_query(group)
    if q:
        out.append((q, PTT_POST_RE, "d" if quick else "w", 1))
    return out


def listing_query(need: dict, profile: dict | None, day: datetime.date | None = None) -> str | None:
    buy = need.get("transaction") == "buy"
    areas = [_split(a) for a in need.get("preferred_areas") or []]
    terms = list(dict.fromkeys(_query_term(c, d) for c, d in areas if c))
    if len(terms) > MAX_QUERY_AREAS and day:                # 地區多：每天輪一批，幾天內全部輪到
        start = (day.toordinal() * MAX_QUERY_AREAS) % len(terms)
        terms = terms[start:] + terms[:start]
    terms = terms[:MAX_QUERY_AREAS]
    if not terms:
        return None
    sites = []
    for p in PLATFORMS:
        if own_brand_hidden(p, profile):
            continue
        host = ("sale." if buy else "rent.") + p.domain if p.name == "591" else p.domain
        sites.append("site:" + host + (DETAIL_PATHS.get(host, "") if buy else ""))
    area = terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"
    kind = f" {need['property_type']}" if need.get("property_type") else ""
    return f'({" OR ".join(sites)}) {area}{kind} {"出售" if buy else "出租"}'


def _query_term(county: str, district: str | None) -> str:
    if not district:
        return PK.county_term(county)
    term = PK.district_term(county, district)
    return district if term == PK.county_term(county) else term      # 宜蘭市→「宜蘭市」，不是整個宜蘭


def _area_rules(need: dict) -> list[tuple[str, str, bool]]:
    """[(地區詞, 縣市, 要不要同時看到縣市)]。跨縣市同名（大安、信義、中山）或通名（東區）一定要看到縣市。"""
    ambiguous = PK.ambiguous_terms()
    rules: list[tuple[str, str, bool]] = []
    for c, d in (_split(a) for a in need.get("preferred_areas") or []):
        if not c:
            continue
        pairs = [(d, _query_term(c, d))] if d else [(x, PK.district_term(c, x)) for x in DISTRICTS[c]]
        if not d:
            rules += [(PK.county_term(c), c, False), (c, c, False)]
        for full, short in pairs:
            shared = short in ambiguous or full in PK._GENERIC
            rules += [(full, c, shared), (short, c, shared)]
    return [r for r in dict.fromkeys(rules) if len(r[0]) >= 2]


def _area_hit(text: str, need: dict) -> bool:
    for brand in BRAND_WORDS:
        text = text.replace(brand, " ")
    for term, county, needs_county in _area_rules(need):
        pattern = re.escape(term) + ("" if term[-1] in "區鄉鎮市縣" else r"(?![路街道])")
        if re.search(pattern, text) and (not needs_county or county in text or PK.county_term(county) in text):
            return True
    return False


def _area_terms(need: dict) -> set[str]:
    """這位客人要的地方，在標題摘要裡可能怎麼寫。"""
    out: set[str] = set()
    for c, d in (_split(a) for a in need.get("preferred_areas") or []):
        if not c:
            continue
        if d:
            out |= {d, _query_term(c, d)}
        else:
            out |= {PK.county_term(c), c} | {PK.district_term(c, x) for x in DISTRICTS[c]}
    return {t for t in out if len(t) >= 2}


def listing_problem(hit, need: dict, profile: dict | None) -> str | None:
    """不給的理由；可以給就回 None。寧可少給，不要給錯（店頭頁、別的縣市、套房給要公寓的人）。"""
    buy = need.get("transaction") == "buy"
    if not _is_listing_url(hit.url, profile, buy):
        return "不是單一物件頁"
    text = f"{hit.title} {hit.snippet}"
    if STORE_TITLE.search(hit.title.split("|")[0].split(" - ")[0].strip()):
        return "店頭頁"
    path = urllib.parse.urlsplit(hit.url).path.lower()
    if (buy and "/rent" in path) or (not buy and any(x in path for x in ("/buy", "/sale", "/sell"))):
        return "買賣／出租不符"
    host = (urllib.parse.urlsplit(hit.url).hostname or "").lower()
    if host == "rent.591.com.tw" and not re.fullmatch(r"/\d+", urllib.parse.urlsplit(hit.url).path):
        return "不是單一物件頁"
    counties = {c for c, _ in (_split(a) for a in need.get("preferred_areas") or []) if c}
    named = {c for c in COUNTIES if c in text.replace("臺", "台")}
    if named and not named & counties:
        return "講的是別的縣市"                                       # 新北市永和區「中山路」不是台北中山區
    # 標題寫了同縣市的別區（摘要裡常混著店家地址或別的物件）→ 以標題為準
    title = re.split(r"[|｜]| - ", hit.title)[0].replace("臺", "台")
    full_title = hit.title.replace("臺", "台")
    wanted = {(c, d) for c, d in (_split(a) for a in need.get("preferred_areas") or []) if c}
    for c in {c for c, d in wanted if d} - {c for c, d in wanted if not d}:     # 只指定到區的縣市才比
        said = {d for d in DISTRICTS[c] if c + d in full_title or PK.county_term(c) + d in full_title}
        if said and not said & {d for cc, d in wanted if cc == c}:
            return "講的是同縣市的別區"
    # 沒有「區鄉鎮市」字尾的短名後面接路街道是路名；同名區要看到縣市；品牌店名不算
    if _area_rules(need) and not _area_hit(text.replace("臺", "台"), need):
        return "沒提到客人要的地區"
    kind = need.get("property_type")
    if kind:
        ok_words = TYPE_WORDS.get(kind, (kind,))
        title, clean = NOT_TYPE.sub(" ", title), NOT_TYPE.sub(" ", text)
        if any(w in title for w in TITLE_KINDS) and not any(w in title for w in ok_words):
            return "型態不符（標題寫的是別的型態）"                  # 標題明寫店面／建地…，摘要裡別的物件不算
        if kind != "套房" and UNIT_WORDS.search(title):
            return "型態不符（是分租套房／雅房）"
        if any(w in title for w in NEED_CONFLICTS.get(kind, ())) and not any(w in title for w in ok_words):
            return "型態不符（標題寫的是別的型態）"
        declared = DECLARED_TYPE.search(hit.snippet or "")
        declared_ok = bool(declared) and any(w in declared.group(1) for w in ok_words)
        if declared and kind != "套房" and not declared_ok:          # 套房看的是房型，不是整棟是什麼建物
            return f"型態不符（物件寫的是{declared.group(1)}）"
        if not declared_ok:
            if not any(w in clean for w in ok_words):
                return "看不出是客人要的型態"
            if kind != "套房" and (UNIT_WORDS.search(clean) or ("農舍" in clean and kind not in ("農地", "土地"))):
                return "型態不符（套房／雅房／農舍）"
    if _over_budget(text, need):
        return "超過預算"
    if not buy and need.get("budget_max"):
        cap = float(need["budget_max"]) * (1 + float(need.get("budget_tolerance_pct") or 0) / 100)
        rents = [int(x.replace(",", "")) for x in RENT_PRICE.findall(text)]
        if rents and min(rents) > cap:
            return "超過預算"
    return None


def _is_listing_url(url: str, profile: dict | None, buy: bool) -> bool:
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    allowed = [("sale." if buy else "rent.") + p.domain if p.name == "591" else p.domain
               for p in PLATFORMS if not own_brand_hidden(p, profile)]
    if u.scheme != "https" or not any(host == d or host.endswith("." + d) for d in allowed):
        return False
    path = (u.path + ("?" + u.query if u.query else "")).lower()
    return u.path not in ("", "/") and not host.startswith("store.") and not any(h in path for h in LIST_HINTS)


def _total_prices(text: str) -> list[float]:
    """總價（萬）。先拿掉單價、月付；寫了「總價」就用它；沒寫又有好幾個不同金額 → 不確定，不拿來擋。"""
    t = UNIT_PRICE.sub(" ", text)
    total = [float(x.replace(",", "")) for x in TOTAL_PRICE.findall(t)]
    if total:
        return total
    prices = {float(p.replace(",", "")) for p in PRICE_RE.findall(t)}
    prices = {p for p in prices if 10 <= p <= 1_000_000}
    return list(prices) if len(prices) == 1 else []


def _over_budget(text: str, need: dict) -> bool:
    if need.get("transaction") != "buy" or not need.get("budget_max"):
        return False
    prices = _total_prices(text)          # 審查：以前拿最小的「N萬」，單價 52.1萬/坪 讓 3280 萬的物件過關
    cap = float(need["budget_max"]) * (1 + float(need.get("budget_tolerance_pct") or 0) / 100)
    return bool(prices) and min(prices) > cap


NOT_SELLER = re.compile(r"(房仲|仲介)\s*(勿擾|免|不要|勿)|不要(房仲|仲介)|請(房仲|仲介)")


def _seller_like(text: str) -> bool:
    """像賣方或同業廣告：強訊號一個就算（物件編號、我的客戶在找…）；弱訊號要兩個以上。
    「房仲勿擾」「請房仲帶看」這類是買方常用語，先拿掉再數。"""
    cleaned = NOT_SELLER.sub("", text)
    if any(w in cleaned for w in PK.STRONG_SELLER):
        return True
    return sum(1 for w in PK.SELLER_SIGNALS if w in cleaned) >= 2


def _do_not_contact(text: str) -> bool:
    """作者明說不要房仲聯絡 → 不列進今日報告（尊重勿擾）。"""
    return any(w in text for w in PK.DO_NOT_CONTACT)


def collect(*, tenant_id: str, search: BudgetedSearch, prospect: dict | None, customers: list[dict],
            profile: dict | None, seen: dict, day: datetime.date, max_customers: int = MAX_CUSTOMERS,
            now: datetime.datetime | None = None, archive: list | None = None, quick: bool = False,
            market=None) -> dict[str, Any]:
    """回 {posts:[(組別, hit, 判斷)], listings:[(客人, 需求摘要, [hit…])], dropped:{理由: 數}, errors, queries}。
    不寫檔、不推播；seen 會加上這次要給的網址（呼叫端送到之後才存）；archive 會收到每一篇候選貼文與判斷（存資料庫用）。
    market(need) → 全市場盤點的物件池裡配得上的（先給，不夠才另外搜尋，省搜尋次數）。"""
    out: dict[str, Any] = {"posts": [], "listings": [], "dropped": {}, "dropped_listings": {}, "errors": [], "queries": 0}
    fresh = lambda url: _h(url) not in seen
    now = now or datetime.datetime.combine(day, datetime.time(12), post_facts.TW)

    def run(query, recency="d", pages=1):
        hits = []
        for page in range(1, pages + 1):
            out["queries"] += 1
            got = search.search(tenant_id, query, recency=recency, page=page) if page > 1 else \
                search.search(tenant_id, query, recency=recency)
            hits += got
            if len(got) < 10:                     # 沒有下一頁了
                break
        return hits

    try:
        if prospect and prospect.get("areas") and prospect.get("kind"):
            groups = PK.build_groups(prospect["areas"], ["buy" if prospect.get("transaction") == "買" else "rent"],
                                     [prospect["kind"]], prospect.get("keywords"))
            # 負責人 2026-10-08「海巡只需要真實的買賣方」：同一批地區另外找屋主自己想賣的（開發機會），用賣方的詞
            sellers = PK.build_groups(prospect["areas"], ["sell"], [prospect["kind"]])
            todays = [(g, src) for g in PK.todays_groups(groups, day) + PK.todays_groups(sellers, day)
                      for src in patrol_sources(g, quick)]
            for g, (query, accept, recency, pages) in todays:
                # 搜一週（搜尋引擎收錄會晚），再用貼文網址解出的發文時間鎖 3 天內（負責人：等於在 Threads 點「最近」）
                for hit in run(query, recency=recency, pages=pages):
                    if not accept.match(hit.url):
                        continue
                    when = post_facts.posted_at(hit.url)
                    verdict = post_triage.judge(f"{hit.title} {hit.snippet}", county=g.county, area_term=g.area_term,
                                                intent=g.intent, posted_at=when, now=now,
                                                handle=post_facts.handle_of(hit.url), own=hit.title)
                    if archive is not None:
                        archive.append({"url": hit.url, "handle": post_facts.handle_of(hit.url),
                                        "posted_at": when.isoformat(timespec="minutes") if when else None,
                                        "source": post_facts.source_of(hit.url), "county": g.county,
                                        "area": g.area_term, "intent": g.intent, "kind": g.kind,
                                        "keep": verdict.keep, "reason": verdict.reason,
                                        "title": hit.title[:200], "snippet": hit.snippet[:300]})
                    if not verdict.keep:
                        out["dropped"][verdict.reason] = out["dropped"].get(verdict.reason, 0) + 1
                        continue
                    if fresh(hit.url) and len(out["posts"]) < MAX_POSTS:   # 滿了的留到下次，不標成看過
                        out["posts"].append((g, hit, verdict))
                        seen[_h(hit.url)] = day.isoformat()
        out["customers_total"] = len(customers)
        if len(customers) > max_customers:                  # 客人多：每天換一批，不會永遠輪不到
            start = (day.toordinal() * max_customers) % len(customers)
            customers = customers[start:] + customers[:start]
        todays = customers[:max_customers]
        out["customers_searched"] = len(todays)
        for cust in todays:
            need = cust.get("need_card") or {}
            keep = []
            for hit in (market(need) if market else []):
                if fresh(hit.url) and len(keep) < LINKS_PER_CUSTOMER:
                    keep.append(hit)
                    seen[_h(hit.url)] = day.isoformat()
            out["pool_links"] = out.get("pool_links", 0) + len(keep)
            q = listing_query(need, profile, day) if len(keep) < LINKS_PER_CUSTOMER else None
            for hit in (run(q) if q else []):
                why = listing_problem(hit, need, profile)
                if why:
                    out["dropped_listings"][why] = out["dropped_listings"].get(why, 0) + 1
                elif fresh(hit.url):
                    keep.append(hit)
                    seen[_h(hit.url)] = day.isoformat()
                if len(keep) >= LINKS_PER_CUSTOMER:
                    break
            if keep:
                out["listings"].append((cust.get("label") or cust["customer_id"], need_line(need), keep))
    except SearchError as e:
        out["errors"].append(str(e))
    return out


def messages_for(result: dict, day: datetime.date, *, patrol_only: bool = False,
                 now: datetime.datetime | None = None, slot: str | None = None) -> list[dict]:
    posts, listings = result["posts"], result["listings"]
    market = result.get("market") or {}
    market_msgs = market_board.messages(market) if market and not slot and not patrol_only else []
    if not posts and not listings and not market_msgs:
        return []
    n_links = sum(len(x[2]) for x in listings)
    if slot:
        head = (f"🔔 海巡加報（{day.month}/{day.day} {slot}）：又找到 {len(posts)} 則新的想買／想租貼文\n"
                "今天報告之後搜尋引擎才收到的；按下面的按鈕直接打開那篇。")
    elif patrol_only:
        head = (f"🔍 今日海巡（{day.month}/{day.day}）：找到 {len(posts)} 則可能想買／想租的貼文\n"
                "每一則都是那篇文章本身，按下面的按鈕直接打開那篇回他。")
    else:
        line = market_board.head_line(market) if market else None
        head = (f"☀ 今日報告（{day.month}/{day.day}，自動）\n"
                f"海巡：找到 {len(posts)} 則可能想買／想租的貼文（按按鈕直接打開那篇）\n"
                + (line + "\n" if line else "")
                + (f"幫買方配對：{len(listings)} 位客人共 {n_links} 筆（點了直接看那間物件）\n"
                   if result.get("customers_total")
                   else "還沒有買方：按「新增買方」建好需求，每天自動從全市場的新物件幫他配對。\n")
                + (f"（客人多，今天找了 {result['customers_searched']}/{result['customers_total']} 位，其他的接下來幾天輪到）\n"
                   if result.get("customers_total", 0) > result.get("customers_searched", 0) else "") +
                "都是搜尋引擎最近一天找到的。")
    out = [message(head, ("今日報告", "今日海巡", "客戶清單"))]
    if posts:
        # 負責人：要直接告訴仲介「這是誰、幾點幾分發文、要找哪裡」；最新的排最前面
        ordered = sorted(posts, key=lambda p: post_facts.posted_at(p[1].url) or datetime.datetime.min.replace(
            tzinfo=post_facts.TW), reverse=True)
        bubbles = [flex.links_message(
            f"海巡：{g.label}",
            post_facts.describe(hit.url, hit.title, hit.snippet, now=now or datetime.datetime.now(post_facts.TW),
                                rent=g.intent == "rent", prefer_county=g.county, selling="屋主" in verdict.reason)
            + [("🏠 " if "屋主" in verdict.reason else "✅ ") + verdict.reason, hit.snippet[:120] or hit.title[:80]],
            [_open_label(hit.url)])["contents"] for g, hit, verdict in ordered]
        out.append(flex.flex_message(f"今日海巡：{len(posts)} 則貼文", flex.carousel(bubbles)))
    out += market_msgs
    if listings:
        bubbles = [flex.links_message(f"可能的新物件：{who}", [line],
                                      [(hit.title[:20] or "看物件", hit.url) for hit in hits])["contents"]
                   for who, line, hits in listings]
        out.append(flex.flex_message(f"可能的新物件：{n_links} 筆", flex.carousel(bubbles)))
    return out


def _open_label(url: str) -> tuple[str, str]:
    # PTT 多數板不准仲介推文招攬：按鈕只寫「看原文」，聯絡方式讓仲介看板規自己決定
    return ("開 PTT 看原文" if post_facts.source_of(url) == "ptt" else "開 Threads 回覆"), url


def run_for_tenant(*, tenant_id: str, store, search: BudgetedSearch, customers_src, now,
                   max_customers: int = MAX_CUSTOMERS, patrol_only: bool = False, slot: str | None = None,
                   scan_market: bool = True):
    """跑一次（排程或「今日報告」指令共用）。回 (要送的訊息, 結果, commit)。
    commit() 要在**真的送到**之後才呼叫，才把這次給的網址記成看過；沒送到就不記，明天還會再出現。
    scan_market：今天還沒盤點的地區要不要現在盤點（指令是同步跑，怕卡太久就不盤點，只用排程已經盤點好的）。"""
    day = now().date()
    with store.lock(tenant_id, "daily-brief"):
        old = store.read_json(tenant_id, *SEEN, default={}) or {}
    cutoff = (day - datetime.timedelta(days=SEEN_DAYS)).isoformat()
    seen = {k: v for k, v in old.items() if v >= cutoff}
    before = set(seen)
    prospect = (store.read_json(tenant_id, "line", "prospect_setup.json", default={}) or {}).get("profile")
    profile = (store.read_json(tenant_id, "line", "agent_profile.json", default={}) or {}).get("profile")
    current = now()
    current = current.astimezone(post_facts.TW) if current.tzinfo else current.replace(tzinfo=post_facts.TW)
    archive: list[dict] = []
    customers = [] if patrol_only else customers_src.list_customers(tenant_id)
    market = None
    if not patrol_only and not slot:
        areas = market_board.tenant_areas(prospect, customers)
        if scan_market:
            market_board.ensure(search, store, areas, day=day)
        market = market_board.board(store, areas, day)
    result = collect(tenant_id=tenant_id, search=search, prospect=prospect, customers=customers, profile=profile,
                     seen=seen, day=day, max_customers=max_customers, now=current, archive=archive,
                     quick=bool(slot),
                     market=(lambda need: market_board.pool_matches(store, need, profile, day)) if market else None)
    if market:
        result["market"] = market
        result["market_items"] = len(market["items"])
    save_archive(store, archive, current)
    added = {k: v for k, v in seen.items() if k not in before}

    def commit():
        with store.lock(tenant_id, "daily-brief"):
            cur = store.read_json(tenant_id, *SEEN, default={}) or {}
            cur = {k: v for k, v in cur.items() if v >= cutoff}
            cur.update(added)
            store.write_json(tenant_id, *SEEN, data=cur)
    return messages_for(result, day, patrol_only=patrol_only, now=current, slot=slot), result, commit


ARCHIVE = ("patrol", "posts.jsonl")          # 系統分區：每一篇看過的候選貼文＋判斷（負責人：存在我們電腦裡，越多越好調）
ARCHIVE_INDEX = ("patrol", "index.json")


def save_archive(store, records: list[dict], now: datetime.datetime) -> int:
    """同一篇只記一次（第一次看到的時間＝時間戳記）。回新增幾篇。"""
    if not records:
        return 0
    added = 0
    with store.lock(SYS_PARTITION, "patrol-archive"):
        index = store.read_json(SYS_PARTITION, *ARCHIVE_INDEX, default={}) or {}
        for rec in records:
            key = _h(rec["url"])
            if key in index:
                continue
            index[key] = now.isoformat(timespec="minutes")
            store.append_jsonl(SYS_PARTITION, *ARCHIVE, record={"first_seen": index[key], **rec})
            added += 1
        if added:
            store.write_json(SYS_PARTITION, *ARCHIVE_INDEX, data=index)
    return added


def due(store, tenant_id: str, now: datetime.datetime) -> bool:
    """今天還沒跑、而且已過仲介設定的時間（沒設定就 09:00）。"""
    prospect = (store.read_json(tenant_id, "line", "prospect_setup.json", default={}) or {}).get("profile") or {}
    hh, mm = (int(x) for x in str(prospect.get("time") or "09:00").split(":"))
    runs = store.read_json(tenant_id, *RUNS, default={}) or {}
    return runs.get("last_day") != now.date().isoformat() and (now.hour, now.minute) >= (hh, mm)


def mark_run(store, tenant_id: str, now: datetime.datetime, result: dict, state: str) -> None:
    store.write_json(tenant_id, *RUNS, data={"last_day": now.date().isoformat(), "at": now.isoformat(timespec="seconds"),
                                            "posts": len(result.get("posts", [])),
                                            "listings": sum(len(x[2]) for x in result.get("listings", [])),
                                            "queries": result.get("queries", 0), "errors": result.get("errors", []),
                                            "push": state})


def _minutes(hhmm: str) -> int:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return hh * 60 + mm


def _parse(ts: str | None) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def due_extra(store, tenant_id: str, now: datetime.datetime) -> str | None:
    """今天的報告已經跑過、過了某個加報時段、還沒巡過那個時段、跟上一次巡隔了 2 小時以上 → 回那個時段。"""
    today = now.date().isoformat()
    runs = store.read_json(tenant_id, *RUNS, default={}) or {}
    if runs.get("last_day") != today:
        return None
    extra = store.read_json(tenant_id, *EXTRA, default={}) or {}
    done = extra.get("slots", []) if extra.get("day") == today else []
    passed = [s for s in EXTRA_SLOTS if now.hour * 60 + now.minute >= _minutes(s) and s not in done]
    if not passed:
        return None
    last = [t for t in (_parse(runs.get("at")), _parse(extra.get("at") if extra.get("day") == today else None)) if t]
    naive = now.replace(tzinfo=None)
    if any(naive - t.replace(tzinfo=None) < EXTRA_GAP for t in last):
        return None
    return passed[-1]


def mark_extra(store, tenant_id: str, now: datetime.datetime, slot: str, result: dict, state: str) -> None:
    """記下這個時段（含之前錯過的時段：補跑一次就好，不連著巡）。"""
    today = now.date().isoformat()
    extra = store.read_json(tenant_id, *EXTRA, default={}) or {}
    done = set(extra.get("slots", []) if extra.get("day") == today else [])
    done |= {s for s in EXTRA_SLOTS if _minutes(s) <= _minutes(slot)}
    store.write_json(tenant_id, *EXTRA, data={"day": today, "slots": sorted(done),
                                              "at": now.isoformat(timespec="seconds"),
                                              "posts": len(result.get("posts", [])),
                                              "queries": result.get("queries", 0),
                                              "errors": result.get("errors", []), "push": state})
