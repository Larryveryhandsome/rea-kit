# -*- coding: utf-8 -*-
"""全市場新物件：各品牌／平台的物件頁怎麼認，怎麼從搜尋結果的標題摘要讀出品牌、地區、總價、型態（純規則、零 I/O）。

負責人 2026-10-03：「每天都要海巡，幫我們找買方、房源，想辦法統整整個市場的，你必須知道哪個品牌今天上架了甚麼房子」。
做法沿用 2026-10-02 定案（docs/法遵/自動海巡與新物件搜尋_檢視_20261002.md）：只用搜尋服務 API 回來的標題、摘要、網址，
不打開、不轉存原頁；仲介點連結回原站看。摘要裡的電話不存、不顯示。

每個來源＝查詢限定的網站＋認物件頁的網址樣式（抓出物件編號）＋品牌：
  - 有的品牌網站也刊登別家品牌的物件（2026-10-03 人工打開確認：信義網站編號結尾 HB＝住商、CT＝中信、GH＝大家，
    頁面寫「本物件非信義房屋受託銷售」）→ 依編號歸給真正的品牌，同一間在兩個網站只算一次。
  - 平台（591、好房網）與集團網站：標題摘要裡寫了品牌名才歸品牌，不然寫網站名。
清單外的品牌與網站（含加盟體系）由執行資料夾的設定檔加（REA_MARKET_SOURCES 指向的 JSON），不寫進 repo。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import patrol_keywords as PK
from core.tw_districts import COUNTIES, DISTRICTS


@dataclass(frozen=True)
class Source:
    key: str                          # 來源代號（記錄用）
    name: str                         # 網站名（找不到品牌時顯示）
    brand: str | None                 # 這個網站自己的品牌；平台填 None
    site: str                         # 查詢的 site: 範圍
    pattern: re.Pattern               # 物件頁網址；第一個抓到的群組是物件編號
    family: str = ""                  # 同一批物件會出現在好幾個網站（同集團）時共用，用來去重
    suffix_brands: tuple = ()         # ((編號結尾, 品牌, family), …)：網站刊登別家品牌的物件
    brand_from_text: bool = False     # 平台／集團網站：從標題摘要認品牌
    terms: str = ""                   # 查詢多帶的字


SOURCES: tuple[Source, ...] = (
    Source("sinyi", "信義房屋", "信義房屋", "sinyi.com.tw/buy/house",
           re.compile(r"^https://www\.sinyi\.com\.tw/buy/house/([A-Za-z0-9]+)(?:[/?#]|$)"),
           suffix_brands=(("HB", "住商不動產", "hb"), ("CT", "中信房屋", "ct"), ("GH", "大家房屋", "gh"))),
    Source("hb", "住商不動產", "住商不動產", "hbhousing.com.tw",
           re.compile(r"^https://(?:www|app)\.hbhousing\.com\.tw/detail/?\?sn=([A-Za-z0-9]+)"), family="hb",
           terms="出售"),
    Source("ct", "中信房屋", "中信房屋", "buy.cthouse.com.tw/house",
           re.compile(r"^https://buy\.cthouse\.com\.tw/house/(\d+)(?:-print)?\.html"), family="ct"),
    Source("tw", "台灣房屋", "台灣房屋", "twhg.com.tw/buy",
           re.compile(r"^https://www\.twhg\.com\.tw/buy/(TG\d+)(?:-print)?(?:[/?#]|$)")),
    Source("et", "東森房屋", "東森房屋", "etwarm.com.tw",
           re.compile(r"^https://(?:www|home|store)\.etwarm\.com\.tw/(?:[A-Za-z0-9]+/)?(?:index\.php/)?houses/buy/(\d+)"
                      r"|^https://www\.etwarm\.com\.tw/print\.php\?id=(\d+)"), terms="出售"),
    Source("pa", "太平洋房屋", "太平洋房屋", "estore.pacific.com.tw",
           re.compile(r"^https://estore\.pacific\.com\.tw/\S*HouseDetail\.aspx\?ID=([A-Za-z0-9]+)", re.I)),
    Source("hf", "好房網", None, "buy.housefun.com.tw/buy/house",
           re.compile(r"^https://buy\.housefun\.com\.tw/buy/house/(\d+)"), brand_from_text=True),
    Source("591", "591", None, "591.com.tw",
           re.compile(r"^https://(?:m\.591\.com\.tw/v2/sale/|sale\.591\.com\.tw/home/house/detail/\d/"
                      r"|(?:land|business)\.591\.com\.tw/sale/)(\d+)"), brand_from_text=True, terms="出售"),
)

# 品牌名（標題摘要裡出現就歸給它）。只放全名或不會跟地名、路名撞的寫法；清單外的由設定檔加。
BRANDS: dict[str, str] = {w: w for w in (
    "信義房屋", "住商不動產", "中信房屋", "台灣房屋", "東森房屋", "太平洋房屋", "大家房屋", "群義房屋",
    "全國不動產", "力霸房屋", "春耕不動產", "僑福房屋", "21世紀不動產")}
BRANDS["21世紀"] = "21世紀不動產"


@dataclass
class Catalog:
    sources: tuple[Source, ...] = SOURCES
    brands: dict[str, str] = field(default_factory=lambda: dict(BRANDS))
    prefix_brands: dict[str, str] = field(default_factory=dict)     # 物件編號開頭 → 品牌（集團網站用）


def load_catalog(path: str | Path | None) -> Catalog:
    """預設清單＋執行資料夾設定檔（沒有或壞掉就只用預設；壞掉的那一筆跳過）。
    {"brands": {"簡稱": "品牌全名"}, "prefix_brands": {"編號開頭": "品牌"},
     "sources": [{"key","name","brand","site","pattern","family","brand_from_text","terms"}]}"""
    cat = Catalog()
    if not path or not Path(path).is_file():
        return cat
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return cat
    if not isinstance(raw, dict):
        return cat
    cat.brands.update({str(k): str(v) for k, v in (raw.get("brands") or {}).items() if k and v})
    cat.prefix_brands.update({str(k): str(v) for k, v in (raw.get("prefix_brands") or {}).items() if k and v})
    extra = []
    for s in raw.get("sources") or []:
        try:
            pat = re.compile(str(s["pattern"]))
            if not str(s["pattern"]).startswith("^https://") or pat.groups < 1:
                continue
            extra.append(Source(str(s["key"]), str(s["name"]), s.get("brand") or None, str(s["site"]), pat,
                                family=str(s.get("family") or ""), brand_from_text=bool(s.get("brand_from_text")),
                                terms=str(s.get("terms") or "")))
        except (KeyError, TypeError, re.error):
            continue
    cat.sources = SOURCES + tuple(extra)
    return cat


# ── 讀標題摘要 ─────────────────────────────────────────────────────────────

PHONE = re.compile(r"(?<![\d,.])0\d{1,3}[-\s]?\d{3,4}[-\s]?\d{3,4}(?!\d)")
TITLE_NOISE = re.compile(r"^列印畫面\s*-\s*|^【[^】]{1,6}推薦】|-[^\s\-]{2,6}出售$|\s*\[[^\]]*(加盟店|直營店|房屋|不動產)[^\]]*\]|\((\d{6,}|[A-Z]{1,3}\d{5,})\)|…|\.\.\.$")
STORE_ADDR = re.compile(r"^[^\s.。,，;；|]{0,24}?\d+(?:之\d+|-\d+)?號")      # 店家地址帶門牌；物件地址多半只到路
ADDR_LABEL = re.compile(r"(地址|位於|位置|坐落)[\s︱:：.．]*$")
UNIT_PRICE = re.compile(r"(單價|每坪)[^\d]{0,6}[\d,.]+\s*萬(元)?(\s*/\s*坪)?|[\d,.]+\s*萬(元)?\s*/\s*坪|每月應付[^\d]{0,4}[\d,]+\s*元?"
                        r"|[\d,]+\s*/\s*月")
TOTAL = re.compile(r"(?:總價|售價|開價)[^\d$?]{0,4}\$?\s*([\d,]+(?:\.\d+)?)\s*萬")
DOLLAR = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*萬")
ANY_PRICE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*萬")
ROOMS = re.compile(r"(?<![\d.])(\d{1,2})\s*房(?!屋|地|產|貸|價|仲)")
PING_LABEL = re.compile(r"(?:建坪|建物坪數|總坪數|坪數|建物登記|權狀|面積|地坪)[^\d]{0,5}([\d,]+(?:\.\d+)?)\s*坪")
PING = re.compile(r"(?<!萬/)(?<!萬)([\d,]+(?:\.\d+)?)\s*坪")
DECLARED = re.compile(r"(?:房屋類型為|類型[\s︱:：.．]+|型態[\s︱:：]*)([^\s，,。；;|｜/]{2,8})")
NOT_KIND = re.compile(r"(主臥|雙|三|四|五|六|全室|大|衛浴)套房|套房式|(無|沒有|沒|不含)電梯|(鄰)?近\S{0,8}?(廠房|工業區|辦公大樓|商辦)"
                      r"|行政大樓|大樓旁")
# 型態：先看物件自己寫的「類型」，再看標題、摘要；順序＝比較具體的先（「電梯農舍」是農舍、「店面透天」是店面）
KINDS = (("農舍", ("農舍",)), ("店面", ("店面", "店住", "金店", "店鋪", "店舖")), ("廠房", ("廠房", "工廠", "廠辦")),
         ("辦公", ("辦公", "商辦")), ("透天", ("透天",)), ("別墅", ("別墅",)), ("華廈", ("華廈",)),
         ("公寓", ("公寓",)), ("大樓", ("大樓", "大廈", "電梯")), ("套房", ("套房",)), ("農地", ("農地", "農牧")),
         ("建地", ("建地",)), ("土地", ("土地",)), ("車位", ("車位",)))
LAND = {"農地", "建地", "土地"}


def clean_title(title: str) -> str:
    parts = [p for p in re.split(r"\s*[|｜]\s*|\s+-\s+|-\s+(?=[^\s]*(?:房屋|不動產))", str(title or "")) if p and p.strip()]
    t = parts[0] if parts else ""
    for extra in parts[1:]:                                    # 「農地|《宜蘭高鐵》稀有凱旋二段美田」：太短就接下一段
        if len(TITLE_NOISE.sub("", t)) >= 6 or re.search(r"房屋|不動產|買房", extra) \
                or _norm(extra).startswith(tuple(COUNTIES)):     # 「｜宜蘭縣宜蘭市住宅出售」是網站加的
            break
        t += " " + extra
    t = TITLE_NOISE.sub("", t)
    t = PHONE.sub("", t).strip(" -｜|,，")
    return t or str(title or "")[:30]


def _norm(text: str) -> str:
    return str(text or "").replace("臺", "台")


def _pairs(text: str) -> list[tuple[int, int, str, str]]:
    """文字裡所有「縣市＋鄉鎮市區」：[(開始, 結束, 縣市, 區)]。"""
    out = []
    for county in COUNTIES:
        for m in re.finditer(re.escape(county), text):
            rest = text[m.end():m.end() + 4]
            for d in sorted(DISTRICTS[county], key=len, reverse=True):
                if rest.startswith(d):
                    out.append((m.start(), m.end() + len(d), county, d))
                    break
    return sorted(out)


def find_area(title: str, snippet: str, hint_county: str | None = None) -> tuple[str, str] | None:
    """物件在哪（縣市, 區）。標題寫的優先；摘要裡帶門牌的多半是店家地址，跳過；「地址」「位於」後面的優先。
    都沒有縣市時，只在 hint_county（這次查的縣市）裡找區名（「礁溪460老農地」），同名的區不猜。"""
    t, s = _norm(title), _norm(snippet)
    tp = _pairs(t)
    if tp:
        return tp[0][2], tp[0][3]
    labeled, plain = [], []
    for start, end, county, d in _pairs(s):
        if STORE_ADDR.match(s[end:end + 30]):
            continue
        (labeled if ADDR_LABEL.search(s[max(0, start - 8):start]) else plain).append((county, d))
    if labeled or plain:
        return (labeled or plain)[0]
    if not hint_county:
        return None
    ambiguous = PK.ambiguous_terms()
    for text in (t, s):
        best = None
        for d in DISTRICTS[hint_county]:
            for term in {d, PK.district_term(hint_county, d)}:
                if (len(term) < 2 or (term in ambiguous and term != d) or term in PK._GENERIC
                        or term == PK.county_term(hint_county)):          # 「宜蘭」是縣，不是宜蘭市
                    continue
                m = re.search(re.escape(term) + ("" if term[-1] in "區鄉鎮市" else r"(?![路街道])"), text)
                if m and (best is None or m.start() < best[0]):
                    best = (m.start(), d)
        if best:
            return hint_county, best[1]
    return None


def find_price(text: str) -> float | None:
    """總價（萬）。寫了總價就用；「$1200 萬」；不然拿掉單價、月付後只剩一個金額才算。"""
    t = UNIT_PRICE.sub(" ", _norm(text))
    for rx in (TOTAL, DOLLAR):
        m = rx.search(t)
        if m:
            return float(m.group(1).replace(",", ""))
    prices = {float(p.replace(",", "")) for p in ANY_PRICE.findall(t)}
    prices = {p for p in prices if 10 <= p <= 1_000_000}
    return prices.pop() if len(prices) == 1 else None


def find_kind(title: str, snippet: str) -> str | None:
    """先看物件自己寫的類型；再看標題（取最後出現的型態字：標題多半以型態結尾，「農舍林立…足坪農地」是農地、
    「168電梯套房」是套房）；最後看摘要（摘要的「套房」多半是房間，不算）。"""
    declared = DECLARED.search(snippet or "")
    if declared:
        kind = _first_kind(declared.group(1), allow={"車位"})
        if kind:
            return kind
    title = NOT_KIND.sub(" ", title or "")
    best = None
    for kind, words in KINDS:
        if kind == "車位":
            continue                                           # 「3房車位」不是車位；只認物件自己寫的類型
        pos = max((title.rfind(w) for w in words), default=-1)
        if pos >= 0 and (best is None or pos > best[0]):
            best = (pos, kind)
    if best:
        return best[1]
    return _first_kind(NOT_KIND.sub(" ", snippet or ""), skip={"車位", "套房"})


def _first_kind(text: str, *, allow: set | None = None, skip: set | None = None) -> str | None:
    for kind, words in KINDS:
        if kind in (skip or ()) or (kind == "車位" and kind not in (allow or ())):
            continue
        if any(w in text for w in words):
            return kind
    return None


FIELDS = ("price", "kind", "rooms", "ping", "brand")


def merge(old: dict, new: dict) -> dict:
    """同一間在別的網址又出現（列印頁、別的網站）：缺的欄位補上；品牌從「網站名」改成認出來的品牌。"""
    out = dict(old)
    for f in FIELDS:
        if out.get(f) in (None, "") and new.get(f) not in (None, ""):
            out[f] = new[f]
    return out


def find_rooms(text: str) -> int | None:
    m = ROOMS.search(text or "")
    return int(m.group(1)) if m and 0 < int(m.group(1)) < 30 else None


def find_ping(text: str) -> float | None:
    t = UNIT_PRICE.sub(" ", text or "")
    m = PING_LABEL.search(t) or PING.search(t)
    try:
        return float(m.group(1).replace(",", "")) if m else None
    except ValueError:
        return None


def _brand_in(text: str, cat: Catalog) -> str | None:
    best = None
    for word, brand in cat.brands.items():
        i = text.find(word)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, brand)
    return best[1] if best else None


def parse(hit: Any, source: Source, cat: Catalog, *, hint_county: str | None = None) -> tuple[dict | None, str | None]:
    """一筆搜尋結果 → (物件, None) 或 (None, 不收的理由)。物件只留網址、整理過的標題與讀出來的欄位，不留摘要原文。"""
    url = str(getattr(hit, "url", "") or "")
    m = source.pattern.match(url)
    if not m:
        return None, "不是物件頁"
    raw_id = next(g for g in m.groups() if g)
    title, snippet = _norm(getattr(hit, "title", "")), _norm(getattr(hit, "snippet", ""))
    text = f"{title} {snippet}"
    brand, family, oid = source.brand, source.family or source.key, raw_id
    for suffix, b, fam in source.suffix_brands:
        if raw_id.upper().endswith(suffix) and len(raw_id) > len(suffix) + 3:
            brand, family, oid = b, fam, raw_id[:-len(suffix)]
            break
    if source.brand_from_text:
        found = None
        for prefix, b in cat.prefix_brands.items():
            if re.search(r"(?<![A-Za-z])" + re.escape(prefix) + r"\d{5,}", text):
                found = b
                break
        brand = found or _brand_in(PHONE.sub(" ", title), cat) or _brand_in(snippet, cat) or brand
    area = find_area(title, snippet, hint_county)
    if not area:
        return None, "看不出在哪"
    digits = re.sub(r"\D", "", oid)
    return {"key": f"{family}:{oid.upper()}", "brand": brand, "site": source.name, "source": source.key,
            "url": canonical_url(url, source, raw_id), "title": clean_title(getattr(hit, "title", "")),
            "county": area[0], "district": area[1],
            "price": find_price(text), "kind": find_kind(title, snippet), "rooms": find_rooms(text),
            "ping": find_ping(text), "num": int(digits) if digits else None}, None


def canonical_url(url: str, source: Source, raw_id: str) -> str:
    """列印頁、追蹤參數換成一般物件頁（仲介點了看到的是正常頁面）。"""
    if source.key == "et" and "print.php" in url:
        return f"https://www.etwarm.com.tw/houses/buy/{raw_id}"
    u = re.sub(r"-print(?=\.html$|$)", "", url)
    u = re.sub(r"/print$", "", u)
    return u.split("?")[0] if source.key == "sinyi" else u


def label(item: dict) -> str:
    """卡片上的一行：宜蘭市｜華廈｜3房｜888萬｜41坪。"""
    bits = [item.get("district") or item.get("county") or ""]
    if item.get("kind"):
        bits.append(item["kind"])
    if item.get("rooms"):
        bits.append(f"{item['rooms']}房")
    if item.get("price"):
        bits.append(f"{item['price']:g}萬")
    if item.get("ping"):
        bits.append(f"{item['ping']:g}坪")
    return "｜".join(b for b in bits if b)
