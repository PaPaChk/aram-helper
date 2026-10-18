"""遊戲機端核心排程：英雄識別、海克斯識別與推薦。**不接入 LCU**。

執行緒：
- data：啟動時及定期重新整理資料（騰訊官方資料；自採統計資料有新版本時下載）；
- observer：只看視窗是否存在——客戶端在前臺且遊戲沒開時，截圖識別選英雄介面：
  頭像比對認出預選欄和我方的英雄（標勝率），OCR 認出自己的英雄名；
  可選讀取遊戲內 2999 介面（預設關閉）；
- vision：遊戲視窗在前臺時截圖識別海克斯三選一。
浮窗只讀 snapshot()，並透過 set_hero / rescan / reset_calibration 操作。
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from pathlib import Path

from . import recommend
from .config import Settings, app_home
from .data.public import PublicStore
from .data.store import DataStore
from .panel import hero_panel
from .vision import window as win
from .vision.matcher import NameMatcher

log = logging.getLogger(__name__)


def pick_my_hero(found: list[tuple[str, float, int]]) -> tuple[str | None, list[str]]:
    """選英雄介面 OCR 到的英雄名 → (本人英雄, 候選)。
    found: [(heroId, 匹配分, 文字高度)]。介面上自己的英雄名字號最大；
    最大字號明顯大於其他（≥1.3 倍）才自動認定，否則只給候選讓玩家點選。"""
    best: dict[str, tuple[float, int]] = {}
    for hid, sc, h in found:
        if hid not in best or h > best[hid][1]:
            best[hid] = (sc, h)
    order = sorted(best, key=lambda k: (-best[k][1], -best[k][0]))
    if not order:
        return None, []
    if len(order) == 1 or best[order[0]][1] >= 1.3 * best[order[1]][1]:
        return order[0], order[:6]
    return None, order[:6]


# 國服勝率排名 → 評級：前 10% S，30% A，60% B，85% C，其餘 D
GRADES = ((0.10, "S"), (0.30, "A"), (0.60, "B"), (0.85, "C"), (1.01, "D"))


def rank_grade(rank, total) -> str | None:
    if not rank or not total:
        return None
    q = rank / total
    return next(g for lim, g in GRADES if q <= lim)


class Engine:
    def __init__(self, settings: Settings, home: Path | None = None, store: DataStore | None = None):
        self.settings = settings
        self.home = home or app_home()
        if store is not None:
            self.store = store
        else:
            self.store = PublicStore(self.home / "data", settings.refresh_hours,
                                     check_updates=settings.check_data_updates)
        if hasattr(self.store, "set_band"):
            self.store.set_band(settings.data_band or None)
        self.live = None
        if settings.use_liveclient:
            from .game.liveclient import LiveClient
            self.live = LiveClient()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._rescan = threading.Event()
        self._detector = None  # 延遲建立，避免沒進遊戲就載入 OCR 模型
        self._icon_bank = None  # 英雄頭像庫，頭像下載好後建立
        from .data.icons import IconCache
        self.icons = IconCache(self.home / "data" / "img")  # 裝備、召喚師技能小圖示
        self._cs_memo = None    # 選人介面各位置的識別結果快取（champselect.Memo）
        self.vision_hold_until = 0.0  # time.monotonic() 在這之前暫停識別（自動截圖用）
        self._manual_hero = False
        self._panel_cache: tuple[str | None, dict | None] = (None, None)
        self.state: dict = {
            "phase": None,  # None / client / ingame
            "hero_id": None, "hero_source": None, "hero_candidates": [],
            "level": None, "game_window": False, "client_window": False,
            "vision": {"status": "idle", "calibrated": False, "last_scan": None, "blank": False},
            "offer": None, "evaluation": None,
            "champ_select": None,  # {"bench": [...], "team": [...]}，每項帶勝率和排名
        }

    # ---------- 生命週期 ----------

    def start(self) -> None:
        for name, fn in (("data", self._data_loop), ("observer", self._observer_loop),
                         ("vision", self._vision_loop)):
            threading.Thread(target=fn, name=name, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict:
        with self._lock:
            s = copy.deepcopy(self.state)
        s["data"] = self.store.status()
        s["settings"] = {"show_winrate": self.settings.show_winrate}
        s["hero"] = self.store.heroes.get(s["hero_id"] or "")
        s["candidates"] = [self.store.heroes.get(h, {"id": h}) for h in s["hero_candidates"]]
        return s

    def _set(self, **kw) -> None:
        with self._lock:
            self.state.update(kw)

    # ---------- 玩家操作 ----------

    def set_hero(self, hero_key) -> None:
        hid = self.store.resolve_hero(hero_key) if hero_key else None
        self._manual_hero = hid is not None
        self._set(hero_id=hid, hero_source="manual" if hid else None, hero_candidates=[])
        if hid:
            threading.Thread(target=self._prefetch_hero, args=(hid,), daemon=True).start()
        self._reevaluate()

    def set_band(self, band: str | None) -> None:
        """切換參考分數段（None/"" = 全體），記住選擇，並按新資料重算面板和三選一推薦。"""
        self.settings.data_band = band or ""
        self.settings.save()
        if hasattr(self.store, "set_band"):
            self.store.set_band(band or None)
        self._panel_cache = (None, None)
        hid = self.state.get("hero_id")
        if hid:
            threading.Thread(target=self._prefetch_hero, args=(hid,), daemon=True).start()
        self._reevaluate()

    def correct_slot(self, index: int, augment_id: str | None) -> None:
        with self._lock:
            offer = self.state.get("offer")
            if not offer or not 0 <= index < 3:
                return
            offer["slots"][index] = augment_id
            offer["corrected"] = True
        self._reevaluate()

    def rescan(self) -> None:
        if self._detector:
            self._detector._last_fp = None
        self._rescan.set()

    def reset_calibration(self) -> None:
        if self._detector:
            self._detector.reset_calibration()
        self.state["vision"]["calibrated"] = False
        self._rescan.set()

    def hero_panel(self, hero_key) -> dict | None:
        hid = self.store.resolve_hero(hero_key)
        if self._panel_cache[0] == hid and self._panel_cache[1]:
            return self._panel_cache[1]
        p = hero_panel(self.store, hid, self.settings.smoothing_games) if hid else None
        self._panel_cache = (hid, p)
        return p

    # ---------- 資料 ----------

    def _data_loop(self) -> None:
        self._warm_up()
        while not self._stop.is_set():
            try:
                self.store.refresh()
                self._load_icons()
                if self._detector:
                    self._detector.set_matcher(self._augment_matcher())
                self._panel_cache = (None, None)
                self._reevaluate()
            except Exception:
                log.exception("資料重新整理異常")
            self._stop.wait(max(600.0, self.settings.refresh_hours * 3600 / 4))

    def _warm_up(self) -> None:
        """啟動時先用本地快取載入頭像庫、預熱 OCR，第一次進選人介面不用等網路和模型載入。"""
        try:
            self._load_icons(download=False)
            import numpy as np
            from .vision.ocr import OCR
            import cv2
            sample = np.full((64, 256, 3), 255, np.uint8)
            cv2.putText(sample, "LolHex 123", (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
            OCR.get().recognize(sample)  # 首次推理最慢，識別和檢測都先各跑一次
            OCR.get().detect(sample)
        except Exception:
            log.exception("預熱失敗")

    def _augment_matcher(self) -> NameMatcher:
        names = {aid: [a.get("name"), a.get("name_cn"), a.get("name_en"), a.get("en")]
                 for aid, a in self.store.mayhem_augments().items()}
        return NameMatcher(names, self.settings.match_threshold)

    def _hero_matcher(self) -> NameMatcher:
        heroes = self.store.heroes
        cached = getattr(self, "_hm", None)
        if cached and cached[0] is heroes:
            return cached[1]
        m = self._build_hero_matcher()
        self._hm = (heroes, m)
        return m

    def _build_hero_matcher(self) -> NameMatcher:
        names = {}
        for hid, h in self.store.heroes.items():
            names[hid] = [h.get("name"), h.get("name_cn"), h.get("alias")]
            names[hid + "#nick"] = [h.get("nick"), h.get("nick_cn")]
            names[hid + "#full"] = [f"{h.get('nick', '')} {h.get('name', '')}",
                                    f"{h.get('nick_cn', '')} {h.get('name_cn', '')}"]
        return NameMatcher(names, 86.0)

    def _load_icons(self, download: bool = True) -> None:
        from .vision.champselect import Memo
        from .vision.portraits import IconBank, ensure_icons
        folder = self.home / "data" / "icons"
        heroes = self.store.heroes
        if not heroes or (not download and not folder.is_dir()):
            return
        new = ensure_icons(folder, heroes) if download else 0
        if new or self._icon_bank is None:
            bank = IconBank.from_dir(folder, heroes)
            if len(bank):
                self._icon_bank = bank
                self._cs_memo = Memo()  # 頭像庫變了，快取的識別結果作廢
                log.info("英雄頭像庫：%d 個", len(bank))

    def hero_brief(self, hid: str) -> dict:
        """選人介面標註用：國服勝率、按勝率的排名，以及由排名換算的評級。
        騰訊英雄榜自帶的排名摻了出場率，這裡只按勝率排。"""
        ranks = self.store.ranks.get("heroes") or {}
        cached = getattr(self, "_win_rank", None)
        if not cached or cached[0] is not ranks:
            order = sorted((k for k, v in ranks.items() if v.get("win") is not None),
                           key=lambda k: -ranks[k]["win"])
            cached = (ranks, {k: i + 1 for i, k in enumerate(order)})
            self._win_rank = cached
        pos = cached[1]
        h = self.store.heroes.get(hid) or {}
        rank, total = pos.get(hid), len(pos) or None
        return {"hero_id": hid, "name": h.get("name"), "nick": h.get("nick"),
                "win": (ranks.get(hid) or {}).get("win"), "rank": rank, "total": total,
                "grade": rank_grade(rank, total)}

    def _prefetch_hero(self, hid: str) -> None:
        self.store.hero(hid)
        self._panel_cache = (None, None)

    # ---------- 視窗狀態與英雄識別 ----------

    def _observer_loop(self) -> None:
        while not self._stop.is_set():
            interval = 3.0
            try:
                interval = self._observe_once()
            except Exception:
                log.exception("狀態讀取異常")
            self._stop.wait(interval)

    def _observe_once(self) -> float:
        game = win.find_game_window()
        client = win.find_client_window()
        prev = self.state["phase"]
        phase = "ingame" if game else ("client" if client else None)
        self._set(phase=phase, game_window=bool(game), client_window=bool(client))

        if prev == "ingame" and phase != "ingame":
            self._on_game_end()
        if phase != "client" and self.state["champ_select"]:
            self._set(champ_select=None)

        if phase == "ingame":
            if self.live and not self._manual_hero:
                snap = self.live.snapshot()
                if snap:
                    self._set(level=snap.get("level"))
                    if not self.state["hero_id"]:
                        hid = self.store.resolve_hero(snap.get("champion_raw")) or \
                            self.store.resolve_hero(snap.get("champion_name"))
                        if hid:
                            self._set_hero_auto(hid, "liveclient")
            return 2.0
        if phase == "client" and win.is_foreground(client):
            self._champ_select_scan(client)
            # 畫面沒變的位置直接複用上次結果，所以可以掃得很勤
            return (0.5 if self.state["champ_select"] else 1.0) * self.settings.speed_factor
        if phase == "client":
            return 1.0  # 客戶端切到後臺：只查視窗不截圖，切回來 1 秒內恢復
        return 3.0

    def _set_hero_auto(self, hid: str, source: str) -> None:
        if self.state["hero_id"] != hid:
            self._set(hero_id=hid, hero_source=source)
            threading.Thread(target=self._prefetch_hero, args=(hid,), daemon=True).start()
            self._reevaluate()

    def _champ_select_scan(self, hwnd: int) -> None:
        """擷取客戶端視窗：頭像比對認出預選欄/我方英雄，OCR 認出自己的英雄名。
        只讀螢幕畫素，不讀客戶端程序。"""
        if time.monotonic() < self.vision_hold_until:  # 自動截圖中：標註層臨時可截，先不識別
            return
        rect = win.client_rect(hwnd)
        if not rect:
            return
        from .vision import capture
        img = capture.grab(rect)
        if capture.is_blank(img):
            return
        t0 = time.monotonic()
        cs = self.analyze_champ_select(img, (rect.left, rect.top))
        dt = time.monotonic() - t0
        if dt > 0.8:
            log.info("選英雄：這次識別用了 %.1f 秒", dt)
        self._set(champ_select=cs or None)
        if cs is False:  # 不在選英雄介面
            return
        if self._manual_hero:
            return
        if cs and cs.get("mine"):
            self._set_hero_auto(cs["mine"], "ocr")
            self._set(hero_candidates=[])
        elif not cs and self._icon_bank is None:
            self._champ_select_ocr(img)  # 頭像庫還沒下載好時，退回整屏文字識別

    def analyze_champ_select(self, img, origin: tuple[int, int] = (0, 0)):
        """客戶端截圖 → 標註資料 {"bench", "team", "mine", "cards"?}；
        不在選英雄介面返回 False，在介面但什麼都沒認出返回 None。"""
        from .vision import champselect
        from .vision.ocr import OCR
        ocr = OCR.get()
        if self._cs_memo is None:
            self._cs_memo = champselect.Memo()
        memo = self._cs_memo
        in_cs = champselect.is_champ_select(img, ocr.recognize, memo)
        # 開局選卡時頂部預選欄被蓋住、沒有"可用"兩個字，所以卡片按"選擇你的英雄"單獨判斷，
        # 否則要等點完卡、回到正常選人介面才有標註
        cards = champselect.read_cards(img, ocr.recognize, ocr.detect, self._hero_by_name, origin, memo)
        if not in_cs and not cards:
            return False  # 大廳、房間、商城等介面：不標註、不識別
        cs = None
        if in_cs and self._icon_bank is not None:
            got = champselect.read(img, self._icon_bank, origin, self._read_hero_name, memo)
            if got["bench"] or got["team"]:
                cs = {k: [{**s, **self.hero_brief(s["hero_id"])} for s in got[k]] for k in ("bench", "team")}
                cs["mine"] = got["mine"]
        if cards:
            cs = cs or {"bench": [], "team": [], "mine": None}
            cs["cards"] = [{**c, **self.hero_brief(c["hero_id"])} for c in cards]
        return cs

    def _read_hero_name(self, crop) -> str | None:
        from .vision.ocr import OCR
        txt, sc = OCR.get().recognize(crop)
        return self._hero_by_name(txt) if sc >= 0.6 else None

    def _hero_by_name(self, txt: str) -> str | None:
        if not txt:
            return None
        key, _ = self._hero_matcher().match(txt)
        return key.split("#")[0] if key else None

    def _champ_select_ocr(self, img) -> None:
        from .vision.detector import _resize
        from .vision.ocr import OCR
        scale = min(1.0, 1600 / max(1, img.shape[1]))
        m = self._hero_matcher()
        found = []
        for ln in OCR.get().detect(_resize(img, scale)):
            key, sc = m.match(ln.text)
            if key:
                found.append((key.split("#")[0], sc, ln.h))
        mine, cands = pick_my_hero(found)
        if mine:
            self._set_hero_auto(mine, "ocr")
            self._set(hero_candidates=[c for c in cands if c != mine])
        elif cands:
            self._set(hero_candidates=cands)

    def _on_game_end(self) -> None:
        self._manual_hero = False
        self._set(hero_id=None, hero_source=None, hero_candidates=[], level=None,
                  offer=None, evaluation=None)

    # ---------- 海克斯識別 ----------

    def _vision_loop(self) -> None:
        from .vision import capture
        from .vision.detector import AugmentDetector

        last_full = last_strip = 0.0
        visible = False
        misses = 0  # 重新整理動畫會短暫缺卡，連續 3 次識別不到才算關閉
        while not self._stop.is_set():
            if time.monotonic() < self.vision_hold_until:  # 自動截圖時浮窗臨時可截：這段時間不識別，免得讀到自己畫的字
                self._stop.wait(0.1)
                continue
            if self.state["phase"] != "ingame":
                if visible:
                    self._on_offer(None)
                    visible = False
                self.state["vision"]["status"] = "idle"
                self._rescan.wait(1.0)
                self._rescan.clear()
                continue
            hwnd = win.find_game_window()
            rect = win.client_rect(hwnd)
            if not rect or not win.is_foreground(hwnd):
                self.state["vision"]["status"] = "paused"
                self._stop.wait(0.5)
                continue
            if self._detector is None:
                self._detector = AugmentDetector(self._augment_matcher(), self.home / "calibration.json")
            det = self._detector
            det.ensure_calibration(rect.width, rect.height)
            now = time.monotonic()
            forced = self._rescan.is_set()
            self._rescan.clear()
            offer, ran = None, False
            try:
                if det.calibrated_for(rect.width, rect.height) and not forced:
                    if now - last_strip >= self.settings.scan_interval_ms / 1000 * self.settings.speed_factor:
                        last_strip = now
                        offer = det.check_strip(capture.grab(det.strip_rect(rect)), rect)
                        ran = True
                        # 一直識別不到：整塊掃描一次，防止卡片位置變了；
                        # 還在用預設位置時照常按 bootstrap 間隔掃，本機校準過就 30 秒一次
                        confirmed = det.confirmed_for(rect.width, rect.height)
                        every = 30 if confirmed else self.settings.bootstrap_interval_s * self.settings.speed_factor
                        if offer is None and not visible and now - last_full > every:
                            last_full = now
                            offer = det.scan_full(capture.grab(rect), (rect.left, rect.top))
                elif forced or now - last_full >= self.settings.bootstrap_interval_s * self.settings.speed_factor:
                    last_full = now
                    frame = capture.grab(rect)
                    blank = capture.is_blank(frame)
                    self.state["vision"]["blank"] = blank
                    offer = None if blank else det.scan_full(frame, (rect.left, rect.top))
                    ran = True
            except Exception:
                log.exception("識別異常")
            self.state["vision"].update(status="scanning", calibrated=det.confirmed_for(rect.width, rect.height))
            if ran:
                self.state["vision"]["last_scan"] = time.time()
                if offer is not None:
                    misses = 0
                    if not visible:
                        self._save_offer_shot(rect)  # 趁浮窗還沒畫上去
                    self._on_offer(offer)
                    visible = True
                elif visible:
                    misses += 1
                    if misses >= 3:
                        self._on_offer(None)
                        visible = False
            self._stop.wait(0.1)

    SHOTS_KEEP = 3

    def _save_offer_shot(self, rect) -> None:
        """前幾次出現三選一時存一張全屏截圖（縮到 1920 寬），用來核對浮窗位置；存夠就不再截。"""
        folder = self.home / "shots"
        try:
            if folder.is_dir() and len(list(folder.glob("offer_*.jpg"))) >= self.SHOTS_KEEP:
                return
            from .vision import capture
            frame = capture.grab(rect)
        except Exception:
            log.exception("截圖失敗")
            return

        def save():
            try:
                import cv2
                from .vision.detector import _resize
                img = _resize(frame, min(1.0, 1920 / max(1, frame.shape[1])))
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if ok:
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / time.strftime("offer_%Y%m%d_%H%M%S.jpg")).write_bytes(buf.tobytes())
            except Exception:
                log.exception("截圖儲存失敗")
        threading.Thread(target=save, daemon=True).start()

    def _on_offer(self, offer) -> None:
        with self._lock:
            prev = self.state.get("offer")
        if offer is None:
            self._set(offer=None, evaluation=None)
            return
        slots = list(offer.slots)
        if prev and prev.get("corrected"):
            slots = [s or p for s, p in zip(slots, prev["slots"])]
        if prev and prev["slots"] == slots:
            return
        self._set(offer={"slots": slots, "texts": offer.texts, "scores": offer.scores,
                         "boxes": offer.boxes, "at": offer.at})
        self._reevaluate()

    def _reevaluate(self) -> dict | None:
        with self._lock:
            offer = self.state.get("offer")
            hid = self.state.get("hero_id")
        if not offer:
            return None
        ev = recommend.evaluate(self.store, hid, offer["slots"], self.settings.smoothing_games)
        self._set(evaluation=ev)
        return ev
