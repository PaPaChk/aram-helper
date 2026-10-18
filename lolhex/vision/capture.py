"""螢幕擷取：只截需要的矩形區域，返回 BGR numpy 陣列。

使用 mss（GDI BitBlt）：無邊框/視窗化下可用；獨佔全屏可能截到黑屏，介面會提示改無邊框。
"""

from __future__ import annotations

import threading

import numpy as np

from .window import Rect

_local = threading.local()


def _mss():
    inst = getattr(_local, "mss", None)
    if inst is None:
        import mss
        inst = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
        _local.mss = inst
    return inst


def grab(rect: Rect) -> np.ndarray:
    shot = _mss().grab({"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height})
    arr = np.asarray(shot)  # BGRA
    return np.ascontiguousarray(arr[:, :, :3])


def is_blank(img: np.ndarray) -> bool:
    """全黑/幾乎純色：多半是獨佔全屏截不到。"""
    return img.size == 0 or float(img.std()) < 2.0
