"""手動選英雄的搜尋補全：名字、稱號之外，別名和拼音縮寫也能搜到（提百萬、快樂風男、tm）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter


def hero_completer(store, parent=None) -> tuple[QCompleter, dict[str, str]]:
    """返回補全器和 {補全文字: 英雄 id}。下拉里顯示"提莫 迅捷斥候（提百萬）"，
    按包含關係匹配名字、稱號、中文別名和英文/拼音關鍵詞。"""
    rows, names = [], {}
    for hid, h in store.heroes.items():
        base = f"{h['name']} {h['nick']}"
        extra = [t for t in store.hero_terms(hid) if t.lower() not in base.lower()]
        cn = [t for t in extra if not t.isascii()]
        key = " ".join([base, *extra])
        names[key] = hid
        rows.append((base + (f"（{'、'.join(cn)}）" if cn else ""), key))
    comp = QCompleter(parent)
    model = QStandardItemModel(comp)  # 掛在補全器上，免得函式返回後被回收
    for display, key in sorted(rows):
        item = QStandardItem(display)
        item.setData(key, Qt.UserRole)
        model.appendRow(item)
    comp.setModel(model)
    comp.setCompletionRole(Qt.UserRole)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setFilterMode(Qt.MatchContains)
    return comp, names
