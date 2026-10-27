"""畫共用通知帳號的圖文選單 assets/richmenu.png（2500×1686，3×2 六格）。格子順序與 tools/line_richmenu.py 的 TILES 相同。
負責人 2026-10-03：「所有東西都要卡片化、圖卡點選化」→ 主要功能放在聊天室下面，點了就開始，不用記指令。
    python tools/make_richmenu.py
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.line_richmenu import TILES, W, H  # noqa: E402

OUT = ROOT / "assets" / "richmenu.png"
BAR, TINT, INK, WHITE, LINE = (15, 110, 86), (225, 245, 238), (4, 52, 44), (255, 255, 255), (190, 214, 205)
FONT_BOLD = "C:/Windows/Fonts/msjhbd.ttc"
FONT = "C:/Windows/Fonts/msjh.ttc"


def centered(d, text, font, cx, y, fill):
    d.text((cx - d.textlength(text, font=font) / 2, y), text, font=font, fill=fill)


def main() -> None:
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    big, small, icon = ImageFont.truetype(FONT_BOLD, 120), ImageFont.truetype(FONT, 66), ImageFont.truetype(FONT_BOLD, 140)
    cw, ch = W // 3, H // 2
    for i, (title, sub, _text, mark) in enumerate(TILES):
        x, y = (i % 3) * cw, (i // 3) * ch
        top = i < 3
        d.rectangle([x, y, x + cw, y + ch], fill=BAR if top else TINT)
        d.rectangle([x, y, x + cw - 1, y + ch - 1], outline=LINE, width=4)
        fg = WHITE if top else INK
        r, cx, cy = 115, x + cw / 2, y + 210                   # 圓圈裡一個字當圖示（微軟正黑體沒有表情符號）
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE if top else BAR)
        centered(d, mark, icon, cx, cy - 98, BAR if top else WHITE)
        centered(d, title, big, x + cw / 2, y + 380, fg)
        centered(d, sub, small, x + cw / 2, y + 580, (205, 236, 225) if top else (60, 110, 96))
    OUT.parent.mkdir(exist_ok=True)
    img.save(OUT, optimize=True)
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
