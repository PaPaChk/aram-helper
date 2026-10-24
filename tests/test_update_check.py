"""助手常駐托盤時也要能查到更新：再次開啟、定時都會查，正在查或下載時不重複；
設定頁「檢查更新」按鈕把結果都彈窗告訴使用者。"""

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from lolhex.ui import mainwindow  # noqa: E402
from lolhex.ui.mainwindow import MainWindow  # noqa: E402


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in self.slots:
            fn(*a)


class FakeWorker:
    started = []

    def __init__(self, mode, info=None, parent=None, strict=False, data_sync=None):
        self.mode, self.strict, self.running, self.data_sync = mode, strict, False, data_sync
        self.found, self.uptodate, self.failed, self.finished, self.data_done, self.cloud = (FakeSignal() for _ in range(6))

    def start(self):
        FakeWorker.started.append(self)
        self.running = True

    def isRunning(self):
        return self.running

    def wait(self, ms):
        return True


class FakeButton:
    def __init__(self):
        self.enabled, self.text = True, ""

    def setEnabled(self, v):
        self.enabled = v

    def setText(self, t):
        self.text = t


def _win():
    shown = []
    win = SimpleNamespace(
        engine=SimpleNamespace(settings=SimpleNamespace()),
        _worker=None, _update_info=None, btn_check=FakeButton(), btn_update=FakeButton(),
        update_text=SimpleNamespace(setText=lambda t: None),
        update_bar=SimpleNamespace(show=lambda: None),
        tray=SimpleNamespace(showMessage=lambda *a: shown.append(a[1])),
    )
    win.check_update = lambda manual=False: MainWindow.check_update(win, manual)
    win._sync_data_now = lambda: "統計資料已是最新。"
    win._data_line = lambda: MainWindow._data_line(win)
    win._apply_cloud = lambda cfg: None
    win._update_found = lambda info, manual=False: MainWindow._update_found(win, info, manual)
    win._check_failed = lambda msg: shown.append("失敗：" + msg)
    win._start_update = lambda: shown.append("開始下載")
    return win, shown


@pytest.fixture(autouse=True)
def _no_qt_icon(monkeypatch):
    """這些測試不建立 QApplication，app_icon() 會造 QPixmap 而直接崩潰（Qt 硬中止）。
    托盤通知的圖示不是這裡要驗的東西，換成 None 就好。"""
    monkeypatch.setattr(mainwindow, "app_icon", lambda: None)


@pytest.fixture
def boxes(monkeypatch):
    said = []
    monkeypatch.setattr(mainwindow, "UpdateWorker", FakeWorker)
    FakeWorker.started = []
    monkeypatch.setattr(mainwindow.QMessageBox, "information", lambda parent, title, text: said.append(text))
    return said


def test_check_skips_while_previous_still_running(boxes):
    win, _ = _win()
    win.check_update()
    win.check_update()  # 上一次還沒查完
    assert len(FakeWorker.started) == 1 and not boxes  # 自動檢查不打擾使用者
    win._worker.running = False
    win.check_update()  # 再次開啟助手 / 定時器：再查一次
    assert len(FakeWorker.started) == 2


def test_tray_notice_once_per_version():
    win, shown = _win()
    info = {"version": "0.3.31", "file": "AramHex-Setup-0.3.31.exe", "sha256": "0" * 64, "url": "http://x/a.exe"}
    win._update_found(info)
    win._update_found(dict(info))  # 半小時後又查到同一個版本：只更新橫條，不再彈通知
    win._update_found({**info, "version": "0.3.32"})
    assert len(shown) == 2 and "0.3.32" in shown[1]


def test_manual_check_reports_every_outcome(boxes, monkeypatch):
    win, shown = _win()
    win.check_update(manual=True)
    w = FakeWorker.started[-1]
    assert w.strict and not win.btn_check.enabled and w.data_sync  # 手動檢查順帶同步統計資料
    w.data_done.emit(w.data_sync())
    w.uptodate.emit()
    w.finished.emit()
    assert "最新版本" in boxes[-1] and "統計資料已是最新" in boxes[-1] and win.btn_check.enabled

    win._worker.running = False
    win.check_update(manual=True)
    FakeWorker.started[-1].failed.emit("連線超時")
    assert shown[-1] == "失敗：連線超時"

    win._worker.running = False
    monkeypatch.setattr(mainwindow.QMessageBox, "question", lambda *a: mainwindow.QMessageBox.Yes)
    win.check_update(manual=True)
    FakeWorker.started[-1].found.emit({"version": "9.9.9", "file": "AramHex-Setup-9.9.9.exe", "sha256": "0" * 64})
    assert shown[-1] == "開始下載"  # 使用者點"是"直接下載，不再彈托盤通知

def test_mirror_result_offers_download_page():
    """GitHub 連不上、從映象查到的新版本：沒有安裝包地址，按鈕變成「去下載」。"""
    win, _ = _win()
    win._update_found({"version": "9.9.9", "file": None, "sha256": None, "url": None, "page": "p", "mirror": True})
    assert win.btn_update.text == "去下載"
    win._update_found({"version": "9.9.10", "file": "AramHex-Setup-9.9.10.exe", "sha256": "0" * 64, "url": "u"})
    assert win.btn_update.text in ("立即更新", "去下載")  # 便攜版跑測試時也是「去下載」


def test_auto_update_starts_download_without_asking(monkeypatch):
    """開啟自動更新時，自動檢查（非手動）查到新版本就直接下載，不彈詢問視窗。"""
    win, shown = _win()
    win.engine.settings = SimpleNamespace(auto_update=True)
    win._can_auto_update = lambda: True
    monkeypatch.setattr(mainwindow.patch, "install_root", lambda: "C:/fake/install")
    win._update_found({"version": "9.9.9", "file": "AramHex-Setup-9.9.9.exe",
                       "sha256": "0" * 64, "url": "https://x/a.exe"})
    assert shown == ["開始下載"]


def test_auto_update_respects_switch(monkeypatch):
    """關掉自動更新時只提示，不自己下載。"""
    win, shown = _win()
    win.tray = None                      # 走完橫條更新就好，不進托盤通知
    win.engine.settings = SimpleNamespace(auto_update=False)
    win._can_auto_update = lambda: True
    monkeypatch.setattr(mainwindow.patch, "install_root", lambda: "C:/fake/install")
    win._update_found({"version": "9.9.9", "file": "AramHex-Setup-9.9.9.exe",
                       "sha256": "0" * 64, "url": "https://x/a.exe"})
    assert shown == []
    assert win.btn_update.text == "立即更新"   # 仍會提示有新版本


def test_auto_update_skips_while_ingame(monkeypatch):
    """對局中不要自動安裝，免得打斷遊戲。"""
    win, shown = _win()
    win.tray = None
    win.engine.settings = SimpleNamespace(auto_update=True)
    win.engine.snapshot = lambda: {"phase": "ingame"}
    win.isHidden = lambda: False
    win.isVisible = lambda: True
    win._can_auto_update = lambda: MainWindow._can_auto_update(win)
    monkeypatch.setattr(mainwindow.patch, "install_root", lambda: "C:/fake/install")
    win._update_found({"version": "9.9.9", "file": "AramHex-Setup-9.9.9.exe",
                       "sha256": "0" * 64, "url": "https://x/a.exe"})
    assert shown == []


def test_tw_build_ignores_upstream_min_version(monkeypatch):
    """台服版不採用上游版本門檻：雲控的 min_version 是國服 1.1.0，
    拿來和 1.0.0+tw.6 比會誤判成太舊，並把使用者導去下載國服版。"""
    win, _ = _win()

    class NoDialog:
        def __init__(self, *args, **kwargs):
            raise AssertionError("台服版不應顯示上游最低版本視窗")

    monkeypatch.setattr(mainwindow, "QMessageBox", NoDialog)
    MainWindow._apply_cloud(win, {"notice": {}, "min_version": "1.1.0"})
    assert not getattr(win, "_min_warned", False)


def test_upstream_min_version_still_warns_when_enabled(monkeypatch):
    win, _ = _win()
    monkeypatch.setattr(mainwindow, "UPSTREAM_MIN_VERSION_ENABLED", True)
    shown = []

    class FakeMessageBox:
        Warning, AcceptRole, RejectRole = 1, 2, 3

        def __init__(self, *args, **kwargs):
            shown.append(args)

        def addButton(self, *args):
            return None

        def exec(self):
            return 0

        def clickedButton(self):
            return object()

    monkeypatch.setattr(mainwindow, "QMessageBox", FakeMessageBox)
    MainWindow._apply_cloud(win, {"notice": {}, "min_version": "1.1.0"})
    assert len(shown) == 1 and win._min_warned


def test_no_update_path_leads_to_the_upstream_site():
    """台服版的每一個「去下載」路徑都必須指向本倉庫。

    aramhex.com 公布的是國服版（安裝包、網盤、版本門檻都是），任何一條路走回
    那裡，使用者就會被換成不能用的國服版。這個測試把每一條路都釘住。
    """
    from lolhex import DOWNLOAD_PAGE, RELEASES_PAGE, __version__, patch, update

    # 下載頁與 Release 頁都指向本倉庫
    assert DOWNLOAD_PAGE == RELEASES_PAGE
    assert "PaPaChk/aram-helper" in DOWNLOAD_PAGE
    assert "aramhex.com" not in DOWNLOAD_PAGE

    # 網盤連結一律不採用（上游雲控給的是國服 123pan）
    assert update.pan_links() == {}

    # 增量更新的每個來源都是本倉庫
    for url in patch.sources_for(__version__):
        assert "aramhex.com" not in url, url
        assert "PaPaChk/aram-helper" in url, url
