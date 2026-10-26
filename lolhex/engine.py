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

# 台服版：選英雄介面會辨識（預選欄與我方英雄的評級／勝率標註，見 ChampSelectLayer），
# 但「自動決定我玩哪隻」仍以手動選擇為準，避免標註誤判就改掉使用者選的英雄。
# 想連英雄也自動認出，把 CHAMP_SELECT_DETECT 保留、MANUAL_HERO_ONLY 設 False 即可。
MANUAL_HERO_ONLY = True
CHAMP_SELECT_DETECT = True


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
        self._prefetching: set[str] = set()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._rescan = threading.Event()
        self._detector = None  # 延遲建立，避免沒進遊戲就載入 OCR 模型
        self._icon_bank = None  # 英雄頭像庫，頭像下載好後建立
        self._icons_lock = threading.RLock()
        self._icons_loading = False
        from .data.icons import IconCache
        self.icons = IconCache(self.home / "data" / "img")  # 裝備、召喚師技能小圖示
        self._cs_memo = None    # 選人介面各位置的識別結果快取（champselect.Memo）
        self.vision_hold_until = 0.0  # time.monotonic() 在這之前暫停識別（自動截圖用）
        self._manual_hero = False
        self._manual_at = 0.0
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
        if CHAMP_SELECT_DETECT:
            # 頭像庫要先用才有東西可比對；下載 173 張小圖，只在缺檔時抓。
            threading.Thread(target=self._load_icons, kwargs={"download": True},
                             name="icons", daemon=True).start()

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
        """手動指定英雄（備援）。不關掉自動辨識：畫面認出別的英雄時會自動接手。"""
        hid = self.store.resolve_hero(hero_key) if hero_key else None
        self._manual_hero = hid is not None
        self._manual_at = time.monotonic()
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

    def hard_reset(self) -> None:
        """完整重置識別狀態：「重新識別」按不動時，使用者一按就回到乾淨狀態。

        清掉校準、指紋快取、三選一與選英雄的識別結果，然後立刻排一次整屏掃描。
        刻意不動：設定、資料快取、截圖、英雄的手動選擇——按一下不該丟掉使用者的東西。
        遊戲中按也安全：只是下一輪從整屏重新找卡片位置。"""
        if self._detector:
            self._detector.reset_calibration()
            self._detector._pending = None
        self._cs_memo = None
        self.state["vision"].update(calibrated=False, blank=False)
        self._set(offer=None, evaluation=None, champ_select=None,
                  hero_candidates=[], level=None)
        self._rescan.set()
        log.info("已硬重置識別狀態（校準、快取、三選一結果）")

    def hero_panel(self, hero_key) -> dict | None:
        hid = self.store.resolve_hero(hero_key)
        if self._panel_cache[0] == hid and self._panel_cache[1]:
            return self._panel_cache[1]
        # UI 執行緒只讀本地快取；官方出裝／加點由 _prefetch_hero 在背景補齊。
        p = hero_panel(self.store, hid, self.settings.smoothing_games, allow_network=False) if hid else None
        self._panel_cache = (hid, p)
        return p

    # ---------- 資料 ----------

    def _data_loop(self) -> None:
        self._warm_up()
        while not self._stop.is_set():
            try:
                self.store.refresh()
                if self._detector:
                    self._detector.set_matcher(self._augment_matcher())
                self._panel_cache = (None, None)
                self._reevaluate()
            except Exception:
                log.exception("資料重新整理異常")
            self._stop.wait(max(600.0, self.settings.refresh_hours * 3600 / 4))

    def _warm_up(self) -> None:
        """預熱海克斯 OCR；英雄改為手動選取，不再下載頭像或載入選人模型。"""
        try:
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
        # 騰訊靜態資料的台服名稱有時和遊戲畫面不一致（例如 3088 遊戲顯示「血色鈷石」，
        # 騰訊寫「深紅鈷藍閃光」）。CommunityDragon 的 zh_tw catalog 是官方名稱，
        # 一律併入成為額外的比對字串；只加名稱，不改國服勝率資料。
        for aid, record in self.store.localizer.augments.items():
            official = record.get("name_zh")
            if not official:
                continue
            if aid not in names:
                names[aid] = [official, record.get("name_en")]
            else:
                have = {str(v) for v in (names[aid] or []) if v}
                if official not in have:
                    names[aid] = list(names[aid]) + [official]
        # 同一個名字可能同時對到騰訊 id（1000+n，有勝率資料）和 CommunityDragon 裸 id
        # （115/41，沒有資料）。告訴 matcher 哪一邊才是評分層認得的，否則會靠 dict
        # 走訪順序亂挑，正確識別的卡變成「暫無可靠資料」甚至推薦錯誤。
        known = {str(a) for a in self.store.augments} | {str(a) for a in self.store.ranks.get("augments") or {}}
        return NameMatcher(names, self.settings.match_threshold, preferred=known)

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
        """建立英雄頭像庫。下載是慢的（173 張），下載期間不要用不完整的頭像庫去比對：
        以前背景下載和每次掃描會同時呼叫這裡，掃描那邊看到資料夾已存在、又還沒有庫，
        就用當下載好的十幾張建庫，之後 new==0 就再也不會重建，於是幾乎什麼都認不出。"""
        from .vision.champselect import Memo
        from .vision.portraits import IconBank, ensure_icons
        with self._icons_lock:
            if self._icons_loading:
                return
            folder = self.home / "data" / "icons"
            heroes = self.store.heroes
            if not heroes or (not download and not folder.is_dir()):
                return
            self._icons_loading = True
        try:
            new = ensure_icons(folder, heroes) if download else 0
            bank = IconBank.from_dir(folder, heroes)
            with self._icons_lock:
                # 只有比現有的大才換：避免一次不完整的下載把好的庫換掉
                if len(bank) and (self._icon_bank is None or len(bank) > len(self._icon_bank)):
                    self._icon_bank = bank
                    self._cs_memo = Memo()  # 頭像庫變了，快取的識別結果作廢
                    log.info("英雄頭像庫：%d 個（新下載 %d）", len(bank), new)
                elif self._icon_bank is None:
                    log.warning("英雄頭像庫為空：%s 沒有可用的頭像", folder)
        finally:
            with self._icons_lock:
                self._icons_loading = False

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

    def _prefetch_site(self, hid: str) -> None:
        """順手把台服官網的這隻英雄抓下來，面板之後就能直接讀快取。"""
        from .panel import _site_build

        try:
            _site_build(self.store, hid, allow_network=True)
        except Exception:
            log.info("台服官網預取失敗：%s", hid)

    def _prefetch_hero(self, hid: str) -> None:
        with self._lock:
            if hid in self._prefetching:
                return
            self._prefetching.add(hid)
        try:
            self.store.hero(hid, allow_network=True)
            self._prefetch_site(hid)
        finally:
            with self._lock:
                self._prefetching.discard(hid)
                if self.state.get("hero_id") == hid:
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
            return 2.0
        if phase == "client":
            # 選英雄介面是靜止畫面，Memo 會快取識別結果，所以可以掃得勤而不吃 CPU。
            # 只在客戶端在前臺時掃：截圖取的是該視窗的螢幕區域，被別視窗蓋住就讀錯。
            if CHAMP_SELECT_DETECT and client and win.is_foreground(client):
                self._load_icons(download=False)
                # 頭像庫還沒好（首次啟動下載中、或上次下載中斷）：補一次下載，
                # 否則整個選人階段都會因為沒有可比對的頭像而什麼都認不出。
                if self._icon_bank is None:
                    threading.Thread(target=self._load_icons, kwargs={"download": True},
                                     name="icons", daemon=True).start()
                self._champ_select_scan(client)
            return 1.0
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
        # 讀螢幕期間暫時把主視窗排除在截圖之外：主視窗可被截取後，
        # 它若蓋住客戶區，OCR 會讀到自己的介面。讀完立刻還原，使用者截圖不受影響。
        with win.hold_scan_exclusion():
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
        # 自動認出自己選的英雄；手動輸入只是「這次」的優先，不是永久關掉自動辨識。
        # 手動選了 A，畫面上認出的是 B：以手動為準，但只要手動的英雄和畫面認出的不同，
        # 就讓自動辨識在下一輪重新接手（換場、重開、或使用者改了選擇都適用）。
        if cs and cs.get("mine") and cs["mine"] != self.state.get("hero_id"):
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
            if got["bench"] or got["team"] or got.get("unknown"):
                cs = {k: [{**s, **self.hero_brief(s["hero_id"])} for s in got[k]] for k in ("bench", "team")}
                cs["mine"] = got["mine"]
                # 有頭像但認不出來的格子：畫面上標「無法識別」，不要靜靜留白
                cs["unknown"] = got.get("unknown") or []
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
            # 前臺不必是遊戲：主視窗／浮層都排除在截取之外，截到的仍是遊戲畫素。
            # 見 vision.window.scannable——舊的 is_foreground 硬性要求會令「已在遊戲中
            # 才啟動助手」永遠 paused，因為啟動時搶到前臺的是助手自己的主視窗。
            if not rect or not win.scannable(hwnd):
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
                # 讀螢幕期間暫時排除主視窗，免得 OCR 讀到自己的介面（見 win.hold_scan_exclusion）
                with win.hold_scan_exclusion():
                    if det.calibrated_for(rect.width, rect.height) and not forced:
                        if now - last_strip >= self.settings.scan_interval_ms / 1000 * self.settings.speed_factor:
                            last_strip = now
                            strip_rect = det.strip_rect(rect)
                            if strip_rect is not None:  # 校準剛被 ensure_frame 丟掉時會是 None
                                offer = det.check_strip(capture.grab(strip_rect), rect)
                                ran = True
                            # 一直識別不到：整塊掃描一次，防止卡片位置變了；
                            # 還在用預設位置時照常按 bootstrap 間隔掃，本機校準過就 30 秒一次
                            confirmed = det.confirmed_for(rect.width, rect.height)
                            every = 30 if confirmed else self.settings.bootstrap_interval_s * self.settings.speed_factor
                            if offer is None and not visible and now - last_full > every:
                                last_full = now
                                offer = det.scan_full(capture.grab(rect), (rect.left, rect.top),
                                                      expect=(rect.width, rect.height))
                    elif forced or now - last_full >= self.settings.bootstrap_interval_s * self.settings.speed_factor:
                        last_full = now
                        frame = capture.grab(rect)
                        blank = capture.is_blank(frame)
                        self.state["vision"]["blank"] = blank
                        offer = None if blank else det.scan_full(frame, (rect.left, rect.top),
                                                                expect=(rect.width, rect.height))
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
            with win.hold_scan_exclusion():
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
