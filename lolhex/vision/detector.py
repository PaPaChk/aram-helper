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
        self._pending: tuple[tuple[int, int], float] | None = None  # 待確認的候選校準

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

    def _invalidate(self) -> None:
        self.calibration = None
        self._last_fp = None
        self._last_result = None

    def ensure_frame(self, frame: np.ndarray, shape: tuple[int, int] | None = None) -> bool:
        """frame 的實際尺寸和呼叫端預期的尺寸一致嗎？不一致就丟掉校準並回傳 False。

        校準是按當時 client_rect() 回報的寬高算出來的；如果實際截到的 frame 是別
        的尺寸（DPI 感知在截圖前後被改掉、視窗換螢幕、遊戲自己改了縮放），拿舊比例
        框去切這張 frame 只會切到錯的位置，而且會一直錯下去、完全不報錯。
        寧可丟掉校準重掃一次，也不要照著對不上的幾何靜靜地讀錯區域。

        但「校準是別的尺寸留下的」不算衝突：整屏掃描本來就會重新建立校準，把舊的
        丟掉照樣往下掃即可（早期寫成一律回傳 False，會讓換解析度後的第一張整屏掃描
        直接放棄）。"""
        H, W = frame.shape[:2]
        if shape is not None and (W, H) != tuple(shape):
            log.warning("截圖尺寸 %dx%d 與預期 %dx%d 不符：丟掉校準重掃", W, H, shape[0], shape[1])
            self._invalidate()
            return False
        if self.calibration is not None and tuple(self.calibration.size) != (W, H):
            # 整屏掃描不需要校準，丟掉舊尺寸的校準繼續掃。
            self.calibration = None
            self._last_fp = None
            self._last_result = None
        return True

    def reset_calibration(self) -> None:
        self.calibration = None
        self._last_fp = None
        self._last_result = None
        if self.calib_path and self.calib_path.exists():
            self.calib_path.unlink()

    # ---------- 1. 全區域掃描 ----------

    def scan_full(self, frame: np.ndarray, origin: tuple[int, int] = (0, 0),
                  expect: tuple[int, int] | None = None) -> Offer | None:
        """frame 為整個遊戲客戶區。找到 ≥2 張卡返回 Offer；3 張齊全時順便校準。"""
        if not self.ensure_frame(frame, expect):
            return None
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
        """由三張標題建立校準，但先驗證再採用（見 _plausible）。

        使用者回報：同一個 3840x2160 介面，四次校準出現三種不同的 y
        （0.4177 / 0.3859 / 0.4198）。其中 0.3859 那次是 _pick_row 把描述行、
        道具提示或玩家文字當成「三張卡的標題」湊出來的。舊版照單全收，之後
        strip_rect/check_strip 就永遠掃錯位置，而且不會報錯——表現就是
        「有時候卡住，什麼都認不出來」。

        穩定性優先於速度：已經有一份校準、而且它還在正常運作時，不因為某一格
        畫面出現不同候選就換掉它；只有現有校準正在失敗（連續 miss）、或新候選
        連續兩次一致時才替換。"""
        if not self._plausible(group, W, H):
            log.debug("候選校準不合理，保留原校準：%s @ %dx%d", [t[0].box for t in group], W, H)
            return
        cy = float(np.median([t[0].cy for t in group]))
        if self.calibration is not None and self.calibrated_for(W, H) and self._last_result is not None:
            # 現有校準仍在產生結果：只接受與它接近的微調，否則要連續兩次一致才換。
            cur_cy = self._calibration_cy(W, H)
            if cur_cy is not None and abs(cy / H - cur_cy) <= 0.01:
                self._pending = None
            else:
                prev = getattr(self, "_pending", None)
                if prev is None or prev[0] != (W, H) or abs(prev[1] / H - cy / H) > 0.01:
                    self._pending = ((W, H), cy)
                    log.debug("候選校準與現有不同，等下一次一致再換：%s", cy)
                    return
                self._pending = None
        centers = [t[0].cx for t in group]
        spacing = (centers[2] - centers[0]) / 2
        th = int(np.median([t[0].h for t in group]))
        half_w = 0.42 * spacing
        half_h = 0.9 * th
        boxes = [((c - half_w) / W, (cy - half_h) / H, (c + half_w) / W, (cy + half_h) / H) for c in centers]
        self.calibration = Calibration(boxes, (W, H))
        self._pending = None
        log.info("已校準三選一標題位置：%s @ %dx%d", boxes, W, H)

    def _calibration_cy(self, W: int, H: int) -> float | None:
        """目前校準的標題中心 y（相對高度）。"""
        if self.calibration is None or not self.calibrated_for(W, H):
            return None
        return float((self.calibration.boxes[0][1] + self.calibration.boxes[0][3]) / 2)

    @staticmethod
    def _plausible(group, W: int, H: int) -> bool:
        """三張卡標題是否長得像真的三張卡標題。

        要求：三張、同一水平線、左右大致等距且橫跨畫面中部、字高相近、
        而且落在畫面中段（卡片在 BAND 裡，不會貼著上下邊緣）。"""
        if len(group) != 3 or W <= 0 or H <= 0:
            return False
        lines = [t[0] for t in group]
        if any(ln.box is None for ln in lines):
            return False
        heights = [float(ln.h) for ln in lines]
        if min(heights) <= 0 or max(heights) / min(heights) > 2.0:
            return False  # 字高差太多：多半混進了不同大小的文字
        cys = [float(ln.cy) for ln in lines]
        if max(cys) - min(cys) > 0.03 * H:
            return False  # 不在同一水平線
        # 垂直位置：卡片標題落在畫面中段
        if not all(0.15 * H <= cy <= 0.85 * H for cy in cys):
            return False
        centers = [float(ln.cx) for ln in lines]
        if centers[0] >= centers[1] or centers[1] >= centers[2]:
            return False  # 必須已按 x 排序且左右分開
        left = centers[1] - centers[0]
        right = centers[2] - centers[1]
        if left <= 0 or right <= 0:
            return False
        if max(left, right) / min(left, right) > 1.6:
            return False  # 左右間距差太多：不是三張並排的卡
        # 三張卡應該大致以畫面中心對稱
        mid = (centers[0] + centers[2]) / 2
        if abs(mid - W / 2) > 0.12 * W:
            return False
        span = centers[2] - centers[0]
        if not 0.3 * W <= span <= 0.85 * W:
            return False  # 太窄或太寬都不像三張卡
        return True

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
        if self.calibration is None or not self.calibrated_for(win.width, win.height):
            return None
        pb = self.calibration.pixel_boxes(win.width, win.height)
        sx, sy = min(b[0] for b in pb), min(b[1] for b in pb)
        ex, ey = max(b[2] for b in pb), max(b[3] for b in pb)
        # 實際截到的窄帶必須正好是校準算出來的大小；不同就是像素空間對不上，
        # 用舊框去切只會讀到錯的區域，所以直接丟掉校準重掃（見 ensure_frame）。
        if strip.shape[:2] != (ey - sy, ex - sx):
            log.warning("窄帶尺寸 %s 與校準 %s 不符：丟掉校準重掃",
                        strip.shape[:2], (ey - sy, ex - sx))
            self._invalidate()
            return None
        fp = fingerprint(strip)
        if not fp_changed(self._last_fp, fp):
            return self._last_result
        self._last_fp = fp
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
