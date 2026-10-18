"""自採統計資料（公開資料倉儲 github.com/czgreat/aramhex-data 的格式）。

一份資料 = 一個目錄：
    latest.json                      清單：版本、樣本時間、檔案列表（SHA-256、大小）
    meta.json                        口徑、樣本時間窗、侷限
    heroes.json / hero_augments.json 全體
    bands/<casual|mid|high|top>/heroes.json、hero_augments.json   分段（可選）

兩個來源，用樣本更新的那份：
- 安裝包內建：lolhex/data/bundled/（發版時由 scripts/update_data.py 放進來）；
- 下載的：<app_home>/data/public/（啟動時查資料倉儲的 latest.json，有新資料就下載，逐個檔案校驗 SHA-256）。
  先試 GitHub，連不上或校驗不過就換 jsDelivr 映象（DATA_SOURCES）。

官方資料（英雄、海克斯字典、出裝、加點）仍由父類 DataStore 直接從騰訊取。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
from pathlib import Path

import requests

from .. import DATA_REPO, MIRROR
from . import http
from .store import DataStore, _read

log = logging.getLogger(__name__)

BANDS = {"casual": "娛樂", "mid": "中分", "high": "高分", "top": "頂尖"}
BUNDLED_DIR = Path(__file__).with_name("bundled")
RAW_BASE = f"https://raw.githubusercontent.com/{DATA_REPO}/main"
# 先走官網映象（DMIT 定時從 GitHub 同步），不通再試 GitHub 和 jsDelivr。每個檔案都按清單校驗 SHA-256。
DATA_SOURCES = [f"{MIRROR}/data", RAW_BASE] + [f"https://{host}/gh/{DATA_REPO}@main"
                             for host in ("fastly.jsdelivr.net", "gcore.jsdelivr.net", "cdn.jsdelivr.net")]
# jsDelivr 按分支（@main）取會快取好幾個小時；資料每更新一次打 tag data-v<序號>，按"下一個序號"試探，按 tag 取是即時的
DATA_TAG_HOSTS = ("fastly.jsdelivr.net", "gcore.jsdelivr.net")
DATA_TAG_FMT = "https://{host}/gh/" + DATA_REPO + "@data-v{seq}"
SYNC_EVERY_S = 6 * 3600
SCHEMA_VERSION = 1


class DatasetError(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise DatasetError("資料清單版本不支援")
    files = manifest.get("files")
    if not isinstance(files, dict) or "meta.json" not in files or "heroes.json" not in files \
            or "hero_augments.json" not in files:
        raise DatasetError("資料清單缺檔案")
    for name, f in files.items():
        if ".." in name or name.startswith(("/", "\\")) or not name.endswith(".json"):
            raise DatasetError(f"資料清單裡有不合法的檔名：{name}")
        if not isinstance(f, dict) or len(str(f.get("sha256", ""))) != 64:
            raise DatasetError(f"資料清單裡 {name} 沒有 SHA-256")
    return manifest


class Dataset:
    """讀進記憶體的一份資料。構造時逐個檔案核對 SHA-256，不對就整份不用。"""

    def __init__(self, folder: Path, origin: str):
        self.folder, self.origin = Path(folder), origin
        manifest = _read(self.folder / "latest.json")
        if manifest is None:
            raise DatasetError(f"{folder} 沒有 latest.json")
        self.manifest = check_manifest(manifest)
        for name, f in self.manifest["files"].items():
            p = self.folder / name
            if not p.is_file() or _sha256(p) != f["sha256"]:
                raise DatasetError(f"{name} 缺失或校驗不對")
        self.meta = _read(self.folder / "meta.json") or {}
        self.patch = str(self.manifest.get("patch") or self.meta.get("patch") or "")
        self.snapshot_at = str(self.manifest.get("snapshot_at") or "")
        self.seq = int(self.manifest.get("seq") or 0)  # 資料更新序號，對應 tag data-v<seq>
        self.mode = str(self.manifest.get("mode") or "normal")       # normal / first-prismatic 等
        self.mode_label = str(self.manifest.get("mode_label") or "")
        # 資料版本號：整份清單（全部檔案的 SHA-256 + 樣本時間）的摘要，任何一個檔案變了都會變
        ident = json.dumps([self.patch, self.snapshot_at, self.manifest["files"]], sort_keys=True)
        self.revision = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:12]
        self._tables: dict[str, tuple[dict, dict]] = {}

    def bands_available(self) -> bool:
        return all(f"bands/{b}/heroes.json" in self.manifest["files"] for b in BANDS)

    def table(self, band: str | None) -> tuple[dict, dict]:
        """(heroes, hero_augments)；band=None 為全體。"""
        key = band or ""
        if key not in self._tables:
            prefix = f"bands/{band}/" if band else ""
            self._tables[key] = (_read(self.folder / f"{prefix}heroes.json") or {},
                                 _read(self.folder / f"{prefix}hero_augments.json") or {})
        return self._tables[key]


def load_best(folders: list[tuple[Path, str]]) -> Dataset | None:
    """在幾個候選目錄裡挑樣本最新、校驗透過的一份。"""
    best = None
    for folder, origin in folders:
        try:
            ds = Dataset(folder, origin)
        except (DatasetError, OSError, ValueError) as e:
            if (Path(folder) / "latest.json").exists():
                log.warning("統計資料 %s 不能用：%s", folder, e)
            continue
        if best is None or (ds.snapshot_at, ds.patch) > (best.snapshot_at, best.patch):
            best = ds
    return best


PACK_FORMAT = "aramhex-pack-1"


def _dump_json(obj) -> bytes:
    """和資料倉儲匯出時完全一樣的寫法，還原出的檔案和原檔案逐位元組一致。"""
    return (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def make_pack(folder: Path, manifest: dict) -> bytes:
    """一份資料 → 壓縮包（官網映象生成，和 unpack 配對）。"""
    import lzma
    files = {}
    for name in manifest["files"]:
        obj = json.loads((Path(folder) / name).read_text(encoding="utf-8"))
        if name.endswith("hero_augments.json"):
            obj = {h: [[int(a), s["games"], s["wins"], 1 if s.get("low_sample") else 0] for a, s in sorted(d.items())]
                   for h, d in obj.items()}
        files[name] = obj
    raw = json.dumps({"format": PACK_FORMAT, "files": files}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return lzma.compress(raw.encode("utf-8"), preset=9 | lzma.PRESET_EXTREME)


def unpack(blob: bytes) -> dict[str, bytes]:
    """官網映象上的壓縮包（xz）→ {檔名: 原檔案位元組}。hero_augments 在包裡是 [海克斯ID, 局數, 勝場, 樣本少]，
    勝率按匯出時的演算法 round(勝場/局數, 6) 還原。"""
    import lzma
    pack = json.loads(lzma.decompress(blob))
    if pack.get("format") != PACK_FORMAT:
        raise DatasetError("壓縮包格式不支援")
    out = {}
    for name, obj in pack["files"].items():
        if name.endswith("hero_augments.json"):
            obj = {h: {str(a): {"games": g, "low_sample": bool(low), "win_rate": round(w / g, 6) if g else 0.0, "wins": w}
                       for a, g, w, low in rows} for h, rows in obj.items()}
        out[name] = _dump_json(obj)
    return out


def download(base_url: str, manifest: dict, dest: Path, timeout: float = 30, progress=None) -> None:
    """按清單下載一份資料到 dest（先寫到旁邊的臨時目錄，全部校驗透過才換上）。progress(已下載位元組, 總位元組)。
    先試官網映象上的壓縮包（約小一半），還原後按清單逐個核對 SHA-256；沒有或不對就逐個檔案下載。"""
    check_manifest(manifest)
    path = str(manifest.get("path") or "").strip("/")
    if not path or ".." in path:
        raise DatasetError("資料清單沒有 path")
    tmp = dest.with_name(dest.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    total = sum(int(f.get("size") or 0) for f in manifest["files"].values())
    done = [0]

    def on_bytes(n):
        done[0] += n
        if progress:
            progress(done[0], total)
    files = None
    try:
        files = unpack(http.fetch(f"{base_url}/{path}.pack.xz", timeout=timeout,
                                  on_bytes=lambda n: progress and progress(0, 0)))
        log.info("統計資料用壓縮包下載：%s", base_url)
    except Exception as e:
        log.debug("沒有可用的壓縮包（%s），逐個檔案下載", e)
    try:
        for name, f in manifest["files"].items():
            body = files.get(name) if files else None
            if body is None or hashlib.sha256(body).hexdigest() != f["sha256"]:
                if files:
                    log.info("壓縮包裡的 %s 對不上，改為逐個檔案下載", name)
                    files = None
                body = http.fetch(f"{base_url}/{path}/{name}", timeout=timeout, on_bytes=on_bytes)
            if hashlib.sha256(body).hexdigest() != f["sha256"] or ("size" in f and len(body) != f["size"]):
                raise DatasetError(f"{name} 校驗不對（下載不完整或檔案被改過）")
            out = tmp / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)
        (tmp / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        Dataset(tmp, "downloaded")  # 整份再核一遍
        old = dest.with_name(dest.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if dest.exists():
            dest.rename(old)
        tmp.rename(dest)
        shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


class PublicStore(DataStore):
    def __init__(self, root: Path, refresh_hours: float = 6.0, bundled: Path | None = None,
                 check_updates: bool = True, base_url: str | list[str] | None = None,
                 tag_hosts=None, tag_fmt: str = DATA_TAG_FMT, event_source=None):
        super().__init__(root, refresh_hours)
        self.bundled = Path(bundled or BUNDLED_DIR)
        self.downloaded = self.root / "public"
        self.event_dir = self.root / "public-event"  # 活動規則的資料（首次必稜彩等）
        self.event: dict | None = None               # 正在進行的活動 {mode, label}（雲控）
        self.event_fallback = False                  # 有活動但還沒有活動資料：先用常規
        if event_source is None:
            from .. import cloud
            event_source = cloud.event if base_url is None else (lambda: None)
        self._event_source = event_source
        self.check_updates = check_updates
        if base_url is None:
            from .. import cloud
            urls = [u.rstrip("/") for u in cloud.mirrors("data")] + DATA_SOURCES
        else:
            urls = [base_url] if isinstance(base_url, str) else base_url
        self.base_urls = [u.rstrip("/") for u in urls]
        # 預設地址時才按 tag 試探（測試裡給了地址就不去連真的 jsDelivr）
        self.tag_hosts = tuple(DATA_TAG_HOSTS if tag_hosts is None and base_url is None else (tag_hosts or ()))
        self.tag_fmt = tag_fmt
        self.data_source: str | None = None  # 上次成功取到清單的地址
        self.band: str | None = None
        self.dataset: Dataset | None = None
        self.data_updated_at: float | None = None
        self.sync_error: str | None = None
        self.sync_progress: dict | None = None  # 下載統計資料時 {done, total}（位元組）
        self._last_sync = 0.0
        self._sync_lock = threading.Lock()
        self._views: dict = {}
        self.reload_dataset()

    # ---------- 資料集 ----------

    def reload_dataset(self) -> bool:
        """重新挑選資料；換了一份返回 True。有活動且有活動資料時用活動的，否則用常規的。"""
        ds = load_best([(self.downloaded, "downloaded"), (self.bundled, "bundled")])
        self.event_fallback = False
        if self.event:
            ev = load_best([(self.event_dir, "downloaded")])
            if ev is not None and ev.mode == self.event["mode"]:
                ds = ev
            else:
                self.event_fallback = True
        with self._lock:
            changed = ds is not None and (self.dataset is None or ds.revision != self.dataset.revision)
            if changed or ds is None:
                self.dataset = ds
                self._views.clear()
            self._apply_ranks()
        return changed

    def sync_data(self, force: bool = False, manual: bool = False) -> bool:
        """查資料倉儲有沒有更新的統計資料，有就下載並換上。下載了新資料返回 True。
        manual=True：使用者點了「檢查更新」，關了自動更新也查。"""
        if (not self.check_updates and not manual) or not self._sync_lock.acquire(blocking=False):
            return False
        try:
            if not force and time.time() - self._last_sync < SYNC_EVERY_S:
                return False
            self._last_sync = time.time()
            event = self._event_source()
            if event != self.event:
                self.event = event
                self.reload_dataset()
            errors, tried_tags = [], False
            for base in self.base_urls:  # 一個地址連不上、或下載的檔案校驗不過，就換下一個
                if not tried_tags and self.tag_hosts and base != self.base_urls[0]:
                    tried_tags = True  # GitHub 連不上了：先按 tag 試探 jsDelivr 上更新的資料
                    tag_base = self._probe_tag()
                    if tag_base:
                        try:
                            changed = self._sync_from(tag_base)
                            self.data_source, self.sync_error = tag_base, None
                            return changed
                        except Exception as e:
                            errors.append(f"{tag_base.split('/')[2]}（tag）：{e}")
                try:
                    changed = self._sync_from(base)
                except Exception as e:
                    errors.append(f"{base.split('/')[2]}：{e}")
                    log.info("從 %s 檢查統計資料更新失敗：%s", base, e)
                    continue
                self.data_source, self.sync_error = base, None
                if self.event:
                    try:
                        changed = self._sync_event(base) or changed
                    except Exception as e:
                        log.info("活動資料下載失敗：%s", e)
                return changed
            # 都連不上很常見：用手頭的資料，不打擾使用者
            self.sync_error = "；".join(errors)[:300]
            return False
        finally:
            self._sync_lock.release()

    def _probe_tag(self, steps: int = 30) -> str | None:
        """從當前資料的序號往後試 data-v<序號+1>、+2……，返回最新一份的地址；沒有更新的返回 None。"""
        seq = self.dataset.seq if self.dataset else 0
        for host in self.tag_hosts:
            best, k, answered = None, seq + 1, False
            for _ in range(steps):
                base = self.tag_fmt.format(host=host, seq=k)
                try:
                    r = requests.get(f"{base}/latest.json", timeout=15)
                except requests.RequestException:
                    break
                answered = True
                try:
                    ok = r.status_code == 200 and int(r.json().get("seq") or 0) == k
                except ValueError:
                    ok = False
                if not ok:
                    break
                best, k = base, k + 1
            if answered:
                return best  # 這個節點答覆了（有或沒有更新），不用再問別的節點
        return None

    def _sync_from(self, base: str) -> bool:
        r = requests.get(f"{base}/latest.json", timeout=15)
        r.raise_for_status()
        remote = check_manifest(r.json())
        cur = self.dataset
        if cur and (str(remote.get("snapshot_at") or ""), str(remote.get("patch") or "")) <= (cur.snapshot_at, cur.patch):
            return False
        log.info("統計資料有更新：%s（樣本截至 %s），從 %s 下載", remote.get("patch"), remote.get("snapshot_at"), base)
        self.sync_progress = {"done": 0, "total": 0}  # 介面據此顯示"統計資料更新中 x / y MB"
        try:
            download(base, remote, self.downloaded,
                     progress=lambda d, t: setattr(self, "sync_progress", {"done": d, "total": t}))
        finally:
            self.sync_progress = None
        if self.reload_dataset():
            self.data_updated_at = time.time()
            return True
        return False

    def _sync_event(self, base: str) -> bool:
        """活動期間：從資料倉儲的 index.json 找同一規則最新的一份，下載到 public-event/。"""
        r = requests.get(f"{base}/index.json", timeout=15)
        r.raise_for_status()
        idx = r.json()
        cands = [dict(d, schema_version=d.get("schema_version", idx.get("schema_version")))
                 for d in idx.get("datasets") or [] if d.get("mode") == self.event["mode"]]
        if not cands:
            return False
        remote = max(cands, key=lambda d: (str(d.get("snapshot_at") or ""), str(d.get("patch") or "")))
        cur = load_best([(self.event_dir, "downloaded")])
        if cur and cur.mode == self.event["mode"] and \
                (str(remote.get("snapshot_at") or ""), str(remote.get("patch") or "")) <= (cur.snapshot_at, cur.patch):
            return False
        log.info("下載活動資料：%s %s", self.event["label"], remote.get("patch"))
        download(base, remote, self.event_dir)
        return self.reload_dataset()

    def refresh(self, force: bool = False) -> None:
        super().refresh(force)
        self.sync_data(force)

    # ---------- 分段 ----------

    def set_band(self, band: str | None) -> None:
        with self._lock:
            self.band = band if band in BANDS else None
            self._apply_ranks()

    def bands_available(self) -> bool:
        return bool(self.dataset and self.dataset.bands_available())

    def effective_band(self) -> str | None:
        """實際使用的分數段：資料裡沒有分段時退回全體。"""
        return self.band if self.band and self.bands_available() else None

    def _apply_ranks(self) -> None:
        """英雄排名、勝率和全英雄海克斯勝率（未識別英雄時的兜底）換成當前分段的。呼叫方持鎖。"""
        if not self.dataset:
            self.ranks = {}
            return
        heroes, hero_augs = self.dataset.table(self.effective_band())
        total = sum(h["games"] for h in heroes.values()) or 1
        order = sorted(heroes, key=lambda h: (-heroes[h]["win_rate"], int(h)))
        agg: dict[str, list[int]] = {}
        for augs in hero_augs.values():
            for aid, a in augs.items():
                s = agg.setdefault(aid, [0, 0])
                s[0] += a["games"]
                s[1] += a["wins"]
        self.ranks = {"source": "public", "patch": self.dataset.patch, "band": self.effective_band(),
                      "heroes": {hid: {"win": heroes[hid]["win_rate"], "games": heroes[hid]["games"],
                                       "pick": heroes[hid]["games"] / total, "rank": i + 1}
                                 for i, hid in enumerate(order)},
                      "augments": {aid: {"win": w / n, "games": n} for aid, (n, w) in agg.items() if n}}

    def label(self) -> str:
        if not self.dataset:
            return "暫無統計資料"
        band = self.effective_band()
        return f"國服樣本·{self.dataset.patch}版本" + (f"·{BANDS[band]}" if band else "")

    # ---------- 查詢（panel / recommend 用） ----------

    def win_data(self, hero_id: str, allow_network: bool = True) -> dict | None:
        """單英雄 × 海克斯勝率（當前分段）。"""
        if not self.dataset:
            return None
        band = self.effective_band()
        heroes, hero_augs = self.dataset.table(band)
        h = heroes.get(str(hero_id))
        if not h:
            return None
        return {"source": "public", "label": self.label(), "patch": self.dataset.patch,
                "sample_games": h["games"], "wins": h["wins"], "sample_win": h["win_rate"],
                "augments": {aid: {"games": a["games"], "wins": a["wins"], "win": a["win_rate"],
                                   "low_sample": a.get("low_sample", False)}
                             for aid, a in (hero_augs.get(str(hero_id)) or {}).items()},
                "band": band, "band_label": BANDS.get(band)}

    def hero(self, hero_id: str, allow_network: bool = True) -> dict | None:
        """官方出裝、加點 + 海克斯列表（有統計的在前，帶出場佔比；官方層級一併保留）。"""
        data = self.official_hero(hero_id, allow_network) or {}
        stats = self.win_data(hero_id)
        if not stats:
            return data or None
        official = {a["id"]: a for a in data.get("augments") or []}
        augments = []
        for aid, a in stats["augments"].items():
            t = official.pop(aid, {})
            augments.append({**t, "id": aid, "rarity": t.get("rarity") or self.augments.get(aid, {}).get("rarity"),
                             "pick": a["games"] / stats["sample_games"]})
        augments += list(official.values())  # 統計裡還沒有的（新海克斯）：只有官方層級
        return {**data, "augments": augments}

    def status(self) -> dict:
        s = super().status()
        ds = self.dataset
        meta = ds.meta if ds else {}
        s.update(dataset=bool(ds), dataset_patch=ds.patch if ds else None,
                 dataset_snapshot=ds.snapshot_at if ds else None, dataset_origin=ds.origin if ds else None,
                 dataset_revision=ds.revision if ds else None, dataset_window=meta.get("window"),
                 dataset_matches=(meta.get("matches") or {}).get("valid") if isinstance(meta.get("matches"), dict) else meta.get("matches"),
                 dataset_collected=(meta.get("matches") or {}).get("collected") if isinstance(meta.get("matches"), dict) else None,
                 dataset_regions=meta.get("regions"),
                 dataset_label=self.label(), bands_available=self.bands_available(),
                 band=self.band, band_effective=self.effective_band(),
                 dataset_mode=ds.mode if ds else None,
                 dataset_mode_label=(ds.mode_label or ds.mode) if ds and ds.mode != "normal" else None,
                 event_label=(self.event or {}).get("label"), event_fallback=self.event_fallback,
                 data_updated_at=self.data_updated_at, sync_error=self.sync_error,
                 data_progress=self.sync_progress)
        for key in ("error", "sync_error", "dataset_mode_label", "event_label"):
            if s.get(key):
                s[key] = self.localizer.tw(s[key])
        for key in ("dataset_window", "dataset_regions"):
            if s.get(key):
                s[key] = self.localizer.deep_tw(s[key])
        return s
