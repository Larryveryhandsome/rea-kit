"""從搜尋結果裡的公開貼文（網址、標題、摘要）整理出：誰發的、幾點發的、要找哪裡／什麼／預算。純計算、不連網。

發文時間：Threads 貼文網址的代碼與 Instagram 同一套媒體編號（64 進位），前段是毫秒時間戳
（自 2011-08-24 起算）。2026-10-02 實測：限定「最近一週」的搜尋結果解出來全落在那一週內。
PTT 文章網址本身就是發文時間（M.<秒數>.A.xxx.html）。
只用來顯示給仲介本人；不存帳號或內容（去重只存網址雜湊）。
"""
from __future__ import annotations

import datetime
import re

from core.tw_districts import COUNTIES, DISTRICTS

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_EPOCH_MS = 1314220021721
TW = datetime.timezone(datetime.timedelta(hours=8))
HANDLE_RE = re.compile(r"threads\.(?:com|net)/@([\w.]+)/post/([\w-]+)", re.I)
PTT_RE = re.compile(r"ptt\.cc/bbs/([\w-]+)/M\.(\d{9,10})\.A\.[0-9A-F]{1,4}\.html", re.I)
PTT_TITLE_TAIL = re.compile(r"\s*-\s*(看板\s*\S+|批踢踢實業坊|PTT\S*)(\s*-\s*\S+)*\s*$")
NAME_RE = re.compile(r"^(.{1,40}?)\s*\(@[\w.]+\)")
BUDGET_RE = re.compile(r"(?:預算|總價|以內|以下|上限)[^\d]{0,4}(\d{2,5}(?:\.\d)?)\s*(萬|w|W)|(\d{2,5})\s*萬\s*(?:以內|以下|內|左右|上下)")
RENT_RE = re.compile(r"(?:月租|租金|預算)[^\d]{0,4}(\d{1,2}(?:,\d{3})|\d{4,6})\s*(?:元|/月|一個月)?")
TYPES = ("透天", "別墅", "公寓", "華廈", "電梯大樓", "大樓", "套房", "雅房", "整層", "店面", "辦公室", "廠房", "倉庫",
         "農地", "建地", "土地", "農舍", "預售", "新成屋", "車位")


def handle_of(url: str) -> str | None:
    m = HANDLE_RE.search(url or "")
    return m.group(1) if m else None


def source_of(url: str) -> str | None:
    if HANDLE_RE.search(url or ""):
        return "threads"
    if PTT_RE.search(url or ""):
        return "ptt"
    return None


def board_of(url: str) -> str | None:
    m = PTT_RE.search(url or "")
    return m.group(1) if m else None


def posted_at(url: str) -> datetime.datetime | None:
    m = HANDLE_RE.search(url or "")
    if not m:
        p = PTT_RE.search(url or "")
        if not p or not 1_300_000_000 < int(p.group(2)) < 4_000_000_000:
            return None
        return datetime.datetime.fromtimestamp(int(p.group(2)), tz=TW)
    n = 0
    try:
        for c in m.group(2):
            n = n * 64 + _ALPHABET.index(c)
    except ValueError:
        return None
    ms = (n >> 23) + _EPOCH_MS
    if not 1_300_000_000_000 < ms < 4_000_000_000_000:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, tz=TW)


def ago(when: datetime.datetime, now: datetime.datetime) -> str:
    sec = (now - when).total_seconds()
    if sec < 0:
        return ""
    if sec < 3600:
        return f"約 {max(1, int(sec // 60))} 分鐘前"
    if sec < 86400:
        return f"約 {int(sec // 3600)} 小時前"
    return f"約 {int(sec // 86400)} 天前"


def _terms():
    from core.patrol_keywords import county_term, district_term      # 避免循環匯入
    out = []
    for county in COUNTIES:
        out.append((county_term(county), county, None))
        out += [(district_term(county, d), county, d) for d in DISTRICTS[county]]
    return sorted({t for t in out if len(t[0]) >= 2}, key=lambda t: -len(t[0]))


_TERMS = None


def places(text: str, prefer_county: str | None = None, limit: int = 3) -> list[str]:
    """貼文裡提到的地方（行政區優先、同縣市優先），最多 limit 個。"""
    global _TERMS
    _TERMS = _TERMS or _terms()
    found, seen_names = [], set()
    for term, county, district in _TERMS:
        if term in text and term not in seen_names and not any(term in s for s in seen_names):
            seen_names.add(term)
            found.append((0 if county == prefer_county else 1, 0 if district else 1, text.index(term), term, county,
                          district))
    # 有提到某縣市底下的鄉鎮（礁溪、羅東）就不必再列縣市本身（宜蘭）
    with_district = {f[4] for f in found if f[5] and f[3] != f[4][:2]}
    found = [f for f in found if f[5] or f[4] not in with_district]
    found = [f for f in found if not (f[5] and f[3] == f[4][:2] and f[4] in with_district)]
    return [t[3] for t in sorted(found)[:limit]]


def wants(text: str, *, rent: bool = False, prefer_county: str | None = None) -> str:
    """「礁溪、羅東｜透天｜預算約 1500萬」；抓不到的部分就省略。"""
    parts = []
    where = places(text, prefer_county)
    if where:
        parts.append("、".join(where))
    kinds = [k for k in TYPES if k in text]
    kinds = [k for k in kinds if not any(k != o and k in o for o in kinds)][:2]
    if kinds:
        parts.append("、".join(kinds))
    if rent:
        m = RENT_RE.search(text)
        if m:
            parts.append(f"月租約 {m.group(1)} 元")
    else:
        m = BUDGET_RE.search(text)
        if m:
            parts.append(f"預算約 {m.group(1) or m.group(3)}萬")
    return "｜".join(parts)


def describe(url: str, title: str, snippet: str, *, now: datetime.datetime, rent: bool = False,
             prefer_county: str | None = None, selling: bool = False) -> list[str]:
    """卡片上的幾行：👤 誰（PTT 是哪個板＋標題）、🕒 幾點、📍 想找什麼。"""
    lines = []
    handle = handle_of(url)
    if handle:
        name = NAME_RE.match(title or "")
        lines.append(f"👤 @{handle}" + (f"（{name.group(1).strip()}）" if name else ""))
    elif board_of(url):
        head = PTT_TITLE_TAIL.sub("", title or "").strip()
        lines.append(f"👤 PTT {board_of(url)} 板" + (f"：{head[:40]}" if head else ""))
    when = posted_at(url)
    if when:
        lines.append(f"🕒 {when.month}/{when.day} {when:%H:%M} 發文" + (f"（{ago(when, now)}）" if ago(when, now) else ""))
    want = wants(f"{title} {snippet}", rent=rent, prefer_county=prefer_county)
    if want:
        lines.append(("📍 要賣：" if selling else "📍 想找：") + want)
    return lines


def code_for(when: datetime.datetime, seq: int = 0) -> str:
    """反過來：給一個時間做出網址代碼（測試用的合成貼文網址）。"""
    n = ((int(when.timestamp() * 1000) - _EPOCH_MS) << 23) + seq
    out = ""
    while n:
        n, r = divmod(n, 64)
        out = _ALPHABET[r] + out
    return out or "A"
