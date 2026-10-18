"""單英雄資料面板：勝率與評級、海克斯全表、出裝、加點。主視窗和遊戲內浮窗共用。"""

from __future__ import annotations

from . import recommend

MIN_SHARE = 0.1     # 出裝按勝率排之前，先去掉出場不到同類最熱門 1/10 的（樣本太少，勝率說明不了什麼）


def by_win(rows: list[dict], min_games: int = 0) -> list[dict]:
    """有一定出場的裡面按勝率從高到低排。出場率缺失時用場次比較。"""
    def share(x):
        return x.get("pick") or x.get("games") or 0
    top = max((share(x) for x in rows), default=0)
    keep = [x for x in rows if x.get("win") is not None and share(x) >= top * MIN_SHARE
            and (x.get("games") or min_games) >= min_games]
    return sorted(keep, key=lambda x: -x["win"])


def hero_panel(store, hero_key, k: int = 300) -> dict | None:
    hid = store.resolve_hero(hero_key)
    if not hid:
        return None
    data = store.hero(hid) or {}
    ag = store.win_data(hid) or {}
    ag_augs = ag.get("augments") or {}

    augs = []
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
    rank = (store.ranks.get("heroes") or {}).get(hid, {})
    n_heroes = len(store.ranks.get("heroes") or {}) or None
    return {
        "hero": store.heroes.get(hid),
        "rank": {**rank, "total": n_heroes},
        "augments": augs, "builds": builds, "skills": data.get("skills", []), "spells": data.get("spells", {}),
        "partners": [{**p, "hero": store.heroes.get(p["hero"], {"id": p["hero"]})}
                     for p in data.get("partners", [])],
        "date": data.get("date"), "patch": store.static.get("patch"),
        "data_patch": ag.get("patch"), "data_revision": (store.status().get("dataset_revision")),
        "splash": data.get("splash"),
        "win_source": ag.get("label") or "暫無統計資料", "summoners": [],
    }
