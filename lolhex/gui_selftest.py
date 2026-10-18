"""打包後的離線自檢：在讀配置、聯網、啟動工作執行緒之前，跑一遍 Qt 視窗、OpenCV 和文字識別。

安裝包精簡時刪掉了一些用不到的庫檔案；這裡實際呼叫一遍識別要用的功能，刪多了就會失敗，build.ps1 據此拒絕生成安裝包。
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path


def _vision_check() -> dict:
    """OpenCV 的圖片處理和 RapidOCR 的檢測、識別：畫一行字，再認出來。"""
    import cv2
    import numpy as np

    img = np.full((96, 480, 3), 255, np.uint8)
    cv2.putText(img, "AramHex 2026", (12, 64), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    ok, buf = cv2.imencode(".png", img)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    img = cv2.resize(img, None, fx=1.0, fy=1.0, interpolation=cv2.INTER_AREA)
    from .vision.ocr import OCR
    ocr = OCR.get()
    text, score = ocr.recognize(img)
    lines = ocr.detect(img)
    return {"ocr_text": text, "ocr_score": round(score, 3), "ocr_lines": [ln.text for ln in lines],
            "ocr_ok": bool(ok) and "2026" in text and any("2026" in ln.text for ln in lines)}


def run(report_path: str) -> int:
    report = {"success": False}
    try:
        from PySide6.QtCore import qVersion
        from PySide6.QtGui import QPixmap
        from PySide6.QtNetwork import QNetworkAccessManager
        from PySide6.QtWidgets import QApplication, QWidget
        from . import __version__
        app = QApplication([])
        widget = QWidget()
        widget.resize(32, 32)
        widget.ensurePolished()
        pixmap = QPixmap(widget.size())
        widget.render(pixmap)
        network = QNetworkAccessManager()
        app.processEvents()
        report.update(version=__version__, qt=qVersion(), platform=app.platformName(),
                      network_class=network.metaObject().className(), gui_ok=not pixmap.isNull())
        widget.close()
        report.update(_vision_check())
        report["success"] = report["gui_ok"] and report["ocr_ok"]
        app.quit()
    except Exception:
        report["error"] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["success"] else 1
