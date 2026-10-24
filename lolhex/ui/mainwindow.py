"""主介面與系統托盤。

- 主視窗：資料狀態、當前英雄（識別結果/候選/搜尋手動選）、英雄評級與出裝加點、當前三選一推薦、設定。
- 關閉主視窗只是隱藏到托盤；退出要在托盤選單裡點「退出」。
- 托盤：雙擊開啟主介面；右鍵選單。
"""

from __future__ import annotations

import logging
import os
import webbrowser
from html import escape
from importlib import resources

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QScrollArea,
                               QPushButton, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)

from .. import (APP_UPDATES_ENABLED, DATA_HOMEPAGE, HELP_PAGE, HOMEPAGE, UPSTREAM_MIN_VERSION_ENABLED,
                WEBSITE, __version__, cloud, patch, rank, update)
from ..config import SPEEDS, is_portable
from ..vision import window as win
from ..data.public import BANDS
from . import autostart
from .autoshot import shots_dir
from . import buildview
from .data_status import data_status_html
from .herosearch import hero_completer

RARITY_CN = {"silver": "白銀", "gold": "黃金", "prismatic": "稜彩"}
VERDICT_CN = {"best": ("首選", "#2e9d5b"), "ok": ("可選", "#3b7dd8"), "reroll": ("可考慮重新整理", "#d0533f"),
              "unknown": ("未知", "#888")}
PHASE_CN = {None: "未檢測到英雄聯盟", "client": "客戶端（請手動選擇英雄）", "ingame": "對局中"}
VISION_CN = {"idle": "待機", "paused": "遊戲不在前臺，暫停", "scanning": "掃描中"}
UPDATE_EVERY_MS = 30 * 60 * 1000  # how often to check for updates while resident


def app_icon() -> QIcon:
    data = resources.files("lolhex.ui").joinpath("icon.png").read_bytes()
    pm = QPixmap()
    pm.loadFromData(data)
    return QIcon(pm)


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _progress_bar() -> QProgressBar:
    bar = QProgressBar()
    bar.setTextVisible(True)
    bar.setMaximumHeight(18)
    bar.hide()
    return bar


def show_progress(bar: QProgressBar, label: str, done: int | None = None, total: int | None = None) -> None:
    """進度條上寫"<在做什麼> 已下載 / 總共 MB"；不知道總量時只寫文字。"""
    if total:
        bar.setRange(0, 1000)
        bar.setValue(int(1000 * min(done or 0, total) / total))
        bar.setFormat(f"{label} {(done or 0) / 1e6:.1f} / {total / 1e6:.1f} MB")
    else:
        bar.setRange(0, 1)
        bar.setValue(0)
        bar.setFormat(label)
    bar.show()


def _card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    # 卡片固定用淺色底；Windows 深色模式會把預設文字設成白色，必須一併指定深色文字，
    # 否則狀態與英雄內容會變成白底白字。
    f.setStyleSheet("QFrame#card{border:1px solid #d7dbe3;border-radius:6px;"
                    "background:#fbfcfe;color:#20242c}"
                    "QFrame#card QLabel{color:#20242c;background:transparent}"
                    "QFrame#card QProgressBar{color:#20242c}")
    return f


def hard_exit_later(seconds: float = 5.0) -> None:
    """更新要替換檔案：正常退出卡住（後臺執行緒、網路請求沒結束）時，幾秒後強制結束本程序。
    1.0.9 之前在 172 上出現過：舊助手沒退出，檔案被佔用，更新被還原。"""
    import threading

    def go():
        logging.getLogger(__name__).warning("退出超時，強制結束以便更新")
        logging.shutdown()
        os._exit(0)
    t = threading.Timer(seconds, go)
    t.daemon = True
    t.start()


class RankWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, riot_id: str, parent=None):
        super().__init__(parent)
        self.riot_id = riot_id

    def run(self):
        try:
            self.done.emit(rank.lookup(self.riot_id))
        except rank.RankError as e:
            self.failed.emit(str(e))
        except Exception as e:
            logging.getLogger(__name__).warning("查分出錯：%s", e)
            self.failed.emit("查詢出錯，請稍後再試")


class UpdateWorker(QThread):
    """後臺執行緒：mode=check 查有沒有新版本（手動檢查時先同步統計資料，結果發 data_done）；
    mode=download 先試增量更新（只下變了的檔案，官網優先），不行再從 GitHub 下完整安裝包；
    增量失敗、安裝包下不了或太慢、便攜版要整包，都發 manual（原因, 網盤連結）讓使用者去網盤下載。
    strict=True（手動檢查）時連不上會發 failed，沒有新版本發 uptodate。"""
    found = Signal(dict)
    uptodate = Signal()
    progress = Signal(int, int)
    ready = Signal(str)
    patched = Signal(list, list)
    phase = Signal(str)  # 當前在做什麼（檢查更新檔案 / 比對本機檔案 / 下載更新 / 下載安裝包）
    failed = Signal(str)
    data_done = Signal(str)
    manual = Signal(str, dict)
    cloud = Signal(dict)

    def __init__(self, mode: str, info: dict | None = None, parent=None, strict: bool = False, data_sync=None):
        super().__init__(parent)
        self.mode, self.info, self.strict, self.data_sync = mode, info, strict, data_sync

    def run(self):
        try:
            if self.mode == "check":
                self.cloud.emit(cloud.refresh())
                if self.data_sync:
                    try:
                        self.data_done.emit(self.data_sync())
                    except Exception as e:
                        logging.getLogger(__name__).warning("手動同步統計資料失敗：%s", e)
                        self.data_done.emit("統計資料這次沒連上，稍後會自動再試。")
                if APP_UPDATES_ENABLED:
                    info = update.check(__version__, strict=self.strict)
                    if info:
                        self.found.emit(info)
                    else:
                        self.uptodate.emit()
                else:
                    self.uptodate.emit()
            else:
                log = logging.getLogger(__name__)
                try:
                    changed, stale = patch.prepare(self.info["version"], self.progress.emit, phase=self.phase.emit)
                    self.patched.emit(changed, stale)
                    return
                except patch.NeedFullInstall as e:
                    log.info("要整包更新：%s", e)
                    reason = "這次更新需要重新下載安裝包。"
                except Exception as e:
                    log.warning("增量更新失敗：%s", e)
                    self.manual.emit("更新檔案下載失敗。", update.pan_links())
                    return
                if not self.info.get("url") or is_portable():
                    self.manual.emit(reason, update.pan_links())
                    return
                self.phase.emit("從 GitHub 下載安裝包…")
                try:
                    self.ready.emit(str(update.download(self.info, self.progress.emit)))
                except update.SlowDownload as e:
                    log.info("GitHub %s", e)
                    self.manual.emit("從 GitHub 下載太慢。", update.pan_links())
                except Exception as e:
                    log.warning("從 GitHub 下載安裝包失敗：%s", e)
                    self.manual.emit("從 GitHub 下載安裝包失敗。", update.pan_links())
        except Exception as e:  # 更新失敗不能影響助手本身
            self.failed.emit(str(e))


BAND_CHOICES = [("", "全體")] + [(c, BANDS[c]) for c in BANDS]


def about_html() -> str:
    links = [f"<a href='{WEBSITE}'>官網</a>", f"<a href='{HOMEPAGE}'>GitHub</a>", f"<a href='{DATA_HOMEPAGE}'>統計資料</a>"]
    for c in cloud.community():  # 雲控：QQ 群、B 站、贊助……
        label = escape(c["name"] + (" " + c["text"] if c.get("text") else ""))
        links.append(f"<a href='{escape(c['url'])}'>{label}</a>" if c.get("url") else label)
    return (f"<b>AramHex 海克斯大亂鬥助手</b> {__version__}{'（便攜版）' if is_portable() else ''}<br>" + " · ".join(links) +
            "<br><span style='color:#777'>非官方工具，與騰訊、Riot Games 無關。</span>")


class MainWindow(QMainWindow):
    def __init__(self, engine, overlay):
        super().__init__()
        self.engine = engine
        self.overlay = overlay
        self._names: dict[str, str] = {}
        self._cand_ids: list = []
        self._panel_hero = None
        self._hint_shown = False
        self.setWindowTitle(f"海克斯大亂鬥助手 v{__version__}")
        self.setWindowIcon(app_icon())
        self.resize(700, 820)
        self.setMinimumSize(640, 700)
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # 頂部狀態
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(40, 40))
        title = QLabel("<b style='font-size:17px'>海克斯大亂鬥助手</b> "
                       f"<span style='font-size:13px;color:#555'>{__version__}</span>")
        head.addWidget(logo)
        head.addWidget(title, 1)
        self.btn_comm = QPushButton()  # 雲控裡標了 primary 的社群入口（比如 QQ 群），沒有就不顯示
        self.btn_comm.clicked.connect(self._open_primary)
        self.btn_comm.hide()
        head.addWidget(self.btn_comm)
        self.btn_dash = QPushButton("幫助")
        self.btn_dash.clicked.connect(lambda: webbrowser.open(HELP_PAGE))
        head.addWidget(self.btn_dash)
        self._show_primary()
        lay.addLayout(head)

        # 有新版本時才顯示
        self.update_bar = _card()
        self.update_bar.setStyleSheet("QFrame#card{border:1px solid #e0b64a;border-radius:6px;"
                                      "background:#fff8e1;color:#20242c}"
                                      "QFrame#card QLabel{color:#20242c;background:transparent}")
        ubv = QVBoxLayout(self.update_bar)
        ub = QHBoxLayout()
        ubv.addLayout(ub)
        self.update_text = QLabel()
        self.update_text.setWordWrap(True)
        self.btn_update = QPushButton("立即更新")
        self.btn_update.clicked.connect(self._start_update)
        ub.addWidget(self.update_text, 1)
        ub.addWidget(self.btn_update)
        self.update_progress = _progress_bar()  # 更新時顯示：在做什麼、下了多少
        ubv.addWidget(self.update_progress)
        self.update_bar.hide()
        lay.addWidget(self.update_bar)
        self._update_info = None
        self._worker = None
        # 助手常駐托盤，可能好幾天不重啟：平時也定時查更新
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self.check_update)
        self._update_timer.start(UPDATE_EVERY_MS)

        self.status = QLabel()
        self.status.setWordWrap(False)  # 內容自帶 <br> 換行；自動換行會讓高度算不準被壓扁
        self.status.setTextFormat(Qt.RichText)
        sc = _card()
        scl = QVBoxLayout(sc)
        scl.addWidget(self.status)
        self.data_progress = _progress_bar()  # 下載統計資料時顯示
        scl.addWidget(self.data_progress)
        lay.addWidget(sc)

        # 英雄
        hc = _card()
        hl = QVBoxLayout(hc)
        self.hero_label = QLabel()
        self.hero_label.setTextFormat(Qt.RichText)
        hl.addWidget(self.hero_label)
        self.cs_label = QLabel()  # 選人介面：待選欄按勝率排序的彙總
        self.cs_label.setTextFormat(Qt.RichText)
        self.cs_label.setWordWrap(True)
        self.cs_label.hide()
        hl.addWidget(self.cs_label)
        self.cands = QHBoxLayout()
        hl.addLayout(self.cands)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋英雄")
        self.search.returnPressed.connect(self._search_pick)
        btn_clear = QPushButton("清除")
        btn_clear.clicked.connect(lambda: self._pick_hero(None))
        row.addWidget(self.search, 1)
        row.addWidget(btn_clear)
        hl.addLayout(row)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("分段"))
        self.band_box = QComboBox()
        for code, label in BAND_CHOICES:
            self.band_box.addItem(label, code)
        self.band_box.setCurrentIndex(max(0, self.band_box.findData(engine.settings.data_band or "")))
        self.band_box.currentIndexChanged.connect(lambda i: self.engine.set_band(self.band_box.itemData(i) or None))
        brow.addWidget(self.band_box)
        self.my_rank_label = QLabel()
        self.my_rank_label.setStyleSheet("color:#555")
        brow.addWidget(self.my_rank_label)
        brow.addStretch(1)
        hl.addLayout(brow)
        lay.addWidget(hc)

        # 標籤頁
        self.tabs = QTabWidget()
        self.tab_hero = QLabel()
        self.tab_hero.setTextFormat(Qt.RichText)
        self.tab_hero.setWordWrap(True)
        self.tab_hero.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.tab_hero.setTextInteractionFlags(Qt.TextSelectableByMouse)
        w1 = QWidget()
        QVBoxLayout(w1).addWidget(self.tab_hero)
        self.tabs.addTab(w1, "出裝與加點")

        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        self.offer_advice = QLabel("未在選海克斯")
        self.offer_advice.setWordWrap(True)
        l2.addWidget(self.offer_advice)
        grid = QGridLayout()
        self.offer_cards = []
        for i in range(3):
            lab = QLabel()
            lab.setTextFormat(Qt.RichText)
            lab.setWordWrap(True)
            lab.setAlignment(Qt.AlignTop)
            lab.setMinimumWidth(170)
            fr = _card()
            QVBoxLayout(fr).addWidget(lab)
            grid.addWidget(fr, 0, i)
            self.offer_cards.append(lab)
        l2.addLayout(grid)
        btns = QHBoxLayout()
        b1 = QPushButton("重新識別")
        b1.clicked.connect(self.engine.rescan)
        b2 = QPushButton("重設識別")
        b2.clicked.connect(self._recalibrate)
        btns.addWidget(b1)
        btns.addWidget(b2)
        btns.addStretch(1)
        l2.addLayout(btns)
        l2.addStretch(1)
        self.tabs.addTab(w2, "海克斯三選一")

        self.tabs.addTab(self._settings_tab(), "設定")
        lay.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def showEvent(self, e):
        # 主視窗永遠排除在截圖之外：選英雄辨識是讀螢幕的，主視窗若蓋在客戶端上面
        # （實測 656x743 正好壓住預選欄與「可使用的英雄」），辨識就會讀到自己的介面而全部失敗。
        # always=True：不受「錄屏時顯示浮窗」設定影響，那設定是給浮層用的。
        hwnd = int(self.winId())
        win.exclude_from_capture(hwnd, always=True)
        # 同時登記成「自己的頂層窗」：前臺是主視窗時仍可掃遊戲。
        # 遊戲已經在跑時才啟動助手，搶到前臺的正是這個主視窗，不登記就會永遠 paused。
        # winId() 在 showEvent 一定已經具體化（上面的 exclude_from_capture 一直依賴這點）。
        win.add_own_window(hwnd)
        super().showEvent(e)

    # ---------- 設定 ----------

    def _settings_tab(self) -> QWidget:
        s = self.engine.settings
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setSpacing(14)
        f = QFormLayout()
        f.setVerticalSpacing(10)
        outer.addLayout(f)
        self.set_win = QCheckBox("顯示勝率數字")
        self.set_win.setChecked(s.show_winrate)
        self.set_corner = QComboBox()
        self.set_corner.addItems(["右上角", "左上角"])
        self.set_corner.setCurrentIndex(0 if s.overlay_corner == "top-right" else 1)
        self.set_overlay = QCheckBox("顯示遊戲內浮窗")
        self.set_overlay.setChecked(s.overlay)
        self.set_speed = QComboBox()
        for key, (label, _) in SPEEDS.items():
            self.set_speed.addItem(label, key)
        self.set_speed.setCurrentIndex(max(0, self.set_speed.findData(s.speed)))
        self.set_capture = QCheckBox("錄屏、截圖時顯示浮窗")
        self.set_capture.setChecked(s.allow_capture)
        self.set_autoshot = QCheckBox("選英雄、三選一時自動截圖")
        self.set_autoshot.setChecked(s.auto_screenshot)
        btn_shots = QPushButton("開啟截圖資料夾")
        btn_shots.clicked.connect(lambda: os.startfile(str(shots_dir())) if hasattr(os, "startfile") else None)
        shot_row = QHBoxLayout()
        shot_row.addWidget(self.set_autoshot, 1)
        shot_row.addWidget(btn_shots)
        self.set_auto = QCheckBox("開機自動啟動")
        self.set_auto.setChecked(autostart.is_enabled())
        self.set_data = QCheckBox("自動更新統計資料")
        self.set_data.setChecked(s.check_data_updates)
        self.set_autoupdate = QCheckBox("自動更新程式（從 GitHub 下載並安裝）")
        self.set_autoupdate.setChecked(getattr(s, "auto_update", True))
        f.addRow("識別頻率", self.set_speed)
        f.addRow("", self.set_win)
        f.addRow("", self.set_overlay)
        f.addRow("浮窗位置", self.set_corner)
        f.addRow("", self.set_capture)
        f.addRow("", shot_row)
        f.addRow("", self.set_auto)
        f.addRow("", self.set_data)
        f.addRow("", self.set_autoupdate)
        save = QPushButton("儲存設定")
        save.clicked.connect(self._save_settings)
        f.addRow("", save)

        rk = _card()
        rv = QVBoxLayout(rk)
        rv.setContentsMargins(18, 14, 18, 14)
        rv.setSpacing(8)
        rv.addWidget(QLabel("<b>我的水平</b>"))
        rrow = QHBoxLayout()
        self.rank_input = QLineEdit(s.riot_id)
        self.rank_input.setPlaceholderText("名字#編號")
        self.rank_input.returnPressed.connect(self._query_rank)
        self.btn_rank = QPushButton("查詢")
        self.btn_rank.setMinimumWidth(90)
        self.btn_rank.clicked.connect(self._query_rank)
        rrow.addWidget(self.rank_input, 1)
        rrow.addWidget(self.btn_rank)
        rv.addLayout(rrow)
        self.rank_result = QLabel()
        self.rank_result.setWordWrap(True)
        rv.addWidget(self.rank_result)
        outer.addWidget(rk)
        self._show_rank(s.my_rank)
        self._rank_worker = None
        outer.addStretch(1)
        card = _card()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(18, 16, 18, 16)
        cv.setSpacing(8)
        about = QLabel(about_html())
        about.setTextFormat(Qt.RichText)
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)
        self.about_label = about
        cv.addWidget(about)
        self.about_data = QLabel()
        self.about_data.setStyleSheet("color:#555")
        cv.addWidget(self.about_data)
        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self.btn_check = QPushButton("檢查更新")
        self.btn_check.setMinimumWidth(140)
        self.btn_check.setMinimumHeight(34)
        self.btn_check.clicked.connect(lambda: self.check_update(manual=True))
        row.addWidget(self.btn_check)
        row.addStretch(1)
        cv.addLayout(row)
        outer.addWidget(card)
        # 設定項越來越多：放進可滾動區域，視窗矮的時候不會被壓扁
        scroll = QScrollArea()
        scroll.setWidget(w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        return scroll

    # ---------- 查我的水平 ----------

    def _show_rank(self, res: dict):
        text = rank.describe(res)
        self.rank_result.setText(text or "<span style='color:#777'>填自己的「名字#編號」，查區內排名，自動選對應分段</span>")
        r = (res or {}).get("results") or []
        if hasattr(self, "my_rank_label"):
            self.my_rank_label.setText(f"你：{r[0]['band_name']}（前 {r[0]['top'] * 100:.1f}%）" if r else "")

    def _query_rank(self, silent: bool = False):
        if self._rank_worker and self._rank_worker.isRunning():
            return
        rid = self.rank_input.text().strip()
        if not silent:
            self.btn_rank.setEnabled(False)
            self.btn_rank.setText("查詢中…")
        self._rank_worker = RankWorker(rid, self)
        self._rank_worker.done.connect(lambda res: self._rank_done(rid, res, silent))
        self._rank_worker.failed.connect(lambda msg: self._rank_failed(msg, silent))
        self._rank_worker.finished.connect(lambda: (self.btn_rank.setEnabled(True), self.btn_rank.setText("查詢")))
        self._rank_worker.start()

    def _rank_done(self, rid: str, res: dict, silent: bool):
        import time
        s = self.engine.settings
        s.riot_id, s.my_rank = rid, {**res, "queried_at": time.time()}
        s.save()
        self._show_rank(s.my_rank)
        band = res["results"][0]["band"]
        if not silent and band in BANDS:
            i = self.band_box.findData(band)
            if i >= 0:
                self.band_box.setCurrentIndex(i)  # 觸發 engine.set_band，記住選擇

    def _rank_failed(self, msg: str, silent: bool):
        if silent:
            logging.getLogger(__name__).info("自動查分失敗：%s", msg)
            return
        self.rank_result.setText(f"<span style='color:#d0533f'>{escape(msg)}</span>")

    def refresh_rank_if_stale(self):
        """啟動時：上次查分超過 7 天就悄悄再查一次（不改你選的分段）。"""
        import time
        s = self.engine.settings
        if s.riot_id and time.time() - float((s.my_rank or {}).get("queried_at") or 0) > 7 * 86400:
            self._query_rank(silent=True)

    # ---------- 雲控 ----------

    def _show_primary(self):
        p = cloud.primary_link()
        if p:
            self.btn_comm.setText(p["name"])
            self.btn_comm.setToolTip(p.get("text") or "")
        self.btn_comm.setVisible(bool(p))

    def _open_primary(self):
        p = cloud.primary_link()
        if p:
            webbrowser.open(p["url"])

    def _apply_cloud(self, cfg: dict):
        if hasattr(self, "about_label"):
            self.about_label.setText(about_html())
        if hasattr(self, "btn_comm"):
            self._show_primary()
        s = self.engine.settings
        notice = cfg.get("notice") or {}
        if notice.get("id") and notice.get("text") and notice["id"] != s.seen_notice:
            s.seen_notice = notice["id"]
            s.save()
            box = QMessageBox(QMessageBox.Information, "公告", notice["text"], parent=self)
            b_open = box.addButton("檢視", QMessageBox.AcceptRole) if notice.get("url") else None
            box.addButton("知道了", QMessageBox.RejectRole)
            box.exec()
            if b_open is not None and box.clickedButton() is b_open:
                webbrowser.open(notice["url"])
        # 台服版不採用上游的版本門檻：雲控的 min_version 是國服版本號（1.1.0），
        # 直接比較會把 1.0.0+tw.6 誤判成太舊，並把使用者引導去下載國服版。
        minv = cfg.get("min_version") or ""
        if (UPSTREAM_MIN_VERSION_ENABLED and minv and update.is_newer(minv, __version__)
                and not getattr(self, "_min_warned", False)):
            self._min_warned = True
            box = QMessageBox(QMessageBox.Warning, "需要更新", f"當前版本 {__version__} 太舊，請更新到最新版本。", parent=self)
            b_up = box.addButton("立即更新", QMessageBox.AcceptRole)
            box.addButton("稍後", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is b_up:
                if self._update_info:
                    self._start_update()
                else:
                    self._offer_manual("", update.pan_links())

    def _save_settings(self):
        s = self.engine.settings
        s.check_data_updates = self.set_data.isChecked()
        s.auto_update = self.set_autoupdate.isChecked()
        s.speed = self.set_speed.currentData() or "standard"
        s.allow_capture = self.set_capture.isChecked()
        s.auto_screenshot = self.set_autoshot.isChecked()
        win.set_capture_allowed(s.allow_capture)
        s.show_winrate = self.set_win.isChecked()
        s.overlay = self.set_overlay.isChecked()
        s.overlay_corner = "top-right" if self.set_corner.currentIndex() == 0 else "top-left"
        s.save()
        self.overlay.set_visible(s.overlay)
        self.overlay.panel.corner = s.overlay_corner
        try:
            autostart.set_enabled(self.set_auto.isChecked())
        except OSError as e:
            QMessageBox.warning(self, "開機自啟", f"設定失敗：{e}")
        QMessageBox.information(self, "設定", "已儲存。")

    def _recalibrate(self):
        self.engine.hard_reset()
        QMessageBox.information(self, "重設識別",
                                "已清除卡片位置、指紋快取和三選一結果。\n"
                                "下一輪會重新整屏找一次卡片位置；遊戲中按也安全。\n\n"
                                "設定、統計資料和截圖都沒有動。")

    # ---------- 更新 ----------

    def check_update(self, manual: bool = False):
        """啟動、再次開啟助手時各查一次，平時每 UPDATE_EVERY_MS 查一次；
        只提示，使用者點了「立即更新」才下載安裝。正在查或正在下載時跳過。
        manual=True 是設定頁「檢查更新」按鈕：結果（最新 / 有新版本 / 失敗）都彈窗告訴使用者。"""
        if self._worker and self._worker.isRunning():
            if manual:
                QMessageBox.information(self, "檢查更新", "正在檢查或下載更新，請稍候。")
            return
        self._data_msg = ""
        self._worker = UpdateWorker("check", parent=self, strict=manual,
                                    data_sync=self._sync_data_now if manual else None)
        self._worker.found.connect(lambda info: self._update_found(info, manual))
        self._worker.cloud.connect(self._apply_cloud)
        if manual:
            self.btn_check.setEnabled(False)
            self.btn_check.setText("檢查中…")
            self._worker.data_done.connect(lambda m: setattr(self, "_data_msg", m))
            self._worker.uptodate.connect(lambda: QMessageBox.information(
                self, "檢查更新", (f"台服版程式目前為最新版本（已停用上游自動更新）；{self._data_line()}"
                                     if not APP_UPDATES_ENABLED else
                                     f"軟體已是最新版本（{__version__}）。" + self._data_line())))
            self._worker.failed.connect(self._check_failed)
            self._worker.finished.connect(lambda: (self.btn_check.setEnabled(True),
                                                   self.btn_check.setText("檢查更新")))
        self._worker.start()

    def _sync_data_now(self) -> str:
        """「檢查更新」按鈕：馬上查統計資料（不管自動更新開關），返回一句結果。"""
        st = self.engine.store
        changed = st.sync_data(force=True, manual=True)
        ds = st.dataset
        tail = f"（{ds.patch} 版本，截至 {str(ds.snapshot_at)[5:10]}）" if ds else ""
        if changed:
            return f"統計資料已更新{tail}。"
        if st.sync_error:
            return "統計資料這次沒連上，稍後會自動再試。"
        return f"統計資料已是最新{tail}。"

    def _data_line(self) -> str:
        msg = getattr(self, "_data_msg", "")
        return f"\n{msg}" if msg else ""

    def _check_failed(self, msg: str):
        logging.getLogger(__name__).warning("檢查更新失敗：%s", msg)
        box = QMessageBox(QMessageBox.Warning, "檢查更新", "檢查更新失敗，請稍後再試。" + self._data_line(), parent=self)
        b_site = box.addButton("官網下載", QMessageBox.ActionRole)
        box.addButton("關閉", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_site:
            webbrowser.open(update.DOWNLOAD_PAGE)

    def _update_found(self, info: dict, manual: bool = False):
        known = (self._update_info or {}).get("version")
        self._update_info = info
        notes = f"<br><span style='color:#777'>{escape(info['notes'][:200])}</span>" if info.get("notes") else ""
        # 打包後的程式都能先試增量更新；原始碼執行時只有帶安裝包地址的才能直接裝
        direct = patch.install_root() is not None or (bool(info.get("url")) and not is_portable())
        self.update_text.setText(f"<b>有新版本 {info['version']}</b>（當前 {__version__}）{notes}")
        self.btn_update.setText("立即更新" if direct else "去下載")
        self.update_bar.show()
        tray = getattr(self, "tray", None)
        auto = bool(getattr(self.engine.settings, "auto_update", True))
        can_auto = getattr(self, "_can_auto_update", None)
        if auto and not manual and direct and can_auto and can_auto():
            # 自動更新：不問使用者，直接下載並安裝，裝完自動重開
            logging.getLogger(__name__).info("自動更新到 %s", info.get("version"))
            self._start_update()
            return
        if manual:
            ask = QMessageBox.question(self, "檢查更新", f"有新版本 {info['version']}（當前 {__version__}）。"
                                       + (f"\n\n{info['notes']}" if info.get("notes") else "")
                                       + (f"\n\n{self._data_msg}" if getattr(self, "_data_msg", "") else "")
                                       + "\n\n現在更新嗎？")
            if ask == QMessageBox.Yes:
                if self._worker:
                    self._worker.wait(3000)  # 檢查執行緒發完訊號就結束，等它收尾再開始下載
                self._start_update()
        elif tray and known != info["version"]:  # 同一個版本只彈一次通知
            tray.showMessage("海克斯大亂鬥助手", f"有新版本 {info['version']}，開啟主介面點「立即更新」。",
                             app_icon(), 6000)

    def _can_auto_update(self) -> bool:
        """自動更新要不要現在就裝：對局中不要（會打斷遊戲），托盤模式下也不要主動跳視窗。"""
        try:
            if self.engine.snapshot().get("phase") == "ingame":
                logging.getLogger(__name__).info("對局中，略過自動更新")
                return False
            if self.isHidden() or not self.isVisible():
                logging.getLogger(__name__).info("主視窗未顯示，略過自動更新")
                return False
        except Exception:
            return False
        return True

    def _start_update(self):
        if not self._update_info or (self._worker and self._worker.isRunning()):
            return
        # 原始碼執行、便攜版、或沒有安裝包地址：只能開啟本倉庫的下載頁。
        # 不可以開 aramhex.com——那裡是國服版。
        if patch.install_root() is None and (is_portable() or not self._update_info.get("url")):
            webbrowser.open(update.DOWNLOAD_PAGE)
            return
        if self.engine.snapshot().get("phase") == "ingame":
            QMessageBox.information(self, "更新", "正在對局中，打完這局再更新。")
            return
        self.btn_update.setEnabled(False)
        self.btn_update.setText("更新中…")
        self._update_stage = "準備更新…"
        show_progress(self.update_progress, self._update_stage)
        self._worker = UpdateWorker("download", info=self._update_info, parent=self)
        self._worker.phase.connect(self._update_phase)
        self._worker.progress.connect(
            lambda done, total: show_progress(self.update_progress, self._update_stage.rstrip("…"), done, total))
        self._worker.ready.connect(self._install)
        self._worker.patched.connect(self._apply_patch)
        self._worker.manual.connect(self._offer_manual)
        self._worker.failed.connect(self._update_failed)
        self._worker.start()

    def _update_phase(self, text: str):
        self._update_stage = text
        show_progress(self.update_progress, text)

    def _apply_patch(self, changed: list, stale: list):
        show_progress(self.update_progress, "下載完成，正在重啟助手…", 1, 1)
        root = patch.install_root()
        try:
            patch.launch_apply(root, changed, stale, self._update_info["version"], relaunch=str(root / "AramHex.exe"))
        except OSError as e:
            return self._update_failed(str(e))
        self.tray.quit()  # 退出讓出檔案；替換完自動重新開啟
        hard_exit_later()

    def _offer_manual(self, reason: str, links: dict | None = None):
        """更新沒能在軟體裡完成：提示原因，按鈕直接開啟網盤下載（連結從官網讀，每次發版會換）或官網下載區。"""
        self.update_progress.hide()
        self.btn_update.setEnabled(True)
        self.btn_update.setText("重試更新")
        # 台服版沒有網盤：一律導到本倉庫的 Releases。links 參數保留給舊呼叫點，
        # 但它的內容來自上游雲控（國服 123pan），不能採用。
        box = QMessageBox(QMessageBox.Information, "更新", f"{reason}請下載新版本，直接覆蓋安裝，設定會保留。", parent=self)
        b_site = box.addButton("前往下載", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(b_site)
        box.exec()
        if box.clickedButton() is b_site:
            webbrowser.open(update.DOWNLOAD_PAGE)

    def _install(self, path: str):
        show_progress(self.update_progress, "下載完成，正在啟動安裝程式…", 1, 1)
        try:
            update.launch_installer(path)
        except OSError as e:
            return self._update_failed(str(e))
        self.tray.quit()  # 退出讓安裝程式替換檔案；裝完會自動重新開啟
        hard_exit_later()

    def _update_failed(self, msg: str):
        logging.getLogger(__name__).warning("更新失敗：%s", msg)
        self._offer_manual("更新失敗。")

    def _ensure_completer(self):
        heroes = self.engine.store.heroes
        if self._names or not heroes:
            return
        comp, self._names = hero_completer(self.engine.store, self)
        comp.activated.connect(lambda text: self._pick_hero(self._names.get(text, text)))
        self.search.setCompleter(comp)

    def _pick_hero(self, hero_key):
        """手動選英雄：立即重畫本地資料，官方資料在背景補齊。"""
        self.engine.set_hero(hero_key)
        self.search.clear()
        self.refresh()

    def _search_pick(self):
        t = self.search.text().strip()
        if t:
            self._pick_hero(self._names.get(t, t))

    def _set_candidates(self, cands):
        ids = [c.get("id") for c in cands]
        if ids == self._cand_ids:
            return
        self._cand_ids = ids
        while self.cands.count():
            it = self.cands.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if cands:
            self.cands.addWidget(QLabel("候選："))
        for c in cands[:6]:
            b = QPushButton(c.get("name") or c.get("id"))
            b.clicked.connect(lambda _=False, hid=c.get("id"): self._pick_hero(hid))
            self.cands.addWidget(b)
        self.cands.addStretch(1)

    # ---------- 重新整理 ----------

    def refresh(self):
        if not self.isVisible():
            return
        snap = self.engine.snapshot()
        self._ensure_completer()
        dd = snap.get("data", {})
        v = snap.get("vision", {})
        self.status.setText(
            f"<b>狀態：</b>{PHASE_CN.get(snap.get('phase'), snap.get('phase'))}<br>"
            f"<b>海克斯識別：</b>{VISION_CN.get(v.get('status'), v.get('status'))}"
            f"{' · <span style=\"color:#d0533f\">截圖全黑，請把遊戲改成無邊框</span>' if v.get('blank') else ''}<br>"
            f"<b>資料：</b>{BANDS.get(dd.get('band_effective'), '全體')} · {data_status_html(dd)}")
        if hasattr(self, "about_data"):
            self.about_data.setText("統計資料：" + data_status_html(dd))
        dp = dd.get("data_progress")
        if dp:
            show_progress(self.data_progress, "統計資料更新中", dp.get("done"), dp.get("total"))
        else:
            self.data_progress.hide()

        h, hid = snap.get("hero"), snap.get("hero_id")
        show_win = snap.get("settings", {}).get("show_winrate", True)
        d = self.engine.hero_panel(hid) if hid else None
        if h:
            r = (d or {}).get("rank") or {}
            b = self.engine.hero_brief(hid)
            rating = []
            if b.get("grade"):
                rating.append(f"評級 {b['grade']}")
            if b.get("rank"):
                rating.append(f"勝率排名 {b['rank']}/{b.get('total') or '?'}")
            if show_win and r.get("win") is not None:
                rating.append(f"勝率 {_pct(r['win'])}")
            if r.get("pick") is not None:
                rating.append(f"出場率 {_pct(r['pick'])}")
            self.hero_label.setText(
                f"<span style='font-size:18px'><b>{h.get('name') or hid}</b></span> {h.get('nick') or ''}<br>"
                f"{' · '.join(rating)}")
        else:
            self.hero_label.setText("<b>請手動選擇英雄</b><br><span style='color:#777'>輸入中文名、英文名、稱號或玩家別名</span>")
        cs = snap.get("champ_select")
        if cs and (cs.get("bench") or cs.get("cards")):
            from .overlay import champ_select_summary
            self.cs_label.setText(champ_select_summary(cs, show_win))
            self.cs_label.show()
        else:
            self.cs_label.hide()
        self._set_candidates(snap.get("candidates") or [])

        key = (hid, d.get("date"), d.get("data_revision"), self.engine.icons.version, dd.get("band_effective")) if d else None
        if d and self._panel_hero != key:
            self._panel_hero = key
            self.tab_hero.setText(self._hero_html(d, show_win))
        elif not d:
            self._panel_hero = None
            self.tab_hero.setText("<span style='color:#777'>還沒有選英雄</span>")
        self._render_offer(snap.get("evaluation"), show_win)

    def _hero_html(self, d, show_win) -> str:
        out = buildview.lines(d, self.engine.icons, show_win, size=28)
        sk = buildview.skills_line(d, show_win)
        if sk:
            out.append(sk)
        top = [a for a in d.get("augments", []) if a.get("delta") is not None and a.get("sample") != "low"]
        top.sort(key=lambda a: -a["delta"])
        if top:
            out.append("<b>推薦海克斯</b>")
            for a in top[:8]:
                out.append(f"　{a['name']} <span style='color:#777'>{RARITY_CN.get(a.get('rarity'), '')}"
                           f" {a.get('tier') or ''}</span> <b style='color:#2e9d5b'>{a['delta']:+.1f}</b>")
        return "<br>".join(out)

    def _render_offer(self, ev, show_win):
        if not ev:
            self.offer_advice.setText("<span style='color:#777'>未在選海克斯</span>")
            for lab in self.offer_cards:
                lab.setText("")
            return
        self.offer_advice.setText(f"<b style='font-size:15px'>{ev['advice']}</b>")
        for lab, r in zip(self.offer_cards, ev["slots"]):
            v, col = VERDICT_CN.get(r["verdict"], VERDICT_CN["unknown"])
            lines = [f"<b style='color:{col}'>{v}</b>", f"<b>{r.get('name') or '未識別'}</b>"]
            meta = [RARITY_CN.get(r.get("rarity"), "")]
            if r.get("tier"):
                meta.append(f"{r['tier']}級")
            lines.append("<span style='color:#777'>" + " ".join(m for m in meta if m) + "</span>")
            if r.get("score") is not None:
                s = f"{r['score']:+.1f}"
                if show_win and r.get("win") is not None:
                    s += f" · 勝率 {_pct(r['win'])}"
                if r.get("thin"):
                    warn = "⚠ 樣本太少" if r["thin"] == "too_few" else "樣本偏少"
                    s += f" · <span style='color:#ff7a6b'>{warn}</span>"
                lines.append(s)
            lab.setText("<br>".join(lines))

    # ---------- 視窗行為 ----------

    def show_and_raise(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.refresh()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        if not self._hint_shown and QSystemTrayIcon.isSystemTrayAvailable():
            self._hint_shown = True
            tray = getattr(self, "tray", None)
            if tray:
                tray.showMessage("海克斯大亂鬥助手", "助手仍在後臺執行，右下角托盤圖示可以重新開啟或退出。",
                                 app_icon(), 4000)


class Tray(QSystemTrayIcon):
    def __init__(self, engine, window: MainWindow, overlay):
        super().__init__(app_icon())
        self.engine, self.window, self.overlay = engine, window, overlay
        self.setToolTip(f"海克斯大亂鬥助手 v{__version__}")
        m = QMenu()
        m.addAction("開啟主介面", window.show_and_raise)
        self.act_overlay = QAction("顯示遊戲浮窗", m, checkable=True)
        self.act_overlay.setChecked(engine.settings.overlay)
        self.act_overlay.toggled.connect(self._toggle_overlay)
        m.addAction(self.act_overlay)
        m.addAction("重新識別", engine.rescan)
        m.addAction("檢查更新", lambda: (window.show_and_raise(), window.check_update(manual=True)))
        self.messageClicked.connect(window.show_and_raise)
        self.act_auto = QAction("開機自動啟動", m, checkable=True)
        self.act_auto.setChecked(autostart.is_enabled())
        self.act_auto.toggled.connect(self._toggle_auto)
        m.addAction(self.act_auto)
        m.addSeparator()
        m.addAction("退出", self.quit)
        self.setContextMenu(m)
        self._menu = m
        self.activated.connect(self._activated)
        self.timer = QTimer()
        self.timer.timeout.connect(self._tooltip)
        self.timer.start(3000)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.window.show_and_raise()

    def _toggle_overlay(self, on: bool):
        self.engine.settings.overlay = on
        self.engine.settings.save()
        self.overlay.set_visible(on)

    def _toggle_auto(self, on: bool):
        try:
            autostart.set_enabled(on)
        except OSError:
            pass

    def _tooltip(self):
        s = self.engine.snapshot()
        h = s.get("hero")
        self.setToolTip(f"海克斯大亂鬥助手 v{__version__}\n" + PHASE_CN.get(s.get("phase"), "") +
                        (f"\n英雄：{h['name']}" if h else ""))

    def quit(self):
        self.engine.stop()
        self.hide()
        QApplication.quit()
