from types import SimpleNamespace

import pytest

from lolhex.config import Settings


def test_datastore_bootstraps_tw_hero_names_without_tencent_static(tmp_path):
    from lolhex.data.store import DataStore

    store = DataStore(tmp_path)
    assert len(store.heroes) >= 250
    assert store.resolve_hero("藍寶") == "68"
    assert store.resolve_hero("Rumble") == "68"


def test_engine_scans_champ_select_when_client_is_foreground(store, tmp_path, monkeypatch):
    """選英雄介面要掃：畫面認出自己選的英雄就自動接手（見下面的自動接手用例），
    手動輸入只是備援。這裡只驗掃描有沒有被叫到。"""
    from lolhex.engine import Engine
    from lolhex.vision import window as win

    engine = Engine(Settings(), home=tmp_path, store=store)
    called = []
    engine._champ_select_scan = lambda hwnd: called.append(hwnd)
    engine._load_icons = lambda download=False: None
    monkeypatch.setattr(win, "find_game_window", lambda: 0)
    monkeypatch.setattr(win, "find_client_window", lambda: 111)
    monkeypatch.setattr(win, "is_foreground", lambda hwnd: True)

    assert engine._observe_once() == 1.0
    assert called == [111]
    assert engine.live is None  # 仍然不接 LCU


def _scan_engine(store, home, monkeypatch, mine):
    """直接呼叫 _champ_select_scan 的 Engine：截圖和 OCR 都換成假資料，只驗掃到之後怎麼處理。"""
    from lolhex.engine import Engine
    from lolhex.vision import capture, window as win

    engine = Engine(Settings(), home=home, store=store)
    engine._prefetch_hero = lambda hid: None
    engine._icon_bank = object()  # 頭像庫已就緒：不再退回整屏文字識別
    monkeypatch.setattr(win, "client_rect", lambda hwnd: win.Rect(0, 0, 1920, 1080))
    monkeypatch.setattr(capture, "grab", lambda rect: None)
    monkeypatch.setattr(capture, "is_blank", lambda img: False)
    engine.analyze_champ_select = lambda img, origin=(0, 0): {"bench": [], "team": [], "mine": mine}
    return engine


def test_scan_auto_selects_detected_hero(store, tmp_path, monkeypatch):
    """畫面認出自己的英雄就自動選：還沒選英雄時，hero_id 直接變成認出的那隻。"""
    engine = _scan_engine(store, tmp_path, monkeypatch, "268")
    assert engine.state["hero_id"] is None
    engine._champ_select_scan(111)
    assert engine.state["hero_id"] == "268"
    assert engine.state["hero_source"] == "ocr"
    assert engine.state["champ_select"]["mine"] == "268"


def test_manual_hero_does_not_block_later_auto_detection(store, tmp_path, monkeypatch):
    """手動選了 A 之後，畫面認出 B：自動辨識要接手，手動只是備援，不是永久鎖住。"""
    engine = _scan_engine(store, tmp_path, monkeypatch, "268")
    engine.set_hero("17")
    assert engine.state["hero_id"] == "17"
    assert engine.state["hero_source"] == "manual"
    assert engine._manual_at > 0.0  # 有記錄手動時間，供備援判斷
    engine._champ_select_scan(111)
    assert engine.state["hero_id"] == "268"
    assert engine.state["hero_source"] == "ocr"


def test_scan_keeps_hero_when_detection_matches(store, tmp_path, monkeypatch):
    """畫面和目前英雄一樣時不重複設定，免得每輪都重建面板快取。"""
    engine = _scan_engine(store, tmp_path, monkeypatch, "268")
    engine._set(hero_id="268", hero_source="manual")
    engine._champ_select_scan(111)
    assert engine.state["hero_id"] == "268"
    assert engine.state["hero_source"] == "manual"


def test_engine_skips_champ_select_when_client_is_background(store, tmp_path, monkeypatch):
    """客戶端在後臺時不截圖：抓的是該視窗的螢幕區域，被蓋住會讀到別人的畫面。"""
    from lolhex.engine import Engine
    from lolhex.vision import window as win

    engine = Engine(Settings(), home=tmp_path, store=store)
    called = []
    engine._champ_select_scan = lambda hwnd: called.append(hwnd)
    monkeypatch.setattr(win, "find_game_window", lambda: 0)
    monkeypatch.setattr(win, "find_client_window", lambda: 111)
    monkeypatch.setattr(win, "is_foreground", lambda hwnd: False)

    assert engine._observe_once() == 1.0
    assert called == []
    assert engine.state["champ_select"] is None


def test_manual_hero_panel_never_waits_for_network(store, tmp_path):
    from lolhex.engine import Engine

    engine = Engine(Settings(), home=tmp_path, store=store)
    calls = []
    real = store.official_hero

    def cached_only(hid, allow_network=True):
        calls.append(allow_network)
        return real(hid, allow_network=False)

    store.official_hero = cached_only
    panel = engine.hero_panel("17")
    assert panel is not None
    assert calls == [False]


def test_panel_shows_public_augments_before_official_data_arrives(store):
    from lolhex.panel import hero_panel

    store.official_hero = lambda hid, allow_network=False: None
    panel = hero_panel(store, "17", allow_network=False)
    assert panel is not None
    by_id = {a["id"]: a for a in panel["augments"]}
    assert by_id["1029"]["source"] == "public"
    assert by_id["1029"]["win"] == 0.6
    assert panel["builds"]["full"] == []


def test_warm_up_skips_bulk_hero_icon_loading(store, tmp_path, monkeypatch):
    from lolhex.engine import Engine
    from lolhex.vision import ocr

    engine = Engine(Settings(), home=tmp_path, store=store)
    called = []
    engine._load_icons = lambda download=True: called.append(download)
    engine._detector = None

    class FakeOCR:
        def recognize(self, img): return "AramHex 2026", 1.0
        def detect(self, img): return []

    monkeypatch.setattr(ocr.OCR, "get", classmethod(lambda cls: FakeOCR()))
    engine._warm_up()
    assert called == []


def test_concurrent_prefetch_work_is_deduplicated(store, tmp_path, monkeypatch):
    import threading

    from lolhex.engine import Engine

    engine = Engine(Settings(), home=tmp_path, store=store)
    calls = []
    started = threading.Event()
    release = threading.Event()

    def fetch(hid, allow_network=True):
        calls.append((hid, allow_network))
        started.set()
        release.wait(2)

    store.hero = fetch
    first = threading.Thread(target=engine._prefetch_hero, args=("17",))
    first.start()
    assert started.wait(1)
    engine._prefetch_hero("17")  # 第一個仍在抓取：不可重複發請求
    release.set()
    first.join(2)
    assert calls == [("17", True)]

