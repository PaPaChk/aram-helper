"""入口：python -m lolhex [選項]

  （無引數）          啟動助手（遊戲浮窗）
  --headless          不顯示浮窗，只跑識別（除錯用）
  --refresh           只重新整理資料並列印狀態後退出
  --scan-image 檔案   用一張遊戲截圖測試三選一識別（排查識別問題用）
  --hero 名稱         配合 --scan-image，指定英雄以輸出推薦
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .config import Settings, app_home


def _fix_stdio() -> None:
    """控制檯不是 UTF-8、或用 pythonw 啟動沒有控制檯時，輸出中文不能崩。"""
    import io
    import os
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8"))
        elif hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _setup_logging(debug: bool) -> None:
    home = app_home()
    handlers = [logging.StreamHandler(sys.stderr),
                logging.FileHandler(home / "aramhex.log", encoding="utf-8")]
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    for noisy in ("urllib3", "RapidOCR"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _ensure_dpi_awareness_for_capture() -> None:
    """非 GUI 分支：先確定程序的 DPI 感知，量度與截圖才在同一個像素空間。

    沒有 Qt 幫忙時，mss 會在它自己第一次截圖時才呼叫 shcore.SetProcessDpiAwareness(2)
    （mss/windows/gdi.py），於是同一次執行裡 client_rect() 在截圖前後回報兩種尺度
    （實測 2560x1440 → 3840x2160），視窗矩形和實際截到的 frame 就對不上。

    GUI 分支刻意不呼叫這個：Qt 建立 QApplication 時已經設成 per-monitor v2，先呼叫
    這裡會把它降級成 v1（實測會印出 SetProcessDpiAwarenessContext() failed）。
    GUI 路徑的 client_rect() 與 capture.grab() 已實測一致（3840x2160 兩邊相同）。
    """
    from .vision.window import enable_dpi_awareness
    enable_dpi_awareness()


def _scan_image(engine, path: str, hero: str | None) -> int:
    import cv2
    import numpy as np

    from . import recommend
    from .vision.detector import AugmentDetector

    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("讀不到圖片：", path)
        return 2
    engine.store.refresh()
    names = {aid: a["name"] for aid, a in engine.store.mayhem_augments().items()}
    from .vision.matcher import NameMatcher
    det = AugmentDetector(NameMatcher(names, engine.settings.match_threshold))
    offer = det.scan_full(img)
    if not offer:
        print("沒有識別到三選一畫面。")
        return 1
    hid = engine.store.resolve_hero(hero) if hero else None
    ev = recommend.evaluate(engine.store, hid, offer.slots, engine.settings.smoothing_games)
    out = {"size": [img.shape[1], img.shape[0]], "texts": offer.texts, "slots": offer.slots,
           "calibration": det.calibration.boxes if det.calibration else None,
           "advice": ev["advice"],
           "cards": [{k: r.get(k) for k in ("name", "rarity", "tier", "rank", "win", "games", "score", "verdict", "reasons")}
                     for r in ev["slots"]]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lolhex", description="海克斯大亂鬥助手")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--scan-image")
    ap.add_argument("--hero")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--minimized", action="store_true", help="啟動後只顯示托盤（開機自啟用）")
    ap.add_argument("--self-test-gui", metavar="REPORT", help="離線檢查打包後的 Qt 和視窗外掛，寫入 JSON 後退出")
    args = ap.parse_args(argv)

    if args.self_test_gui:
        from .gui_selftest import run
        return run(args.self_test_gui)

    _fix_stdio()
    _setup_logging(args.debug)
    settings = Settings.load()
    from . import __version__
    logging.getLogger("lolhex").info("海克斯大亂鬥助手 %s 啟動；目錄：%s；引數：%s", __version__,
                                     app_home(), " ".join(sys.argv[1:]) or "（無）")

    from .engine import Engine

    if args.refresh:
        engine = Engine(settings)
        engine.store.refresh(force=True)
        print(json.dumps(engine.store.status(), ensure_ascii=False, indent=2))
        return 0 if not engine.store.last_error else 1
    if args.scan_image:
        return _scan_image(Engine(settings), args.scan_image, args.hero)

    if args.headless:
        _ensure_dpi_awareness_for_capture()
        engine = Engine(settings)
        engine.start()
        print("海克斯大亂鬥助手已啟動（無介面）。Ctrl+C 退出")
        try:
            engine._stop.wait()
        except KeyboardInterrupt:
            pass
        return 0

    from .ui.overlay import run
    try:
        code = run(lambda: Engine(settings), minimized=args.minimized)
    except KeyboardInterrupt:
        code = 0
    # 介面已關：直接結束程序，不等後臺執行緒收尾（卡住時會佔著程式檔案，導致更新替換失敗）
    logging.shutdown()
    os._exit(code or 0)


if __name__ == "__main__":
    sys.exit(main())
