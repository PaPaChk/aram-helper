"""ARAM Mayhem（arammayhem.com）台服「大混戰」資料：站點字典 + 單英雄出裝。

站點是 Astro 伺服器端渲染，一般 HTTP GET 就能拿到完整 HTML（務必帶 User-Agent，
否則 403）。增幅裝置的 id 是字串 slug（crimson_cobalt），不是 Riot 的數字 id；
本模組用 slug()（CamelCase → snake_case）把 CommunityDragon 的 augmentNameId
橋接到數字 id，讓內部 id 能對上遊戲內中文名。

目錄：<cache_dir>/arammayhem/
  dictionary.json       增幅裝置、裝備、英雄的 zh-TW 字典
  augment_ids.json      CommunityDragon 的數字 id ↔ augmentNameId／官方名稱
  build_<slug>.json     單英雄出裝（按需抓取）

網路失敗一律降級：回傳舊快取或 None，不向呼叫端拋錯。
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import threading
import time
from pathlib import Path

from . import http

log = logging.getLogger(__name__)

BASE = "https://arammayhem.com"
LOCALE = "zh-tw"
DICT_URL = f"{BASE}/{LOCALE}/combo-submission-options.json"
BUILD_URL = f"{BASE}/{LOCALE}/build/{{slug}}/"
# 數字 id 只存在於 Riot 的資料；這裡用 zh_tw 才有台服官方名（nameTRA）。
CDRAGON_AUG = ("https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
               "global/zh_tw/v1/cherry-augments.json")

# 出裝頁四個區塊標題 → 回傳鍵
SECTIONS = {"出門裝": "start", "鞋子": "boots", "核心出裝": "core", "其他完整裝備": "full"}
# 增幅裝置稀有度標題 → 內部值
RARITY_HEADS = {"稜彩增幅裝置": "prismatic", "金色增幅裝置": "gold", "銀色增幅裝置": "silver"}
# CommunityDragon 的稀有度值 → 內部值
CDRAGON_RARITY = {"kSilver": "silver", "kGold": "gold", "kPrismatic": "prismatic"}

# 連續抓多個英雄時，兩次請求之間至少間隔這麼多秒（站點已對同一來源限速）。
BUILD_INTERVAL_S = 0.6
EMPTY_DICT = {"augments": {}, "items": {}, "champions": {}}


# ---------- 通用小工具 ----------


def slug(name: str) -> str:
    """把 CamelCase 的 id 轉成站點用的 snake_case slug。

    CrimsonCobalt → crimson_cobalt、StillHere → still_here、
    Nightstalking → nightstalking、ARAM_BacktoBasics → aram_back_to_basics。
    縮寫與數字邊界也切開（ADAPt → a_da_pt），呼叫端另有容錯比對。
    """
    text = re.sub(r"[^0-9A-Za-z]+", "_", str(name or "").strip())
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)      # aB → a_B
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", text)    # ABCd → AB_Cd
    text = re.sub(r"(?<=[A-Za-z])(?=[0-9])", "_", text)      # a1 → a_1
    text = re.sub(r"(?<=[0-9])(?=[A-Za-z])", "_", text)      # 1a → 1_a
    return re.sub(r"_+", "_", text).strip("_").lower()


def _norm(text) -> str:
    """比對用：只留英數與中日韓字，去掉標點、空白、大小寫差異。"""
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(text or "").lower())


def _read(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data) -> None:
    """寫快取：先寫暫存檔再 replace，避免半截檔案。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _stale(blob: dict, refresh_s: float) -> bool:
    return not blob or time.time() - float(blob.get("fetched_at") or 0) > refresh_s


def _pct(text: str, label: str) -> float | None:
    """抓「標籤（登場率／勝率）後面那個百分比」；抓不到回 None。"""
    m = re.search(label + r"[:：]?\s*<span[^>]*>\s*([\d.]+)\s*%", text)
    return float(m.group(1)) if m else None


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.S)
    return m.group(1) if m else None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


# ---------- 頁面剖析 ----------


def _json_ld_blocks(page: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            block = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(block, dict):
            out.append(block)
    return out


def _ld_item_list(page: str, keyword: str) -> list[dict]:
    """找出名稱含 keyword 的 ItemList，回 [{name, slug}]（JSON-LD 沒有百分比）。"""
    for block in _json_ld_blocks(page):
        if block.get("@type") != "ItemList" or keyword not in str(block.get("name") or ""):
            continue
        rows = []
        for item in block.get("itemListElement") or []:
            name = _clean_text(str(item.get("name") or ""))
            url = str(item.get("url") or "")
            found = re.search(r"/(?:augments|items|champions)/([^/?#]+)/?$", url)
            rows.append({"name": name, "slug": found.group(1) if found else None})
        return rows
    return []


def _champion_name(page: str, ld: list[dict]) -> str | None:
    """英雄中文名：優先麵包屑（純名字），其次 h1（去掉「大混戰出裝」）。"""
    for block in ld:
        if block.get("@type") != "BreadcrumbList":
            continue
        for item in block.get("itemListElement") or []:
            if int(item.get("position") or 0) == 3 and item.get("name"):
                return _clean_text(str(item["name"]))
    h1 = _first(r"<h1[^>]*>([^<]+)</h1>", page)
    if h1:
        return re.sub(r"\s*(?:大混戰|大亂鬥)?出裝\s*$", "", _clean_text(h1)) or None
    return None


def _item_sections(page: str) -> dict[str, str]:
    """依四個 <div class="font-semibold mb-3">標題</div> 的位置切段。"""
    marks = [(m.end(), SECTIONS[m.group(1).strip()]) for m in
             re.finditer(r'<div class="font-semibold mb-3"[^>]*>([^<]{1,16})</div>', page)
             if m.group(1).strip() in SECTIONS]
    out: dict[str, str] = {}
    for i, (start, key) in enumerate(marks):
        if i + 1 < len(marks):
            end = marks[i + 1][0]
        else:
            close = page.find("</section>", start)  # 最後一段：切到下一個 section 結束
            end = close if close > 0 else len(page)
        out.setdefault(key, page[start:end])
    return out


# 一列裝備：整列容器的開頭
_ITEM_ROW = re.compile(r'<div class="flex flex-col gap-2 rounded-md[^"]*"')
_ITEM_LINK = re.compile(r'<a [^>]*href="[^"]*/items/[^"]*"[^>]*>')


def _parse_item_section(segment: str) -> list[dict]:
    """裝備區塊 → [{"name", "pick", "win"}]；一列可能是「長劍 › 海神之斧」的組合。"""
    rows: list[dict] = []
    for chunk in _ITEM_ROW.split(segment)[1:]:
        names: list[str] = []
        for link in _ITEM_LINK.finditer(chunk):
            title = _first(r'title="([^"]*)"', link.group(0))
            if title:
                name = _clean_text(title)
                if name and name not in names:
                    names.append(name)
        if not names:  # 沒有 title 時退而用 sr-only 文字
            for m in re.finditer(r'<span class="sr-only"[^>]*>([^<]+)</span>', chunk):
                name = _clean_text(m.group(1))
                if name and name not in names:
                    names.append(name)
        if not names:
            continue
        entry: dict = {"name": " + ".join(names), "pick": _pct(chunk, "登場率"),
                       "win": _pct(chunk, "勝率")}
        if len(names) > 1:
            entry["items"] = names  # 起手裝常是好幾件一起買，保留原始序列
        rows.append(entry)
    return rows


# 增幅裝置區塊：稀有度標題（class 或文字都認）或一列的開頭
_AUG_TOKEN = re.compile(
    r'<h3[^>]*text-rarity-(prismatic|gold|silver)[^>]*>'
    r'|<h3[^>]*>(稜彩|金色|銀色)增幅裝置</h3>'
    r'|<a [^>]*href="[^"]*/augments/[^"]*"'
)
_AUG_TITLE = r'text-rarity-(?:prismatic|gold|silver)"\s+title="([^"]+)"'


def _augment_window(page: str) -> str:
    head = re.search(r"<h2[^>]*>[^<]*最佳增幅裝置</h2>", page)
    if not head:
        return ""
    tail = page.find("<h2", head.end())
    return page[head.start(): tail if tail > 0 else len(page)]


def _parse_augment_rows(page: str) -> list[dict]:
    """HTML 逐列：名稱、稀有度、登場率／勝率（勝率常常沒有）。"""
    window = _augment_window(page)
    if not window:
        return []
    tokens = list(_AUG_TOKEN.finditer(window))
    rows: list[dict] = []
    rarity: str | None = None
    for i, token in enumerate(tokens):
        if token.group(1) or token.group(2):
            rarity = token.group(1) or RARITY_HEADS.get(token.group(2) + "增幅裝置")
            continue
        end = tokens[i + 1].start() if i + 1 < len(tokens) else len(window)
        chunk = window[token.end():end]
        href_slug = _first(r'/augments/([^/"]+)/', token.group(0))
        name = _first(_AUG_TITLE, chunk) or _first(r'alt="([^"]+)"', chunk)
        if not name or name == "？":
            continue
        rows.append({"name": _clean_text(name), "rarity": rarity,
                     "pick": _pct(chunk, "登場率"), "win": _pct(chunk, "勝率"),
                     "slug": href_slug})
    return rows


def _parse_augments(page: str) -> list[dict]:
    """JSON-LD 的榜單（穩定）＋ HTML 的百分比（唯一來源）合併。"""
    rows = _parse_augment_rows(page)
    listed = _ld_item_list(page, "最佳增幅裝置")
    if not rows:
        return [{"name": r["name"], "rarity": None, "pick": None, "win": None,
                 "slug": r.get("slug")} for r in listed]
    if not listed:
        return rows
    by_name = {r["name"]: r for r in rows}
    merged: list[dict] = []
    for item in listed:
        row = by_name.get(item["name"])
        if row:
            entry = dict(row)
            entry["slug"] = entry.get("slug") or item.get("slug")
        else:
            entry = {"name": item["name"], "rarity": None, "pick": None, "win": None,
                     "slug": item.get("slug")}
        merged.append(entry)
    # 榜單和 HTML 對不上（改版）時，退回 HTML 逐列結果，至少還有數字
    if not any(r.get("pick") is not None for r in merged):
        return rows
    return merged


def _parse_skills(page: str) -> dict | None:
    """技能主升順序：{order, max_order, pick, win}；沒有這個區塊回 None。"""
    head = page.find("技能主升順序")
    if head < 0:
        return None
    close = page.find("</section>", head)
    window = page[head: close if close > 0 else head + 40000]
    m = re.search(r'text-sm font-semibold text-primary"[^>]*>\s*([QWE])\s*(?:&gt;|>)\s*'
                  r'([QWE])\s*(?:&gt;|>)\s*([QWE])\s*<', window)
    if not m:
        return None
    order = None
    seq = re.search(r"技能加點序列[:：]\s*([QWER](?:\s+[QWER])+)", window[m.end():], re.S)
    if seq:
        order = seq.group(1).split()
    stats = window[m.end(): m.end() + 1200]
    return {
        "order": order,
        "max_order": [m.group(1), m.group(2), m.group(3)],
        "pick": _pct(stats, "登場率"),
        "win": _pct(stats, "勝率"),
    }


def _parse_header(page: str) -> dict:
    """勝率、登場率、梯隊、排名、補丁。"""
    out: dict = {"patch": None, "win": None, "pick": None, "tier": None, "rank": None}
    win = re.search(r"<dt[^>]*>勝率</dt><dd[^>]*>\s*([\d.]+)\s*%", page)
    pick = re.search(r"<dt[^>]*>登場率</dt><dd[^>]*>\s*([\d.]+)\s*%", page)
    if win:
        out["win"] = float(win.group(1))
    if pick:
        out["pick"] = float(pick.group(1))
    rank_block = re.search(r"<dt[^>]*>梯隊</dt><dd[^>]*>(.*?)</dd>", page, re.S)
    if rank_block:
        tier = re.search(r"bg-tier-([a-z]+)", rank_block.group(1))
        rank = re.search(r"#(\d+)", rank_block.group(1))
        out["tier"] = tier.group(1).upper() if tier else None
        out["rank"] = int(rank.group(1)) if rank else None
    patch = re.search(r"補丁[:：]\s*([\d.]+)", page) or re.search(r"([\d]+\.\d+)\s*版本", page)
    if patch:
        out["patch"] = patch.group(1)
    return out


def parse_build(page: str, champion: str | None = None) -> dict | None:
    """整頁 HTML → build 字典；連英雄名都認不出來就當作頁面不可用。"""
    ld = _json_ld_blocks(page)
    name = _champion_name(page, ld)
    if not name:
        return None
    data: dict = {"champion": name, "slug": champion}
    data.update(_parse_header(page))
    sections = _item_sections(page)
    for key in ("start", "boots", "core", "full"):
        data[key] = _parse_item_section(sections.get(key, ""))
    data["skills"] = _parse_skills(page)
    data["augments"] = _parse_augments(page)
    return data


# ---------- 主類別 ----------


class AramMayhem:
    """arammayhem.com 台服資料來源：字典與單英雄出裝，全部落盤快取。"""

    def __init__(self, cache_dir: Path, refresh_hours: float = 24.0) -> None:
        self.root = Path(cache_dir) / "arammayhem"
        self.refresh_s = float(refresh_hours) * 3600
        self._lock = threading.RLock()
        self._dict: dict | None = None
        self._augment_ids: dict | None = None
        self._builds: dict[str, dict | None] = {}
        self._last_build_at = 0.0

    # ----- 字典 -----

    def dictionary(self, allow_network: bool = True) -> dict:
        """{"augments": {slug: {...}}, "items": {...}, "champions": {slug: {...}}}。

        有快取且未過期就直接用；過期才聯網。聯網失敗回舊快取，沒有快取回空字典。
        """
        with self._lock:
            if self._dict is None:
                self._dict = _read(self.root / "dictionary.json") or {}
            blob = self._dict
        if blob.get("augments") and (not _stale(blob, self.refresh_s) or not allow_network):
            return blob
        if not allow_network:
            return blob or {k: {} for k in EMPTY_DICT}
        try:
            raw = http.get_json(DICT_URL, timeout=30)
            fresh = _shape_dictionary(raw)
            if not fresh["augments"]:
                raise ValueError("字典沒有增幅裝置資料")
            fresh["fetched_at"] = time.time()
            _write(self.root / "dictionary.json", fresh)
            with self._lock:
                self._dict = fresh
            return fresh
        except Exception as e:  # 網路或格式問題：沿用舊快取
            log.warning("取得 ARAM Mayhem 字典失敗：%s", e)
            return blob or {k: {} for k in EMPTY_DICT}

    # ----- 單英雄出裝 -----

    def build(self, champion_slug: str, allow_network: bool = True) -> dict | None:
        """單英雄出裝；沒有資料或抓不到時回 None（或舊快取）。"""
        key = str(champion_slug or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", key):
            return None
        path = self.root / f"build_{key}.json"
        with self._lock:
            cached = self._builds.get(key)
        if cached is None:
            cached = _read(path)
        if cached and (not _stale(cached, self.refresh_s) or not allow_network):
            self._remember(key, cached)
            return cached
        if not allow_network:
            return cached
        page = self._fetch_build_page(key)
        if page is None:
            return cached
        data = parse_build(page, key)
        if data is None:
            log.info("ARAM Mayhem 頁面沒有可解析內容：%s", key)
            return cached
        data["fetched_at"] = time.time()
        try:
            _write(path, data)
        except OSError as e:
            log.info("寫入 ARAM Mayhem 快取失敗（%s）：%s", key, e)
        self._remember(key, data)
        return data

    def _remember(self, key: str, data: dict) -> None:
        with self._lock:
            self._builds[key] = data

    def _fetch_build_page(self, key: str) -> str | None:
        with self._lock:
            wait = BUILD_INTERVAL_S - (time.monotonic() - self._last_build_at)
        if wait > 0:
            time.sleep(wait)  # 禮貌：連續抓多個英雄時放慢
        try:
            resp = http.get(BUILD_URL.format(slug=key), timeout=30)
            return resp.content.decode("utf-8", "replace")
        except Exception as e:
            log.warning("取得 ARAM Mayhem 出裝頁失敗（%s）：%s", key, e)
            return None
        finally:
            with self._lock:
                self._last_build_at = time.monotonic()

    # ----- 名稱對照 -----

    def champion_slug(self, name: str) -> str | None:
        """台服英雄名（伊瑞莉雅）→ 站點 slug（irelia）；也接受英文 id 或 slug 本身。"""
        key = _clean_text(str(name or ""))
        if not key:
            return None
        champs = self.dictionary().get("champions") or {}
        if not champs:
            return None
        low = key.lower()
        if low in champs:
            return low
        for s, c in champs.items():
            if _clean_text(c.get("name") or "") == key:
                return s
        target = _norm(key)
        for s, c in champs.items():
            if _norm(s) == target or _norm(c.get("name")) == target:
                return s
        return None

    def augment_name_map(self) -> dict[str, str]:
        """{數字增幅 id: 台服名稱}；用 CommunityDragon 的 augmentNameId 橋接站點 slug。

        主路徑是 slug 橋接；對不上的再用「中文名＋稀有度」補，兩者都不成立就略過。
        """
        site = self.dictionary().get("augments") or {}
        rows = self._load_augment_ids()
        if not site or not rows:
            return {}
        by_norm: dict[str, list[str]] = {}
        for s, a in site.items():
            for key in (_norm(s), _norm(a.get("name"))):
                if key:
                    by_norm.setdefault(key, []).append(s)
        out: dict[str, str] = {}
        claimed: dict[str, str] = {}  # 數字 id → 站點 slug
        for aid, row in rows.items():
            hit = _match_augment_slug(str(row.get("name_id") or ""), site, by_norm)
            if hit:
                claimed[str(aid)] = hit
        for aid, row in rows.items():
            if str(aid) in claimed:
                continue
            # 補漏：中文名相同且稀有度相符才算，避免「回春」這種同名不同東西誤配
            key = _norm(row.get("name"))
            if not key or key == _norm("？？？"):
                continue
            want = row.get("rarity")
            for cand in by_norm.get(key) or []:
                if site[cand].get("rarity") == want:
                    claimed[str(aid)] = cand
                    break
        for aid, site_slug in claimed.items():
            name = _clean_text(site[site_slug].get("name") or "") \
                or _clean_text(rows[aid].get("name") or "")
            if name:
                out[str(aid)] = name
        log.debug("ARAM Mayhem 增幅橋接：%d 個數字 id，%d 個站點條目", len(out), len(site))
        return out

    def _load_augment_ids(self) -> dict[str, dict]:
        """CommunityDragon：{數字 id: {"name_id", "name"}}，落盤快取。"""
        with self._lock:
            if self._augment_ids:
                return self._augment_ids
            blob = _read(self.root / "augment_ids.json") or {}
        rows = blob.get("rows") or {}
        if rows and not _stale(blob, self.refresh_s):
            with self._lock:
                self._augment_ids = rows
            return rows
        try:
            raw = http.get_json(CDRAGON_AUG, timeout=30)
            fresh: dict[str, dict] = {}
            for entry in raw if isinstance(raw, list) else []:
                name_id = str((entry or {}).get("augmentNameId") or "")
                if not name_id or entry.get("id") is None:
                    continue
                fresh[str(entry["id"])] = {
                    "name_id": name_id,
                    "name": _clean_text(entry.get("nameTRA") or ""),
                    "rarity": CDRAGON_RARITY.get(str(entry.get("rarity") or "")),
                }
            if fresh:
                _write(self.root / "augment_ids.json", {"fetched_at": time.time(), "rows": fresh})
                with self._lock:
                    self._augment_ids = fresh
                return fresh
        except Exception as e:
            log.info("取得 CommunityDragon 增幅 id 失敗：%s", e)
        with self._lock:
            self._augment_ids = rows
        return rows


def _shape_dictionary(raw: dict) -> dict:
    """站點字典（三個 list）→ 以 slug 為鍵的字典。英雄鍵用站點 build 頁的 slug（全小寫）。"""
    fields = {"augments": ("name", "rarity", "icon"),
              "items": ("name", "icon"),
              "champions": ("name", "icon")}
    out: dict = {"augments": {}, "items": {}, "champions": {}}
    if not isinstance(raw, dict):
        return out
    for key, keep in fields.items():
        for entry in raw.get(key) or []:
            if not isinstance(entry, dict):
                continue
            raw_id = _clean_text(str(entry.get("id") or ""))
            if not raw_id:
                continue
            item = {f: entry.get(f) for f in keep}
            item["name"] = _clean_text(item.get("name") or "")
            if key == "champions":
                item["id"] = raw_id
                out[key][raw_id.lower()] = item
            else:
                out[key][raw_id] = item
    return out


def _augment_variants(name_id: str) -> list[str]:
    """同一個 augmentNameId 的幾種可能寫法（站點有時省掉 ARAM_ 前綴）。"""
    text = str(name_id or "")
    base = re.sub(r"^(?:ARAM|KIWI|CHERRY)_", "", text, flags=re.I)
    return [slug(text), slug(base), _norm(text), _norm(base)]


def _match_augment_slug(name_id: str, site: dict, by_norm: dict[str, list[str]]) -> str | None:
    for variant in _augment_variants(name_id):
        if variant in site:
            return variant
        hits = by_norm.get(variant)
        if hits:
            return hits[0]
    return None
