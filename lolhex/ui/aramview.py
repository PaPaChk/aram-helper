"""ARAM 專屬調整（英雄增減益）顯示。

資料來自 League of Legends Wiki 的 `Module:ChampionData/data` 的 `["aram"]` 子表，
授權 CC BY-SA 3.0（見專案根目錄 NOTICE.md）。資料檔：`lolhex/data/bundled/aram_adjust.json`。

對外只有一個函式：

    adjustments(hid, store) -> list[str]

`hid` 是內部英雄數字 id（例如 "120"）；`store` 只用來當對照表拿不到 alias 時的備援。
任何問題（檔案缺失、JSON 壞掉、id 不認得）都回傳空 list，不拋例外，不影響介面。
"""

from __future__ import annotations

import json
from pathlib import Path

_BUNDLED = Path(__file__).resolve().parent.parent / "data" / "bundled"
_ADJUST_PATH = _BUNDLED / "aram_adjust.json"
_CATALOG_PATH = _BUNDLED / "tw-catalog.json"

# 乘算欄位：1.0 代表沒調整，顯示成百分比增減。
# 平加欄位：直接顯示 +N / -N。
MULTIPLIER_FIELDS = (
    "dmg_dealt", "dmg_taken", "healing", "shielding", "manaregen_mod",
    "energyregen_mod", "total_as", "ms_mod", "tenacity",
)
FLAT_FIELDS = ("ability_haste",)

# 顯示順序與台服譯名。
LABELS = (
    ("dmg_dealt", "造成傷害"),
    ("dmg_taken", "承受傷害"),
    ("healing", "治療效果"),
    ("shielding", "護盾效果"),
    ("manaregen_mod", "魔力回復"),
    ("energyregen_mod", "能量回復"),
    ("total_as", "攻擊速度"),
    ("ms_mod", "移動速度"),
    ("tenacity", "韌性"),
    ("ability_haste", "技能急速"),
)

_adjust: dict | None = None
_apinames: dict | None = None
_aliases: dict | None = None


def _load_adjust() -> tuple[dict, dict]:
    """(champions: 名稱 -> 數值表, apinames: apiname -> 名稱)。失敗回空字典。"""
    global _adjust, _apinames, _aliases
    if _adjust is None:
        champions: dict = {}
        apinames: dict = {}
        try:
            data = json.loads(_ADJUST_PATH.read_text(encoding="utf-8"))
            raw = data.get("champions")
            if isinstance(raw, dict):
                for key, row in raw.items():
                    if not isinstance(row, dict):
                        continue
                    # 條目內若自帶 apiname，一樣拿來做反查；數值欄位只留真正的數字。
                    api = row.get("apiname")
                    if isinstance(api, str) and api.strip():
                        apinames[api.strip()] = str(key)
                    values = {k: v for k, v in row.items()
                              if k != "apiname" and isinstance(v, (int, float))
                              and not isinstance(v, bool)}
                    if values:
                        champions[str(key)] = values
            mapping = data.get("apinames") or data.get("apiname") or {}
            if isinstance(mapping, dict):
                for k, v in mapping.items():
                    apinames.setdefault(str(k), str(v))
        except (OSError, ValueError, AttributeError):
            champions, apinames = {}, {}
        _adjust, _apinames = champions, apinames
        _aliases = None
    return _adjust, _apinames or {}


def _load_aliases() -> dict:
    """內部英雄 id -> wiki/Riot 英文 alias。"""
    global _aliases
    if _aliases is None:
        mapping: dict = {}
        try:
            data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            for row in data.get("champions") or []:
                if not isinstance(row, dict) or row.get("id") is None:
                    continue
                alias = str(row.get("alias") or "").strip()
                if alias:
                    mapping[str(row["id"])] = alias
        except (OSError, ValueError, AttributeError):
            mapping = {}
        _aliases = mapping
    return _aliases


def _alias_from_store(hid: str, store) -> str:
    """對照表沒有時，從 store 的英雄資料撈 alias。"""
    if store is None:
        return ""
    for getter in ("heroes", "static"):
        try:
            obj = getattr(store, getter, None)
            if obj is None and isinstance(store, dict):
                obj = store.get(getter)
            if isinstance(obj, dict):
                row = obj.get("heroes") if getter == "static" else obj
                if not isinstance(row, dict):
                    row = obj
                rec = row.get(hid) or row.get(str(hid)) or {}
                if isinstance(rec, dict) and rec.get("alias"):
                    return str(rec["alias"]).strip()
        except Exception:
            continue
    return ""


def champion_name(hid, store=None) -> str:
    """把內部英雄 id 換成 wiki 上的英文英雄名；認不得就回空字串。"""
    if hid is None:
        return ""
    key = str(hid).strip()
    if not key:
        return ""
    champions, apinames = _load_adjust()
    if not champions:
        return ""
    if key in champions:
        return key
    alias = _load_aliases().get(key) or _alias_from_store(key, store)
    if not alias:
        return ""
    if alias in champions:
        return alias
    if alias in apinames and apinames[alias] in champions:
        return apinames[alias]
    for name in champions:
        if name.lower() == alias.lower():
            return name
    return ""


def _pct(value: float) -> str:
    """(1.05 -> "+5", 0.9 -> "-10", 1.025 -> "+2.5")。"""
    text = f"{(float(value) - 1.0) * 100:+.1f}"
    return text[:-2] if text.endswith(".0") else text


def _flat(value: float) -> str:
    number = float(value)
    return f"{number:+.0f}" if number == int(number) else f"{number:+g}"


# 這些欄位數值下降才是好事（承受傷害越低越好）。
LOWER_IS_BETTER = {"dmg_taken"}


def _arrow(value: float, field: str) -> str:
    """↑ = 對自己有利，↓ = 不利。承受傷害這類欄位方向相反。

    百分比類欄位（傷害、治療、攻速…）的原始值是以 1.0 為基準的倍率，
    不是 0 為基準的增減量，所以要和 1.0 比；只有 FLAT_FIELDS（技能急速）
    才是以 0 為基準的加減值。
    """
    v = float(value)
    if field in FLAT_FIELDS:
        up = v > 0
    else:
        up = v > 1.0
    if field in LOWER_IS_BETTER:
        return "↑" if not up else "↓"
    return "↑" if up else "↓"


def adjustments(hid, store=None) -> list[str]:
    """回傳這個英雄在 ARAM 的調整字串，例如 ["↑ 造成傷害 +5%", "↓ 承受傷害 -10%"]。

    箭頭代表對自己有利或不利，不是數值本身加或減：承受傷害下降是好事，要標 ↑。
    沒有任何調整、或資料有問題時回傳 []。
    """
    try:
        champions, _ = _load_adjust()
        if not champions:
            return []
        name = champion_name(hid, store)
        mods = champions.get(name) if name else None
        if not isinstance(mods, dict):
            return []

        out: list[str] = []
        for field, label in LABELS:
            if field not in mods:
                continue
            try:
                value = float(mods[field])
            except (TypeError, ValueError):
                continue
            if field in FLAT_FIELDS:
                if value == 0:
                    continue
                out.append(f"{_arrow(value, field)} {label} {_flat(value)}")
            else:
                if abs(value - 1.0) < 1e-9:
                    continue
                pct = (value - 1.0) * 100
                if round(pct, 1) == 0:      # 例如 1.0001，四捨五入後沒有意義
                    continue
                out.append(f"{_arrow(value, field)} {label} {_pct(value)}%")
        return out
    except Exception:
        return []


def patch() -> str:
    """資料對應的版本號（讀不到就回空字串）。"""
    try:
        return str(json.loads(_ADJUST_PATH.read_text(encoding="utf-8")).get("patch") or "")
    except Exception:
        return ""
