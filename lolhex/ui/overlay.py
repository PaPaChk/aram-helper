"""遊戲內懸浮層（PySide6）。

- 小按鈕：常駐遊戲視窗右上角，點一下展開/收起詳情（英雄、推薦出裝、加點、識別狀態）。
  點完按鈕、候選或連結後把焦點還給遊戲，免得空格等按鍵落在浮窗上；展開後滑鼠離開
  AUTO_HIDE_SECONDS 秒自動收起（正在搜尋框裡打字時不收）。
- 卡片標籤：識別到三選一時，在每張卡的標題下方顯示「首選 / 可選 / 可考慮重新整理」與依據。
  標籤層對滑鼠完全透明，不擋遊戲點選；所有懸浮窗都設定為不被截圖，避免識別到自己。
只有無邊框/視窗化模式下懸浮層才能蓋在遊戲上面。
"""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..vision import window as win
from .. import patch
from . import buildview, single_instance
from .autoshot import AutoShot

from .data_status import data_status_html
from .herosearch import hero_completer

log = logging.getLogger(__name__)

RARITY_CN = {"silver": "白銀", "gold": "黃金", "prismatic": "稜彩"}
VERDICT = {"best": ("首選", QColor(95, 211, 141)), "ok": ("可選", QColor(98, 168, 255)),
           "reroll": ("可考慮重新整理", QColor(255, 122, 107)), "unknown": ("未知", QColor(150, 150, 150))}


AUTO_HIDE_SECONDS = 5

# 浮窗詳情的分區（依顯示順序）：(代號, 標題, 預設是否展開)。每個分區可獨立折疊，
# 折疊狀態存在 ControlPanel.folds 裡，update_from 每 250ms 重畫也不會被重設。
SECTIONS = (
    ("adjust", "大亂鬥調整", True),
    ("augments", "推薦海克斯", True),
    ("combos", "海克斯組合", True),
    ("skills", "加點順序", True),
    ("start", "出門裝", True),
    ("shoes", "鞋子", True),
    ("core", "核心三件", True),
    ("full", "其他完成裝", True),
)

# buildview.lines() 每一行都以 <b>標題</b> 開頭；用開頭的標題把清單分到各分區。
# 沒有對應分區的行（召喚師技能、資料來源）歸入「其他」。
_LINE_MARKERS = {"大亂鬥調整": "adjust", "核心三件": "core", "鞋子": "shoes",
                 "出門裝": "start", "其他完成裝": "full"}

# 分區沒有資料時顯示這句，而不是留一片空白讓人以為壞掉
_NO_DATA = "<span style='color:#8b93a7'>暫無資料</span>"
_NO_COMBOS = "<span style='color:#8b93a7'>暫無組合資料</span>"


def _strip_marker(html: str) -> str:
    """去掉行首的 <b>標題</b> 和緊跟的全角空白：標題已經顯示在分區的標題按鈕上。"""
    if not html.startswith("<b>"):
        return html
    end = html.find("</b>")
    if end < 0:
        return html
    return html[end + 4:].lstrip("　 ")


def _split_build_lines(lines) -> dict:
    """把 buildview.lines() 的 HTML 片段清單按開頭標題分組：{分區代號: [片段, ...]}。

    buildview 先輸出一行粗體標題，再把細項緊接在後面（細項本身沒有標題），
    所以沒有標題的行沿用上一個標題所屬的分區。"""
    out: dict[str, list[str]] = {}
    current = "misc"
    for ln in lines or []:
        if "<b>" in ln:
            head = ln.split("<b>", 1)[1].split("</b>", 1)[0].strip()
            current = _LINE_MARKERS.get(head, "misc")
            # 標題行去掉重複的粗體標題，其餘行原樣保留
            if current != "misc":
                ln = _strip_marker(ln)
        if ln:
            out.setdefault(current, []).append(ln)
    return out


def _dpr() -> float:
    s = QGuiApplication.primaryScreen()
    return s.devicePixelRatio() if s else 1.0


def _logical(x: float) -> int:
    return int(round(x / _dpr()))


def _flags(widget: QWidget, click_through: bool) -> None:
    f = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    if click_through:
        f |= Qt.WindowTransparentForInput
    widget.setWindowFlags(f)
    widget.setAttribute(Qt.WA_TranslucentBackground)
    widget.setAttribute(Qt.WA_ShowWithoutActivating)


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


class BadgeLayer(QWidget):
    """覆蓋遊戲客戶區的透明層，只畫三張卡的標籤。"""

    def __init__(self):
        super().__init__()
        _flags(self, click_through=True)
        self.snapshot: dict = {}
        self.origin = QPoint(0, 0)

    def showEvent(self, e):
        win.exclude_from_capture(int(self.winId()))
        super().showEvent(e)

    def update_from(self, snap: dict, rect) -> None:
        self.snapshot = snap
        ev, offer = snap.get("evaluation"), snap.get("offer")
        if not ev or not offer or rect is None:
            self.hide()
            return
        geo = QRect(_logical(rect.left), _logical(rect.top), _logical(rect.width), _logical(rect.height))
        if self.geometry() != geo:
            self.setGeometry(geo)
        self.origin = QPoint(rect.left, rect.top)
        if not self.isVisible():
            self.show()
        self.update()

    def paintEvent(self, _):
        snap = self.snapshot
        ev, offer = snap.get("evaluation"), snap.get("offer")
        if not ev or not offer:
            return
        show_win = snap.get("settings", {}).get("show_winrate", True)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dpr = _dpr()
        f_big = QFont("Microsoft YaHei UI", 12, QFont.Bold)
        f_small = QFont("Microsoft YaHei UI", 9)
        boxes = offer.get("boxes") or []
        known = [b for b in boxes if b]
        for r in ev["slots"]:
            i = r["index"]
            box = boxes[i] if i < len(boxes) else None
            if box is None and len(known) >= 2:
                continue
            if box is None:
                continue
            x0 = (box[0] - self.origin.x()) / dpr
            x1 = (box[2] - self.origin.x()) / dpr
            y0 = (box[1] - self.origin.y()) / dpr
            w = max(170.0, x1 - x0)
            cx = (x0 + x1) / 2
            label, color = VERDICT.get(r["verdict"], VERDICT["unknown"])
            if r.get("thin") == "too_few":
                label = "樣本太少 · 建議重新整理"
            lines = []
            if r.get("score") is not None:
                s = f"{r['score']:+.1f}"
                if show_win and r.get("win") is not None:
                    s += f" · 勝率{_pct(r['win'])}"
                lines.append(s)
            meta = []
            if r.get("rarity") and r.get("rank"):
                metric = "勝率" if r.get("rank_basis") == "hero_rarity_win_rate" else ""
                meta.append(f"{RARITY_CN.get(r['rarity'], '')}{metric}第{r['rank']}/{r.get('rank_total') or '?'}")
            if r.get("tier"):
                meta.append(f"{r['tier']}級")
            if r.get("basis") == "tier_only":
                meta.append("按官方層級")
            if r.get("thin") == "few":
                meta.insert(0, "樣本偏少")
            if meta:
                lines.append(" · ".join(meta))
            h = 30 + 18 * len(lines)
            # 放在標題正上方（壓在海克斯圖示下半部分）：不擋名字、描述和下方的重新整理按鈕
            rect = QRect(int(cx - w / 2), int(y0 - 4 - h), int(w), int(h))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(10, 12, 16, 215))
            p.drawRoundedRect(rect, 6, 6)
            p.setPen(QPen(color, 2 if r["verdict"] == "best" else 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
            p.setFont(f_big)
            p.setPen(color)
            p.drawText(QRect(rect.x(), rect.y() + 4, rect.width(), 24), Qt.AlignHCenter, label)
            p.setFont(f_small)
            p.setPen(QColor(225, 228, 235))
            for k, ln in enumerate(lines):
                p.drawText(QRect(rect.x() + 4, rect.y() + 28 + 18 * k, rect.width() - 8, 18), Qt.AlignHCenter, ln)
        p.end()


GRADE_COLOR = {"S": QColor(240, 200, 90), "A": QColor(95, 211, 141), "B": QColor(98, 168, 255),
               "C": QColor(200, 204, 214), "D": QColor(255, 122, 107)}


def win_color(win) -> QColor:
    if win is None:
        return QColor(150, 150, 150)
    if win >= 0.53:
        return QColor(95, 211, 141)
    if win >= 0.50:
        return QColor(98, 168, 255)
    if win >= 0.48:
        return QColor(225, 228, 235)
    return QColor(255, 122, 107)


def champ_select_summary(cs: dict, show_win: bool = True) -> str:
    """浮窗/主介面用的一行彙總：待選欄按勝率排序，和自己當前英雄比較。"""
    mine = next((t for t in cs.get("team") or [] if t["hero_id"] == cs.get("mine")), None)
    my_win = (mine or {}).get("win")
    bench = sorted(cs.get("bench") or [], key=lambda b: -(b.get("win") or 0))
    items = []
    for b in bench:
        txt = f"{b.get('name') or b['hero_id']} {b.get('grade') or ''}"
        if show_win and b.get("win") is not None:
            txt += f" {_pct(b['win'])}"
        if my_win is not None and b.get("win") is not None and b["win"] > my_win:
            txt = f"<b style='color:#5fd38d'>{txt} ↑{(b['win'] - my_win) * 100:.1f}</b>"
        items.append(txt)
    if cs.get("cards"):
        cards = sorted(cs["cards"], key=lambda c: -(c.get("win") or 0))
        return "開局選英雄：" + "、".join(
            f"{c.get('name') or c['hero_id']} {c.get('grade') or ''}{' ' + _pct(c.get('win')) if show_win else ''}"
            for c in cards)
    head = "待選欄"
    if mine:
        head += f"（你：{mine.get('name')} {mine.get('grade') or ''}{' ' + _pct(my_win) if show_win else ''}）"
    return f"{head}：" + "、".join(items)


class ChampSelectLayer(QWidget):
    """選英雄介面：在預選欄和我方每個英雄頭像旁標評級（國服排名換算 S–D）與勝率；
    預選欄裡勝率比自己當前英雄高的標綠，最高的那個加金框（值得換）。
    覆蓋客戶端視窗，對滑鼠完全透明，不擋點選。"""

    def __init__(self):
        super().__init__()
        _flags(self, click_through=True)
        self.cs: dict | None = None
        self.origin = QPoint(0, 0)
        self.show_win = True

    def showEvent(self, e):
        win.exclude_from_capture(int(self.winId()))
        super().showEvent(e)

    def update_from(self, snap: dict, rect) -> None:
        cs = snap.get("champ_select")
        if not cs or rect is None:
            self.cs = None
            self.hide()
            return
        self.show_win = snap.get("settings", {}).get("show_winrate", True)
        geo = QRect(_logical(rect.left), _logical(rect.top), _logical(rect.width), _logical(rect.height))
        if self.geometry() != geo:
            self.setGeometry(geo)
        self.origin = QPoint(rect.left, rect.top)
        if cs != self.cs:
            self.cs = cs
            self.update()
        if not self.isVisible():
            self.show()

    def paintEvent(self, _):
        cs = self.cs
        if not cs:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        dpr = _dpr()
        bench = cs.get("bench") or []
        mine = next((t for t in cs.get("team") or [] if t["hero_id"] == cs.get("mine")), None)
        my_win = (mine or {}).get("win")
        better = [b for b in bench if b.get("win") is not None and my_win is not None and b["win"] > my_win]
        best = max(better, key=lambda b: b["win"]) if better else None
        # 開局英雄卡：勝率最高的那張加金框
        cards = [c for c in cs.get("cards") or [] if c.get("win") is not None]
        best_card = max(cards, key=lambda c: c["win"]) if len(cards) >= 2 else None
        ox, oy = self.origin.x(), self.origin.y()
        for kind in ("cards", "bench", "team"):
            for s in cs.get(kind) or []:
                x0, y0, x1, y1 = ((s["box"][0] - ox) / dpr, (s["box"][1] - oy) / dpr,
                                  (s["box"][2] - ox) / dpr, (s["box"][3] - oy) / dpr)
                pw = x1 - x0
                # 字號跟頭像大小走：不同解析度、縮放比例、客戶端尺寸下比例一致
                px = max(9, int(pw * {"bench": 0.24, "team": 0.21, "cards": 0.1}[kind]))
                big = QFont("Microsoft YaHei UI")
                big.setPixelSize(px)
                big.setBold(True)
                small = QFont("Microsoft YaHei UI")
                small.setPixelSize(max(9, int(px * 0.85)))
                win = s.get("win")
                win_txt = _pct(win) if self.show_win else ""
                grade = s.get("grade") or ""
                if kind == "bench":
                    color = QColor(95, 211, 141) if s in better else QColor(215, 218, 226)
                    r = QRect(int(x0 - 4), int(y1 + 2), int(pw + 8), int(px * 1.45))
                elif kind == "cards":  # 卡片正下方
                    color = win_color(win)
                    r = QRect(int(x0 + pw * 0.07), int(y1 + 6), int(pw * 0.86), int(px * 3.0))
                else:
                    color = win_color(win)
                    r = QRect(int(x1 + pw * 1.9), int((y0 + y1) / 2 - px * 1.5), int(pw * 1.2), int(px * 3.0))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(10, 12, 16, 225))
                p.drawRoundedRect(r, 4, 4)
                if s is best or s is best_card:
                    gold = QPen(QColor(240, 200, 90), 2)
                    p.setPen(gold)
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
                    p.drawRect(QRect(int(x0) - 2, int(y0) - 2, int(pw) + 4, int(y1 - y0) + 4))
                line = QRect(r.x(), r.y() + (int(px * 0.15) if kind != "bench" else 0), r.width(), int(px * 1.45))
                # 第一行：評級字母（按評級著色）+ 勝率
                fm_w = QFontMetrics(big)
                gap = fm_w.horizontalAdvance(" ")
                tw = fm_w.horizontalAdvance(grade) + (gap if grade and win_txt else 0) + fm_w.horizontalAdvance(win_txt)
                x = line.x() + (line.width() - tw) / 2
                p.setFont(big)
                if grade:
                    p.setPen(GRADE_COLOR.get(grade, QColor(200, 200, 200)))
                    p.drawText(QRect(int(x), line.y(), fm_w.horizontalAdvance(grade) + 2, line.height()),
                               Qt.AlignVCenter | Qt.AlignLeft, grade)
                    x += fm_w.horizontalAdvance(grade) + gap
                if win_txt:
                    p.setPen(color)
                    p.drawText(QRect(int(x), line.y(), fm_w.horizontalAdvance(win_txt) + 2, line.height()),
                               Qt.AlignVCenter | Qt.AlignLeft, win_txt)
                if kind == "team":
                    is_me = s["hero_id"] == cs.get("mine")
                    sub = f"第{s['rank']}/{s.get('total') or '?'}" if s.get("rank") else ""
                    p.setFont(small)
                    p.setPen(QColor(240, 200, 90) if is_me else QColor(170, 176, 190))
                    p.drawText(QRect(r.x(), line.bottom(), r.width(), r.bottom() - line.bottom()),
                               Qt.AlignHCenter | Qt.AlignTop, ("我 · " if is_me else "") + sub)
                elif kind == "cards":
                    sub = f"勝率第{s['rank']}/{s.get('total') or '?'}" if s.get("rank") else ""
                    p.setFont(small)
                    p.setPen(QColor(240, 200, 90) if s is best_card else QColor(170, 176, 190))
                    p.drawText(QRect(r.x(), line.bottom(), r.width(), r.bottom() - line.bottom()),
                               Qt.AlignHCenter | Qt.AlignTop, "★ 推薦" if s is best_card else sub)
        p.end()


class ControlPanel(QWidget):
    """右上角的小按鈕 + 可展開詳情。選英雄階段跟隨客戶端視窗，進遊戲後跟隨遊戲視窗。"""

    STYLE_BODY = ("QWidget#body{background:#101318ee;border:1px solid #2c3240;border-radius:8px}"
                  "QLabel{color:#e6e8ee;font:12px 'Microsoft YaHei UI'}"
                  "QLineEdit{background:#0c0e12;color:#e6e8ee;border:1px solid #2c3240;border-radius:4px;padding:3px 6px}"
                  "QPushButton{background:#1b2130;color:#e6e8ee;border:1px solid #2c3240;border-radius:4px;padding:2px 8px}"
                  "QPushButton:hover{border-color:#62a8ff}"
                  "QToolButton{background:transparent;color:#e7c35a;border:none;text-align:left;"
                  "font:12px 'Microsoft YaHei UI';padding:1px 0}"
                  "QToolButton:hover{color:#62a8ff}")

    def __init__(self, engine, corner: str = "top-right"):
        super().__init__()
        # 面板需要能輸入（搜英雄），所以不設 WindowDoesNotAcceptFocus
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.engine = engine
        self.corner = corner
        self.expanded = False
        self.target_hwnd = 0      # 遊戲視窗（進遊戲後）或客戶端視窗，點完浮窗把焦點還給它
        self._away_since = None   # 展開後滑鼠離開浮窗的時刻
        self._hovered = False     # 這次展開後滑鼠是否進過浮窗
        self._auto_opened = False
        self._auto_opened_for = None
        self._names = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        from .mainwindow import app_icon
        self.btn = QPushButton()
        self.btn.setIcon(app_icon())
        self.btn.setIconSize(QSize(30, 30))
        self.btn.setToolTip("海克斯大亂鬥助手：點選展開/收起")
        self.btn.setFixedSize(40, 40)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setStyleSheet("QPushButton{background:#171a21ee;color:#e7c35a;border:1px solid #3a4150;"
                               "border-radius:20px}"
                               "QPushButton:hover{border-color:#62a8ff}")
        self.btn.clicked.connect(self._click_toggle)

        self.body = QWidget()
        self.body.setObjectName("body")
        self.body.setAttribute(Qt.WA_StyledBackground)
        self.body.setStyleSheet(self.STYLE_BODY)
        self.body.setFixedWidth(360)
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(6)
        # 英雄：識別結果 / 候選 / 搜尋手動選
        self.hero_label = QLabel()
        self.hero_label.setTextFormat(Qt.RichText)
        self.hero_label.setWordWrap(True)
        # 會換行的 QLabel 高度隨寬度變動，但外層垂直佈局預設不採計 heightForWidth，
        # 於是標題只分到一行的高度、第二行壓到下面的搜尋框。明確要求它回報最小高度。
        self.hero_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.hero_label.setMinimumHeight(1)
        self.cands = QHBoxLayout()
        self.cands.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜英雄手動選擇：提莫 / 提百萬 / tm")
        self._completer_ready = False
        self.search.returnPressed.connect(self._search_pick)
        self.search.installEventFilter(self)
        bl.addWidget(self.hero_label)
        bl.addLayout(self.cands)
        bl.addWidget(self.search)
        # 七個可折疊分區：標題按鈕 + 摺頁內容。折疊狀態存在 self.folds，update_from 不會重設。
        self.folds = {key: expanded for key, _title, expanded in SECTIONS}
        self.sections: dict[str, dict] = {}
        for key, title, expanded in SECTIONS:
            head = QToolButton()
            head.setProperty("title", title)
            head.setCheckable(True)
            head.setChecked(expanded)
            head.setAutoRaise(True)
            head.setCursor(Qt.PointingHandCursor)
            head.setToolButtonStyle(Qt.ToolButtonTextOnly)
            head.toggled.connect(lambda on, k=key: self._fold(k, on))
            body = QLabel()
            body.setTextFormat(Qt.RichText)
            body.setWordWrap(True)
            body.setOpenExternalLinks(False)
            body.setContentsMargins(8, 0, 0, 0)
            body.linkActivated.connect(self._link)
            # QToolButton 不理 QSS 的 text-align，文字會置中。用外層橫列把按鈕靠左收緊，
            # 標題才會貼齊左邊界（跟內容一致）。
            head.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            row.addWidget(head, 0, Qt.AlignLeft)
            row.addStretch(1)
            bl.addLayout(row)
            bl.addWidget(body)
            self.sections[key] = {"head": head, "body": body}
            self._fold(key, expanded)
        # 分區以外的即時資訊（選英雄彙總、提醒、資料狀態、連結、沒有對應分區的出裝行）
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.info.setWordWrap(True)
        self.info.setOpenExternalLinks(False)
        self.info.linkActivated.connect(self._link)
        bl.addWidget(self.info)
        self.body.hide()
        lay.addWidget(self.btn, 0, Qt.AlignRight)
        lay.addWidget(self.body)
        self._cand_ids = []

    def showEvent(self, e):
        win.exclude_from_capture(int(self.winId()))
        win.add_companion(int(self.winId()))  # 點浮窗不算離開客戶端，標註照常顯示
        super().showEvent(e)

    def toggle(self):
        self.expanded = not self.expanded
        self.body.setVisible(self.expanded)
        self._away_since, self._hovered, self._auto_opened = None, False, False
        self.adjustSize()

    def _fold(self, key: str, on: bool) -> None:
        """折疊/展開一個分區。狀態記在 self.folds，跨 update_from 保留。"""
        self.folds[key] = bool(on)
        sec = self.sections.get(key)
        if not sec:
            return
        sec["body"].setVisible(bool(on))
        sec["head"].setChecked(bool(on))
        sec["head"].setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        sec["head"].setText(("▾ " if on else "▸ ") + sec["head"].property("title"))
        self.adjustSize()

    @staticmethod
    def _body_html(parts) -> str:
        return "<br>".join(p for p in (parts or []) if p)

    def _set_section(self, key: str, parts, placeholder: str = "") -> None:
        """更新分區內容。parts 為空時用 placeholder 說明「沒有資料」，不留空白一片。"""
        sec = self.sections[key]
        placeholder = placeholder or _NO_DATA
        html = self._body_html(parts) or placeholder
        body = sec["body"]
        if body.text() != html:
            body.setText(html)
            # 會換行的 QLabel 高度隨寬度變動，外層垂直佈局預設不採計 heightForWidth，
            # 摺頁只會分到一行的高度，之後的內容被裁掉（看起來像「分區是空的，只剩標題」）。
            # 這裡自己把需要的高度算給佈局。
            need = body.heightForWidth(max(1, body.width() or 340))
            if need > 0:
                body.setMinimumHeight(need)
        body.setVisible(bool(html) and self.folds[key])

    def _click_toggle(self):
        self.toggle()
        self.give_back_focus()

    def give_back_focus(self):
        # 等這次點選處理完再還焦點，否則 Windows 會在點選結束時又把浮窗啟用
        QTimer.singleShot(0, lambda: win.give_focus(self.target_hwnd))

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.search.clear()
            self.give_back_focus()
            return True
        return super().eventFilter(obj, ev)

    def _typing(self) -> bool:
        return self.search.hasFocus() and self.isActiveWindow()

    def auto_hide(self, phase) -> None:
        """展開後滑鼠離開一段時間就收起。選英雄階段自動展開的，滑鼠進來過或進了遊戲才開始計時。"""
        if not self.expanded or not self.isVisible():
            return
        if self.frameGeometry().contains(QCursor.pos()):
            self._hovered, self._away_since = True, None
            return
        if self._typing() or (self._auto_opened and not self._hovered and phase == "client"):
            self._away_since = None
            return
        now = time.monotonic()
        if self._away_since is None:
            self._away_since = now
        elif now - self._away_since >= AUTO_HIDE_SECONDS:
            self.toggle()

    def _ensure_completer(self):
        heroes = self.engine.store.heroes
        if self._completer_ready or not heroes:
            return
        comp, self._names = hero_completer(self.engine.store, self)
        comp.activated.connect(self._completer_pick)
        self.search.setCompleter(comp)
        self._completer_ready = True

    def _completer_pick(self, text):
        hid = self._names.get(text)
        if hid:
            self.engine.set_hero(hid)
            self.search.clear()
            self.give_back_focus()

    def _search_pick(self):
        t = self.search.text().strip()
        if t:
            self.engine.set_hero(self._names.get(t, t))
            self.search.clear()
        self.give_back_focus()

    def _link(self, href):
        if href == "rescan":
            self.engine.rescan()
            self._flash("已重新識別")
            self.give_back_focus()
        elif href == "hardreset":
            # 「重新識別」按不動時（校準卡在錯的位置）用這個：整個識別狀態回到乾淨
            self.engine.hard_reset()
            self._flash("已重設識別，重新找卡片位置")
            self.give_back_focus()
        elif href == "quit":
            self.engine.stop()
            QApplication.quit()

    def _flash(self, text: str) -> None:
        """在浮窗的即時資訊區顯示一句結果，讓使用者知道按了有效（幾秒後自動恢復）。"""
        self._flash_until = time.monotonic() + 4.0
        self._flash_text = text
        self.info.setText(f"<span style='color:#5fd38d'>{text}</span>")
        self.adjustSize()

    def place(self, rect) -> None:
        self.adjustSize()
        if rect is not None:
            left, top, right = _logical(rect.left), _logical(rect.top), _logical(rect.right)
        else:
            g = QGuiApplication.primaryScreen().availableGeometry()
            left, top, right = g.left(), g.top(), g.right()
        x = right - self.width() - 12 if self.corner == "top-right" else left + 12
        self.move(x, top + 90)

    def _set_candidates(self, cands):
        ids = [c.get("id") for c in cands]
        if ids == self._cand_ids:
            return
        self._cand_ids = ids
        while self.cands.count():
            w = self.cands.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in cands[:5]:
            b = QPushButton(c.get("name") or c.get("id"))
            b.clicked.connect(lambda _=False, hid=c.get("id"): (self.engine.set_hero(hid), self.give_back_focus()))
            self.cands.addWidget(b)
        self.cands.addStretch(1)

    def update_from(self, snap: dict) -> None:
        # 選英雄階段識別到新英雄時自動展開一次，方便看勝率、出裝、加點
        hid = snap.get("hero_id")
        if hid and snap.get("phase") == "client" and self._auto_opened_for != hid:
            self._auto_opened_for = hid
            if not self.expanded:
                self.toggle()
                self._auto_opened = True
        if not self.expanded:
            return
        self._ensure_completer()
        show_win = snap.get("settings", {}).get("show_winrate", True)
        h = snap.get("hero")
        d = self.engine.hero_panel(hid) if hid else None
        if h:
            r = (d or {}).get("rank") or {}
            b = self.engine.hero_brief(hid)
            rating = []
            if b.get("grade"):
                rating.append(f"評級 {b['grade']}")
            if b.get("rank"):
                rating.append(f"勝率第{b['rank']}/{b.get('total') or '?'}")
            if show_win and r.get("win") is not None:
                rating.append(f"勝率 {_pct(r['win'])}")
            if r.get("pick") is not None:
                rating.append(f"出場 {_pct(r['pick'])}")
            hero_html = (f"<b style='color:#e7c35a;font-size:14px'>{h.get('name') or hid}</b> "
                         f"{h.get('nick') or ''}<br>{' · '.join(rating)}")
        else:
            hero_html = "<span style='color:#8b93a7'>未識別英雄</span>"
        if self.hero_label.text() != hero_html:
            self.hero_label.setText(hero_html)
            # 換行後的實際高度要自己算給佈局，否則第二行會壓到下一個控件。
            need = self.hero_label.heightForWidth(max(1, self.hero_label.width() or 340))
            if need > 0:
                self.hero_label.setMinimumHeight(need)
        self._set_candidates(snap.get("candidates") or [])

        # 先依 buildview 的輸出把出裝分到各分區
        groups: dict[str, list[str]] = {}
        skills = None
        augments = []
        if d:
            groups = _split_build_lines(buildview.lines(d, self.engine.icons, show_win, size=22, compact=True))
            skills = buildview.skills_line(d, show_win)
            augments = [a for a in d.get("augments", []) if a.get("delta") is not None and a.get("sample") != "low"]
            augments.sort(key=lambda a: -a["delta"])

        parts = []
        cs = snap.get("champ_select")
        if cs and (cs.get("bench") or cs.get("cards")):
            parts.append(champ_select_summary(cs, show_win))
        ev = snap.get("evaluation")
        if ev:
            parts.append(f"<b>{ev['advice']}</b>")
        # 沒有對應分區的出裝行（召喚師技能、資料來源）留在分區之外
        parts.extend(groups.get("misc") or [])
        if snap.get("vision", {}).get("blank"):
            parts.append("<span style='color:#ff7a6b'>截圖全黑，請把遊戲改成無邊框</span>")
        parts.append(f"<span style='color:#8b93a7'>{data_status_html(snap.get('data', {}))}</span>")
        parts.append("<a href='rescan' style='color:#62a8ff'>重新識別</a>　"
                     "<a href='hardreset' style='color:#e7c35a'>重設識別</a>　"
                     "<a href='quit' style='color:#ff7a6b'>退出助手</a>")
        html = "<br>".join(parts)
        # 按鈕回饋：顯示幾秒後恢復正常內容
        if getattr(self, "_flash_until", 0) > time.monotonic():
            html = f"<span style='color:#5fd38d'>{self._flash_text}</span><br>{html}"
        if self.info.text() != html:
            self.info.setText(html)

        for key in ("adjust", "core", "shoes", "start", "full"):
            self._set_section(key, groups.get(key) or [])
        self._set_section("skills", [_strip_marker(skills)] if skills else [])
        self._set_section("augments", ["、".join(f"{a['name']}({a['delta']:+.1f})" for a in augments[:5])]
                          if augments else [])
        # 還沒有組合資料：標題照顯示，內容給佔位提示，不編造
        self._set_section("combos", [], _NO_COMBOS)
        self.adjustSize()


class Overlay:
    def __init__(self, engine):
        self.engine = engine
        self.badges = BadgeLayer()
        self.champ = ChampSelectLayer()
        self.panel = ControlPanel(engine, engine.settings.overlay_corner)
        self.panel.show()
        self.autoshot = AutoShot(engine)  # 設定裡開了自動截圖時，三選一和選英雄時自動截整屏
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)

    def set_visible(self, on: bool):
        self.visible = on
        if on:
            self.panel.show()
        else:
            self.panel.hide()
            self.badges.hide()
            self.champ.hide()

    def _tick(self):
        if not getattr(self, "visible", True):
            return
        snap = self.engine.snapshot()
        if snap.get("vision", {}).get("blank") and not getattr(self, "_blank_warned", False):
            self._blank_warned = True  # 每次開啟軟體最多提醒一次
            notify = getattr(self, "notify", None)
            if notify:
                notify("截圖是黑的：遊戲可能是全屏模式。請在遊戲設定 → 影片裡，把視窗模式改成「無邊框」。")
        game = win.find_game_window()
        grect = win.client_rect(game) if game else None
        self.badges.update_from(snap, grect)
        client = None if grect else win.find_client_window()
        crect = win.client_rect(client) if client else None
        # 標註層置頂：客戶端不在前臺（切到別的視窗）時隱藏，免得蓋在別的程式上
        self.champ.update_from(snap, crect if crect and win.is_foreground(client) else None)
        self.autoshot.tick(snap, grect, crect if crect and win.is_foreground(client) else None)
        self.panel.target_hwnd = game or client or 0
        self.panel.update_from(snap)
        self.panel.auto_hide(snap.get("phase"))
        # 選英雄階段跟隨客戶端視窗，進遊戲後跟隨遊戲視窗；兩者都不在時不顯示浮窗（用托盤和主介面）
        rect = grect or crect
        if rect is None:
            self.panel.hide()
            return
        if not self.panel.isVisible():
            self.panel.show()
        self.panel.place(rect)


SINGLE_INSTANCE = "aramhex-single-instance"


def version_notice(settings) -> str | None:
    """剛更新過（這次的版本和上次執行的不一樣）就返回一句提示；第一次安裝不提示。記下這次的版本。
    老版本沒記過 last_version：有設定檔案就算更新過來的。"""
    from .. import __version__
    last = settings.last_version
    if last == __version__:
        return None
    settings.last_version = __version__
    settings.save()
    return f"已更新到 {__version__}" if last or not getattr(settings, "fresh_install", True) else None


def run(make_engine, minimized: bool = False) -> int:
    """啟動圖形介面。已有例項在執行時，只通知它顯示主視窗然後退出。"""
    import getpass
    import sys

    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    from .mainwindow import MainWindow, Tray, app_icon

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("海克斯大亂鬥助手")
    app.setWindowIcon(app_icon())

    name = f"{SINGLE_INSTANCE}-{getpass.getuser()}"
    # 只在開發／並行驗證時設定；正常使用者仍共用一個單例名稱。
    if suffix := os.environ.get("ARAMHEX_INSTANCE_SUFFIX", "").strip():
        name += f"-{suffix}"

    def notify_running() -> bool:
        for _ in range(3):  # 已有的助手可能正忙，多試幾次
            probe = QLocalSocket()
            probe.connectToServer(name)
            if probe.waitForConnected(1000):
                probe.write(b"show")
                probe.flush()
                probe.waitForBytesWritten(1000)
                return True
        return False

    if not single_instance.acquire(name):
        # 已經有助手在跑：讓它顯示主視窗。通知不到時多半是舊程序正在退出（例如更新後自動重啟），
        # 等它退出後接班；等不到就不再起第二個
        if notify_running() or not single_instance.acquire(name, 10_000):
            return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)

    engine = make_engine()
    win.set_capture_allowed(engine.settings.allow_capture)  # 錄屏、截圖時是否顯示浮窗
    engine.start()
    ov = Overlay(engine)
    ov.set_visible(engine.settings.overlay)
    main_win = MainWindow(engine, ov)
    tray = Tray(engine, main_win, ov)
    main_win.tray = tray
    tray.show()

    def on_second_instance():
        conn = server.nextPendingConnection()
        if conn:
            conn.readAll()
        main_win.show_and_raise()
        main_win.check_update()  # 使用者再點一次圖示：順便查更新，不用退出重開

    server.newConnection.connect(on_second_instance)
    note = version_notice(engine.settings)
    if note:
        tray.showMessage("海克斯大亂鬥助手", note, app_icon(), 8000)
    ov.notify = lambda text: tray.showMessage("海克斯大亂鬥助手", text, app_icon(), 12000)
    if not engine.settings.seen_welcome:
        def welcome():
            engine.settings.seen_welcome = True
            engine.settings.save()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(main_win, "使用前", "請在遊戲設定 → 影片裡，把視窗模式改成「無邊框」（或「視窗化」）。\n\n"
                                    "全屏模式下截不到畫面，識別不了。")
        QTimer.singleShot(1200, welcome)
    failed = patch.take_failure()
    if failed:
        log.warning("上次更新沒裝上：%s", failed)
        tray.showMessage("海克斯大亂鬥助手", "上次更新沒有裝上，已恢復原版本。開啟主介面點「立即更新」再試一次。",
                         app_icon(), 10000)
    main_win.check_update()
    main_win.refresh_rank_if_stale()
    if not minimized:
        main_win.show_and_raise()
    app._keep = (ov, main_win, tray, server)  # 保持引用
    return app.exec()
