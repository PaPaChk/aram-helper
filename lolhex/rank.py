"""查自己的水平：名字#編號 → 區內前百分之幾 + 分段（aramhex.com/api/rank，家裡伺服器經 DMIT 中轉）。

只返回前百分比、分段、近 30 天局數和資料日期，不返回分數。查詢有次數限制。
"""

from __future__ import annotations

import requests

from . import __version__, cloud


class RankError(Exception):
    """查不了：訊息直接給使用者看。"""


def lookup(riot_id: str, timeout: float = 10) -> dict:
    """返回 {"as_of", "results": [...]}；查不到或失敗拋 RankError。"""
    name, sep, tag = (riot_id or "").strip().rpartition("#")
    if not sep or not name.strip() or not tag.strip():
        raise RankError("請填「名字#編號」，比如：提莫#12345")
    cfg = cloud.get().get("rank") or {}
    if not cfg.get("enabled", True):
        raise RankError(cfg.get("message") or "查詢暫時關閉，請稍後再試")
    try:
        r = requests.get(cfg.get("api") or cloud.DEFAULT["rank"]["api"], params={"id": riot_id.strip()},
                         headers={"X-AramHex": __version__, "User-Agent": f"aramhex/{__version__}"}, timeout=timeout)
    except requests.RequestException:
        raise RankError("連不上查詢服務，請稍後再試")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code == 200 and body.get("results"):
        return body
    raise RankError(body.get("error") or ("查詢服務暫時不可用，請稍後再試" if r.status_code >= 500 else f"查詢失敗（{r.status_code}）"))


def _pct(x: float) -> str:
    v = x * 100
    return f"{v:.2f}%" if v < 1 else f"{v:.1f}%" if v < 10 else f"{v:.0f}%"


def describe(res: dict) -> str:
    """一句話：前 3.1%（高分）· 艾歐尼亞 · 近 30 天 120 局 · 資料截至 10-16"""
    if not res or not res.get("results"):
        return ""
    r = res["results"][0]
    s = f"前 {_pct(r['top'])}（{r['band_name']}）· {r['region_name']} · 近 30 天 {r['games']} 局"
    if res.get("as_of"):
        s += f" · 資料截至 {res['as_of'][5:10]}"
    if r.get("solo_top"):
        s += f"<br>單排對局水平：相當於區內前 {_pct(r['solo_top'])}（近 30 天單排 {r.get('solo_games') or 0} 局）"
    if len(res["results"]) > 1:
        s += "<br>另有：" + "、".join(f"{x['region_name']} {x['band_name']}" for x in res["results"][1:3])
    return s
