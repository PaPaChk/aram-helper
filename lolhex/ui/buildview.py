"""出裝、召喚師技能的富文字（主視窗和浮窗共用）：裝備和召喚師技能都只放圖示。
圖示還沒下載好時先顯示名字，下載完 IconCache.version 變化後介面重新渲染。"""

from __future__ import annotations
from html import escape

GRAY = "#8b93a7"


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _img(path: str, size: int) -> str:
    return f'<img src="{path}" width="{size}" height="{size}" align="middle">'


def item(icons, it: dict, size: int) -> str:
    """裝備：只放圖示（還沒下載好時臨時用名字）。"""
    p = icons.local("item", it.get("id"), it.get("icon")) if icons else None
    return _img(p, size) if p else (it.get("name") or it.get("id") or "")


def spell_pair(icons, row: dict, size: int) -> str:
    """召喚師技能組合：只放圖示（沒下載好時臨時用名字）。"""
    out = []
    for s in row.get("spells") or []:
        p = icons.local("spell", s.get("id"), s.get("icon")) if icons and s.get("id") else None
        out.append(_img(p, size) if p else s.get("name", ""))
    return "&nbsp;".join(out)


def skills_line(d: dict, show_win: bool) -> str | None:
    """加點只寫主副：「主 Q · 副 E」（不列逐級加點）。"""
    sk = d.get("skills") or []
    mx = [k for k in (sk[0].get("max") or []) if k in "QWE"] if sk else []
    if not mx:
        return None
    s = "<b>加點</b>　主 " + mx[0] + (" · 副 " + mx[1] if len(mx) > 1 else "")
    if show_win and sk[0].get("win") is not None:
        s += f" <span style='color:{GRAY}'>{_pct(sk[0]['win'])}</span>"
    return s


def lines(d: dict, icons, show_win: bool, size: int = 24, compact: bool = False) -> list[str]:
    """出裝相關的幾行：召喚師技能（有資料時）、核心三件（最多 3 套）、鞋子、出門裝。compact=浮窗（圖示小一號、行更緊湊）。"""
    b = d.get("builds") or {}
    wr = (lambda x: f" <span style='color:{GRAY}'>{_pct(x)}</span>") if show_win else (lambda x: "")
    out = []
    sums = (d.get("summoners") or [])[: 2 if compact else 3]
    if sums and d.get("summoner_source"):
        out.append("<span style='color:" + GRAY + "'>召喚師技能：" + escape(d["summoner_source"])
                   + " · " + escape(str(d.get("summoner_source_date") or "日期未知")) + "</span>")
    if sums and compact:
        out.append("<b>召喚師技能</b>　" + "　　".join(
            spell_pair(icons, s, size) + f" <span style='color:{GRAY}'>{_pct(s.get('pick'))}</span>" for s in sums))
    elif sums:
        out.append("<b>召喚師技能</b>")
        out.extend(f"　{spell_pair(icons, s, size)} <span style='color:{GRAY}'>出場 {_pct(s.get('pick'))}"
                   + (f" · 勝率 {_pct(s.get('win'))}" if show_win else "") + "</span>" for s in sums)

    def core(c):
        return " → ".join(item(icons, x, size) for x in c.get("items") or []) + wr(c.get("win"))
    cores = b.get("core") or []
    if cores:
        out.append("<b>核心三件</b>")
        out.extend("　" + core(c) for c in cores[:3])
    shoes = (b.get("shoes") or [])[:2]
    if shoes:
        out.append("<b>鞋子</b>　" + "　".join(item(icons, x["item"], size) + wr(x.get("win")) for x in shoes))
    if b.get("start"):
        s = b["start"][0]
        out.append("<b>出門裝</b>　" + " + ".join(item(icons, x, size) for x in s.get("items") or []) + wr(s.get("win")))
    return out
