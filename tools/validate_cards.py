"""把每一種回覆畫面送去 LINE 官方格式檢查（/v2/bot/message/validate/reply：只檢查、不發送）。
在本機用合成資料跑一遍主要流程（綁定、新增買方、新增物件、配對、清單、更多功能、隱私），
收集所有回覆（去重），先跑本機自檢；加 --line 再送 LINE 官方檢查（要環境變數 REA_SHARED_LINE_TOKEN，由保險箱帶入）。
    python tools/validate_cards.py            # 只本機自檢
    python tools/validate_cards.py --line     # 加送 LINE 官方檢查
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.line import area_picker as AP  # noqa: E402
from adapters.line.client import LineClient  # noqa: E402
from adapters.line.fake_api import FakeLineApi, synthetic_line_id  # noqa: E402
from adapters.line.flex import validate_message  # noqa: E402
from adapters.line.shared import SharedChannelConfig  # noqa: E402
from adapters.line.signature import sign  # noqa: E402
from adapters.storage import TenantStore  # noqa: E402
from core.tw_districts import DISTRICTS  # noqa: E402
from web.jobs import market_board  # noqa: E402
from web.line_app import create_app  # noqa: E402

SECRET = "synthetic-secret"
UID = synthetic_line_id("U", "validate-cards")


def collect() -> list[dict]:
    msgs: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp, FakeLineApi(token="synthetic-token") as api:
        store, clock, n = TenantStore(tmp), {"t": datetime.datetime(2026, 10, 2, 10, 0)}, [0]
        app = create_app(store=store, channel=SharedChannelConfig(SECRET, "synthetic-token"), now=lambda: clock["t"],
                         client_factory=lambda token: LineClient(token, api_base=api.base_url, min_interval=0),
                         public_base="https://example.test")

        def post(event):
            n[0] += 1
            event.update({"webhookEventId": f"e{n[0]}", "replyToken": f"r{n[0]}", "source": {"type": "user", "userId": UID}})
            body = json.dumps({"events": [event]}).encode()
            app.handle(body, sign(SECRET, body))
            hit = [r for r in api.replies if r["replyToken"] == f"r{n[0]}"]
            msgs.extend(hit[0]["messages"] if hit else [])

        say = lambda t: post({"type": "message", "message": {"type": "text", "text": t}})  # noqa: E731
        tap = lambda op, p, v="", k="": post({"type": "postback", "postback": {"data": AP.data(op, p, v, k)}})  # noqa: E731
        d = lambda c, x: str(DISTRICTS[c].index(x))  # noqa: E731

        say("你好")                                         # 還沒開始用：歡迎卡（同意並開始＋服務條款）
        say(app.registry.issue_code("tenant-v"))
        for t in ("新手體驗", "確認合成檔案", "更多功能", "隱私說明", "客人告知範本", "我的資料",
                  "自營／個人工作室", "合成王小姐"):
            say(t)
        for t in ("新增買方", "合成陳先生", "買"):
            say(t)
        tap("c", "intake", "宜蘭縣"); tap("next", "intake"); tap("d", "intake", d("宜蘭縣", "羅東鎮"), "宜蘭縣")  # noqa: E702
        tap("done", "intake", "", "宜蘭縣")
        for t in ("1200-1800", "透天", "3", "30以上", "不限", "要車位", "不限", "確認儲存"):
            say(t)
        say("新增物件"); say("出售")  # noqa: E702
        tap("c", "listing", "宜蘭縣"); tap("d", "listing", d("宜蘭縣", "羅東鎮"), "宜蘭縣")  # noqa: E702
        for t in ("中正北路", "合成羅東車墅", "1650", "透天", "4", "52", "15", "有車位", "沒有電梯",
                  "https://example.test/m1", "確認儲存"):
            say(t)
        for t in ("客戶清單", "我的物件", "配對 M001", "物件 M001", "新案", "匯出我的資料", "刪除我的資料"):
            say(t)
        for t in ("找新買方", "今日海巡"):
            say(t)
        # 今日報告的全市場卡（排程推播，不走回覆）：用合成的物件池直接排出來，最多那種（12 張）也要過
        brands = ("合成甲房屋", "合成乙不動產", "591", "合成丙房屋")
        items = [{"key": f"x:{i}", "brand": brands[i % 4], "site": "合成網站", "url": f"https://example.test/m/{i}",
                  "title": "合成宜市學區大三房平車電梯華廈邊間採光好" + str(i), "county": "宜蘭縣", "district": "宜蘭市",
                  "price": 888.0 + i, "kind": "華廈", "rooms": 3, "ping": 34.5, "num": i, "fresh": i % 3 == 0}
                 for i in range(70)]
        msgs.extend(market_board.messages({"areas": [("宜蘭縣", "宜蘭市")], "items": items, "nearby": items[:3],
                                           "baseline": False, "scanned": True, "errors": []}))
    seen, out = set(), []
    for m in msgs:
        key = json.dumps(m, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def line_validate(msg: dict, token: str) -> str | None:
    req = urllib.request.Request("https://api.line.me/v2/bot/message/validate/reply", method="POST",
                                 data=json.dumps({"messages": [msg]}, ensure_ascii=False).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            return None
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace")[:300]


def main(argv: list[str]) -> int:
    msgs = collect()
    bad = 0
    token = os.environ.get("REA_SHARED_LINE_TOKEN", "") if "--line" in argv else ""
    if "--line" in argv and not token:
        print("缺 REA_SHARED_LINE_TOKEN，只做本機自檢")
    for m in msgs:
        label = m.get("altText") or (m.get("text") or "")[:24].replace("\n", " ")
        local = validate_message(m)
        remote = line_validate(m, token) if token else None
        if local or remote:
            bad += 1
            print("✗", m["type"], label, local or "", remote or "")
    # 按鈕字太長，窄手機會被截字（經驗值：整排按鈕 16 字以內；快速回覆 LINE 自己限 20 字）
    labels = set()
    for m in msgs:
        for hit in __import__("re").finditer(r'"type": "button".*?"label": "([^"]*)"', json.dumps(m, ensure_ascii=False)):
            labels.add(hit.group(1))
    width = lambda s: sum(1 if ord(c) > 0x2E80 else 0.55 for c in s)  # noqa: E731  中文一格、英數半格
    long = sorted(x for x in labels if width(x) > 16)
    for x in long:
        print("⚠ 按鈕字太長（窄手機可能截字）：", x)
    print(f"{len(msgs)} 種回覆，{bad} 種有問題" + ("（含 LINE 官方檢查）" if token else "（本機自檢）")
          + (f"；{len(long)} 個按鈕字太長" if long else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
