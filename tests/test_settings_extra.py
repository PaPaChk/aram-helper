"""識別頻率檔位和"錄屏、截圖時顯示浮窗"開關。"""
import json

from lolhex.config import SPEEDS, Settings
from lolhex.vision import window


def test_speed_factor(tmp_path):
    p = tmp_path / "config.json"
    s = Settings.load(p)
    assert s.speed == "standard" and s.speed_factor == 1.0
    p.write_text(json.dumps({"speed": "low"}), encoding="utf-8")
    assert Settings.load(p).speed_factor == SPEEDS["low"][1] == 4.0
    p.write_text(json.dumps({"speed": "不存在"}), encoding="utf-8")
    assert Settings.load(p).speed_factor == 1.0  # 認不出的檔位按標準


def test_capture_toggle_applies_to_open_windows(monkeypatch):
    applied = []
    monkeypatch.setattr(window, "_apply_affinity", lambda h: applied.append((h, window._capture_allowed)))
    monkeypatch.setattr(window, "_overlay_windows", set())
    monkeypatch.delenv("LOLHEX_DEBUG_CAPTURABLE", raising=False)
    window.set_capture_allowed(False)
    window.exclude_from_capture(101)
    window.exclude_from_capture(202)
    assert applied == [(101, False), (202, False)]
    applied.clear()
    window.set_capture_allowed(True)  # 開啟後，已經開著的浮窗立即能被截到
    assert sorted(applied) == [(101, True), (202, True)] and window.capture_allowed()
    window.set_capture_allowed(False)


def test_overlay_is_capturable_by_default(tmp_path):
    """浮窗預設就要能被截圖、錄影。

    使用者要能把浮窗內容截下來分享；預設排除會讓人以為功能壞了。
    要維持這個預設值，別又改回 False。
    """
    s = Settings.load(tmp_path / "config.json")
    assert s.allow_capture is True

    # 沒有任何設定檔時，浮窗屬性要直接是可截取的
    from lolhex.vision import window as w

    w.set_capture_allowed(s.allow_capture)
    assert w.capture_allowed() is True


def test_allow_capture_can_still_be_turned_off(tmp_path):
    """想畫面乾淨的人還是可以關掉，關掉後就不會被截到。"""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"allow_capture": False}), encoding="utf-8")
    assert Settings.load(p).allow_capture is False