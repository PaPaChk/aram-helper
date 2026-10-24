"""選英雄介面（大亂鬥）的頭像位置與讀取。只讀螢幕畫素，不接入客戶端。

客戶端介面按視窗等比縮放，所以頭像位置用視窗比例儲存，1080p / 2K / 4K 通用。
- bench：頂部"可選英雄"預選欄（最多 10 個）；
- cards：開局"選擇你的英雄"階段中間的 2–3 張英雄卡，讀卡片下方的英雄稱號；
- team：左側我方 5 個召喚師。隊友頭像顯示的是所選皮膚，頭像比對可能認不出，
  所以優先用每行的英雄稱號文字（如"卡牌大師"）識別，頭像比對兜底；自己那一行稱號是金色字。
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from .portraits import IconBank

log = logging.getLogger(__name__)

# 以 1920×1080 客戶區為基準量取（國服 2026-09 客戶端實機截圖），存成比例。
REF_W, REF_H = 1920, 1080


def _r(x0, y0, x1, y1):
    return (x0 / REF_W, y0 / REF_H, x1 / REF_W, y1 / REF_H)


# (x0, y0, x1, y1)，相對客戶端視窗客戶區。
LAYOUT: dict[str, list[tuple[float, float, float, float]]] = {
    # 頂部"可用"預選欄：10 個方形頭像，邊長 72，間距 88
    "bench": [_r(528 + 88 * i, 16, 600 + 88 * i, 88) for i in range(10)],
    # 左側我方 5 人的圓形頭像，直徑約 86，行距 120
    "team": [_r(85, 160 + 120 * i, 171, 246 + 120 * i) for i in range(5)],
}
# 預選欄左邊的"可使用的英雄"：只有選英雄介面有，用來確認當前介面，避免在大廳等介面誤標。
# 量自 2026-10 台服客戶端實機截圖：文字實際範圍 x 358..482, y 31..59（1920×1080 基準）。
# 這個框必須留在該範圍內：往左或往下放大就會框到大廳的《英雄聯盟》導覽列（x 349..477, y 46..79），
# OCR 會改讀到導覽列的字，於是永遠認不出選英雄介面。
MARKER_BOX = _r(352, 28, 492, 62)
# 標題實際文字是「可使用的英雄」。原本只比對「可用」，但三個字並不連續（可-使-用），
# 用 in 比對永遠不會成立，於是整個選英雄介面都判定失敗。這裡放真正會出現的字串。
MARKER_TEXT = ("可使用的英雄", "可使用", "可用")
# 開局"選擇你的英雄"：標題、卡片稱號所在的橫條、卡片上下邊和半寬
CARD_TITLE_BOX = _r(780, 155, 1140, 220)
CARD_TITLE_TEXT = "選擇你的英雄"
CARD_NAME_BAND = _r(430, 600, 1490, 690)
CARD_TOP, CARD_BOTTOM, CARD_HALF_W = 270 / REF_H, 718 / REF_H, 138 / REF_W
# 我方每行的英雄名文字區域：自己那一行是金色字
NAME_BOXES = [_r(188, 176 + 120 * i, 330, 206 + 120 * i) for i in range(5)]


class Memo:
    """按小塊畫面快取識別結果：和上次識別時的畫面比，沒變就直接用上次的結果。
    選人介面大部分時間是靜止的，這樣可以掃得很勤，而幾乎不多佔 CPU。

    keep(結果) 為假的結果（沒認出來）不復用：卡片和文字是淡入的，淡入到六七成時
    縮圖已經和最終畫面差不多，卻還認不出字；快取下來就會一直"認不出"，直到畫面大變。

    結果要等連續兩次畫面一樣才複用：換英雄時名字淡出淡入，半透明那一幀可能還讀成舊英雄，
    快取下來以後最終畫面和它差得不多，就會一直顯示舊英雄。

    縮圖按原比例縮到 ROWS 行高，比較逐畫素差的 99 分位：名字是細長橫條，換一個字只改動
    一小塊；以前壓成 12×12 再比平均差，同字數的兩個名字（如寒冰射手→暗夜獵手）會被當成沒變。"""
    ROWS = 24    # 縮圖行高；寬按原比例，最多 8 倍
    TOL = 12.0   # 逐畫素差 99 分位在這以內算沒變（換一個字也有 90 以上，截圖噪聲約 1）

    def __init__(self):
        self._d: dict = {}
        self.seen = {}  # 診斷日誌用：同樣的情況只記一次

    def _sig(self, crop):
        h, w = crop.shape[:2]
        cols = max(1, min(self.ROWS * 8, round(self.ROWS * w / max(1, h))))
        return cv2.resize(crop, (cols, self.ROWS), interpolation=cv2.INTER_AREA).astype(np.float32)

    def __call__(self, key, crop, fn, keep=None):
        if crop is None or crop.size == 0:
            return fn(crop)
        sig = self._sig(crop)
        key = (key, crop.shape)
        hit = self._d.get(key)
        same = hit is not None and float(np.percentile(np.abs(hit[0] - sig), 99)) < self.TOL
        if same and hit[2] and (keep is None or keep(hit[1])):
            return hit[1]
        val = fn(crop)
        self._d[key] = (sig, val, same)  # 和上次畫面一樣才算靜止，下次可以直接複用
        return val


def _plain(key, crop, fn, keep=None):
    return fn(crop)


def boxes(kind: str, width: int, height: int) -> list[tuple[int, int, int, int]]:
    rects = NAME_BOXES if kind == "team_name" else LAYOUT.get(kind, [])
    return [(int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height))
            for x0, y0, x1, y1 in rects]


def is_champ_select(img, recognize, memo=None) -> bool:
    """recognize(小塊圖) → (文字, 置信度)。讀到"可用"才算在選英雄介面。"""
    txt, sc = (memo or _plain)("marker", _crop(img, MARKER_BOX), recognize, _has_text(MARKER_TEXT))
    return _has_text(MARKER_TEXT)((txt, sc))


def _has_text(want):
    """want 可以是字串或字串tuple：任何一個出現就算命中。"""
    wants = (want,) if isinstance(want, str) else tuple(want)

    def check(r):
        if r[1] < 0.6:
            return False
        text = (r[0] or "").replace(" ", "")
        return any(w in text for w in wants)
    return check


def _crop(img, box):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def text_spans(band) -> list[tuple[int, int]]:
    """卡片稱號橫條 → 每段淺色文字的 (x0, x1)。稱號是米白字、卡底是深紫色；
    卡片邊框是細豎線，按寬度過濾掉。"""
    if band is None or band.size == 0:
        return []
    h, w = band.shape[:2]
    light = band.min(axis=2) > 150  # 米白字三個通道都亮；金色花紋藍通道暗
    cols = light.sum(axis=0) >= max(2, h // 30)
    gap, min_w, pad = max(4, w // 50), max(12, w // 25), max(4, w // 100)
    spans, start, last = [], None, None
    for x, on in enumerate(cols):
        if on:
            if start is None:
                start = x
            elif x - last > gap:
                spans.append((start, last))
                start = x
            last = x
    if start is not None:
        spans.append((start, last))
    return [(max(0, a - pad), min(w, b + 1 + pad)) for a, b in spans if b - a >= min_w]


def read_cards(img, recognize, detect, name_to_hero, origin: tuple[int, int] = (0, 0),
               memo=None) -> list[dict]:
    """開局英雄卡（二選一/三選一）。不在這個階段時返回 []。
    detect(圖) → 文字行列表（帶 box）；name_to_hero(文字) → 英雄 id 或 None。"""
    memo = memo or _plain
    title = memo("card_title", _crop(img, CARD_TITLE_BOX), recognize, _has_text(CARD_TITLE_TEXT))
    seen = getattr(memo, "seen", {})
    if not _has_text(CARD_TITLE_TEXT)(title):
        seen.pop("title", None)
        seen.pop("cards", None)
        return []
    if not seen.get("title"):
        seen["title"] = True
        log.info("選英雄：看到「%s」", CARD_TITLE_TEXT)
    h, w = img.shape[:2]
    bx0 = int(CARD_NAME_BAND[0] * w)

    def lines(band):
        # 先按亮度列投影切出每段稱號，只對這幾段做文字識別（每段約 10ms）；
        # 切不出來再退回整條文字檢測（約 0.5s）
        out = []
        for x0, x1 in text_spans(band):
            t, c = recognize(band[:, x0:x1])
            out.append((t, c, x0, x1))
        if not any(name_to_hero(t) for t, *_ in out):
            out = [(ln.text, ln.score, ln.box[0], ln.box[2]) for ln in detect(band)]
        return out

    cards = []
    found = memo("card_band", _crop(img, CARD_NAME_BAND), lines,
                 lambda out: sum(1 for t, *_ in out if name_to_hero(t)) >= 2)  # 至少二選一
    for text, score, x0, x1 in found:
        hid = name_to_hero(text)
        if not hid:
            continue
        cx = bx0 + (x0 + x1) / 2
        half = CARD_HALF_W * w
        cards.append({"slot": len(cards), "hero_id": hid, "score": round(float(score), 3),
                      "box": (int(cx - half) + origin[0], int(CARD_TOP * h) + origin[1],
                              int(cx + half) + origin[0], int(CARD_BOTTOM * h) + origin[1])})
    cards.sort(key=lambda c: c["box"][0])
    for i, c in enumerate(cards):
        c["slot"] = i
    got = tuple(c["hero_id"] for c in cards)
    if seen.get("cards") != got:
        seen["cards"] = got
        if len(cards) >= 2:
            log.info("選英雄：認出 %d 張英雄卡 %s", len(cards), list(got))
        else:
            log.info("選英雄：標題在，英雄卡沒認全，文字識別讀到 %s", [(t, round(float(sc), 2)) for t, sc, *_ in found])
    return cards


def my_slot(img) -> int | None:
    """我方哪一行是自己：英雄名是金色字（其他人是白字）。"""
    h, w = img.shape[:2]
    best, idx = 0.0, None
    for i, (x0, y0, x1, y1) in enumerate(boxes("team_name", w, h)):
        c = img[y0:y1, x0:x1].astype(int)
        if c.size == 0:
            continue
        b, g, r = c[..., 0], c[..., 1], c[..., 2]
        gold = ((r > 190) & (g > 140) & (b < 120) & (r - b > 110)).mean()
        if gold > best:
            best, idx = float(gold), i
    return idx if best >= 0.02 else None


def read(img, bank: IconBank, origin: tuple[int, int] = (0, 0), name_reader=None, memo=None) -> dict:
    """截圖（客戶端客戶區）→ {"bench": [...], "team": [...], "mine": 自己的英雄 id 或 None}。
    每項 {"slot", "hero_id", "score", "box"}，box 為螢幕物理畫素座標；認不出的位置不返回。
    name_reader(小塊圖) → 英雄 id 或 None：用來讀我方每行的英雄稱號。
    memo：Memo 例項時，畫面沒變的位置直接用上次的結果。"""
    memo = memo or _plain
    h, w = img.shape[:2]
    ox, oy = origin
    out: dict = {}
    names = boxes("team_name", w, h)
    for kind in LAYOUT:
        found = []
        for i, (x0, y0, x1, y1) in enumerate(boxes(kind, w, h)):
            hid, score = None, 0.0
            if kind == "team" and name_reader is not None:
                nx0, ny0, nx1, ny1 = names[i]
                hid = memo(("name", i), img[ny0:ny1, nx0:nx1], name_reader, bool)
                score = 1.0 if hid else 0.0
            if hid is None:
                m = memo((kind, i), img[y0:y1, x0:x1], bank.classify)
                hid, score = m.hero_id, m.score
            if hid:
                found.append({"slot": i, "hero_id": hid, "score": round(score, 3),
                              "box": (x0 + ox, y0 + oy, x1 + ox, y1 + oy)})
        out[kind] = found
    me = my_slot(img)
    out["mine"] = next((s["hero_id"] for s in out["team"] if s["slot"] == me), None)
    return out
