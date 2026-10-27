# -*- coding: utf-8 -*-
"""CSV 匯入的共用解析：編碼、欄位對映、數字／金額／日期／型態的正規化。

仲介手上的 CSV 來源五花八門（自家 Excel、刊登平台後台匯出、CRM 匯出），
欄名、單位、日期寫法都不一樣。這裡把它們收斂成產品內部唯一的寫法：
  - 交易：buy（出售）／rent（出租）
  - 售價：萬元；租金：元／月
  - 坪數：坪；屋齡：年
  - 日期：YYYY-MM-DD（民國年自動換算）
  - 型態：內政部實價登錄的建物型態名稱（見 PROPERTY_TYPES）
  - 區域：「縣市＋鄉鎮市區」，臺→台
解析失敗回 None 或丟 ValueError（由匯入器記成該列錯誤），絕不猜。
"""
from __future__ import annotations

import csv
import datetime
import io
import re
from typing import Any, Iterable, Mapping
from core.property_schema import canonical_type

# ── 編碼 ──
def decode_bytes(data: bytes | str) -> str:
    """Excel 存的 CSV 在台灣常是 Big5（cp950）；新一點的是 UTF-8 帶 BOM。"""
    if isinstance(data, str):
        return data.lstrip("﻿")
    for enc in ("utf-8-sig", "cp950", "big5hkscs"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("看不懂這個檔案的編碼：請另存成 UTF-8 的 CSV")


def read_table(text: str) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """回 (欄名, [(CSV 列號, 列)])。列號從 2 起算（第 1 列是表頭），錯誤訊息直接對得到 Excel 的列。"""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("檔案是空的")
    header = [h.strip().lstrip("﻿") for h in header]
    if not any(header):
        raise ValueError("第 1 列必須是欄名")
    rows = []
    for i, raw in enumerate(reader, start=2):
        if not any(c.strip() for c in raw):
            continue
        rows.append((i, {header[j]: (raw[j].strip() if j < len(raw) else "") for j in range(len(header))}))
    return header, rows


def _norm_header(h: str) -> str:
    """「總價(萬)」「坪數（坪）」→ 總價、坪數：括號裡多半是單位，比對時拿掉（單位另外從原欄名讀）。"""
    h = re.sub(r"[（(【\[].*?[）)】\]]", "", h)
    return re.sub(r"[\s_\-]", "", h).casefold()


def resolve_mapping(headers: Iterable[str], aliases: Mapping[str, Iterable[str]],
                    overrides: Mapping[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    """欄位對映：回 ({內部欄名: CSV 欄名}, 沒對到的 CSV 欄名)。
    overrides 由後台「欄位對映精靈」給：{內部欄名: CSV 欄名}，優先於自動對映。"""
    headers = list(headers)
    by_norm = {_norm_header(h): h for h in headers}
    mapping: dict[str, str] = {}
    for field, header in (overrides or {}).items():
        if header not in headers:
            raise ValueError(f"對映指定的欄位「{header}」不在檔案裡")
        mapping[field] = header
    used = set(mapping.values())
    for field, names in aliases.items():
        if field in mapping:
            continue
        for name in names:
            h = by_norm.get(_norm_header(name))
            if h and h not in used:
                mapping[field] = h
                used.add(h)
                break
    unmapped = [h for h in headers if h not in used]
    return mapping, unmapped


def sensitive_columns(headers: Iterable[str], words: Iterable[str]) -> list[str]:
    # 用原欄名（含括號內容）比：「備用(電話)」也要擋
    ws = [w.casefold() for w in words]
    return [h for h in headers if any(w in h.casefold().replace(" ", "") for w in ws)]


# ── 數字 ──
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def parse_number(v: Any) -> float | None:
    s = str(v or "").replace(",", "").replace("，", "").strip()
    if not s:
        return None
    m = _NUM.search(s)
    if not m:
        raise ValueError(f"不是數字：{s[:20]}")
    return float(m.group())


def parse_price(v: Any, *, transaction: str, header: str = "") -> float | None:
    """售價一律換成萬元、租金一律換成元／月。
    值本身有寫單位（「1,280萬」「2.5萬/月」「18000元」）就照寫的；沒寫就看數字大小，不看欄名——
    欄名常跟內容對不上（「預算(萬)」底下填 18000 的租金），數量級才不會騙人：
      出售：≥10 萬（100000）一定是元 → 換成萬；否則當萬
      出租：<100 一定是萬（1.5＝1.5 萬）→ 換成元；否則當元
    header 參數保留給呼叫端相容，不參與判斷。"""
    s = str(v or "").replace(",", "").replace("，", "").strip()
    if not s:
        return None
    n = parse_number(s)
    unit = "萬" if "萬" in s else ("元" if "元" in s else "")
    if transaction == "rent":
        return n * 10000 if unit == "萬" or (not unit and n < 100) else n
    if unit == "元" or (not unit and n >= 100000):
        return round(n / 10000, 2)
    return n


def parse_rooms(v: Any) -> float | None:
    s = str(v or "").strip()
    if not s:
        return None
    m = re.search(r"(\d+)\s*房", s)
    if m:
        return float(m.group(1))
    if re.search(r"開放|套房|無隔間", s):
        return 0.0
    return parse_number(s)


def parse_size_ping(v: Any, header: str = "") -> float | None:
    s = str(v or "").strip()
    if not s:
        return None
    n = parse_number(s)
    if any(u in s + header for u in ("㎡", "平方公尺", "平方米", "m2", "m²")):
        return round(n / 3.30579, 2)
    return n


def parse_age(v: Any) -> float | None:
    s = str(v or "").strip()
    if not s:
        return None
    if re.search(r"新成屋|預售", s):
        return 0.0
    return parse_number(s)


def parse_date(v: Any) -> str | None:
    s = str(v or "").strip()
    if not s:
        return None
    m = re.match(r"^(?:民國)?\s*(\d{2,4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", s)
    if not m:
        raise ValueError(f"看不懂的日期：{s[:20]}")
    y, mo, d = (int(x) for x in m.groups())
    if y < 1911:                          # 民國年
        y += 1911
    return datetime.date(y, mo, d).isoformat()


# ── 交易、型態、上架、區域 ──
def parse_transaction(v: Any) -> str | None:
    s = str(v or "").strip().casefold()
    if not s:
        return None
    if s in ("buy", "sale", "sell") or any(k in s for k in ("售", "買")):
        return "buy"
    if s in ("rent", "lease") or "租" in s:
        return "rent"
    return None


# 內政部實價登錄的建物型態（加上土地、車位兩類），以及常見寫法
PROPERTY_TYPES = ("電梯大樓", "華廈", "公寓", "透天", "別墅", "套房", "店面", "辦公", "廠房", "土地", "農地", "車位")
_TYPE_RULES = (
    ("套房", ("套房",)),
    ("店面", ("店面", "店鋪", "店住", "金店")),
    ("辦公", ("辦公", "商辦", "寫字樓")),
    ("廠房", ("廠房", "廠辦", "工廠", "倉庫")),
    ("車位", ("車位",)),
    ("農地", ("農地", "農舍", "農牧", "耕地")),
    ("土地", ("土地", "建地", "素地")),
    ("別墅", ("別墅",)),
    ("透天", ("透天",)),
    # 華廈、公寓要比電梯大樓先判：官方寫法「華廈(10層含以下有電梯)」「公寓(5樓含以下無電梯)」都含「電梯」
    ("華廈", ("華廈",)),
    ("公寓", ("公寓",)),
    ("電梯大樓", ("住宅大樓", "電梯大樓", "大樓", "電梯")),
)


def parse_property_type(v: Any) -> str | None:
    s = canonical_type(v)
    if not s:
        return None
    for canon, keys in _TYPE_RULES:
        if any(k in s for k in keys):
            return canon
    return None


_ON_EXACT = ("是", "y", "yes", "true", "1", "online", "on", "v", "✓")
_OFF_EXACT = ("否", "n", "no", "false", "0", "offline", "off", "x")
_ON_WORDS = ("上架", "刊登", "銷售中", "出租中", "招租中", "有效")
_OFF_WORDS = ("未上架", "未刊登", "下架", "已售", "成交", "已出租", "已租", "停售", "停止", "暫停", "失效",
              "解約", "過期")


def parse_online(v: Any) -> bool | None:
    """上架旗標：空白回 None（由匯入器決定預設），認不得也回 None。
    下架詞先比，避免「停止刊登」「未上架」被當成上架。英文只認整個字。"""
    s = str(v or "").strip().casefold()
    if not s:
        return None
    if s in _OFF_EXACT or any(k in s for k in _OFF_WORDS):
        return False
    if s in _ON_EXACT or any(k in s for k in _ON_WORDS):
        return True
    return None


CITIES = ("台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", "基隆市", "新竹市", "嘉義市",
          "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
          "台東縣", "澎湖縣", "金門縣", "連江縣")


def normalize_area(area: Any, *, city: Any = None, default_city: str | None = None) -> tuple[str | None, str | None]:
    """回 (縣市, 區域全名)。區域全名＝縣市＋鄉鎮市區（例：示範市中央區）；臺一律寫成台。
    只有鄉鎮名、又沒有縣市欄時，用租戶設定的 default_city 補，免得各縣市同名的「東區」「中正區」撞在一起。"""
    a = str(area or "").strip().replace("臺", "台").replace(" ", "")
    c = str(city or "").strip().replace("臺", "台").replace(" ", "") or None
    if not a:
        return c or default_city, None
    hit = next((x for x in CITIES if a.startswith(x)), None)
    if hit:
        return hit, a
    if c and a.startswith(c):
        return c, a
    c = c or (default_city.replace("臺", "台") if default_city else None)
    return c, (c + a) if c else a


def split_areas(v: Any) -> list[str]:
    return [x.strip() for x in re.split(r"[、,，/／;；|｜\s]+", str(v or "")) if x.strip()]
