"""選英雄介面的英雄頭像識別：把截圖裡的頭像小塊和官方方形頭像庫比對。

只讀螢幕畫素。頭像庫來自騰訊公開 CDN（game.gtimg.cn/.../champion/{alias}.png），
首次使用時下載到本地快取。

比對方法：取頭像中間的圓形區域（避開邊框、圓角和選中高亮），縮到 20×20，
頭像庫按幾種放大倍數各算一份（客戶端頭像裁得更緊），
各通道減均值後做歸一化相關；對截圖小塊再試幾種輕微的平移和縮放，容忍位置誤差。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

SIDE = 20
# 截圖小塊的平移（佔邊長比例）與縮放，覆蓋定位誤差
SHIFTS = (-0.06, 0.0, 0.06)
SCALES = (0.9, 1.0, 1.1)
# 官網方形頭像 → 客戶端圓角格子的取景：多數英雄是「取中間約 84%」，
# 但少數英雄的官方圖是半身構圖，客戶端只把臉放大填滿格子（例如艾菲利歐 Aphelios：
# 官方圖裡臉在右下方，客戶端取的是 57% 大小、中心偏下 12% 的區域）。
# 只用居中倍數時，這些英雄永遠認不出來（艾菲利歐實測第一名 0.68、正確答案排 65 名）。
# 所以除了居中倍數，再準備幾個「放大 + 偏移」的取景。順序即優先次序：
# 命中居中取景的就先算它，偏移取景只在居中取景都對不上時才有機會勝出。
VIEWS = (
    (0.84, 0.0, 0.0),
    (0.74, 0.0, 0.0),
    (0.66, 0.0, 0.0),
    (0.57, 0.0, 0.12),    # 臉偏下的半身構圖（艾菲利歐）
    (0.60, 0.0, 0.09),
    (0.62, 0.0, 0.0),
    (0.55, 0.0, 0.10),
)
# 客戶端頭像格有時比頭像本身還貼：框住的範圍剛好是頭像、四周沒有留邊，
# 於是特徵和頭像庫（官網圖有留邊）對不上。實測薇古絲 Vex 在 1920x1080 基準下
# 拿到 72x72 的格子時只有 0.583、正確答案排 19 名，看起來就像「認不出」。
# 先補一圈暗邊再取特徵就能修好（0.813）。空格、深色空格補邊後最高只到 0.47/0.55，
# 不會被誤認，所以可以安全地一併嘗試。
PADS = (0.12, 0.16)
# 實機截圖（取各倍數最好的一個）：真頭像 0.79–0.98、領先第二名 0.15 以上；
# 空位、重新整理動畫中的暗頭像最高約 0.68，幾乎不領先
MIN_SCORE = 0.75   # 低於它就當作不是頭像（空位、問號、鎖定圖示、別的介面圖片）
MIN_MARGIN = 0.10  # 第一名要比第二名高出這麼多才算確定


def _mask() -> np.ndarray:
    yy, xx = np.mgrid[0:SIDE, 0:SIDE]
    c = (SIDE - 1) / 2
    return ((xx - c) ** 2 + (yy - c) ** 2) <= (SIDE * 0.42) ** 2


MASK = _mask()


def _feature(img: np.ndarray, inner: float = 0.84,
             dx: float = 0.0, dy: float = 0.0) -> np.ndarray | None:
    """方形頭像 → 歸一化特徵向量。

    inner：取多大比例（去掉外圈邊框）。dx/dy：取景中心相對正中的偏移（比例），
    用來描述客戶端「只把臉放大填滿格子」的取景方式。"""
    if img is None or img.size == 0 or min(img.shape[:2]) < 8:
        return None
    h, w = img.shape[:2]
    s = min(h, w) * inner
    cx, cy = w / 2 + dx * w, h / 2 + dy * h
    x0, y0 = int(round(cx - s / 2)), int(round(cy - s / 2))
    x1, y1 = x0 + int(round(s)), y0 + int(round(s))
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    crop = img[y0:y1, x0:x1]
    small = cv2.resize(crop, (SIDE, SIDE), interpolation=cv2.INTER_AREA).astype(np.float32)
    v = small[MASK]  # (n, 3)
    v = v - v.mean(axis=0, keepdims=True)
    v = v.ravel()
    n = float(np.linalg.norm(v))
    if n < 1e-3:
        return None
    return v / n


def _pad_variants(img: np.ndarray, frac: float, dark: float = 0.20) -> list[np.ndarray]:
    """把截圖小塊先補一圈暗邊再取特徵：模擬「識別框比頭像本身大」。

    客戶端頭像格在不同解析度／縮放下，實際框住的範圍會比頭像稍大或稍小。
    框太貼（頭像填滿整個截圖）時，特徵會失真：實測薇古絲 Vex 的 72x72 框只有
    0.583（正確答案排名 19），補 12% 暗邊後升到 0.813 並認對。
    暗邊用乘上 dark 的鏡像內容，避免整塊純色把特徵向量拉偏。"""
    if frac <= 0:
        return []
    h, w = img.shape[:2]
    m = max(1, int(round(min(h, w) * frac)))
    out = cv2.copyMakeBorder(img, m, m, m, m, cv2.BORDER_REPLICATE).astype(np.float32)
    out[:m] *= dark
    out[-m:] *= dark
    out[:, :m] *= dark
    out[:, -m:] *= dark
    padded = out.astype(np.uint8)
    ph, pw = padded.shape[:2]
    res = []
    for sc in SCALES:
        s = min(ph, pw) * 0.84 / sc
        for dy in SHIFTS:
            for dx in SHIFTS:
                cx, cy = pw / 2 + dx * pw, ph / 2 + dy * ph
                x0, y0 = int(round(cx - s / 2)), int(round(cy - s / 2))
                x1, y1 = x0 + int(round(s)), y0 + int(round(s))
                if x0 < 0 or y0 < 0 or x1 > pw or y1 > ph:
                    continue
                f = _feature(padded[y0:y1, x0:x1], inner=1.0)
                if f is not None:
                    res.append(f)
    return res


def _variants(img: np.ndarray) -> list[np.ndarray]:
    h, w = img.shape[:2]
    out = []
    for sc in SCALES:
        s = min(h, w) * 0.84 / sc
        for dy in SHIFTS:
            for dx in SHIFTS:
                cx, cy = w / 2 + dx * w, h / 2 + dy * h
                x0, y0 = int(round(cx - s / 2)), int(round(cy - s / 2))
                x1, y1 = x0 + int(round(s)), y0 + int(round(s))
                if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                    continue
                f = _feature(img[y0:y1, x0:x1], inner=1.0)
                if f is not None:
                    out.append(f)
    for frac in PADS:
        out.extend(_pad_variants(img, frac))
    return out


@dataclass
class Match:
    hero_id: str | None
    score: float
    second: float

    @property
    def sure(self) -> bool:
        return self.hero_id is not None


class IconBank:
    def __init__(self, icons: dict[str, np.ndarray]):
        ids, feats = [], []
        for hid, img in icons.items():
            fs = [_feature(img, *v) for v in VIEWS]
            if all(f is not None for f in fs):
                ids.append(hid)
                feats.extend(fs)
        self.ids = ids
        # 每個英雄 len(VIEWS) 行，按英雄連續排列
        self.nviews = len(VIEWS)
        self.mat = np.stack(feats) if feats else np.zeros((0, int(MASK.sum()) * 3), np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    def classify(self, crop: np.ndarray) -> Match:
        """一個頭像小塊（BGR，大致方形、頭像居中）→ 英雄 id。"""
        if not self.ids:
            return Match(None, 0.0, 0.0)
        vs = _variants(crop)
        if not vs:
            return Match(None, 0.0, 0.0)
        sims = (np.stack(vs) @ self.mat.T).max(axis=0)  # 每行取最好的截圖變體
        sims = sims.reshape(len(self.ids), self.nviews).max(axis=1)  # 每個英雄取最好的取景
        order = np.argsort(-sims)
        best, second = float(sims[order[0]]), float(sims[order[1]]) if len(order) > 1 else 0.0
        hid = self.ids[order[0]] if best >= MIN_SCORE and best - second >= MIN_MARGIN else None
        return Match(hid, best, second)

    @classmethod
    def from_dir(cls, folder: Path, heroes: dict[str, dict]) -> "IconBank":
        icons = {}
        for hid, h in heroes.items():
            p = folder / f"{h.get('alias')}.png"
            if p.exists():
                img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    icons[hid] = img
        return cls(icons)


def ensure_icons(folder: Path, heroes: dict[str, dict]) -> int:
    """下載缺少的英雄頭像，返回新下載的數量。失敗的下次再試。"""
    from ..data import http
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for h in heroes.values():
        alias, url = h.get("alias"), h.get("icon")
        if not alias or not url:
            continue
        p = folder / f"{alias}.png"
        if p.exists() and p.stat().st_size > 0:
            continue
        try:
            p.write_bytes(http.get(url, timeout=15, retries=1).content)
            n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("頭像下載失敗 %s：%s", alias, e)
    return n
