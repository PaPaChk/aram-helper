"""合成海克斯三選一畫面，用於在沒有遊戲截圖時測試識別流程。"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT = r"C:\Windows\Fonts\msyh.ttc"


def _font(path: str, size: int):
    for p in (path, FONT, "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return None


def fonts_available() -> bool:
    return _font(FONT_BOLD, 10) is not None


def render_offer(names: list[str | None], size=(3840, 2160), seed: int = 0,
                 desc: str = "獲得1個隨機強化符文。") -> np.ndarray:
    """返回 BGR 圖。names 中 None 表示該位置不畫卡。卡片按螢幕中心對稱排布。"""
    W, H = size
    rng = np.random.default_rng(seed)
    base = rng.integers(10, 70, (H, W, 3), dtype=np.uint8)
    img = Image.fromarray(base)
    d = ImageDraw.Draw(img)
    s = H / 1080
    title = _font(FONT_BOLD, int(26 * s))
    small = _font(FONT, int(14 * s))
    # 卡距、標題高度按國服 4K 實機校準結果（標題中心約 0.41H，左右卡距約 369×s）
    card_w, card_h, gap = int(250 * s), int(400 * s), int(369 * s)
    cx0 = W // 2
    for i, n in enumerate(names):
        if n is None:
            continue
        cx = cx0 + (i - 1) * gap
        top = int(H * 0.28)
        d.rectangle([cx - card_w // 2, top, cx + card_w // 2, top + card_h],
                    fill=(45, 38, 70), outline=(210, 180, 70), width=max(2, int(3 * s)))
        tw = d.textlength(n, font=title)
        d.text((cx - tw / 2, int(0.41 * H) - int(17 * s)), n, font=title, fill=(245, 235, 205))
        dw = d.textlength(desc, font=small)
        d.text((cx - dw / 2, int(0.41 * H) + int(40 * s)), desc, font=small, fill=(185, 185, 185))
    arr = np.asarray(img)[:, :, ::-1]
    return np.ascontiguousarray(arr)
