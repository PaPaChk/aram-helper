"""自動截圖：海克斯三選一和選英雄時，自動儲存一張整屏截圖（含助手畫的浮窗和標註）。

浮窗平時不會被截進去（見 vision/window.py）。截圖那一下臨時放開，截完馬上恢復；
這段時間識別暫停（engine.vision_hold_until），免得把自己畫的字當成遊戲內容。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer

from ..config import app_home
from ..vision import window as win

log = logging.getLogger(__name__)
KEEP = 300                # 最多留這麼多張，多了刪最早的
SETTLE_MS = {"三選一": 900, "選英雄": 300}  # 推薦和標註畫出來以後再截
CS_STABLE_S = 4.0         # 選英雄：標出來的英雄數這麼久沒再增加才截（隊友陸續選好、識別完）
HOLD_S = 0.8              # 截圖前後暫停識別的時間


def shots_dir() -> Path:
    d = app_home() / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


class AutoShot:
    def __init__(self, engine):
        self.engine = engine
        self._offer_key = None   # 已經截過的三選一（三張海克斯）
        self._cs_shot = 0        # 這次選英雄截圖時標了幾個英雄
        self._cs_seen = (0, 0.0)  # (標出來的英雄數, 這個數第一次出現的時間)
        self._busy = False

    def tick(self, snap: dict, game_rect, client_rect) -> None:
        """浮窗每次重新整理時呼叫：出現新的三選一推薦、或進入選英雄介面，就安排截一張。"""
        if not self.engine.settings.auto_screenshot:
            return
        ev, offer = snap.get("evaluation"), snap.get("offer")
        if game_rect and ev and offer:
            key = tuple(offer.get("slots") or [])
            if key != self._offer_key and any(key):
                self._offer_key = key
                self._schedule(game_rect, "三選一")
        elif not offer:
            self._offer_key = None
        cs = snap.get("champ_select")
        if client_rect and cs:
            n = sum(1 for k in ("team", "bench", "cards") for s in cs.get(k) or [] if s.get("grade"))
            now = time.monotonic()
            if n != self._cs_seen[0]:
                self._cs_seen = (n, now)
            elif n > self._cs_shot and now - self._cs_seen[1] >= CS_STABLE_S:
                self._cs_shot = n  # 後面又多標出英雄時再截一張
                self._schedule(client_rect, "選英雄")
        elif not cs:
            self._cs_shot, self._cs_seen = 0, (0, 0.0)

    def _schedule(self, rect, kind: str) -> None:
        if self._busy:
            return
        self._busy = True
        QTimer.singleShot(SETTLE_MS[kind], lambda: self._open(rect, kind))

    def _open(self, rect, kind: str) -> None:
        self.engine.vision_hold_until = time.monotonic() + HOLD_S
        self._restore = win.capture_allowed()
        win.set_capture_allowed(True)
        QTimer.singleShot(200, lambda: self._grab(rect, kind))  # 等視窗屬性生效

    def _grab(self, rect, kind: str) -> None:
        try:
            import cv2

            from ..vision import capture
            img = capture.grab(rect)
            if not capture.is_blank(img):
                ok, buf = cv2.imencode(".png", img)
                if ok:
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]  # 帶毫秒：連著重新整理也不會互相覆蓋
                    path = shots_dir() / f"{stamp}-{kind}.png"
                    path.write_bytes(buf.tobytes())
                    log.info("自動截圖：%s", path.name)
                    self._prune()
        except Exception:
            log.exception("自動截圖失敗")
        finally:
            win.set_capture_allowed(self._restore or self.engine.settings.allow_capture)
            self._busy = False

    @staticmethod
    def _prune() -> None:
        files = sorted(shots_dir().glob("*.png"))
        for old in files[:-KEEP]:
            old.unlink(missing_ok=True)
