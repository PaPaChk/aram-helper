"""Traditional Chinese names and descriptions for the TW client.

Interaction conclusions remain sourced from the project's curated database.
This module only localizes static Riot assets supplied by CommunityDragon.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover - requirements should install it
    OpenCC = None


class TWLocalizer:
    def __init__(self, path: Path | None = None):
        path = Path(path or Path(__file__).with_name("bundled") / "tw-catalog.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.game_version = data.get("gameVersion") or ""
        self.champions = {str(x.get("id")): x for x in data.get("champions", []) if x.get("id") is not None}
        self.augments = {str(x.get("id")): x for x in data.get("augments", []) if x.get("id") is not None}
        self.items = {str(x.get("id")): x for x in data.get("items", []) if x.get("id") is not None}
        self._converter = OpenCC("s2twp") if OpenCC else None
        self._lock = threading.Lock()

    def tw(self, text):
        if not isinstance(text, str) or not text:
            return text or ""
        if self._converter is None:
            return text
        with self._lock:
            return self._converter.convert(text)

    def _localized(self, record: dict, name_key: str, desc_key: str = "") -> tuple[str, str]:
        name = str(record.get(name_key) or "").strip()
        desc = str(record.get(desc_key) or "").strip() if desc_key else ""
        return name, desc

    def _apply_record(self, obj: dict, record: dict, name_key: str, desc_key: str = "") -> None:
        cn_name = obj.get("name_cn")
        if cn_name is None:
            cn_name = obj.get("name", "")
            obj["name_cn"] = cn_name
        if record:
            name, desc = self._localized(record, name_key, desc_key)
            if name:
                obj["name"] = name
            elif obj.get("name"):
                obj["name"] = self.tw(obj["name"])
            if desc:
                if obj.get("desc_cn") is None:
                    obj["desc_cn"] = obj.get("desc", "")
                obj["desc"] = desc
            elif obj.get("desc"):
                if obj.get("desc_cn") is None:
                    obj["desc_cn"] = obj["desc"]
                obj["desc"] = self.tw(obj["desc"])
            obj["name_en"] = record.get("name_en") or obj.get("name_en") or obj.get("en", "")
        else:
            if obj.get("name"):
                obj["name"] = self.tw(obj["name"])
            if obj.get("desc"):
                if obj.get("desc_cn") is None:
                    obj["desc_cn"] = obj["desc"]
                obj["desc"] = self.tw(obj["desc"])
        obj["locale"] = "zh-TW"

    def apply_static(self, static: dict) -> None:
        for hid, hero in (static.get("heroes") or {}).items():
            rec = self.champions.get(str(hid), {})
            self._apply_record(hero, rec, "name_zh")
            if hero.get("nick"):
                hero["nick_cn"] = hero.get("nick_cn") or hero["nick"]
                hero["nick"] = self.tw(hero["nick"])

        for aid, augment in (static.get("augments") or {}).items():
            self._apply_record(augment, self.augments.get(str(aid), {}), "name_zh", "desc_zh")

        for iid, item in (static.get("items") or {}).items():
            self._apply_record(item, self.items.get(str(iid), {}), "name_zh", "description_zh")

        for spell in (static.get("spells") or {}).values():
            if spell.get("name"):
                spell["name"] = self.tw(spell["name"])

    def apply_hero(self, hero_id: str, data: dict) -> None:
        hero = self.champions.get(str(hero_id), {})
        if hero.get("name_zh"):
            data["name"] = hero["name_zh"]
        elif data.get("name"):
            data["name"] = self.tw(data["name"])
        if data.get("nick"):
            data["nick"] = self.tw(data["nick"])
        for augment in data.get("augments") or []:
            aid = str(augment.get("id", ""))
            self._apply_record(augment, self.augments.get(aid, {}), "name_zh", "desc_zh")
        for spell in (data.get("spells") or {}).values():
            if spell.get("name"):
                spell["name"] = self.tw(spell["name"])
        data["locale"] = "zh-TW"

    def deep_tw(self, value):
        if isinstance(value, str):
            return self.tw(value)
        if isinstance(value, list):
            return [self.deep_tw(x) for x in value]
        if isinstance(value, dict):
            return {self.tw(k) if isinstance(k, str) else k: self.deep_tw(v) for k, v in value.items()}
        return value

    def hero_record(self, hero_id: str) -> dict:
        return self.champions.get(str(hero_id), {})
