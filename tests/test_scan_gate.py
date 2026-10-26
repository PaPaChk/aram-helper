"""遊戲中重啟：助手自己的視窗在前臺時仍要識別；自動截圖期間仍要暫停。

使用者回報：先開助手再進遊戲正常，但在遊戲中重啟助手後浮層永遠不出現。
原因是 _vision_loop 舊的條件要求遊戲視窗必須在前臺（win.is_foreground），
而啟動時搶到前臺的是助手自己的主視窗，於是永遠 paused。
「不要讀到自己畫的字」這個舊理由已由 exclude_from_capture 解決。

這些測試刻意不 stub「自己的窗」清單，而是走真實登記路徑（MainWindow.showEvent /
exclude_from_capture(always=True)），否則假造集合會讓測試通過但實際仍然壞掉。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest

from lolhex.vision import window as win

GAME = 9001
MAIN = 9002
OVERLAY = 9003
OTHER = 9004


@pytest.fixture
def screen(monkeypatch):
    """可控的前臺視窗；IS_WINDOWS 當作真，但 user32 換成假的。"""
    state = {"fg": GAME, "iconic": set(), "applied": []}

    class FakeUser32:
        @staticmethod
        def GetForegroundWindow():
            return state["fg"]

        @staticmethod
        def IsIconic(hwnd):
            return hwnd in state["iconic"]

        @staticmethod
        def SetWindowDisplayAffinity(hwnd, aff):
            state["applied"].append((hwnd, aff))
            return 1

    monkeypatch.setattr(win, "IS_WINDOWS", True)
    monkeypatch.setattr(win.ctypes, "windll", SimpleNamespace(user32=FakeUser32), raising=False)
    monkeypatch.setattr(win, "_companions", set())
    monkeypatch.setattr(win, "_overlay_windows", set())
    monkeypatch.setattr(win, "_hidden_windows", set())
    monkeypatch.setattr(win, "_own_windows", set())
    monkeypatch.setattr(win, "_capture_allowed", False)
    monkeypatch.setattr(win, "_scan_holds", 0)
    # client_rect 的量測留給各測試自己決定
    return state


def test_scannable_when_game_is_foreground(screen):
    assert win.scannable(GAME)


def test_scannable_when_main_window_holds_foreground(screen):
    """這就是「遊戲中重啟」：主視窗在前臺，必須仍然可掃。"""
    win.add_own_window(MAIN)          # 真實路徑：MainWindow.showEvent 會這樣登記
    screen["fg"] = MAIN
    assert not win.is_foreground(GAME)  # 舊條件在此為 False —— 正是原本永遠 paused 的原因
    assert win.scannable(GAME)


def test_scannable_when_overlay_or_companion_holds_foreground(screen):
    win.exclude_from_capture(OVERLAY)      # 浮層：受 allow_capture 控制
    win.add_companion(OVERLAY)
    screen["fg"] = OVERLAY
    assert win.scannable(GAME)


def test_not_scannable_when_another_app_is_foreground(screen):
    """前臺是別的程式時仍然不掃：那時使用者正在看別的東西。"""
    win.add_own_window(MAIN)
    screen["fg"] = OTHER
    assert not win.scannable(GAME)


def test_main_window_is_capturable_when_setting_allows(screen):
    """回歸：使用者要截圖、錄影看得到助手介面，主視窗不能永遠排除在截圖外。

    以前 exclude_from_capture(always=True) 直接寫死 0x11，完全不理 allow_capture 設定，
    所以主視窗的資料頁（出裝、評級表）截圖和錄影都拍不到，只有手機拍屏看得到。"""
    applied = screen["applied"]

    win.set_capture_allowed(True)
    win.exclude_from_capture(MAIN, always=True)
    assert applied and applied[-1] == (MAIN, 0), f"主視窗應可截取，實際套用 {applied[-1:]}"

    # 使用者關掉設定：這時候才該排除
    win.set_capture_allowed(False)
    assert applied[-1] == (MAIN, 0x11), f"設定關閉時應排除，實際 {applied[-1:]}"

    # 再開回來
    win.set_capture_allowed(True)
    assert applied[-1] == (MAIN, 0), f"設定開啟時應恢復可截取，實際 {applied[-1:]}"


def test_scan_exclusion_hides_main_window_then_restores(screen):
    """讀螢幕期間主視窗要暫時排除（否則 OCR 讀到自己的介面），讀完立刻還原。"""
    applied = screen["applied"]

    win.set_capture_allowed(True)
    win.exclude_from_capture(MAIN, always=True)
    assert applied[-1] == (MAIN, 0)

    with win.hold_scan_exclusion():
        assert applied[-1] == (MAIN, 0x11), "掃描期間應暫時排除主視窗"
        # 巢狀呼叫不該提前還原
        with win.hold_scan_exclusion():
            pass
        assert applied[-1] == (MAIN, 0x11), "內層結束後仍應保持排除"

    assert applied[-1] == (MAIN, 0), "掃描結束後應立刻恢復可截取"

    # 浮層不受掃描影響：只有主視窗暫停顯示
    win.exclude_from_capture(OVERLAY, always=False)
    before = len(applied)
    with win.hold_scan_exclusion():
        assert all(hwnd == MAIN for hwnd, _ in applied[before:]), "掃描不應改動浮層"


def test_scan_exclusion_keeps_window_excluded_when_setting_off(screen):
    """設定關閉時，掃描結束不能把主視窗「還原」成可截取（那就是隱私洩漏）。"""
    applied = screen["applied"]

    win.set_capture_allowed(False)
    win.exclude_from_capture(MAIN, always=True)
    assert applied[-1] == (MAIN, 0x11)

    with win.hold_scan_exclusion():
        assert applied[-1] == (MAIN, 0x11)
    assert applied[-1] == (MAIN, 0x11), "設定關閉時掃描後仍須排除，不可變成 0"


def test_not_scannable_when_game_minimised(screen):
    win.add_own_window(MAIN)
    screen["fg"] = MAIN
    screen["iconic"].add(GAME)
    assert not win.scannable(GAME)


def test_not_scannable_without_a_game_window(screen):
    assert not win.scannable(0)


def test_mainwindow_show_registers_itself(monkeypatch):
    """MainWindow 真的會登記自己的 hwnd（不是靠測試假造集合）。"""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class FakeEngine:
        def __init__(self):
            self.store = SimpleNamespace(heroes={}, status=lambda: {})
            self.icons = None
            from lolhex.config import Settings
            self.settings = Settings.load()
            self.state = {"hero_id": None, "phase": None, "offer": None, "evaluation": None,
                          "vision": {}, "data": {}}

        def snapshot(self):
            return {"hero_id": None, "phase": None, "offer": None, "evaluation": None,
                    "vision": {}, "data": {}, "settings": {}}

        def hero_panel(self, _hid):
            return None

        def hero_brief(self, _hid):
            return {}

        def rescan(self):
            pass

        def set_hero(self, _hid):
            pass

    from lolhex.ui import mainwindow

    registered, excluded = [], []
    monkeypatch.setattr(mainwindow.win, "exclude_from_capture",
                        lambda hwnd, always=False: excluded.append((hwnd, always)))
    monkeypatch.setattr(mainwindow.win, "add_own_window", registered.append)
    mw = mainwindow.MainWindow(FakeEngine(), SimpleNamespace())
    mw.show()
    app.processEvents()
    hwnd = int(mw.winId())
    assert hwnd != 0
    assert registered and registered[-1] == hwnd   # 不是 0、也不是別人的 hwnd
    assert excluded and excluded[-1] == (hwnd, True)
    mw.close()
