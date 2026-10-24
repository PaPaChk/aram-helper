"""校準驗證、id 空間選擇、硬重置。

使用者回報的三件事：
1. 同一個 3840x2160 介面四次校準出現三種 y（0.4177/0.3859/0.4198），錯的那次
   把描述行／道具提示當成卡片標題，之後永遠掃錯位置且不報錯。
2. 同一個名字同時對到騰訊 id（1115，有勝率資料）和 CommunityDragon 裸 id（115，
   沒資料），舊版靠 dict 走訪順序挑，識別正確卻變成「暫無可靠資料」甚至推薦錯誤。
3. 「重新識別」按不動時需要一個重新開始的按鈕。
"""
from __future__ import annotations

import random
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lolhex.vision.detector import AugmentDetector, Calibration
from lolhex.vision.matcher import NameMatcher
from lolhex.vision.ocr import TextLine


@pytest.fixture
def home():
    """Engine 要一個 home 目錄；這幾個測試不會真的寫入它。

    刻意不建目錄、不寫檔：IconCache 只在 __init__ 記住路徑，識別與重置流程用不到
    檔案。這樣測試完全不依賴可寫的暫存目錄（這台機器上 pytest 的 basetemp 不可寫）。"""
    return Path(__file__).resolve().parent / "_unused_home"


def _line(text, x0, y0, x1, y1):
    return TextLine(text, 100.0, (x0, y0, x1, y1))


def _group(W=3840, H=2160, cy=0.418, h=52, centers=(0.308, 0.5, 0.692)):
    """三張卡的標題：正常情況。cy 是相對高度。"""
    out = []
    y = cy * H
    for i, f in enumerate(centers):
        cx = f * W
        out.append((_line(f"卡{i}", int(cx - 100), int(y - h / 2), int(cx + 100), int(y + h / 2)),
                    str(1000 + i), 100.0))
    out.sort(key=lambda t: t[0].cx)
    return out


class EchoMatcher:
    threshold = 72.0

    def match(self, text):
        return (None, 0.0)


class FakeOCR:
    def recognize(self, img):
        return ("", 0.0)

    def detect(self, img):
        return []


def _det():
    return AugmentDetector(EchoMatcher(), ocr=FakeOCR())


# ---------- 1. 校準驗證 ----------

def test_plausible_accepts_normal_three_card_row():
    det = _det()
    assert det._plausible(_group(), 3840, 2160)


def test_implausible_row_is_rejected_and_leaves_calibration_alone():
    """把描述行當成標題湊出來的一行（y 明顯偏離、貼近邊緣）不得被採用。"""
    det = _det()
    assert det.calibration is None
    det._calibrate(_group(cy=0.418), 3840, 2160)
    good = det.calibration
    assert good is not None
    bad = _group(cy=0.95, h=20, centers=(0.10, 0.5, 0.90))
    det._calibrate(bad, 3840, 2160)
    assert det.calibration is good  # 保留原本的校準


def test_rejected_candidate_does_not_log_as_calibrated(caplog):
    det = _det()
    bad = _group(cy=0.95, h=20, centers=(0.10, 0.5, 0.90))
    with caplog.at_level("INFO"):
        det._calibrate(bad, 3840, 2160)
    assert det.calibration is None
    assert "已校準" not in caplog.text


def test_uneven_spacing_is_rejected():
    det = _det()
    assert not det._plausible(_group(centers=(0.15, 0.30, 0.80)), 3840, 2160)


def test_vertical_mismatch_is_rejected():
    det = _det()
    g = _group()
    ln, aid, sc = g[2]
    y0, y1 = ln.box[1], ln.box[3]
    g[2] = (TextLine(ln.text, ln.score, (ln.box[0], y0 + 200, ln.box[2], y1 + 200)), aid, sc)
    assert not det._plausible(g, 3840, 2160)


def test_stable_calibration_not_replaced_by_single_outlier():
    """現有校準還在出結果時，一格畫面的不同候選不得立刻換掉它。"""
    det = _det()
    det._calibrate(_group(cy=0.418), 3840, 2160)
    good = det.calibration
    det._last_result = object()  # 假裝目前校準仍在產生結果
    det._calibrate(_group(cy=0.395), 3840, 2160)   # 第一次出現：只記錄候選
    assert det.calibration is good
    det._calibrate(_group(cy=0.395), 3840, 2160)   # 第二次一致：才替換
    assert det.calibration is not good


# ---------- 2. id 空間 ----------

def test_ambiguous_name_prefers_id_with_stats():
    """同一個名字對到 1115（有資料）和 115（沒資料）時，必須選 1115。"""
    names = {"1115": ["頂狙武器"], "115": ["頂狙武器"]}
    m = NameMatcher(names, 72.0, preferred={"1115", "1041", "1048"})
    assert m.match("頂狙武器")[0] == "1115"


def test_ambiguous_id_choice_is_order_independent():
    """走訪順序不能影響結果（舊版的 bug）。"""
    base = {"1115": ["頂狙武器"], "115": ["頂狙武器"],
            "1041": ["巨人"], "41": ["巨人"]}
    preferred = {"1115", "1041"}
    got = set()
    for seed in range(8):
        items = list(base.items())
        random.Random(seed).shuffle(items)
        m = NameMatcher(dict(items), 72.0, preferred=preferred)
        got.add((m.match("頂狙武器")[0], m.match("巨人")[0]))
    assert got == {("1115", "1041")}


def test_without_preferred_longer_id_wins_deterministically():
    """沒有評分層提示時，仍要穩定（騰訊 1000+n 較長，優先）。"""
    for seed in range(6):
        items = [("1115", ["頂狙武器"]), ("115", ["頂狙武器"])]
        random.Random(seed).shuffle(items)
        m = NameMatcher(dict(items), 72.0)
        assert m.match("頂狙武器")[0] == "1115"


class _FakeStore:
    """只提供 Engine 用到的幾個介面，避免依賴 tmp_path（沙箱裡寫不了）。"""

    def __init__(self):
        self.augments = {"1115": {"name": "頂狙武器"}, "1041": {"name": "巨人"},
                         "1048": {"name": "寶石手套"}}
        self.ranks = {"augments": {"1115": {}, "1041": {}, "1048": {}}}
        self.heroes = {}
        self.localizer = SimpleNamespace(augments={
            "115": {"name_zh": "頂狙武器", "name_en": "Sniper"},
            "41": {"name_zh": "巨人", "name_en": "Giant"},
        })

    def mayhem_augments(self):
        return self.augments

    def status(self):
        return {}

    def set_band(self, _b):
        pass


def test_engine_matcher_resolves_to_scoring_id_space(home):
    """真實 Engine 路徑：同名同時存在於兩套 id 時，必須選評分層認得的那一個。"""
    from lolhex.config import Settings
    from lolhex.engine import Engine

    engine = Engine(Settings(), home=home, store=_FakeStore())
    m = engine._augment_matcher()
    assert m.match("頂狙武器")[0] == "1115"   # 不是 CommunityDragon 的 115
    assert m.match("巨人")[0] == "1041"       # 不是 41
    aid = m.match("寶石手套")[0]
    assert aid in engine.store.augments


# ---------- 3. 硬重置 ----------

def test_hard_reset_clears_recognition_state_but_keeps_settings(home):
    from lolhex.config import Settings
    from lolhex.engine import Engine

    settings = Settings()
    settings.show_winrate = False
    engine = Engine(settings, home=home, store=_FakeStore())
    engine._detector = AugmentDetector(EchoMatcher(), ocr=FakeOCR())
    engine._detector.calibration = Calibration([(0.1, 0.4, 0.2, 0.5)] * 3, (1920, 1080))
    engine._detector._last_fp = np.zeros((12, 96), np.int16)
    engine._detector._last_result = object()
    engine._cs_memo = object()
    engine.settings.overlay = True
    engine._set(offer={"slots": ["1", None, None], "texts": [], "scores": [], "boxes": [], "at": 0.0},
                evaluation={"advice": "x"}, champ_select={"bench": [], "team": []})

    engine.hard_reset()

    assert engine._detector.calibration is None
    assert engine._detector._last_fp is None
    assert engine._detector._last_result is None
    assert engine._cs_memo is None
    assert engine.state["offer"] is None
    assert engine.state["evaluation"] is None
    assert engine.state["champ_select"] is None
    assert engine.state["vision"]["calibrated"] is False
    assert engine._rescan.is_set()            # 下一輪立刻整屏掃描
    # 使用者的東西不能動
    assert engine.settings.show_winrate is False
    assert engine.settings.overlay is True
    assert isinstance(engine.store, _FakeStore)


def test_hard_reset_is_safe_without_detector(home):
    from lolhex.config import Settings
    from lolhex.engine import Engine

    engine = Engine(Settings(), home=home, store=_FakeStore())
    engine.hard_reset()                        # 還沒建立 detector 也不能炸
    assert engine.state["offer"] is None
