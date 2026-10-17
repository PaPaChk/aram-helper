"""游戏内浮窗：点完把焦点还给游戏，展开后鼠标离开一段时间自动收起（无界面模式运行）。"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QPoint  # noqa: E402


class FakeEngine:
    def __init__(self):
        self.store = SimpleNamespace(heroes={})
        self.settings = SimpleNamespace(nas_url="")
        self.icons = None
        self.picked = []

    def hero_panel(self, _hid):
        return None

    def hero_brief(self, _hid):
        return {}

    def set_hero(self, hid):
        self.picked.append(hid)

    def rescan(self):
        pass


@pytest.fixture
def panel(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from lolhex.ui import overlay
    focused, clock, cursor = [], [1000.0], [QPoint(-500, -500)]
    monkeypatch.setattr(overlay.win, "give_focus", focused.append)
    monkeypatch.setattr(overlay.win, "exclude_from_capture", lambda _h: None)
    monkeypatch.setattr(overlay.win, "add_companion", lambda _h: None)
    monkeypatch.setattr(overlay.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(overlay.QCursor, "pos", staticmethod(lambda: cursor[0]))
    p = overlay.ControlPanel(FakeEngine())
    p.target_hwnd = 4242
    p.show()
    yield SimpleNamespace(p=p, app=app, focused=focused, clock=clock, cursor=cursor, overlay=overlay)
    p.close()


def _wait(t, s):
    t.clock[0] += s


def test_click_gives_focus_back_to_game(panel):
    panel.p.btn.click()
    panel.app.processEvents()
    assert panel.p.expanded
    assert panel.focused == [4242]


def test_manual_open_hides_after_mouse_away(panel):
    p = panel.p
    p.btn.click()
    p.auto_hide("ingame")              # 开始计时
    _wait(panel, panel.overlay.AUTO_HIDE_SECONDS - 1)
    p.auto_hide("ingame")
    assert p.expanded
    _wait(panel, 1)
    p.auto_hide("ingame")
    assert not p.expanded


def test_hover_resets_timer(panel):
    p = panel.p
    p.btn.click()
    p.auto_hide("ingame")
    _wait(panel, panel.overlay.AUTO_HIDE_SECONDS - 1)
    panel.cursor[0] = p.frameGeometry().center()
    p.auto_hide("ingame")              # 鼠标在浮窗上：不收
    panel.cursor[0] = QPoint(-500, -500)
    p.auto_hide("ingame")              # 离开：重新开始计时（实际每 250ms 检查一次）
    _wait(panel, panel.overlay.AUTO_HIDE_SECONDS - 1)
    p.auto_hide("ingame")
    assert p.expanded                  # 离开后重新计时
    _wait(panel, 2)
    p.auto_hide("ingame")
    assert not p.expanded


def test_champ_select_auto_open_waits_for_hover(panel):
    p = panel.p
    p.update_from({"hero_id": "1", "phase": "client"})
    assert p.expanded and p._auto_opened
    for _ in range(3):
        _wait(panel, panel.overlay.AUTO_HIDE_SECONDS)
        p.auto_hide("client")
    assert p.expanded                  # 没碰过就一直开着，方便看胜率
    panel.cursor[0] = p.frameGeometry().center()
    p.auto_hide("client")
    panel.cursor[0] = QPoint(-500, -500)
    p.auto_hide("client")
    _wait(panel, panel.overlay.AUTO_HIDE_SECONDS)
    p.auto_hide("client")
    assert not p.expanded


def test_champ_select_auto_open_hides_in_game(panel):
    p = panel.p
    p.update_from({"hero_id": "1", "phase": "client"})
    p.auto_hide("ingame")
    _wait(panel, panel.overlay.AUTO_HIDE_SECONDS)
    p.auto_hide("ingame")
    assert not p.expanded


def test_search_pick_and_escape_give_focus_back(panel):
    p = panel.p
    p.btn.click()
    panel.app.processEvents()
    panel.focused.clear()
    p.search.setText("提莫")
    p._search_pick()
    panel.app.processEvents()
    assert p.engine.picked == ["提莫"] and panel.focused == [4242]
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    p.search.setText("abc")
    QtWidgets.QApplication.sendEvent(p.search, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    panel.app.processEvents()
    assert p.search.text() == "" and panel.focused == [4242, 4242]
