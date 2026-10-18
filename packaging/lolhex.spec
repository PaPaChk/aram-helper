# PyInstaller 配置：海克斯大亂鬥助手（onedir，無控制檯視窗）。
# 用法：pyinstaller packaging/lolhex.spec --noconfirm --distpath build/dist --workpath build/work
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPEC).parent))
from binary_provenance import check_binary_sources

datas = collect_data_files("rapidocr")  # OCR 模型（.onnx）與配置（.yaml）
datas += [("../lolhex/ui/icon.png", "lolhex/ui")]
datas += [("../lolhex/data/hero_aliases.json", "lolhex/data")]  # 英雄別名（來源 Hexdata）
datas += [("../lolhex/data/bundled", "lolhex/data/bundled")]  # 內建統計資料（scripts/update_data.py）
datas += [("../lolhex/data/hero_nicknames.json", "lolhex/data")]  # 英雄外號（網上常見叫法）
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    ["launcher.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=["lolhex.ui.overlay", "lolhex.vision.detector", "lolhex.vision.capture", "lolhex.vision.ocr",
                   "lolhex.game.liveclient", "lolhex.ui.mainwindow", "lolhex.ui.autostart",
                   "PySide6.QtNetwork"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
check_binary_sources(a.binaries, [sys.prefix, sys.base_prefix, os.environ["SystemRoot"], Path(SPEC).parent.parent])

# 精簡：去掉用不到的大檔案（壓縮後共約 20MB）。打包後的自檢會跑一遍 OpenCV 和文字識別，確認沒刪到要用的。
# - opencv_videoio_ffmpeg：影片解碼，我們只處理截圖
# - opengl32sw.dll：Qt 的軟體 OpenGL，介面只用 Widgets
# - PIL 的 _avif：AVIF 圖片格式
# - qdirect2d.dll：Qt 的 Direct2D 平臺外掛，用的是 qwindows
# - PySide6/translations：Qt 自帶介面的翻譯，程式沒有載入
DROP_BINARIES = ("opencv_videoio_ffmpeg", "opengl32sw.dll", "PIL/_avif.", "platforms/qdirect2d.dll")


def _keep(entry):
    name = entry[0].replace("\\", "/")
    return not any(k in name for k in DROP_BINARIES) and not name.startswith("PySide6/translations/")


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AramHexTW",
    console=False,
    icon="lolhex.ico",
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AramHexTW")
