"""自動截圖：每次三選一、每次選英雄各截一張；截圖那一下浮窗臨時可截，截完恢復，期間暫停識別。"""
import time
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("PySide6")

from lolhex.ui import autoshot  # noqa: E402
from lolhex.vision import capture, window  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    later = []
    monkeypatch.setattr(autoshot.QTimer, "singleShot", lambda ms, fn: later.append(fn))
    shots = []

    def grab(rect):
        shots.append(window.capture_allowed())  # 截的那一刻浮窗是否可截
        return np.full((40, 60, 3), 128, np.uint8) + np.arange(60, dtype=np.uint8)[None, :, None]
    monkeypatch.setattr(capture, "grab", grab)
    monkeypatch.setattr(window, "_overlay_windows", set())
    window.set_capture_allowed(False)
    engine = SimpleNamespace(settings=SimpleNamespace(auto_screenshot=True, allow_capture=False), vision_hold_until=0.0)
    return autoshot.AutoShot(engine), later, shots, engine


def run(later):
    while later:
        later.pop(0)()


def test_one_shot_per_offer_and_restores_capture(env):
    shot, later, shots, engine = env
    snap = {"evaluation": {"x": 1}, "offer": {"slots": ["1", "2", "3"]}}
    shot.tick(snap, "rect", None)
    run(later)
    assert shots == [True] and not window.capture_allowed()  # 截時可截，截完恢復
    assert engine.vision_hold_until > time.monotonic() - 1  # 截圖期間暫停過識別
    shot.tick(snap, "rect", None)  # 同一次三選一不重複截
    run(later)
    assert len(shots) == 1
    shot.tick({**snap, "offer": {"slots": ["4", "5", "6"]}}, "rect", None)  # 重新整理後換了三張：再截
    run(later)
    assert len(shots) == 2
    files = sorted(p.name for p in autoshot.shots_dir().glob("*.png"))
    assert len(files) == 2 and all(n.endswith("-三選一.png") for n in files)


def test_champ_select_waits_until_labels_settle(env, monkeypatch):
    shot, later, shots, _ = env
    clock = [100.0]
    monkeypatch.setattr(autoshot.time, "monotonic", lambda: clock[0])
    def cs(n):
        return {"champ_select": {"team": [{"hero_id": str(i), "grade": "A"} for i in range(n)], "bench": []}}
    shot.tick(cs(2), None, "client"); run(later)
    clock[0] += 2; shot.tick(cs(4), None, "client"); run(later)   # 還在陸續識別：不截
    assert not shots
    clock[0] += 4; shot.tick(cs(4), None, "client"); run(later)   # 4 個穩定 4 秒：截
    assert len(shots) == 1
    clock[0] += 5; shot.tick(cs(4), None, "client"); run(later)   # 沒變化：不重複截
    assert len(shots) == 1
    shot.tick(cs(5), None, "client"); clock[0] += 5; shot.tick(cs(5), None, "client"); run(later)  # 又多標一個：再截
    assert len(shots) == 2
    shot.tick({"champ_select": None}, None, None)                  # 離開選人介面：下一局重新算
    shot.tick(cs(3), None, "client"); clock[0] += 5; shot.tick(cs(3), None, "client"); run(later)
    assert len(shots) == 3


def test_off_by_default_does_nothing(env):
    shot, later, shots, engine = env
    engine.settings.auto_screenshot = False
    shot.tick({"evaluation": {"x": 1}, "offer": {"slots": ["1", "2", "3"]}}, "rect", None)
    assert not later and not shots