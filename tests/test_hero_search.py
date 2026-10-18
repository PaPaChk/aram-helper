"""手動搜英雄：別名、玩家叫法、拼音縮寫都能搜到。"""
import os

import pytest


def test_resolve_hero_by_alias(store):
    assert store.resolve_hero("提百萬") == "17"      # 玩家叫法（Hexdata）
    assert store.resolve_hero("快樂風男") == "157"
    assert store.resolve_hero("tm") == "17"          # 騰訊關鍵詞裡的拼音縮寫
    assert store.resolve_hero("火女") == "1"
    assert store.resolve_hero("託兒所") == "157"     # 網上常見外號（hero_nicknames.json）
    assert store.resolve_hero("蘑菇") == "17"
    assert store.resolve_hero("龍王") == "136"
    assert store.resolve_hero("快樂風") == "157"     # 外號的一部分
    assert store.resolve_hero("提莫") == "17"        # 原有的名字照舊
    assert store.resolve_hero("不存在的英雄") is None


def test_completer_matches_aliases(store):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from lolhex.ui.herosearch import hero_completer
    app = QApplication.instance() or QApplication([])
    comp, names = hero_completer(store)

    def hits(prefix):
        comp.setCompletionPrefix(prefix)
        m = comp.completionModel()
        return [names[m.index(i, 0).data(Qt.UserRole)] for i in range(m.rowCount())]

    assert "17" in hits("提百萬")
    assert "157" in hits("快樂風男")
    assert "17" in hits("xjch")
    assert "157" in hits("託兒所")
    assert hits("提莫") == ["17"]
    m = comp.completionModel()
    comp.setCompletionPrefix("提百萬")
    assert m.index(0, 0).data().startswith("提摩 迅捷斥候（")  # 下拉里顯示的文字
    assert app is not None
