"""啟動冒煙測試：overlay.run 能走到事件迴圈（1.0.8/1.0.9 曾因變數名衝突一啟動就崩）。"""
import pytest

pytest.importorskip("PySide6")


def test_run_starts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    from lolhex.config import Settings
    from lolhex.engine import Engine
    from lolhex.ui import mainwindow, overlay

    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(mainwindow.MainWindow, "check_update", lambda self, manual=False: None)
    monkeypatch.setattr(Engine, "start", lambda self: None)
    s = Settings.load(tmp_path / "config.json")
    s.check_data_updates = False
    assert overlay.run(lambda: Engine(s), minimized=True) == 0


def test_version_notice_once(tmp_path, monkeypatch):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    from lolhex import __version__
    from lolhex.config import Settings
    from lolhex.ui.overlay import version_notice
    s = Settings.load(tmp_path / "config.json")
    assert version_notice(s) is None            # 第一次安裝：不提示
    assert version_notice(s) is None            # 同一個版本再開：不提示
    s.last_version = "0.0.1"                    # 模擬剛從舊版本更新上來
    assert version_notice(s) == f"已更新到 {__version__}"
    assert version_notice(s) is None            # 只提示一次
    old = tmp_path / "old.json"                 # 老版本留下的設定檔案（沒有 last_version）
    old.write_text('{"show_winrate": true}', encoding="utf-8")
    assert version_notice(Settings.load(old)) == f"已更新到 {__version__}"


def test_launcher_shows_friendly_error(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("launcher", Path(__file__).parent.parent / "packaging" / "launcher.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    path = launcher._crash_log("Traceback: 測試")
    assert path and "測試" in Path(path).read_text(encoding="utf-8")


def test_blank_capture_warns_once():
    from types import SimpleNamespace
    from lolhex.ui import overlay
    said = []
    ov = SimpleNamespace(visible=True, notify=said.append,
                         engine=SimpleNamespace(snapshot=lambda: {"vision": {"blank": True}}))
    for _ in range(3):
        try:
            overlay.Overlay._tick(ov)
        except AttributeError:
            pass  # 後面畫浮窗的部分在這個替身上沒有，提醒已經發了
    assert len(said) == 1 and "無邊框" in said[0]
