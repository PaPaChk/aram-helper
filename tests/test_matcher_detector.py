import pytest
from conftest import fixture

from lolhex.data.tencent import parse_kiwi_augments
from lolhex.data.tw_localization import TWLocalizer
from lolhex.vision.matcher import NameMatcher, normalize

AUGS = parse_kiwi_augments(fixture("tencent_kiwi_augments.json"))
LOC = TWLocalizer()
DISPLAY = {k: (LOC.augments.get(k, {}).get("name_zh") or v["name"]) for k, v in AUGS.items()}
NAMES = {k: [DISPLAY[k], v["name"]] for k, v in AUGS.items()}


def test_normalize():
    assert normalize("質變：稜鏡") == normalize("質變:稜鏡") == "質變稜鏡"
    assert normalize("質變:稜彩階") == "質變稜彩階"


def test_matcher_tolerates_ocr_noise():
    m = NameMatcher(NAMES)
    assert m.match("幻影武器")[0] == "1029"
    assert m.match("質變:棱彩階")[0] == "1238"
    assert m.match("熾燃利忌")[0] == "2128"          # 一個字識別錯
    assert m.match("獲得1個隨機強化符文。")[0] is None  # 描述文字不應命中
    assert m.match("A")[0] is None


def test_engine_matcher_uses_tw_catalog_when_tencent_static_is_stale(store, tmp_path):
    """靜態資料還沒補到新 ID 時，仍要用台服 catalog 名稱完成 OCR 識別。"""
    from lolhex.config import Settings
    from lolhex.engine import Engine

    engine = Engine(Settings(), home=tmp_path, store=store)
    matcher = engine._augment_matcher()
    assert matcher.match("終極革新")[0] == "1088"
    assert matcher.match("風語者的祝福")[0] == "1095"
    assert matcher.match("最終型態")[0] == "1344"


rapidocr = pytest.importorskip("rapidocr")
synth = pytest.importorskip("synth")
if not synth.fonts_available():
    pytest.skip("沒有中文字型，跳過合成畫面測試", allow_module_level=True)


@pytest.fixture(scope="module")
def detector():
    from lolhex.vision.detector import AugmentDetector
    return AugmentDetector(NameMatcher(NAMES))


def names(offer):
    return [DISPLAY.get(s) if s else None for s in offer.slots]


@pytest.mark.parametrize("size", [(3840, 2160), (1920, 1080)])
def test_full_scan_calibrates_and_strip_tracks_reroll(detector, size):
    from lolhex.vision.window import Rect
    detector.calibration = None
    offer = detector.scan_full(synth.render_offer(["質變：稜鏡", "燃燒利息", "幻影武器"], size))
    assert names(offer) == ["質變：稜鏡", "燃燒利息", "幻影武器"]
    assert detector.calibrated_for(*size)

    win = Rect(0, 0, *size)
    sr = detector.strip_rect(win)
    frame = synth.render_offer(["泰坦的決意", "燃燒利息", "幻影武器"], size, seed=3)
    offer2 = detector.check_strip(frame[sr.top:sr.bottom, sr.left:sr.right], win)
    assert names(offer2) == ["泰坦的決意", "燃燒利息", "幻影武器"]

    empty = synth.render_offer([None, None, None], size, seed=4)
    assert detector.check_strip(empty[sr.top:sr.bottom, sr.left:sr.right], win) is None

    # 點選位置對映到卡片列
    b = detector.calibration.pixel_boxes(*size)[2]
    assert detector.column_of((b[0] + b[2]) // 2, b[3] + 50, win) == 2


@pytest.mark.parametrize("ui_scale", [0.75, 1.0, 1.25])
@pytest.mark.parametrize("size", [(1920, 1080), (2560, 1440)])
def test_dynamic_detection_handles_ui_scale(tmp_path, size, ui_scale):
    """卡牌大小隨玩家 UI scale 改變，首次偵測仍要由 OCR 自行建立校準。"""
    from lolhex.vision.detector import AugmentDetector

    det = AugmentDetector(NameMatcher(NAMES), tmp_path / "ignored.json")
    det.ensure_calibration(*size)
    assert det.calibration is None
    offer = det.scan_full(synth.render_offer(
        ["質變：稜鏡", "燃燒利息", "幻影武器"], size, ui_scale=ui_scale))
    assert names(offer) == ["質變：稜鏡", "燃燒利息", "幻影武器"]
    assert det.calibration is not None


def test_two_cards_are_placed_by_symmetry(detector):
    size = (3840, 2160)
    assert names(detector.scan_full(synth.render_offer(["燃燒利息", None, "幻影武器"], size))) == ["燃燒利息", None, "幻影武器"]
    assert names(detector.scan_full(synth.render_offer([None, "燃燒利息", "幻影武器"], size))) == [None, "燃燒利息", "幻影武器"]


def test_no_offer_on_plain_screen(detector):
    assert detector.scan_full(synth.render_offer([None, None, None], (3840, 2160), seed=9)) is None


def test_no_guessed_calibration_is_loaded_from_disk(tmp_path):
    """舊版留下的比例框不可信；首次偵測必須先跑整屏 OCR。"""
    from lolhex.vision.detector import AugmentDetector

    path = tmp_path / "calibration.json"
    path.write_text('{"boxes": [[0,0,1,1]], "size": [1920, 1080]}', encoding="utf-8")
    det = AugmentDetector(NameMatcher(NAMES), path)
    det.ensure_calibration(1920, 1080)
    assert det.calibration is None
    assert not det.confirmed_for(1920, 1080)
