"""把 OCR 文字模糊匹配到已知名稱（海克斯 / 英雄）。"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process

from ..data.tw_localization import TWLocalizer

_LOCALIZER = TWLocalizer()

_PUNCT = re.compile(r"[\s·•・:：,，.。!！?？'\"“”‘’()（）\[\]【】<>《》\-—_~～|/\\]+")


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return _PUNCT.sub("", s).lower()


class NameMatcher:
    def __init__(self, names: dict[str, str], threshold: float = 72.0,
                 preferred: set[str] | None = None):
        """names: {id: 顯示名}。preferred: 評分層認得的 id（同一個名字對到多個 id 時優先）。

        同一個名字常常同時存在於兩套 id：騰訊 static.json 的 1000+n（1115「頂狙武器」）
        與 CommunityDragon 的裸 n（115）。舊版把兩者都塞進平行陣列、靠 dict 走訪順序
        決定誰贏，於是同一個名字有時解析成有勝率資料的 id、有時解析成沒資料的 id，
        正確的識別結果就變成「暫無可靠資料」，甚至把推薦指向另一張卡。
        現在同名只保留一個 id，並按 (preferred, id 長度, id) 穩定挑選，與走訪順序無關。"""
        self.threshold = threshold
        self._preferred = set(preferred or ())
        self._ids: list[str] = []
        self._keys: list[str] = []
        best: dict[str, tuple[tuple, str]] = {}
        for i, value in names.items():
            variants = value if isinstance(value, (list, tuple, set)) else [value]
            for name in variants:
                for candidate in (name or '', _LOCALIZER.tw(name or '')):
                    k = normalize(candidate)
                    if not k:
                        continue
                    rank = self._rank(i)
                    cur = best.get(k)
                    if cur is None or rank < cur[0]:
                        best[k] = (rank, i)
        for k in sorted(best):  # 排序：索引順序也要穩定，否則同分時 partial 匹配會飄
            self._keys.append(k)
            self._ids.append(best[k][1])

    def _rank(self, i: str) -> tuple:
        """越小越優先：評分層認得的 id > 較長的 id（騰訊 1000+n）> 字串本身（穩定）。"""
        sid = str(i)
        return (0 if sid in self._preferred else 1, -len(sid), sid)

    def __len__(self) -> int:
        return len(self._keys)

    def match(self, text: str) -> tuple[str | None, float]:
        raw_q = normalize(text)
        q = _LOCALIZER.tw(raw_q)
        if len(q) < 2 or not self._keys:
            return None, 0.0
        hit = process.extractOne(q, self._keys, scorer=fuzz.ratio)
        if raw_q != q:
            hit2 = process.extractOne(raw_q, self._keys, scorer=fuzz.ratio)
            if hit2 and (not hit or hit2[1] > hit[1]):
                hit = hit2
        if not hit:
            return None, 0.0
        key, score, pos = hit
        # 名字較長時允許 OCR 多識別出前字尾（如"稜彩階"標記），用 partial 再試一次。
        if score < self.threshold and len(q) > 3:
            hit2 = process.extractOne(q, self._keys, scorer=fuzz.partial_ratio)
            if hit2 and hit2[1] >= 90 and len(hit2[0]) >= 3 and abs(len(hit2[0]) - len(q)) <= 3:
                key, score, pos = hit2
        if score < self.threshold:
            return None, float(score)
        return self._ids[pos], float(score)
