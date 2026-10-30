"""頭像比對：用隨機紋理當"英雄頭像"，檢查縮放、平移、圓形遮罩、變暗、JPEG 之後仍能認對。"""

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np

from lolhex.vision import champselect
from lolhex.vision.portraits import IconBank


def _icons(n=40, seed=0):
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n):
        base = rng.integers(0, 256, (6, 6, 3), dtype=np.uint8)
        out[str(i + 1)] = cv2.resize(base, (120, 120), interpolation=cv2.INTER_CUBIC)
    return out


def _distort(img, size, dx, dy, circle, dark):
    s = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    pad = size // 6
    canvas = np.full((size + 2 * pad, size + 2 * pad, 3), 20, np.uint8)
    canvas[pad:pad + size, pad:pad + size] = s
    cv2.rectangle(canvas, (pad, pad), (pad + size - 1, pad + size - 1), (60, 170, 200), 2)
    crop = canvas[pad + dy:pad + dy + size, pad + dx:pad + dx + size].copy()
    if circle:
        m = np.zeros(crop.shape[:2], np.uint8)
        cv2.circle(m, (size // 2, size // 2), size // 2, 255, -1)
        crop[m == 0] = 15
    if dark:
        crop = (crop * 0.6).astype(np.uint8)
    _, enc = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


def test_classify_distorted():
    icons = _icons()
    bank = IconBank(icons)
    rng = np.random.default_rng(1)
    wrong = 0
    for hid, img in icons.items():
        crop = _distort(img, int(rng.choice([40, 64, 96])), int(rng.integers(-2, 3)), int(rng.integers(-2, 3)),
                        bool(rng.integers(0, 2)), bool(rng.integers(0, 2)))
        m = bank.classify(crop)
        assert m.hero_id in (hid, None)
        wrong += m.hero_id != hid
    assert wrong <= 2


def test_blank_slot_not_matched():
    bank = IconBank(_icons())
    assert bank.classify(np.full((64, 64, 3), 30, np.uint8)).hero_id is None
    assert bank.classify(np.zeros((4, 4, 3), np.uint8)).hero_id is None


def test_champselect_read(monkeypatch):
    icons = _icons()
    bank = IconBank(icons)
    frame = np.full((900, 1600, 3), 25, np.uint8)
    layout = {"bench": [], "team": []}
    for i, hid in enumerate(["3", "7", "11"]):
        x, y = 500 + i * 70, 20
        frame[y:y + 56, x:x + 56] = cv2.resize(icons[hid], (56, 56), interpolation=cv2.INTER_AREA)
        layout["bench"].append((x / 1600, y / 900, (x + 56) / 1600, (y + 56) / 900))
    layout["bench"].append((1200 / 1600, 20 / 900, 1256 / 1600, 76 / 900))  # 空位
    monkeypatch.setattr(champselect, "LAYOUT", layout)
    got = champselect.read(frame, bank, (100, 50))
    assert [s["hero_id"] for s in got["bench"]] == ["3", "7", "11"]
    assert got["bench"][0]["box"][:2] == (600, 70)
    assert got["team"] == []


def test_team_uses_name_reader_and_gold_name(monkeypatch):
    """隊友頭像是皮膚圖認不出時，用稱號文字；金色稱號那一行是自己。"""
    bank = IconBank(_icons())
    frame = np.full((1080, 1920, 3), 25, np.uint8)
    frame[176 + 240:206 + 240, 200:300] = (60, 190, 240)  # 第 3 行稱號塗成金色（BGR）
    reads = iter([None, "5", "9", None, None])
    got = champselect.read(frame, bank, (0, 0), lambda crop: next(reads))
    assert [(s["slot"], s["hero_id"]) for s in got["team"]] == [(1, "5"), (2, "9")]
    assert got["mine"] == "9"
    assert got["bench"] == []


def test_rank_grade_and_summary():
    from lolhex.engine import rank_grade
    assert [rank_grade(r, 100) for r in (1, 10, 11, 30, 31, 60, 61, 85, 86, 100)] == \
        ["S", "S", "A", "A", "B", "B", "C", "C", "D", "D"]
    assert rank_grade(None, 100) is None
    pytest.importorskip("PySide6")
    from lolhex.ui.overlay import champ_select_summary
    cs = {"mine": "1", "team": [{"hero_id": "1", "name": "韋魯斯", "win": 0.47, "grade": "C"}],
          "bench": [{"hero_id": "2", "name": "奧拉夫", "win": 0.464, "grade": "C"},
                    {"hero_id": "3", "name": "霞", "win": 0.492, "grade": "B"}]}
    s = champ_select_summary(cs)
    assert s.index("霞") < s.index("奧拉夫")  # 按勝率排序
    assert "↑2.2" in s and "你：韋魯斯" in s


def test_is_champ_select_marker():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    seen = []

    def rec(text, score=0.99):
        def f(crop):
            seen.append(crop.shape)
            return text, score
        return f
    # 標題實際文字是「可使用的英雄」；MARKER_TEXT 是可接受的幾個字串（tuple）
    assert isinstance(champselect.MARKER_TEXT, tuple)
    assert champselect.is_champ_select(frame, rec("可使用的英雄"))
    # 讀的是"可使用的英雄"那一小塊，不是整張畫面
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = champselect.MARKER_BOX
    assert seen[0][:2] == (int((y1 - y0) * h), int((x1 - x0) * w))
    assert not champselect.is_champ_select(frame, rec("開始匹配"))
    assert not champselect.is_champ_select(frame, rec("可使用的英雄", 0.3))


def test_marker_accepts_real_champion_select_label():
    """回歸：標題寫的是「可使用的英雄」，可－使－用 三個字並不連續，
    以前只比對「可用」時 `"可用" in text` 永遠不成立，整個選英雄介面因此判定失敗。
    大廳導覽列的《英雄聯盟》不可以被當成選英雄介面。"""
    frame = np.zeros((1080, 1920, 3), np.uint8)

    def ok(text, score):
        return champselect.is_champ_select(frame, lambda crop: (text, score))

    assert ok("可使用的英雄", 0.99995)  # 實機 OCR 量到的結果
    assert ok("可使用", 0.9)            # 簡寫兜底
    assert ok("可 使用 的英雄", 0.9)     # OCR 在字之間插空格：先去掉空格再比對
    assert not ok("可使用的英雄", 0.59)  # 置信度不足 0.6
    assert not ok("《英雄聯盟》", 0.99)  # 大廳導覽列
    assert not ok("開始匹配", 0.99)


def test_read_cards_two_or_three():
    """開局英雄卡：讀到"選擇你的英雄"才識別；卡片位置按稱號文字定位，二選一/三選一通用。"""
    from lolhex.vision.ocr import TextLine
    frame = np.zeros((1080, 1920, 3), np.uint8)
    names = {"沙漠皇帝": "268", "黑暗之女": "1"}
    lines = [TextLine("黑暗之女", 0.99, (789, 26, 914, 65)), TextLine("沙漠皇帝", 0.99, (142, 25, 266, 65)),
             TextLine("傳說", 0.7, (400, 0, 500, 60))]
    cards = champselect.read_cards(frame, lambda c: ("選擇你的英雄", 0.99), lambda c: lines, names.get, (10, 0))
    assert [c["hero_id"] for c in cards] == ["268", "1"]
    cx = (cards[0]["box"][0] + cards[0]["box"][2]) / 2
    assert abs(cx - (10 + 430 + 204)) <= 1
    assert champselect.read_cards(frame, lambda c: ("", 0.0), lambda c: lines, names.get) == []


def test_memo_reuses_until_crop_changes():
    calls = []
    memo = champselect.Memo()

    def fn(crop):
        calls.append(1)
        return int(crop.mean())

    a = np.full((40, 40, 3), 100, np.uint8)
    assert memo("k", a, fn) == 100
    assert memo("k", a.copy(), fn) == 100  # 第二次畫面一樣：算靜止，再算一次並快取
    a2 = a.copy()
    a2[0, 0] = 101  # 細微噪聲：不重算
    memo("k", a2, fn)
    assert len(calls) == 2
    b = np.full((40, 40, 3), 160, np.uint8)  # 換了英雄：重算
    assert memo("k", b, fn) == 160
    assert memo("other", b, fn) == 160  # 不同位置分開快取
    assert len(calls) == 4


def _name_box(strokes):
    """模擬我方一行的英雄名：深色底，每個字是幾道淺色筆畫。"""
    box = np.full((60, 284, 3), (30, 22, 18), np.uint8)
    for x, y, w, h in strokes:
        box[y:y + h, x:x + w] = (200, 225, 235)
    return box


def test_memo_sees_name_change_with_same_length():
    """同字數的兩個名字，壓成小方塊後平均差很小，以前會被當成沒變、一直顯示舊英雄。"""
    old = _name_box([(10 + 34 * k, 14, 26, 4) for k in range(4)] + [(20 + 34 * k, 14, 4, 30) for k in range(4)])
    new = old.copy()
    new[14:44, 78:104] = (30, 22, 18)  # 只換第三個字
    new[28:32, 78:104] = (200, 225, 235)
    new[14:44, 89:93] = (200, 225, 235)
    memo = champselect.Memo()
    read = {old.tobytes(): "舊", new.tobytes(): "新"}
    fn = lambda crop: read[crop.tobytes()]
    for _ in range(3):
        assert memo("name", old, fn) == "舊"
    assert memo("name", new, fn) == "新"


def test_memo_does_not_freeze_fade_frame():
    """換英雄時名字淡出淡入：半透明那一幀讀成舊英雄，不能被快取成最終結果。"""
    old = _name_box([(10, 14, 120, 4), (10, 40, 120, 4)])
    new = _name_box([(10, 14, 4, 30), (60, 14, 4, 30), (110, 14, 4, 30)])
    # 快淡入完的一幀：和最終畫面只差一點，按"沒變"算，靠"連續兩次一樣才快取"兜住
    fade = (old.astype(np.float32) * 0.05 + new.astype(np.float32) * 0.95).astype(np.uint8)
    memo = champselect.Memo()
    reads = iter(["舊", "舊", "舊（半透明）", "新", "新"])
    fn = lambda crop: next(reads)
    assert memo("name", old, fn) == "舊"
    assert memo("name", old, fn) == "舊"
    assert memo("name", fade, fn) == "舊（半透明）"
    assert memo("name", new, fn) == "新"
    assert memo("name", new, fn) == "新"
    assert memo("name", new, fn) == "新"  # 已靜止：複用，不再呼叫


def test_text_spans_skips_thin_borders():
    band = np.full((90, 1060, 3), (60, 30, 40), np.uint8)
    band[:, 330:333] = 200  # 卡片邊框細豎線
    for x in (140, 465, 790):  # 三段稱號，字間有空隙
        for k in range(4):
            band[30:60, x + k * 32:x + k * 32 + 26] = (190, 210, 225)
    spans = champselect.text_spans(band)
    assert len(spans) == 3
    assert all(a < x < b for (a, b), x in zip(spans, (200, 525, 850)))


def test_clicking_own_panel_keeps_client_foreground(monkeypatch):
    """點右上角浮窗時前臺變成浮窗，但客戶端還在畫面上：選人標註不能消失。"""
    from types import SimpleNamespace
    from lolhex.vision import window as win
    fg = {"h": 111}
    user32 = SimpleNamespace(GetForegroundWindow=lambda: fg["h"], IsIconic=lambda h: 0)
    monkeypatch.setattr(win, "IS_WINDOWS", True)
    monkeypatch.setattr(win, "ctypes", SimpleNamespace(windll=SimpleNamespace(user32=user32)))
    monkeypatch.setattr(win, "_companions", set())
    assert win.is_foreground(111)
    fg["h"] = 222  # 點了自己的浮窗
    assert not win.is_foreground(111)
    win.add_companion(222)
    assert win.is_foreground(111)
    fg["h"] = 333  # 切到別的程式：照常隱藏
    assert not win.is_foreground(111)


def test_memo_retries_unrecognized_until_found():
    """稱號淡入時先認不出；畫面只差一點（縮圖沒超閾值）也要重認，不能一直用"認不出"的快取。"""
    memo = champselect.Memo()
    results = iter([None, None, "268"])
    calls = []

    def fn(crop):
        calls.append(1)
        return next(results)

    a = np.full((40, 40, 3), 100, np.uint8)
    assert memo("k", a, fn, bool) is None
    assert memo("k", a.copy(), fn, bool) is None
    assert memo("k", a.copy(), fn, bool) == "268"
    assert memo("k", a.copy(), fn, bool) == "268"  # 認出來之後照常複用
    assert len(calls) == 3


def test_read_cards_not_stuck_after_fade_in():
    """先在淡入中途掃到（有標題、認不出名字），畫面穩定後再掃一次就要出卡。"""
    from lolhex.vision.ocr import TextLine
    frame = np.zeros((1080, 1920, 3), np.uint8)
    names = {"沙漠皇帝": "268", "黑暗之女": "1"}
    memo = champselect.Memo()
    title = lambda c: ("選擇你的英雄", 0.99)
    faded = [TextLine("沙漠", 0.4, (142, 25, 266, 65))]
    shown = [TextLine("黑暗之女", 0.99, (789, 26, 914, 65)), TextLine("沙漠皇帝", 0.99, (142, 25, 266, 65))]
    assert champselect.read_cards(frame, title, lambda c: faded, names.get, memo=memo) == []
    cards = champselect.read_cards(frame, title, lambda c: shown, names.get, memo=memo)
    assert [c["hero_id"] for c in cards] == ["268", "1"]


def test_icon_view_with_face_zoom_and_offset():
    """回歸：艾菲利歐（Aphelios）官方頭像是半身構圖，客戶端只把臉放大填滿格子。

    以前只準備「居中取中間 66–84%」的取景，這種英雄永遠認不出來：
    實機截圖裡正確答案排 65 名、第一名反而是別的英雄（0.68）。
    現在多準備了「放大 + 中心偏下」的取景，兩者都要能認對。"""
    icons = _icons()
    bank = IconBank(icons)
    for hid, img in icons.items():
        h, w = img.shape[:2]
        # 客戶端取景：圖像 57% 大小、中心往下 12%（= 艾菲利歐實測值）
        s = int(min(h, w) * 0.57)
        cx, cy = w / 2, h / 2 + 0.12 * h
        x0, y0 = int(round(cx - s / 2)), int(round(cy - s / 2))
        crop = cv2.resize(img[y0:y0 + s, x0:x0 + s], (72, 72), interpolation=cv2.INTER_CUBIC)
        m = bank.classify(crop)
        assert m.hero_id == hid, f"英雄 {hid} 的放大偏下取景認不出來（得到 {m.hero_id}）"


def test_tightly_cropped_portrait_still_matches():
    """回歸：薇古絲（Vex）的格子被裁得「太貼」時曾經認不出來。

    客戶端在 1920x1080 基準給的是 72x72 的格子，頭像剛好填滿、四周幾乎沒有留邊；
    官網頭像則有留邊。特徵因此對不上：實測正確答案只有 0.583、排 19 名，
    使用者看到的就是「無法識別」。補一圈暗邊再取特徵（PADS）就能修好（0.813）。
    這裡用合成圖驗證「頭像填滿整個格子」的情況仍能認對。"""
    icons = _icons()
    bank = IconBank(icons)
    for hid, img in icons.items():
        # 把整張官網圖塞滿格子：等於客户端的框比頭像還貼
        tight = cv2.resize(img, (72, 72), interpolation=cv2.INTER_AREA)
        m = bank.classify(tight)
        assert m.hero_id == hid, f"英雄 {hid} 在「頭像填滿格子」的取景下認不出來（得到 {m.hero_id}）"


def test_padded_variants_do_not_match_blank_slots():
    """補邊變體不能讓空格、深色空格被誤認成英雄。"""
    from lolhex.vision.portraits import PADS
    assert PADS, "PADS 應該是開啟的（修薇古絲用的）"
    bank = IconBank(_icons())
    for value in (0, 12, 18, 24, 30, 40, 55, 70):
        flat = np.full((72, 72, 3), value, np.uint8)
        m = bank.classify(flat)
        assert m.hero_id is None, f"純色 {value} 被誤認成 {m.hero_id}"


def test_occupied_slot_with_unknown_champion_is_reported(monkeypatch):
    frame = np.full((1080, 1920, 3), 22, np.uint8)
    layout = {"bench": [], "team": []}
    # 一格有頭像（彩色、有明暗變化）但不在圖標庫裡 → 認不出
    unknown_img = np.zeros((56, 56, 3), np.uint8)
    unknown_img[:, :28] = (200, 60, 40)
    unknown_img[:, 28:] = (40, 90, 200)
    frame[20:76, 500:556] = unknown_img
    layout["bench"].append((500 / 1920, 20 / 1080, 556 / 1920, 76 / 1080))
    # 一格是真正的空位（近乎純色）
    frame[20:76, 700:756] = (30, 26, 24)
    layout["bench"].append((700 / 1920, 20 / 1080, 756 / 1920, 76 / 1080))
    monkeypatch.setattr(champselect, "LAYOUT", layout)
    got = champselect.read(frame, IconBank(_icons()), (0, 0))
    assert got["bench"] == []
    assert [u["slot"] for u in got["unknown"]] == [0]
    assert got["unknown"][0]["box"] == (500, 20, 556, 76)


def test_summary_mentions_unknown_count():
    """彙總行要把「無法識別 N 個」寫出來，不能靜靜省略。"""
    pytest.importorskip("PySide6")
    from lolhex.ui.overlay import champ_select_summary
    cs = {"mine": None, "team": [], "bench": [],
          "unknown": [{"kind": "bench", "slot": 0, "score": 0.6, "box": (0, 0, 1, 1)},
                      {"kind": "bench", "slot": 3, "score": 0.5, "box": (0, 0, 1, 1)}]}
    s = champ_select_summary(cs)
    assert "無法識別 2 個" in s
    assert "暫無資料" not in s

