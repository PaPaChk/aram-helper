"""查詢遊戲 / 客戶端視窗並取得客戶區在螢幕上的物理畫素座標（Win32，只讀）。"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

GAME_CLASS = "RiotWindowClass"
GAME_TITLE = "League of Legends (TM) Client"
CLIENT_CLASS = "RCLIENT"

IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def enable_dpi_awareness() -> None:
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _find(cls: str | None, title: str | None) -> int:
    if not IS_WINDOWS:
        return 0
    return ctypes.windll.user32.FindWindowW(cls, title) or 0


def find_game_window() -> int:
    return _find(GAME_CLASS, None) or _find(None, GAME_TITLE)


def find_client_window() -> int:
    return _find(CLIENT_CLASS, None)


def client_rect(hwnd: int) -> Rect | None:
    if not IS_WINDOWS or not hwnd:
        return None
    u = ctypes.windll.user32
    if u.IsIconic(hwnd) or not u.IsWindowVisible(hwnd):
        return None
    rc = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = wintypes.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w < 200 or h < 150:
        return None
    return Rect(pt.x, pt.y, w, h)


# 貼在客戶端/遊戲上的自己的懸浮小窗：點它時前臺變成它，但畫面上客戶端還在，按客戶端仍在前臺算
_companions: set[int] = set()


def add_companion(hwnd: int) -> None:
    if hwnd:
        _companions.add(int(hwnd))


def is_foreground(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    fg = ctypes.windll.user32.GetForegroundWindow()
    return fg == hwnd or (fg in _companions and not ctypes.windll.user32.IsIconic(hwnd))


_overlay_windows: set[int] = set()          # 浮層：受 allow_capture 控制
_hidden_windows: set[int] = set()           # 永遠排除（主視窗：絕不能蓋到識別區域）
_capture_allowed = bool(os.environ.get("LOLHEX_DEBUG_CAPTURABLE"))  # 除錯截圖時讓懸浮層可見


def exclude_from_capture(hwnd: int, always: bool = False) -> None:
    """讓自己的窗不出現在截圖和錄屏裡（Win10 2004+）：一是避免識別到自己畫的字，
    二是錄影片、直播時畫面乾淨。設定裡開啟"錄屏、截圖時顯示浮窗"就不排除。

    always=True 的窗（主視窗）不受那個設定影響：主視窗不是浮層，而且它會蓋住客戶端的
    選人區域，一旦可被截取就會讓辨識讀到自己的介面而全面失敗。
    """
    if not hwnd:
        return
    if always:
        _hidden_windows.add(int(hwnd))
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(hwnd), 0x11)
        except Exception:
            pass
        return
    _overlay_windows.add(int(hwnd))
    _apply_affinity(int(hwnd))


def _apply_affinity(hwnd: int) -> None:
    if IS_WINDOWS and hwnd:
        try:
            # 0x11 = WDA_EXCLUDEFROMCAPTURE；0 = 正常（能被截到）
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0 if _capture_allowed else 0x11)
        except Exception:
            pass


def set_capture_allowed(allowed: bool) -> None:
    """錄屏、截圖時是否顯示浮窗；對已經開啟的浮窗立即生效。"""
    global _capture_allowed
    _capture_allowed = bool(allowed) or bool(os.environ.get("LOLHEX_DEBUG_CAPTURABLE"))
    for hwnd in list(_overlay_windows):
        _apply_affinity(hwnd)


def capture_allowed() -> bool:
    return _capture_allowed


def give_focus(hwnd: int) -> None:
    """把前臺（鍵盤焦點）還給遊戲或客戶端視窗。只有本程序當前在前臺時 Windows 才允許，
    所以要在點了浮窗、浮窗剛被啟用之後呼叫。不傳送任何按鍵或滑鼠。"""
    if not IS_WINDOWS or not hwnd:
        return
    u = ctypes.windll.user32
    if u.IsWindow(hwnd) and not u.IsIconic(hwnd) and u.GetForegroundWindow() != hwnd:
        u.SetForegroundWindow(hwnd)


def left_button_clicked() -> bool:
    """自上次呼叫以來左鍵是否按下過（GetAsyncKeyState 低位），只讀輸入狀態。"""
    if not IS_WINDOWS:
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x0001)


def cursor_pos() -> tuple[int, int]:
    if not IS_WINDOWS:
        return (0, 0)
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y
