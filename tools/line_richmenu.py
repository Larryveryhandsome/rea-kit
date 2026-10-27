"""把圖文選單掛到共用通知帳號（所有好友預設看到）。金鑰從環境變數 REA_SHARED_LINE_TOKEN 來（保險箱帶入），不印出。
先刪掉以前我們建的（名稱開頭 rea-kit），再建新的、上傳圖片、設成預設。每一格都是「點了等於打那句話」。
    python tools/line_richmenu.py check     # 只看目前掛了什麼
    python tools/line_richmenu.py apply     # 建立並設為預設
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
W, H = 2500, 1686
NAME = "rea-kit main menu v1"
# (標題, 小字, 點了送出的字, 圓圈裡的字)
TILES = [
    ("找新買方", "想買房的人的貼文", "今日海巡", "找"),
    ("替買方找房", "記需求・每天找新物件", "新增買方", "需"),
    ("新增物件", "馬上配對你的買方", "新增物件", "物"),
    ("客戶清單", "卡片直接點", "客戶清單", "客"),
    ("今日報告", "海巡＋各平台新物件", "今日報告", "報"),
    ("更多功能", "物件・報告・設定", "更多功能", "多"),
]
API, DATA_API = "https://api.line.me/v2/bot", "https://api-data.line.me/v2/bot"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):          # 不跟轉址：授權標頭不能被帶去別的主機
        return None


OPEN = urllib.request.build_opener(_NoRedirect).open


def call(method: str, url: str, token: str, body: bytes | None = None, ctype: str = "application/json") -> dict:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    try:
        with OPEN(req, timeout=20) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"LINE API {method} {url.rsplit('/bot', 1)[1]} → {e.code} {e.read()[:200]!r}") from None
    return json.loads(raw or b"{}")


def menu() -> dict:
    cw, ch = W // 3, H // 2
    return {"size": {"width": W, "height": H}, "selected": True, "name": NAME, "chatBarText": "功能選單",
            "areas": [{"bounds": {"x": (i % 3) * cw, "y": (i // 3) * ch, "width": cw, "height": ch},
                       "action": {"type": "message", "label": title, "text": text}}
                      for i, (title, _sub, text, _mark) in enumerate(TILES)]}


def main(argv: list[str]) -> None:
    token = os.environ.get("REA_SHARED_LINE_TOKEN", "")
    if not token:
        raise SystemExit("缺 REA_SHARED_LINE_TOKEN（請用啟動器的保險箱帶入）")
    mine = [m for m in call("GET", f"{API}/richmenu/list", token).get("richmenus", [])
            if str(m.get("name", "")).startswith("rea-kit")]
    if argv[:1] != ["apply"]:
        print("our menus:", [(m["richMenuId"][-6:], m["name"]) for m in mine])
        return
    png = (ROOT / "assets" / "richmenu.png").read_bytes()
    if len(png) > 1_000_000:
        raise SystemExit("圖片超過 1MB")
    new_id = call("POST", f"{API}/richmenu", token, json.dumps(menu(), ensure_ascii=False).encode())["richMenuId"]
    call("POST", f"{DATA_API}/richmenu/{new_id}/content", token, png, "image/png")
    call("POST", f"{API}/user/all/richmenu/{new_id}", token, b"")
    for m in mine:                                   # 新的掛好才刪舊的，中間不會沒有選單
        call("DELETE", f"{API}/richmenu/{m['richMenuId']}", token)
    print("default rich menu set:", new_id[-6:], "| removed old:", len(mine))


if __name__ == "__main__":
    main(sys.argv[1:])
