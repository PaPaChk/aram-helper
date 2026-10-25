"""增量更新要認得台服版的執行檔名 AramHexTW.exe。

以前只認上游的 AramHex.exe，於是 exe 本身永遠不在可替換清單裡：版本號更新了，
跑的還是舊外殼；替換完成後又用錯的檔名重啟，助手就再也不會自己回來。"""
from __future__ import annotations

import re
from pathlib import Path

from lolhex import patch


def test_portable_exe_name_is_patchable():
    assert patch.is_patchable("AramHexTW.exe")


def test_upstream_exe_name_still_patchable():
    """保留舊名字：上游國服版的包是 AramHex.exe，不能因為改了名字就不認它。"""
    assert patch.is_patchable("AramHex.exe")


def test_program_files_are_patchable():
    assert patch.is_patchable("_internal/base_library.zip")
    assert patch.is_patchable("_internal/lolhex/engine.py")
    assert patch.is_patchable("_internal/lolhex/vision/detector.py")


def test_third_party_binaries_need_a_full_install():
    """第三方庫（Qt、OpenCV、識別模型）變了就只能整包更新，不能增量替換。"""
    assert not patch.is_patchable("_internal/PySide6/Qt6Core.dll")
    assert not patch.is_patchable("_internal/cv2/cv2.pyd")
    assert not patch.is_patchable("_internal/onnxruntime/capi/onnxruntime.dll")


def test_the_real_exe_name_matches_what_the_spec_builds():
    """把 spec 裡的 name= 和 PATCHABLE_EXES 對上，避免以後改打包名又忘了改這裡。"""
    spec = Path(__file__).resolve().parent.parent / "packaging" / "lolhex.spec"
    text = spec.read_text(encoding="utf-8")
    m = re.search(r'name\s*=\s*"([^"]+)"', text)
    assert m, "spec 裡找不到 name="
    built = f"{m.group(1)}.exe"
    assert built in patch.PATCHABLE_EXES, f"spec 產出 {built}，但 PATCHABLE_EXES 是 {patch.PATCHABLE_EXES}"
