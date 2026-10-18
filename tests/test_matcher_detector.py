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


def test_two_cards_are_placed_by_symmetry(detector):
    size = (3840, 2160)
    assert names(detector.scan_full(synth.render_offer(["燃燒利息", None, "幻影武器"], size))) == ["燃燒利息", None, "幻影武器"]
    assert names(detector.scan_full(synth.render_offer([None, "燃燒利息", "幻影武器"], size))) == [None, "燃燒利息", "幻影武器"]


def test_no_offer_on_plain_screen(detector):
    assert detector.scan_full(synth.render_offer([None, None, None], (3840, 2160), seed=9)) is None


@pytest.mark.parametrize("size", [(3840, 2160), (1920, 1080), (2560, 1600)])
def test_default_calibration_reads_first_offer(tmp_path, size):
    """沒校準過也能直接走輕量檢查；三張都對上後存成本機校準。"""
    from lolhex.vision.detector import AugmentDetector
    from lolhex.vision.window import Rect
    det = AugmentDetector(NameMatcher(NAMES), tmp_path / "calibration.json")
    det.ensure_calibration(*size)
    assert det.calibrated_for(*size) and not det.confirmed_for(*size)
    win = Rect(0, 0, *size)
    sr = det.strip_rect(win)
    frame = synth.render_offer(["質變：稜鏡", "燃燒利息", "幻影武器"], size)
    offer = det.check_strip(frame[sr.top:sr.bottom, sr.left:sr.right], win)
    assert names(offer) == ["質變：稜鏡", "燃燒利息", "幻影武器"]
    assert det.confirmed_for(*size)
    assert AugmentDetector(NameMatcher(NAMES), tmp_path / "calibration.json").confirmed_for(*size)
