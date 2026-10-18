"""騰訊國服公開資料（101.qq.com / 掌盟同源）。

兩類來源：
- 靜態資料 game.gtimg.cn：英雄、海克斯（kiwi）、裝備、技能。
- 統計 mlol.qt.qq.com/go/battle_info/odp_proxy：海克斯大亂斗的英雄榜、海克斯榜、
  單英雄的海克斯/出裝/加點。按天更新（欄位 dtstatdate）。

這些介面沒有公開文件，欄位含義按 101.qq.com 前端的用法與數值核對得出；
解析函式都是純函式，介面變了只需改這裡和對應測試。
"""

from __future__ import annotations

import json
import re

from . import http

GTIMG = "https://game.gtimg.cn/images/lol/act/img"
MLOL = "https://mlol.qt.qq.com/go"
ODP = MLOL + "/battle_info/odp_proxy"
REFERER = "https://101.qq.com/"

RARITY = {"kSilver": "silver", "kGold": "gold", "kPrismatic": "prismatic"}
RARITY_CN = {"silver": "白銀", "gold": "黃金", "prismatic": "稜彩"}
SKILL_KEYS = {"1": "Q", "2": "W", "3": "E", "4": "R"}


# ---------- 抓取 ----------

def fetch_versions() -> list[dict]:
    return http.get_json(f"{MLOL}/database/versionlist?zone=lol&from=h5", referer=REFERER)["data"]


def fetch_hero_list() -> dict:
    return http.get_json(f"{GTIMG}/js/heroList/hero_list.js")


def fetch_kiwi_augments() -> list:
    return http.get_json(f"{GTIMG}/js/kiwi/kiwi_augments.json")


def fetch_items() -> dict:
    return http.get_json(f"{GTIMG}/js/items/items.js")


def fetch_summoner_spells() -> dict:
    return http.get_json(f"{GTIMG}/js/summonerskillList/summonerskill_list.js")


def fetch_hero_file(hero_id: str) -> dict:
    return http.get_json(f"{GTIMG}/js/hero/{hero_id}.js")


def fetch_hero_rank(dtstatdate: str) -> dict:
    """必須帶統計日期（yyyymmdd）；當天資料未生成時返回空，呼叫方應往前一天重試。"""
    return http.get_json(f"{ODP}/fuwen_aram_hero_rank_v2?dtstatdate={dtstatdate}", referer=REFERER)


def fetch_augment_rank() -> dict:
    return http.get_json(f"{ODP}/fuwen_aram_rune_rank_v2?augmentid_level=255", referer=REFERER)


def fetch_hero_hex(hero_id: str) -> dict:
    return http.get_json(f"{ODP}/fuwen_hero_rank?championid={hero_id}", referer=REFERER)


# ---------- 解析 ----------

def _field_values(raw: dict) -> dict:
    """odp_proxy 的返回：{"code":0,"data":{"_fieldValues":{"R12345":"<json 字串>"}}}。"""
    if not isinstance(raw, dict) or raw.get("code") not in (0, "0"):
        raise ValueError("odp_proxy 返回異常")
    fv = (raw.get("data") or {}).get("_fieldValues") or {}
    out: dict = {}
    for v in fv.values():
        try:
            inner = json.loads(v) if isinstance(v, str) else v
        except ValueError:
            continue
        if isinstance(inner, dict):
            out.update(inner)
    return out


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _i(x) -> int | None:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def parse_hero_list(raw: dict) -> dict[str, dict]:
    heroes = {}
    for h in raw.get("hero", []):
        hid = str(h["heroId"])
        heroes[hid] = {
            "id": hid,
            # 騰訊的 name 是稱號（迅捷斥候），title 是英雄名（提莫）；這裡反過來存更直觀。
            "name": h.get("title") or h.get("name"),
            "nick": h.get("name"),
            "alias": h.get("alias"),
            "icon": f"{GTIMG}/champion/{h.get('alias')}.png",
            "keywords": h.get("keywords", ""),
            # 定位：fighter 戰士 / mage 法師 / assassin 刺客 / tank 坦克 / marksman 射手 / support 輔助，主定位在前
            "roles": list(h.get("roles") or []),
        }
    return heroes


_TAG = re.compile(r"<[^>]+>")


def parse_kiwi_augments(raw: list) -> dict[str, dict]:
    out = {}
    for a in raw:
        aid = str(a["augmentID"])
        modes = [m.strip() for m in str(a.get("mode", "")).split(",") if m.strip()]
        out[aid] = {
            "id": aid,
            "name": a.get("name_cn", "").strip(),
            "en": a.get("name_en", ""),
            "rarity": RARITY.get(a.get("level", ""), "unknown"),
            "desc": _TAG.sub("", a.get("tooltip") or a.get("desc") or "").strip(),
            "icon": a.get("small_Icon") or a.get("large_Icon") or "",
            "modes": modes,
        }
    return out


def parse_summoner_spells(raw: dict) -> dict[str, dict]:
    """召喚師技能：id 與 Riot 一致（4 閃現、14 引燃、32 標記…），帶官方圖示。"""
    out = {}
    for sid, s in (raw.get("summonerskill") or {}).items():
        if s.get("name") and s.get("icon"):
            out[str(sid)] = {"id": str(sid), "name": s["name"], "icon": s["icon"]}
    return out


def parse_items(raw: dict) -> dict[str, dict]:
    out = {}
    for it in raw.get("items", []):
        iid = str(it["itemId"])
        out[iid] = {
            "id": iid,
            "name": it.get("name", ""),
            "icon": it.get("iconPath", ""),
            "desc": it.get("plaintext") or "",
            "price": _i(it.get("total")),
        }
    return out


def parse_hero_splash(raw: dict) -> str | None:
    """英雄原畫（預設皮膚的大圖）。"""
    for s in raw.get("skins", []):
        if s.get("mainImg"):
            return s["mainImg"]
    return None


def parse_hero_spells(raw: dict) -> dict[str, dict]:
    spells = {}
    for s in raw.get("spells", []):
        key = str(s.get("spellKey", "")).upper()
        if key in ("Q", "W", "E", "R", "PASSIVE"):
            spells[key] = {"name": s.get("name", ""), "icon": s.get("abilityIconPath", "")}
    return spells


def parse_hero_rank(raw: dict) -> tuple[str, dict[str, dict]]:
    """英雄榜。記錄用 # 分隔，欄位用 _ 分隔：
    heroId_rank_排名變化_勝率_選取率_隊友列表_評分_…_推薦海克斯(逗號分隔)。"""
    fv = _field_values(raw)
    out = {}
    for rec in str(fv.get("listcollect", "")).split("#"):
        f = rec.split("_")
        if len(f) < 5:
            continue
        hid = f[0]
        out[hid] = {
            "rank": _i(f[1]),
            "rank_change": f[2],
            "win": _f(f[3]),
            "pick": _f(f[4]),
            "top_augments": [x for x in (f[10].split(",") if len(f) > 10 else []) if x],
        }
    return str(fv.get("dtstatdate", "")), out


def parse_augment_rank(raw: dict) -> tuple[str, dict[str, dict]]:
    """海克斯總榜：augId_level_選取率_選取排名_變化_勝率_勝率排名_變化_常用英雄。"""
    fv = _field_values(raw)
    out = {}
    for rec in str(fv.get("augmentlist", "")).split("#"):
        f = rec.split("_")
        if len(f) < 7:
            continue
        out[f[0]] = {
            "pick": _f(f[2]),
            "pick_rank": _i(f[3]),
            "win": _f(f[5]),
            "win_rank": _i(f[6]),
            "heroes": [x for x in (f[8].split(",") if len(f) > 8 else []) if x],
        }
    return str(fv.get("dtstatdate", "")), out


def _seq_to_keys(seq: str) -> list[str]:
    return [SKILL_KEYS.get(x, x) for x in seq.split("&") if x]


def parse_hero_hex(raw: dict) -> dict:
    """單英雄的海克斯、出裝、加點。"""
    fv = _field_values(raw)
    out: dict = {"date": str(fv.get("dtstatdate", ""))}

    # 海克斯：分段 "255:…&kGold:…&kPrismatic:…&kSilver:…"，255 是不分稀有度的總排名。
    # 每條 rank|hero|aug|稀有度|選取率|層級，組內已按層級→選取率排好。
    by_id: dict[str, dict] = {}
    for section in str(fv.get("augment_json_irank", "")).split("&"):
        key, _, body = section.partition(":")
        for rec in body.split("#"):
            f = rec.split("|")
            if len(f) < 6:
                continue
            a = by_id.setdefault(f[2], {"id": f[2], "rarity": None, "rank": None, "tier": None,
                                        "pick": _f(f[4]), "overall_rank": None, "overall_tier": None})
            if key == "255":
                a["overall_rank"] = _i(f[0])
                a["overall_tier"] = f[5].strip() or None
            else:
                a["rarity"] = RARITY.get(key, key)
                a["rank"] = _i(f[0])
                a["tier"] = f[5].strip() or None
    out["augments"] = sorted(by_id.values(), key=lambda a: (a["rarity"] or "", a["rank"] or 999))

    # 出裝
    builds: dict = {}
    full = []
    for rec in str(fv.get("itemover_rec", "")).split(";"):
        f = rec.split("_")
        if len(f) >= 4:
            full.append({"items": [x for x in f[1].split(",") if x], "pick": _f(f[2]), "win": _f(f[3])})
    builds["full"] = full

    def _json(key):
        try:
            return json.loads(fv.get(key) or "{}")
        except ValueError:
            return {}

    core = []
    for _, v in sorted(_json("itemcore_json").items(), key=lambda kv: _i(kv[0]) or 0):
        core.append({
            "items": [x for x in str(v.get("itemcore", "")).split("&") if x],
            "win": (_i(v.get("winrate")) or 0) / 10000,
            "pick": (_i(v.get("showrate")) or 0) / 10000,  # showrate 是出場率（萬分比），不是場次
        })
    builds["core"] = core

    first = []
    for _, v in sorted(_json("itemone_json").items(), key=lambda kv: _i(kv[0]) or 0):
        # 單件裝備：出過這件裝備的對局佔比（各件加起來遠超 100%），不是"第一件"
        first.append({"item": str(v.get("itemone")), "win": (_i(v.get("winrate")) or 0) / 10000,
                      "pick": (_i(v.get("showrate")) or 0) / 10000})
    builds["first"] = first

    def _dollar_list(key, multi):
        res = []
        for rec in str(fv.get(key, "")).split("#"):
            f = rec.split("$")
            if len(f) >= 3:
                items = [x for x in f[0].split(",") if x]
                res.append({("items" if multi else "item"): items if multi else items[0],
                            "pick": _f(f[1]), "win": _f(f[2])})
        return res

    builds["shoes"] = _dollar_list("itemshoes", multi=False)
    builds["start"] = _dollar_list("itemout", multi=True)
    out["builds"] = builds

    # 技能：先按主升順序（qwe）聚合，再給出前幾種逐級加點。
    orders = []
    for _, v in sorted(_json("skill_json").items(), key=lambda kv: _i(kv[0]) or 0):
        seqs = []
        for _, s in sorted((v.get("sks") or {}).items(), key=lambda kv: _i(kv[0]) or 0):
            seqs.append({"seq": _seq_to_keys(str(s.get("sk", ""))), "games": _i(s.get("sk_s")),
                         "win": (_i(s.get("sk_w")) or 0) / 10000})
        orders.append({"max": _seq_to_keys(str(v.get("qwe", ""))), "games": _i(v.get("qwe_s")),
                       "win": (_i(v.get("qwe_w")) or 0) / 10000, "sequences": seqs})
    out["skills"] = orders

    partners = []
    for rec in str(fv.get("championid_json", "")).split("#"):
        f = rec.split("|")
        if len(f) >= 4:
            partners.append({"hero": f[0], "win": _f(f[1]), "pick": _f(f[2]), "rank": _i(f[3])})
    out["partners"] = partners
    return out
