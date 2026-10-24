"""單英雄資料面板：勝率與評級、海克斯全表、出裝、加點。主視窗和遊戲內浮窗共用。"""

from __future__ import annotations

from . import recommend

MIN_SHARE = 0.1     # 出裝按勝率排之前，先去掉出場不到同類最熱門 1/10 的（樣本太少，勝率說明不了什麼）


def _site_build(store, hid: str, allow_network: bool = True) -> dict | None:
    """取台服官網（arammayhem.com）的出裝；沒有網路或沒這個英雄就回 None。

    allow_network=False 時只讀磁碟快取，UI 執行緒才不會被網路卡住。
    """
    mm = getattr(store, "arammayhem", None)
    if mm is None:
        return None
    try:
        slug = mm.champion_slug((store.heroes.get(hid) or {}).get("name") or "")
        if not slug:
            alias = (store.heroes.get(hid) or {}).get("alias")
            slug = str(alias).lower() if alias else None
        return mm.build(slug, allow_network=allow_network) if slug else None
    except Exception:
        return None


def _site_builds(site, store) -> dict | None:
    """把 arammayhem 的台服出裝換成面板用的形狀（item 補 id 與圖示）。

    官網沒有逐個海克斯的勝率、沒有大亂鬥調整值、也沒有海克斯組合，
    那三項仍由原本的騰訊統計與內建資料提供。
    """
    if not site:
        return None
    by_name = {}
    for iid, it in store.items.items():
        name = it.get("name")
        if name:
            by_name.setdefault(name, {"id": str(iid), "name": name, "icon": it.get("icon")})

    def item(name):
        return by_name.get(name) or {"id": name, "name": name, "icon": None}

    def frac(v):
        """官網給的是 46.16 這種百分數，面板要 0.4616。"""
        return None if v is None else (float(v) / 100.0)

    def combo(rows):
        """三件式的名字是「A + B + C」，拆回圖示清單。"""
        out = []
        for r in rows or []:
            names = r.get("items") or [n.strip() for n in str(r.get("name", "")).split("+") if n.strip()]
            out.append({**r, "pick": frac(r.get("pick")), "win": frac(r.get("win")),
                        "items": [item(n) for n in names]})
        return out

    def single(rows):
        out = []
        for r in rows or []:
            names = r.get("items") or [r.get("name")]
            out.append({**r, "pick": frac(r.get("pick")), "win": frac(r.get("win")),
                        "item": item(names[0])})
        return out

    return {
        "start": combo(site.get("start")),
        "core": combo(site.get("core")),
        "full": combo(site.get("full")),
        "shoes": single(site.get("boots")),
        "first": [],
    }


def by_win(rows: list[dict], min_games: int = 0) -> list[dict]:
    """有一定出場的裡面按勝率從高到低排。出場率缺失時用場次比較。"""
    def share(x):
        return x.get("pick") or x.get("games") or 0
    top = max((share(x) for x in rows), default=0)
    keep = [x for x in rows if x.get("win") is not None and share(x) >= top * MIN_SHARE
            and (x.get("games") or min_games) >= min_games]
    return sorted(keep, key=lambda x: -x["win"])


def hero_panel(store, hero_key, k: int = 300, allow_network: bool = True) -> dict | None:
    hid = store.resolve_hero(hero_key)
    if not hid:
        return None
    data = store.hero(hid, allow_network=allow_network) or {}
    ag = store.win_data(hid) or {}
    ag_augs = ag.get("augments") or {}

    augs = []
    seen_augments = set()
    for a in data.get("augments", []):
        meta = store.augments.get(a["id"], {})
        x = ag_augs.get(a["id"]) or {}
        d = None
        if x.get("win") is not None and x.get("games") and ag.get("sample_win") is not None:
            d = recommend.smoothed_delta(x["win"], x["games"], ag["sample_win"], k)
        augs.append({**a, "name": meta.get("name", a["id"]), "icon": meta.get("icon"),
                     "desc": meta.get("desc"), "win": x.get("win"), "games": x.get("games"),
                     "source": "public" if x else None,
                     "delta": None if d is None else round(d, 2),
                     "sample": recommend.sample_level(x.get("games"))})
        seen_augments.add(str(a["id"]))

    # 官方單英雄資料尚未下載時，仍先顯示本地統計能算出的海克斯勝率；
    # 背景預取完成後會清除面板快取，再補上出裝、加點與官方層級。
    for aid, x in ag_augs.items():
        if str(aid) in seen_augments:
            continue
        meta = store.augments.get(str(aid), {})
        d = None
        if x.get("win") is not None and x.get("games") and ag.get("sample_win") is not None:
            d = recommend.smoothed_delta(x["win"], x["games"], ag["sample_win"], k)
        augs.append({"id": str(aid), "name": meta.get("name", str(aid)), "icon": meta.get("icon"),
                     "desc": meta.get("desc"), "win": x.get("win"), "games": x.get("games"),
                     "source": "public", "delta": None if d is None else round(d, 2),
                     "sample": recommend.sample_level(x.get("games"))})

    items = store.items

    def item(i, name=None):
        it = items.get(str(i), {})
        return {"id": str(i), "name": it.get("name") or name or str(i), "icon": it.get("icon")}

    b = data.get("builds") or {}
    # 官方出裝都按勝率排（只比有一定出場的）
    builds = {
        "full": [{**x, "items": [item(i) for i in x["items"]]} for x in by_win(b.get("full", []))],
        "core": [{**x, "items": [item(i) for i in x["items"]]} for x in by_win(b.get("core", []))],
        "first": [{**x, "item": item(x["item"])} for x in by_win(b.get("first", []))],
        "shoes": [{**x, "item": item(x["item"])} for x in by_win(b.get("shoes", []))],
        "start": [{**x, "items": [item(i) for i in x["items"]]} for x in by_win(b.get("start", []))],
    }
    # 台服官網有出裝時優先採用：騰訊那邊常常整隻英雄都抓不到。
    # 官網沒有逐個海克斯勝率，海克斯區塊仍用上面的統計。
    site_skills, site_patch = None, None
    site = _site_build(store, hid, allow_network=allow_network)
    if site:
        sb = _site_builds(site, store)
        if any(sb.get(k) for k in ("start", "core", "full", "shoes")):
            for k in ("start", "core", "full", "shoes"):
                if sb.get(k):
                    builds[k] = sb[k]
        site_skills, site_patch = site.get("skills"), site.get("patch")
    rank = (store.ranks.get("heroes") or {}).get(hid, {})
    n_heroes = len(store.ranks.get("heroes") or {}) or None
    from .ui.aramview import adjustments
    # 加點：官網只有「主點順序 + 出場/勝率」，湊成 skills 需要的形狀；
    # 騰訊有逐級序列時仍以騰訊為準（比較細）。
    skills = data.get("skills", [])
    if not skills and site_skills and site_skills.get("max_order"):
        skills = [{"max": site_skills["max_order"],
                   "pick": ((site_skills.get("pick") or 0) / 100) or None,
                   "win": ((site_skills.get("win") or 0) / 100) or None}]
    return {
        "hero": store.heroes.get(hid),
        "rank": {**rank, "total": n_heroes},
        "augments": augs, "builds": builds, "skills": skills, "spells": data.get("spells", {}),
        "partners": [{**p, "hero": store.heroes.get(p["hero"], {"id": p["hero"]})}
                     for p in data.get("partners", [])],
        "adjust": adjustments(hid, store),
        "date": data.get("date") or (site or {}).get("date"),
        "patch": store.static.get("patch") or site_patch,
        "data_patch": ag.get("patch"), "data_revision": (store.status().get("dataset_revision")),
        "splash": data.get("splash"),
        "win_source": ag.get("label") or "暫無統計資料", "summoners": [],
    }
