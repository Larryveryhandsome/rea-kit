# -*- coding: utf-8 -*-
"""內政部實價登錄開放資料（免金鑰）：下載某縣市某季的買賣 CSV，算行政區的成交概況。

資料來源：https://plvr.land.moi.gov.tw/DownloadOpenData （政府開放資料，政府資料開放授權條款）
- 每縣市每季一個檔，下載後存在 <資料根>/lvr/<季>_<縣市代碼>_A.csv，同一季不重抓。
- 門牌在原始資料就只到區段（例：XX路1~30號），我們不再加工、不對外散布原檔。
- 只做「概況」（筆數、單價中位數、最近幾筆），不做估價。
"""
from __future__ import annotations

import csv
import io
import os
import pathlib
import statistics

from adapters.integration_checks import COUNTY_LETTER, NetError, http, lvr_seasons, lvr_url
from adapters.storage import DATA_ENV, REPO

SQM_PER_PING = 3.305785


def cache_dir(root=None) -> pathlib.Path:
    return pathlib.Path(root or os.environ.get(DATA_ENV) or (REPO / "data")).resolve() / "lvr"


def fetch(county: str, *, season: str | None = None, opener=None, root=None, today=None) -> tuple[str, bytes]:
    """回 (季別, CSV bytes)。沒指定季別就從最近一季往回找有資料的。"""
    if county not in COUNTY_LETTER:
        raise ValueError(f"不認得的縣市：{county}")
    d = cache_dir(root)
    for s in ([season] if season else lvr_seasons(today)):
        f = d / f"{s}_{COUNTY_LETTER[county]}_A.csv"
        if f.exists() and f.stat().st_size > 0:
            return s, f.read_bytes()
        try:
            r = http("GET", lvr_url(county, s), opener=opener, timeout=60)
        except NetError as e:
            raise RuntimeError("連不上內政部實價登錄網站") from e
        if r.status == 200 and "鄉鎮市區".encode("utf-8") in r.body[:200]:
            d.mkdir(parents=True, exist_ok=True)
            f.write_bytes(r.body)
            return s, r.body
    raise RuntimeError("最近幾季都抓不到資料（政府網站可能在維護）")


def _num(x) -> float | None:
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


def parse(body: bytes) -> list[dict]:
    text = body.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows[1:] if rows and rows[0].get("鄉鎮市區", "").startswith("The ") else rows   # 第二列是英文欄名


def summary(rows: list[dict], district: str, *, building_only: bool = True, recent: int = 10) -> dict:
    """某行政區：筆數、單價中位數（萬/坪）、最近幾筆（不含特殊交易）。"""
    picked = []
    for r in rows:
        if r.get("鄉鎮市區") != district:
            continue
        if building_only and "建物" not in (r.get("交易標的") or ""):
            continue
        if (r.get("備註") or "").strip():          # 備註有寫的多半是親友、瑕疵等特殊交易，概況先排除
            continue
        unit = _num(r.get("單價元平方公尺"))
        total = _num(r.get("總價元"))
        if not unit or not total:
            continue
        area = _num(r.get("建物移轉總面積平方公尺")) or 0
        picked.append({"date": r.get("交易年月日", ""), "type": r.get("建物型態", ""),
                       "place": r.get("土地位置建物門牌", ""),
                       "unit_wan_per_ping": round(unit * SQM_PER_PING / 10000, 1),
                       "total_wan": round(total / 10000), "ping": round(area / SQM_PER_PING, 1)})
    picked.sort(key=lambda x: x["date"], reverse=True)
    units = [p["unit_wan_per_ping"] for p in picked]
    return {"district": district, "count": len(picked),
            "median_unit_wan_per_ping": round(statistics.median(units), 1) if units else None,
            "recent": picked[:recent]}


def districts(rows: list[dict]) -> list[str]:
    return sorted({r.get("鄉鎮市區", "") for r in rows if r.get("鄉鎮市區")})
