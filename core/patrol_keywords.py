"""海巡關鍵字模組（純邏輯、零 I/O）。

負責人 2026-10-01 定的邏輯：
  一組海巡 ＝「地區詞」×「需求詞組」，例如 地區「彰化」＋需求「買房」→ 在 Threads 搜「彰化 買房」「彰化 找房」…
  - 需求詞組由仲介點選（買／租 × 住宅／土地／廠房／商用，可複選）
  - 地區詞來自他點選的縣市／行政區（縣市 → 「彰化」；行政區 → 「大同」）
  - 每位仲介一天最多海巡 3 組；選超過 3 組就逐日輪流，全部都會輪到

關鍵字是初版，依台灣社群常見的找房說法整理；接上官方搜尋後要依實際命中率調整排序與增刪。
本模組只產生搜尋字串與排程，不搜尋、不連網、不判斷貼文；判斷真買方／同業／廣告是另一步。
"""
from __future__ import annotations

import datetime
import urllib.parse
from dataclasses import dataclass

from core.tw_districts import COUNTIES, DISTRICTS, WHOLE

INTENTS = {"buy": "買", "rent": "租", "sell": "賣"}    # sell：找屋主自己想賣的（負責人 2026-10-08「只要真實的買賣方」）
KINDS = ("住宅", "土地", "廠房", "商用")

# 依預期命中率排序（越前面越先用）。同一詞組內不重複。
# 2026-10-02 併入早期海巡專案的經驗（docs/協作/2026-10-02_海巡經驗移植_關鍵字建議.md）：實際用過的詞放前段尾、推論的詞放最後，
# 等今日報告累積命中率再調排序。
KEYWORDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("buy", "住宅"): ("買房", "找房", "想買房", "求購", "徵屋", "購屋", "首購", "換屋", "找房子", "買屋",
                    "我要買房", "誠徵房子", "想買", "找透天", "買透天"),
    ("rent", "住宅"): ("租屋", "找租屋", "求租", "徵租", "想租房", "租房子", "找套房", "租套房", "找租", "找整層",
                     "租整層", "可養寵物", "找雅房"),
    ("buy", "土地"): ("買地", "找地", "求購土地", "徵地", "買農地", "找建地", "買建地", "建地", "找農地", "蓋農舍",
                    "找工業地"),
    ("rent", "土地"): ("租地", "找地租", "徵求土地出租", "租農地", "租空地", "找空地", "承租土地"),
    ("buy", "廠房"): ("買廠房", "找廠房", "求購廠房", "徵廠房", "買廠辦", "找廠地"),
    ("rent", "廠房"): ("租廠房", "找廠房", "徵廠房出租", "租倉庫", "找倉庫", "承租廠房", "找倉儲"),
    ("buy", "商用"): ("買店面", "找店面", "買辦公室", "求購店面", "買商辦", "買整棟"),
    ("rent", "商用"): ("租店面", "找店面", "租辦公室", "找辦公室", "租商辦", "找一樓店面", "找工作室"),
    ("sell", "住宅"): ("想賣房", "房子要賣", "房子想賣", "老家要賣", "屋主自售", "賣房子要注意"),
    ("sell", "土地"): ("想賣地", "土地要賣", "賣農地", "農地自售", "賣土地"),
    ("sell", "廠房"): ("廠房要賣", "賣廠房", "廠房自售"),
    ("sell", "商用"): ("店面要賣", "賣店面", "店面自售"),
}

# 同業／賣方／廣告：強訊號一個就排除；弱訊號要兩個以上（買方也會說開價、帶看、實價登錄）
STRONG_SELLER = ("物件編號", "來電洽詢", "服務專線", "預約賞屋", "接待中心", "代銷", "經紀營業員", "證號",
                 "加盟店", "直營店", "我的客戶在找", "幫買方找", "收購中", "誠徵物件", "收委託", "誠徵業務",
                 "底薪", "新人培訓", "加入團隊")
SELLER_SIGNALS = ("出售", "售屋", "開價", "降價", "帶看", "經紀人", "房仲", "歡迎洽詢", "加賴", "賞屋",
                  "專任", "委託", "實價登錄", "店長推薦", "出租", "招租", "自售", "屋主直售", "誠售", "急售",
                  "免仲介費", "房東直租", "低總價", "釋出", "稀有", "可貸", "成數", "斡旋")
# 作者明說不要被房仲聯絡（不代表是買方，屋主也會寫）→ 今日報告不列、不給回覆按鈕
DO_NOT_CONTACT = ("勿擾", "謝絕仲介", "婉拒仲介", "拒絕仲介", "仲介退散", "房仲退散", "不找仲介", "不透過仲介",
                  "不經仲介", "限屋主", "只找屋主", "勿推銷")

DAILY_GROUPS = 3          # 每位仲介每天最多海巡幾組
QUERIES_PER_GROUP = 6     # 每組最多用幾個需求詞（受官方搜尋次數上限影響，之後依實測調整）

_GENERIC = {"東區", "西區", "南區", "北區", "中區", "中西區"}


def county_term(county: str) -> str:
    """台北市→台北、彰化縣→彰化。新竹市／新竹縣、嘉義市／嘉義縣都變成同一個詞，社群上本來就不太分。"""
    return county[:-1] if county.endswith(("市", "縣")) else county


def district_term(county: str, district: str) -> str:
    """西屯區→西屯、員林市→員林、那瑪夏區→那瑪夏；東區、中區這類通名前面加縣市：台中東區。"""
    if district in _GENERIC:
        return county_term(county) + district
    if len(district) > 2 and district.endswith(("區", "鄉", "鎮", "市")):
        return district[:-1]
    return district


def ambiguous_terms() -> set[str]:
    """同一個地區詞出現在不只一個縣市（例：大同、信義、中山）。搜尋照樣用，分類時要再看縣市。"""
    seen: dict[str, set[str]] = {}
    for county, names in DISTRICTS.items():
        for d in names:
            seen.setdefault(district_term(county, d), set()).add(county)
    return {t for t, cs in seen.items() if len(cs) > 1}


def threads_url(query: str) -> str:
    """Threads 搜尋頁（最新）。仲介點了用自己的 Threads 看貼文、自己回覆；這裡不去抓任何內容。"""
    return "https://www.threads.com/search?" + urllib.parse.urlencode({"q": query, "filter": "recent",
                                                                       "serp_type": "default"})


def default_keywords(intent: str, kind: str) -> tuple[str, ...]:
    return KEYWORDS[(intent, kind)][:QUERIES_PER_GROUP]


@dataclass(frozen=True)
class PatrolGroup:
    area_term: str                 # 例：彰化、西屯、台中東區
    county: str                    # 例：彰化縣（給分類步驟核對地區用）
    intent: str                    # buy／rent
    kind: str                      # 住宅／土地／廠房／商用
    keywords: tuple[str, ...] = ()  # 仲介自己勾的需求詞；空的就用預設前幾個

    @property
    def label(self) -> str:
        if self.intent == "sell":
            return f"{self.area_term}・屋主想賣"
        return f"{self.area_term}・{INTENTS[self.intent]}{self.kind}"

    def queries(self, limit: int = QUERIES_PER_GROUP) -> list[str]:
        words = self.keywords or KEYWORDS[(self.intent, self.kind)]
        return [f"{self.area_term} {kw}" for kw in words[:limit]]


def area_terms(selection: dict[str, list[str]]) -> list[tuple[str, str]]:
    """{縣市: [區…] 或 ["*"]} → [(地區詞, 縣市)]，依字典順序、不重複。"""
    out: list[tuple[str, str]] = []
    for county in COUNTIES:
        picked = selection.get(county)
        if not picked:
            continue
        if WHOLE in picked:
            pairs = [(county_term(county), county)]
        else:
            pairs = [(district_term(county, d), county) for d in DISTRICTS[county] if d in picked]
        for p in pairs:
            if p not in out:
                out.append(p)
    return out


def build_groups(selection: dict[str, list[str]], intents: list[str], kinds: list[str],
                 keywords: list[str] | None = None) -> list[PatrolGroup]:
    for i in intents:
        if i not in INTENTS:
            raise ValueError(f"不認得的需求：{i}")
    for k in kinds:
        if k not in KINDS:
            raise ValueError(f"不認得的類別：{k}")
    chosen = tuple(keywords or ())
    # 仲介勾的＋自己打的關鍵字都用（負責人 2026-10-02：要能自由選、也能自己輸入）
    return [PatrolGroup(term, county, i, k, chosen)
            for term, county in area_terms(selection)
            for i in [x for x in INTENTS if x in intents]
            for k in [x for x in KINDS if x in kinds]]


def todays_groups(groups: list[PatrolGroup], day: datetime.date, per_day: int = DAILY_GROUPS) -> list[PatrolGroup]:
    """每天最多 per_day 組；超過就逐日輪流（以日期決定起點，同一天重算結果一樣）。"""
    if len(groups) <= per_day:
        return list(groups)
    rounds = -(-len(groups) // per_day)
    start = (day.toordinal() % rounds) * per_day
    picked = groups[start:start + per_day]
    if len(picked) < per_day:                       # 最後一輪不足時，從頭補滿
        picked += groups[:per_day - len(picked)]
    return picked


def merge_queries(plans: dict[str, list[PatrolGroup]]) -> dict[str, list[str]]:
    """多位仲介同一天的查詢合併去重：{搜尋字串: [租戶…]}。同一個「彰化 買房」只查一次，結果分給所有要的人。"""
    out: dict[str, list[str]] = {}
    for tenant, groups in plans.items():
        for g in groups:
            for q in g.queries():
                out.setdefault(q, [])
                if tenant not in out[q]:
                    out[q].append(tenant)
    return out
