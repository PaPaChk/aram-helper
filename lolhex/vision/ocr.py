"""RapidOCR（PaddleOCR 模型的 ONNX 版）封裝，離線執行。

兩種用法：
- detect(img)：檢測+識別，找出畫面中所有文字行（約 0.3–0.5s，僅在未校準時用）；
- recognize(img)：已知文字區域時只做識別（每塊約 10–20ms）。
模型首次使用時載入（約 0.5s），之後常駐。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class TextLine:
    text: str
    score: float
    box: tuple[int, int, int, int]  # x0, y0, x1, y1（相對輸入圖）

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def h(self) -> int:
        return self.box[3] - self.box[1]


class OCR:
    _inst = None
    _inst_lock = threading.Lock()

    def __init__(self):
        from rapidocr import RapidOCR
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        self._engine = RapidOCR()
        self._lock = threading.Lock()

    @classmethod
    def get(cls) -> "OCR":
        with cls._inst_lock:
            if cls._inst is None:
                cls._inst = cls()
            return cls._inst

    def detect(self, img: np.ndarray) -> list[TextLine]:
        with self._lock:
            r = self._engine(img, use_det=True, use_cls=False, use_rec=True)
        lines = []
        if r is None or getattr(r, "boxes", None) is None or getattr(r, "txts", None) is None:
            return lines
        for box, txt, sc in zip(r.boxes, r.txts, r.scores):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append(TextLine(str(txt), float(sc), (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))))
        return lines

    def recognize(self, img: np.ndarray) -> tuple[str, float]:
        if img.size == 0:
            return "", 0.0
        with self._lock:
            r = self._engine(img, use_det=False, use_cls=False, use_rec=True)
        if r is None or not getattr(r, "txts", None):
            return "", 0.0
        return str(r.txts[0]), float(r.scores[0])
