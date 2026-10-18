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
    def __init__(self, names: dict[str, str], threshold: float = 72.0):
        """names: {id: 顯示名}。"""
        self.threshold = threshold
        self._ids: list[str] = []
        self._keys: list[str] = []
        for i, value in names.items():
            variants = value if isinstance(value, (list, tuple, set)) else [value]
            seen = set()
            for name in variants:
                for candidate in (name or '', _LOCALIZER.tw(name or '')):
                    k = normalize(candidate)
                    if k and k not in seen:
                        seen.add(k)
                        self._ids.append(i)
                        self._keys.append(k)

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
