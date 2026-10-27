"""每位買方的「找房連結」：點了直接開平台自己的搜尋頁（最新上架在前）。只產生網址，不連網、不採集。

負責人 2026-10-01：已經有買方的，照一般上網找房的邏輯直接搜；先確認仲介的品牌，預設避開他自己品牌
（自家物件他本來就熟），他要也可以列。

網址格式來源：
  - 591 售屋：2026-10-01 由瀏覽器實際操作篩選後讀網址列（縣市代碼、價格、型態、房數、最新排序）。
    行政區代碼 591 沒有公開對照，所以只帶到縣市，進頁面後再點行政區。
  - 其他平台與 591 租屋：格式沒有實際看過，不猜；改用 Google 限定該站＋最近一週，結果點進去就是平台自己的頁面。
平台清單是公開的物件網站與全國性品牌；清單外的品牌（含加盟體系）不在這裡，仲介設定時自己打品牌名，只用來避開。
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Mapping

from core.tw_districts import COUNTIES, DISTRICTS

# 591 售屋：縣市代碼與型態代碼（2026-10-01 實際操作讀到）
R591 = {"台北市": 1, "基隆市": 2, "新北市": 3, "新竹市": 4, "新竹縣": 5, "桃園市": 6, "苗栗縣": 7, "台中市": 8,
        "彰化縣": 10, "南投縣": 11, "嘉義市": 12, "嘉義縣": 13, "雲林縣": 14, "台南市": 15, "高雄市": 17,
        "屏東縣": 19, "宜蘭縣": 21, "台東縣": 22, "花蓮縣": 23, "金門縣": 25, "連江縣": 26, "澎湖縣": 24}
SHAPE591 = {"公寓": 1, "電梯大樓": 2, "透天": 3, "別墅": 4, "華廈": 5}
KIND591 = {"套房": 10, "車位": 8}


@dataclass(frozen=True)
class Platform:
    name: str
    domain: str
    brand: str | None = None          # 是仲介品牌官網才填：用來避開仲介自己的品牌


PLATFORMS = (
    Platform("591", "591.com.tw"),
    Platform("樂屋網", "rakuya.com.tw"),
    Platform("好房網", "housefun.com.tw"),
    Platform("信義房屋", "sinyi.com.tw", "信義房屋"),
    Platform("住商不動產", "hbhousing.com.tw", "住商不動產"),
    Platform("台灣房屋", "twhg.com.tw", "台灣房屋"),
    Platform("中信房屋", "cthouse.com.tw", "中信房屋"),
    Platform("東森房屋", "etwarm.com.tw", "東森房屋"),
    Platform("21世紀", "century21.com.tw", "21世紀不動產"),
    Platform("太平洋房屋", "pacific.com.tw", "太平洋房屋"),
)
MAX_COUNTY_LINKS = 3


def _split(area: str) -> tuple[str, str | None]:
    """「台中市西屯區」→（台中市, 西屯區）；「彰化縣」→（彰化縣, None）。看不懂的回 ("", None)。"""
    a = str(area or "").replace("臺", "台").replace(" ", "")
    for county in COUNTIES:
        if a.startswith(county):
            rest = a[len(county):]
            return county, (rest if rest in DISTRICTS[county] else None)
    return "", None


def _n(v) -> str:
    return f"{float(v):g}"


def _google(query: str) -> str:
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "tbs": "qdr:w"})


def own_brand_hidden(platform: Platform, profile: Mapping | None) -> bool:
    brand = (profile or {}).get("brand")
    if not platform.brand or not brand or (profile or {}).get("include_own_brand"):
        return False
    return platform.brand in brand or brand in platform.brand


def links_for(need: Mapping, profile: Mapping | None = None) -> list[tuple[str, str]]:
    """客需卡 → [(按鈕文字, 網址)]，591 原生連結在前。避開仲介自己的品牌（他選要的話就不避）。"""
    buy = need.get("transaction") == "buy"
    areas = [_split(a) for a in need.get("preferred_areas") or []]
    areas = [(c, d) for c, d in areas if c]
    counties = list(dict.fromkeys(c for c, _ in areas))
    terms = list(dict.fromkeys(d or c for c, d in areas))[:4]
    kind = str(need.get("property_type") or "")
    out: list[tuple[str, str]] = []
    if buy:
        for county in counties[:MAX_COUNTY_LINKS]:
            q = {"regionid": R591[county], "shType": "list", "order": "posttime_desc"}
            if need.get("budget_max"):
                q["price"] = f"{_n(need.get('budget_min') or 0)}_{_n(need['budget_max'])}"
            if kind in SHAPE591:
                q["shape"] = SHAPE591[kind]
            elif kind in KIND591:
                q["kind"] = KIND591[kind]
            if need.get("rooms_min"):
                q["pattern"] = int(float(need["rooms_min"]))
            label = "591 最新" + (f"・{county[:2]}" if len(counties) > 1 else "")
            out.append((label, "https://sale.591.com.tw/?" + urllib.parse.urlencode(q)))
    words = " ".join(terms) + (f" {kind}" if kind else "") + (" 出售" if buy else " 出租")
    for p in PLATFORMS:
        if own_brand_hidden(p, profile) or (p.name == "591" and buy):
            continue
        site = ("rent." if p.name == "591" else "") + p.domain
        out.append((f"{p.name}（近一週）", _google(f"site:{site} {words}")))
    budget = ""
    if need.get("budget_max"):
        unit = "萬" if buy else "元"
        budget = f" {_n(need['budget_min'])}-{_n(need['budget_max'])}{unit}" if need.get("budget_min") \
            else f" {_n(need['budget_max'])}{unit}以內"
    out.append(("全網搜尋（近一週）", _google(words + budget)))
    return out
