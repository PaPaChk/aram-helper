from pathlib import Path
import json

import cv2
import pytest

from lolhex.vision.matcher import NameMatcher

pytest.importorskip("rapidocr")


def _matcher() -> NameMatcher:
    root = Path(__file__).resolve().parent.parent
    catalog = json.loads((root / "lolhex" / "data" / "bundled" / "tw-catalog.json").read_text(encoding="utf-8"))
    names = {str(a["id"]): [a.get("name_zh"), a.get("name_en")] for a in catalog["augments"]}
    return NameMatcher(names)


@pytest.mark.parametrize("filename, slots", [
    ("real-tw-offer-4k.png", ["1088", "1095", "1344"]),
    ("real-tw-offer-2k.png", ["1088", "1095", "1344"]),
    ("real-tw-offer-1080p.png", ["1088", "1095", "1344"]),
    ("real-tw-offer-gold.png", ["2032", "1328", "1068"]),
    ("real-tw-offer-silver.png", ["1136", "2024", "1007"]),
])
def test_real_tw_client_screenshots(filename, slots):
    """台服實機 4K、2K、1080p、金色與銀色卡牌；UI 與稀有度都要動態找到三張。"""
    from lolhex.vision.detector import AugmentDetector

    root = Path(__file__).resolve().parent.parent
    frame = cv2.imread(str(root / "tests" / "fixtures" / filename))
    assert frame is not None
    det = AugmentDetector(_matcher())
    offer = det.scan_full(frame)
    assert offer is not None
    assert offer.slots == slots
    assert offer.matched() == 3
    assert all(text for text in offer.texts)
    assert det.calibration is not None


def test_catalog_covers_the_full_kiwi_augment_list():
    """回歸：內建 catalog 曾經只有 594 個海克斯裡的 450 個，缺的那批正好包含
    3088（官方台服名「血色鈷石」），所以那張卡無論 OCR 多準都配不到名字。"""
    root = Path(__file__).resolve().parent.parent
    catalog = json.loads((root / "lolhex" / "data" / "bundled" / "tw-catalog.json").read_text(encoding="utf-8"))
    augments = {str(a["id"]): a for a in catalog["augments"]}
    assert len(augments) >= 590
    assert augments["3088"]["name_zh"] == "血色鈷石"
    assert all(a.get("name_zh") for a in augments.values())


def test_ocr_misread_of_blood_diamond_still_matches():
    """OCR 讀成「血色鈷石」也要配到 3088；這是使用者實機截圖上的真實字串。"""
    aid, score = _matcher().match("血色鈷石")
    assert aid == "3088"
    assert score >= 72
