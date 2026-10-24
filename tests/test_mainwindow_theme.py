import pytest

pytest.importorskip("PySide6")


def test_light_cards_keep_dark_text_in_dark_system_palette():
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout

    from lolhex.ui.mainwindow import _card

    qapp = QApplication.instance() or QApplication([])
    # 模擬 Windows 深色模式：視窗預設白字。卡片仍有自己的淺色底，文字必須可讀。
    palette = qapp.palette()
    palette.setColor(QPalette.Window, QColor("#20242c"))
    palette.setColor(QPalette.WindowText, QColor("#ffffff"))
    qapp.setPalette(palette)

    card = _card()
    label = QLabel("海克斯識別：掃描中")
    QVBoxLayout(card).addWidget(label)
    card.ensurePolished()
    label.ensurePolished()
    qapp.processEvents()

    assert label.palette().color(QPalette.WindowText).lightness() < 128
