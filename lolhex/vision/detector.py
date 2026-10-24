"""海克斯三選一畫面的識別與低負載跟蹤。

怎麼判定"現在要選海克斯"：不依賴固定座標，而是看畫面裡是否同時出現
≥2 個能匹配到海克斯字典的文字，且它們在同一水平線上、左右排開。

負載控制分三級：
1. 未校準：每 bootstrap_interval 秒擷取畫面中部，縮小後做一次"檢測+識別"（約 0.3–0.5s）。
   一旦完整識別到三張，就記住三個標題的位置（按視窗比例儲存，換解析度自動失效）。
2. 已校準：每 scan_interval 只截三個標題所在的一條窄帶；先算縮圖指紋，
   和上次一樣就直接複用結果（幾乎零開銷）；變了才對三個小塊做"僅識別"（每塊約 10–20ms）。
3. 已校準但識別不到：說明沒在選海克斯，保持第 2 級的輕量檢查。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .matcher import NameMatcher
from .ocr import OCR, TextLine
from .window import Rect

log = logging.getLogger(__name__)

# 未校準時掃描的區域（相對視窗）：三張卡片都在螢幕中部。
BAND = (0.12, 0.10, 0.88, 0.85)  # x0, y0, x1, y1
DETECT_MAX_W = 1600               # 檢測前把區域縮到這個寬度以內（4K 下約縮一半）
REC_HEIGHT = 48                   # 識別前把標題塊縮放到這個高度
@dataclass
class Calibration:
    """三個標題框，存為相對視窗的比例座標 (x0, y0, x1, y1)。

    只由當次 OCR 實際找到的三個標題建立，不在不同 UI scale、解析度或程式啟動之間沿用。
    """
    boxes: list[tuple[float, float, float, float]]
    size: tuple[int, int]

    def pixel_boxes(self, w: int, h: int) -> list[tuple[int, int, int, int]]:
        return [(int(a * w), int(b * h), int(c * w), int(d * h)) for a, b, c, d in self.boxes]


@dataclass
class Offer:
    slots: list[str | None]
    texts: list[str]
    scores: list[float]
    boxes: list[tuple[int, int, int, int] | None]  # 螢幕座標下的標題框
    at: float = field(default_factory=time.time)

    def key(self) -> tuple:
        return tuple(self.slots)

    def matched(self) -> int:
        return sum(1 for s in self.slots if s)


def _resize(img: np.ndarray, scale: float) -> np.ndarray:
    if abs(scale - 1.0) < 1e-3:
        return img
    import cv2
    h, w = img.shape[:2]
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=interp)


def fingerprint(img: np.ndarray) -> np.ndarray:
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.resize(g, (96, 12), interpolation=cv2.INTER_AREA).astype(np.int16)


def fp_changed(a: np.ndarray | None, b: np.ndarray) -> bool:
    """只換了一張卡時整體均值變化很小，所以看區域性：任一格子明顯變化就算變了。"""
    if a is None or a.shape != b.shape:
        return True
    d = np.abs(a - b)
    return float(d.max()) > 24 or float(d.mean()) > 3


class AugmentDetector:
    def __init__(self, matcher: NameMatcher, calib_path: Path | None = None, ocr: OCR | None = None):
        self.matcher = matcher
        # 保留參數以兼容舊呼叫端；校準不再從磁碟載入。玩家會改 UI scale，
        # 同解析度的舊比例框不能證明仍然有效。
        self.calib_path = calib_path
        self._ocr = ocr
        self.calibration: Calibration | None = None
        self._last_fp: np.ndarray | None = None
        self._last_result: Offer | None = None

    @property
    def ocr(self) -> OCR:
        if self._ocr is None:
            self._ocr = OCR.get()
        return self._ocr

    def set_matcher(self, matcher: NameMatcher) -> None:
        self.matcher = matcher
        self._last_fp = None

    def calibrated_for(self, w: int, h: int) -> bool:
        return self.calibration is not None and tuple(self.calibration.size) == (w, h)

    def confirmed_for(self, w: int, h: int) -> bool:
        return self.calibrated_for(w, h)

    def ensure_calibration(self, w: int, h: int) -> None:
        """視窗尺寸變了就丟掉舊校準；新尺寸必須由整屏 OCR 重新找到。"""
        if self.calibration is not None and not self.calibrated_for(w, h):
            self.calibration = None
            self._last_fp = None
            self._last_result = None

    def reset_calibration(self) -> None:
        self.calibration = None
        self._last_fp = None
        self._last_result = None
        if self.calib_path and self.calib_path.exists():
            self.calib_path.unlink()

    # ---------- 1. 全區域掃描 ----------

    def scan_full(self, frame: np.ndarray, origin: tuple[int, int] = (0, 0)) -> Offer | None:
        """frame 為整個遊戲客戶區。找到 ≥2 張卡返回 Offer；3 張齊全時順便校準。"""
        H, W = frame.shape[:2]
        x0, y0, x1, y1 = int(BAND[0] * W), int(BAND[1] * H), int(BAND[2] * W), int(BAND[3] * H)
        band = frame[y0:y1, x0:x1]
        scale = min(1.0, DETECT_MAX_W / max(1, band.shape[1]))
        lines = self.ocr.detect(_resize(band, scale))
        hits: list[tuple[TextLine, str, float]] = []
        for ln in lines:
            aid, sc = self.matcher.match(ln.text)
            if aid:
                bx = tuple(int(v / scale) for v in ln.box)
                hits.append((TextLine(ln.text, ln.score, (bx[0] + x0, bx[1] + y0, bx[2] + x0, bx[3] + y0)), aid, sc))
        group = self._pick_row(hits, H)
        if len(group) < 2:
            return None
        group.sort(key=lambda t: t[0].cx)
        slots, texts, scores, boxes = self._assign_columns(group, W)
        if len(group) == 3:
            self._calibrate(group, W, H)
        ox, oy = origin
        sboxes = [None if b is None else (b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy) for b in boxes]
        return Offer(slots, texts, scores, sboxes)

    @staticmethod
    def _pick_row(hits, H):
        """同一水平線上、橫向分開的匹配項；一張卡只取分數最高的一條。"""
        best: list = []
        for ln, _, _ in hits:
            row = [t for t in hits if abs(t[0].cy - ln.cy) < 0.03 * H]
            # 同一張卡上可能匹配到多行（標題 + 描述裡提到別的海克斯名），按橫向距離去重。
            row.sort(key=lambda t: -t[2])
            uniq: list = []
            for t in row:
                if all(abs(t[0].cx - u[0].cx) > 0.08 * H for u in uniq):
                    uniq.append(t)
            if len(uniq) > len(best):
                best = uniq
        return best[:3]

    @staticmethod
    def _assign_columns(group, W):
        """把識別到的卡片放進左/中/右三個位置。只有兩張時按左右對稱推斷缺的是哪張。"""
        slots: list[str | None] = [None, None, None]
        texts = ["", "", ""]
        scores = [0.0, 0.0, 0.0]
        boxes: list = [None, None, None]
        if len(group) == 3:
            idx = [0, 1, 2]
        else:
            a, b = group[0][0].cx, group[1][0].cx
            mid = W / 2
            gap = b - a
            if abs((a + b) / 2 - mid) < 0.25 * gap:
                idx = [0, 2]          # 左右兩張，中間缺
            elif abs(a - mid) < 0.25 * gap:
                idx = [1, 2]          # 中、右
            else:
                idx = [0, 1]          # 左、中
        for i, (ln, aid, sc) in zip(idx, group):
            slots[i], texts[i], scores[i], boxes[i] = aid, ln.text, sc, ln.box
        return slots, texts, scores, boxes

    def _calibrate(self, group, W, H) -> None:
        centers = [t[0].cx for t in group]
        spacing = (centers[2] - centers[0]) / 2
        th = int(np.median([t[0].h for t in group]))
        cy = float(np.median([t[0].cy for t in group]))
        half_w = 0.42 * spacing
        half_h = 0.9 * th
        boxes = [((c - half_w) / W, (cy - half_h) / H, (c + half_w) / W, (cy + half_h) / H) for c in centers]
        self.calibration = Calibration(boxes, (W, H))
        log.info("已校準三選一標題位置：%s @ %dx%d", boxes, W, H)

    # ---------- 2. 已校準的輕量檢查 ----------

    def strip_rect(self, win: Rect) -> Rect | None:
        """三個標題框的外接矩形（螢幕座標），只截這一條。"""
        if not self.calibrated_for(win.width, win.height):
            return None
        pb = self.calibration.pixel_boxes(win.width, win.height)
        x0, y0 = min(b[0] for b in pb), min(b[1] for b in pb)
        x1, y1 = max(b[2] for b in pb), max(b[3] for b in pb)
        return Rect(win.left + x0, win.top + y0, x1 - x0, y1 - y0)

    def check_strip(self, strip: np.ndarray, win: Rect) -> Offer | None:
        """strip 為 strip_rect 截圖。畫面沒變化時直接複用上次結果。"""
        fp = fingerprint(strip)
        if not fp_changed(self._last_fp, fp):
            return self._last_result
        self._last_fp = fp
        pb = self.calibration.pixel_boxes(win.width, win.height)
        sx, sy = min(b[0] for b in pb), min(b[1] for b in pb)
        slots: list[str | None] = []
        texts, scores, boxes = [], [], []
        for (x0, y0, x1, y1) in pb:
            crop = strip[y0 - sy:y1 - sy, x0 - sx:x1 - sx]
            scale = REC_HEIGHT / max(1, crop.shape[0])
            txt, conf = self.ocr.recognize(_resize(crop, scale))
            aid, sc = self.matcher.match(txt)
            slots.append(aid)
            texts.append(txt)
            scores.append(sc)
            boxes.append((win.left + x0, win.top + y0, win.left + x1, win.top + y1))
        offer = Offer(slots, texts, scores, boxes)
        self._last_result = offer if offer.matched() >= 2 else None
        return self._last_result

    def column_of(self, x: int, y: int, win: Rect) -> int | None:
        """螢幕座標 (x, y) 落在哪張卡的豎列上；用於記錄玩家點了哪張。"""
        if not self.calibrated_for(win.width, win.height):
            return None
        pb = self.calibration.pixel_boxes(win.width, win.height)
        spacing = (pb[2][0] - pb[0][0]) / 2
        title_y = (pb[0][1] + pb[0][3]) / 2 + win.top
        if abs(y - title_y) > 0.35 * win.height:
            return None
        for i, b in enumerate(pb):
            cx = (b[0] + b[2]) / 2 + win.left
            if abs(x - cx) < spacing / 2:
                return i
        return None
