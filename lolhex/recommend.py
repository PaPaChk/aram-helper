"""三選一評分：以本英雄的海克斯勝率為主，官方層級只做兜底。

資料來源（依次）：
1. 自採統計：本英雄 × 這個海克斯的勝率（可按分段）；
2. 騰訊官方層級 S/A/B/C（沒有勝率時粗估）；
3. 未識別英雄時：自採統計裡這個海克斯在所有英雄上的合計勝率。

分數 = 相對該英雄基準勝率的Δ勝率（百分點）：
1. 貝葉斯平滑：smoothed = (勝率×場次 + 基準×k) / (場次 + k)，k 預設 300，小樣本的高勝率會被拉回基準附近。
2. Δ = smoothed − 該英雄基準勝率。
3. 樣本分檔：<250 局僅參考、250–999 中等、≥1000 充足，顯示在介面上。
4. 首選只在樣本充足（≥1000 局）的海克斯裡挑：冷門海克斯偶爾勝率高，多半是局數少碰巧打出來的。
   比同屏其他海克斯少一個數量級以上（<1/10）的，標"樣本太少"並提示重新整理，不管勝率多高；
   只是不足 1000 局的，不當首選、標"樣本偏少"。三張都不足時才正常比較。
選取率只展示，不進分數：常拿不代表強。
"""

from __future__ import annotations

from .data.tencent import RARITY_CN

TIER_PP = {"S": 1.5, "A": 0.5, "B": -0.5, "C": -1.5, "D": -2.5}
REROLL_BELOW = -0.5  # 低於英雄基準 0.5pp 以上：可考慮重新整理
REROLL_GAP = 2.0     # 比首選低 2pp 以上：可考慮重新整理
RELIABLE_GAMES = 1000  # 本英雄局數達到這個數才能當首選
TOO_FEW_RATIO = 0.1    # 局數不到同屏最多那張的 1/10：樣本太少，提示重新整理


def sample_level(games: int | None) -> str:
    if not games:
        return "none"
    if games < 250:
        return "low"
    if games < 1000:
        return "medium"
    return "high"


SAMPLE_CN = {"none": "無樣本", "low": "樣本少，僅參考", "medium": "樣本中等", "high": "樣本充足"}


def smoothed_delta(win: float | None, games: int | None, base: float | None, k: int) -> float | None:
    """貝葉斯平滑後的Δ勝率（百分點）。"""
    if win is None or base is None or not games:
        return None
    s = (win * games + base * k) / (games + k)
    return (s - base) * 100


def win_ranks(augments: dict, static: dict) -> dict:
    """本英雄同稀有度裡按原始勝率排名；勝率相同名次相同。"""
    groups = {}
    for aid, stats in augments.items():
        win = stats.get("win")
        rarity = (static.get(aid) or {}).get("rarity")
        if rarity and type(win) in (int, float) and 0 <= win <= 1 and stats.get("games", 0) > 0:
            groups.setdefault(rarity, []).append((aid, win))
    ranks = {}
    for rows in groups.values():
        rows.sort(key=lambda row: (-row[1], row[0]))
        previous = None
        rank = 0
        for position, (aid, win) in enumerate(rows, 1):
            if previous is None or win != previous:
                rank = position
            ranks[aid] = {"rank": rank, "rank_total": len(rows), "rank_basis": "hero_rarity_win_rate"}
            previous = win
    return ranks


def evaluate(store, hero_id: str | None, slots: list[str | None], k: int = 300) -> dict:
    # 三選一辨識執行緒不能因單英雄官方資料逾時而卡住；資料由 Engine 背景預取。
    hero = store.hero(hero_id, allow_network=False) if hero_id else None
    ag = store.win_data(hero_id) if hero_id else None
    label = (ag or {}).get("label") or "自採統計"
    ag_augs = (ag or {}).get("augments") or {}
    ranks_by_win = win_ranks(ag_augs, store.augments)
    base = (ag or {}).get("sample_win")
    if base is None and hero_id:
        base = ((store.ranks.get("heroes") or {}).get(str(hero_id)) or {}).get("win")
    official = {a["id"]: a for a in (hero or {}).get("augments", [])}
    rarity_total: dict[str, int] = {}
    for a in official.values():
        if a.get("tier") and a.get("rarity"):
            rarity_total[a["rarity"]] = rarity_total.get(a["rarity"], 0) + 1
    global_augs = store.ranks.get("augments") or {}
    total_games = sum(g.get("games") or 0 for g in global_augs.values())
    global_mean = (sum(g["win"] * g["games"] for g in global_augs.values() if g.get("games")) / total_games
                   if total_games else None)

    results = []
    for idx, aid in enumerate(slots):
        r: dict = {"index": idx, "augment_id": aid, "score": None, "basis": None,
                   "verdict": "unknown", "reasons": []}
        if not aid:
            r["reasons"].append("未識別")
            results.append(r)
            continue
        meta = store.augments.get(aid, {})
        r.update(name=meta.get("name", aid), rarity=meta.get("rarity"), icon=meta.get("icon"),
                 desc=meta.get("desc", ""))
        t = official.get(aid)
        if t:
            r.update(tier=t.get("tier"), pick=t.get("pick"))
        if aid in ranks_by_win:
            r.update(ranks_by_win[aid])
            r["reasons"].append(f"本英雄{RARITY_CN.get(r.get('rarity'), '')}勝率第{r['rank']}/{r['rank_total']}")
        elif t and t.get("rank") and t.get("tier"):
            rarity = t.get("rarity") or meta.get("rarity")
            r.update(rank=t["rank"], rank_total=rarity_total.get(rarity))
            r["reasons"].append(f"官方{RARITY_CN.get(rarity, '')}第{t['rank']}/{rarity_total.get(rarity, '?')}"
                                f"（{t['tier']}級）")

        # 1) 本英雄勝率
        a = ag_augs.get(aid)
        if a and a.get("win") is not None and a.get("games") and base is not None:
            d = smoothed_delta(a["win"], a["games"], base, k)
            r.update(win=a["win"], games=a["games"], sample=sample_level(a["games"]), source="public")
            r["reasons"].append(f"本英雄勝率 {a['win'] * 100:.1f}%（{a['games']}局，{SAMPLE_CN[r['sample']]}，"
                                f"{label}），平滑後較英雄基準 {d:+.1f}pp")
            r["score"] = round(d, 2)
            r["basis"] = "hero_win"
        # 2) 未識別英雄：所有英雄合計的勝率
        if r["score"] is None and not hero_id:
            g = global_augs.get(aid)
            if g and g.get("win") and global_mean:
                d = (g["win"] - global_mean) * 100
                r.update(win=g["win"], games=g.get("games"), score=round(d, 2), basis="global_win")
                r["reasons"].append(f"全英雄勝率 {g['win'] * 100:.1f}%，較平均 {d:+.1f}pp")
        # 3) 只有官方層級
        if r["score"] is None and r.get("tier") in TIER_PP:
            r["score"] = TIER_PP[r["tier"]]
            r["basis"] = "tier_only"
            r["reasons"].append("沒有勝率資料，按官方層級估計，可信度低")
        if r["score"] is None:
            if hero_id and (official or ag):
                r["score"] = -3.0
                r["basis"] = "rare"
                r["reasons"].append("該英雄幾乎不選，資料不足")
            else:
                r["reasons"].append("暫無可靠資料")
        results.append(r)

    scored = [r for r in results if r["score"] is not None]
    hero_games = [r.get("games") or 0 for r in scored if r.get("basis") == "hero_win"]
    most = max(hero_games, default=0)
    for r in scored:
        if r.get("basis") != "hero_win":
            continue
        g = r.get("games") or 0
        if most >= RELIABLE_GAMES and g < most * TOO_FEW_RATIO:
            r["thin"] = "too_few"
            r["reasons"].append(f"只有 {g} 局，比同屏其他海克斯少一個數量級以上，勝率不可信")
        elif most >= RELIABLE_GAMES and g < RELIABLE_GAMES:
            r["thin"] = "few"
            r["reasons"].append(f"只有 {g} 局，勝率偶然性大，不作首選")

    pool = [r for r in scored if not r.get("thin")] or scored
    best = max(pool, key=lambda r: r["score"]) if pool else None
    passed = [r for r in scored if r is not best and r.get("thin") and best is not None and r["score"] > best["score"]]
    for r in scored:
        if r is best:
            r["verdict"] = "best"
        elif r.get("thin") == "too_few":
            r["verdict"] = "reroll"
        elif r.get("thin"):
            r["verdict"] = "ok"
        elif r["score"] < REROLL_BELOW or r["score"] <= best["score"] - REROLL_GAP:
            r["verdict"] = "reroll"
        else:
            r["verdict"] = "ok"

    if best is None:
        advice = "暫無可靠資料，請自行判斷"
    elif len(scored) == len(slots) and all(r["score"] < REROLL_BELOW for r in scored):
        advice = f"三張都不理想，可考慮重新整理；非要選就拿「{best.get('name')}」"
    else:
        advice = f"首選「{best.get('name')}」"
        if passed:
            advice += "；" + "、".join(f"「{r.get('name')}」勝率雖高但" +
                                      {"too_few": "樣本太少，不可信"}.get(r["thin"], "樣本偏少") for r in passed)
    if best is not None and best.get("basis") == "tier_only":
        advice += "（沒有勝率資料，按官方層級）"
    if not hero_id:
        advice += "（未識別英雄，按全英雄資料）"

    return {
        "hero_id": hero_id,
        "base_win": base,
        "slots": results,
        "best_index": best["index"] if best else None,
        "advice": advice,
        "sources": {"tencent_date": (hero or {}).get("date"), "win_source": label,
                    "data_patch": (ag or {}).get("patch"), "patch": store.static.get("patch")},
    }
