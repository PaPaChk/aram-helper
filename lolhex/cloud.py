"""雲控配置：aramhex.com/config.json（網站和軟體共用，改了不用發版）。

    downloads   網盤連結 {setup, portable}（每次發版會換）
    community   社群入口列表 [{name, text, url, qr, primary}]：QQ 群、B 站、贊助……
                軟體「關於」裡全部列出；primary 的那條在主介面頂部顯示成按鈕（網站同理）
    notice      公告 {id, text, url}：同一個 id 只彈一次
    min_version 低於這個版本必須更新
    rank        查分 {enabled, api, message}：可以遠端關掉查詢
    event       當前活動 {mode, label, start, end}：例如 first-prismatic「首次必稜彩」，活動期間改用這個規則的統計資料
    mirrors     額外線路 {update: [".../{version}"], data: [...]}：換伺服器、加線路不用發版，排在內建線路前面
    features    功能開關（預留）：{名字: true/false}

連不上就用上次存下的（app_home/cloud.json），再沒有就用內建預設值。
"""

from __future__ import annotations

import json
import logging
import threading

import requests

from . import WEBSITE, __version__
from .config import app_home

log = logging.getLogger(__name__)
URL = f"{WEBSITE}/config.json"
DEFAULT = {
    "downloads": {},
    "community": [],
    "notice": {},
    "min_version": "",
    "rank": {"enabled": True, "api": f"{WEBSITE}/api/rank", "message": ""},
    "event": {"mode": "", "label": "", "start": "", "end": ""},
    "mirrors": {"update": [], "data": []},
    "features": {},
}
_lock = threading.Lock()
_cache: dict | None = None


def _path():
    return app_home() / "cloud.json"


def _merge(raw: dict) -> dict:
    out = json.loads(json.dumps(DEFAULT))
    for k, v in (raw or {}).items():
        if k == "community" and isinstance(v, list):
            items = []
            for it in v[:8]:
                if not isinstance(it, dict) or not str(it.get("name") or "").strip():
                    continue
                url = str(it.get("url") or "")
                qr = str(it.get("qr") or "")
                items.append({"name": str(it["name"]).strip()[:20], "text": str(it.get("text") or "").strip()[:40],
                              "url": url if url.startswith(("https://", "http://")) else "",
                              "qr": qr if qr.startswith("https://") else "", "primary": bool(it.get("primary"))})
            out[k] = items
        elif k == "mirrors" and isinstance(v, dict):
            for kk in ("update", "data"):
                urls = v.get(kk)
                if isinstance(urls, list):
                    out[k][kk] = [u for u in urls if isinstance(u, str) and u.startswith("https://")][:5]
        elif k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k].update({kk: vv for kk, vv in v.items() if isinstance(vv, (str, bool, int, float))})
        elif k in out and not isinstance(out[k], dict) and isinstance(v, (str, int, float)):
            out[k] = str(v)
    return out


def get() -> dict:
    """當前配置（不聯網）。"""
    global _cache
    with _lock:
        if _cache is None:
            try:
                _cache = _merge(json.loads(_path().read_text(encoding="utf-8")))
            except (OSError, ValueError):
                _cache = _merge({})
        return _cache


def mirrors(kind: str) -> list[str]:
    """雲控裡的額外線路（update 裡的 {version} 由呼叫方替換）。"""
    return list((get().get("mirrors") or {}).get(kind) or [])


def community() -> list[dict]:
    return list(get().get("community") or [])


def primary_link() -> dict | None:
    """主介面頂部按鈕：第一條標了 primary 且有連結的。"""
    return next((c for c in community() if c.get("primary") and c.get("url")), None)


def event() -> dict | None:
    """正在進行的活動 {mode, label}；沒有返回 None。start / end 是帶時區的 ISO 時間，空著表示不限。"""
    from datetime import datetime, timezone
    ev = get().get("event") or {}
    mode = str(ev.get("mode") or "").strip()
    if not mode or mode == "normal":
        return None
    now = datetime.now(timezone.utc)
    try:
        if ev.get("start") and now < datetime.fromisoformat(ev["start"]):
            return None
        if ev.get("end") and now >= datetime.fromisoformat(ev["end"]):
            return None
    except ValueError:
        return None
    return {"mode": mode, "label": str(ev.get("label") or mode)}


def feature(name: str, default: bool = True) -> bool:
    v = (get().get("features") or {}).get(name)
    return default if v is None else bool(v)


def refresh(timeout: float = 6, url: str = URL) -> dict:
    """聯網取最新配置並存下來；失敗就返回上次的。"""
    global _cache
    try:
        r = requests.get(url, headers={"User-Agent": f"aramhex/{__version__}"}, timeout=timeout)
        r.raise_for_status()
        raw = r.json()
        if not isinstance(raw, dict):
            raise ValueError("格式不對")
    except (requests.RequestException, ValueError) as e:
        log.info("取雲控配置失敗：%s", e)
        return get()
    cfg = _merge(raw)
    with _lock:
        _cache = cfg
    try:
        _path().write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return cfg
