"""程式更新：查 GitHub Releases 有沒有新版本；使用者點了才下載安裝，從不自己裝。

    GET https://api.github.com/repos/<倉庫>/releases/latest
      tag_name  版本（v1.2.3）
      body      更新說明
      assets    AramHex-Setup-<版本>.exe（安裝版）、AramHex-Portable-<版本>.zip（便攜版）、SHA256SUMS.txt

安裝包的 SHA-256 優先用 GitHub 給每個 asset 算的 digest（"sha256:..."），沒有時讀 SHA256SUMS.txt。
下載後核對 SHA-256，不一致就刪掉並報錯。匿名介面每個 IP 每小時 60 次，啟動、再次開啟、每 30 分鐘各查一次足夠。

便攜版也自己更新：改為下載便攜版 ZIP、校驗雜湊、解壓到暫存目錄，再由替換指令碼在助手退出後
把新檔案疊到程式目錄（排除 userdata，使用者資料一律保留），最後自動重新開啟。安裝版仍然下載安裝包靜默安裝。

國內常常連不上 GitHub：查不到時改從 jsDelivr 讀最新版本號（取最新 tag 裡的 lolhex/__init__.py）。
這條路拿不到安裝包和 SHA-256，所以只提示有新版本、開啟下載頁，不在程式裡直接安裝。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from . import DOWNLOAD_PAGE, GITHUB_REPO, MIRROR, RELEASES_PAGE, WEBSITE
from .config import is_portable, program_dir

log = logging.getLogger(__name__)
API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
FILE_RE = re.compile(r"^AramHex(?:TW)?-Setup-[0-9][0-9A-Za-z.+\-]*\.exe$")
# 便攜版的整包 ZIP：更新時優先取它，下載後整包疊進程式目錄
PORTABLE_RE = re.compile(r"^AramHex(?:TW)?-Portable-[0-9][0-9A-Za-z.+\-]*\.zip$")
SUMS = "SHA256SUMS.txt"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "aramhex"}
VERSION_MIRRORS = [f"https://{host}/gh/{GITHUB_REPO}@latest/lolhex/__init__.py"
                   for host in ("fastly.jsdelivr.net", "gcore.jsdelivr.net", "cdn.jsdelivr.net")]
_VERSION = re.compile(r'^__version__\s*=\s*"([0-9][0-9A-Za-z.\-]*)"', re.M)


PROBE_HOSTS = ("fastly.jsdelivr.net", "gcore.jsdelivr.net")
SITE_LATEST = f"{MIRROR}/latest.json"
# DOWNLOAD_PAGE 由 lolhex/__init__.py 指向本倉庫的 Releases（不再用官網下載區）。
SLOW_BPS = 150 * 1024    # 整包下載：前 SLOW_AFTER_S 秒平均低於這個速度就放棄，改讓使用者去下載頁
SLOW_AFTER_S = 12


class SlowDownload(Exception):
    """從 GitHub 下載安裝包太慢。"""


def pan_links(timeout: float = 6) -> dict:
    """網盤連結一律不採用。

    上游雲控 aramhex.com/config.json 的 downloads 指向國服的 123pan 網盤，
    台服版照著去下載會拿到國服安裝包。台服版沒有網盤，一律回空字典，
    呼叫端會退回 DOWNLOAD_PAGE（本倉庫的 Releases）。
    """
    return {}


def check_site(current: str, timeout: float = 6, url: str = SITE_LATEST) -> dict | None:
    """官網映象上的最新版本（DMIT 從 GitHub Release 同步：版本、說明、安裝包名、SHA-256、GitHub 下載地址）。"""
    r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    version = str(j["version"]).lstrip("vV")
    if not is_newer(version, current):
        return None
    s = j.get("setup") or {}
    sha = str(s.get("sha256") or "").lower()
    ok = bool(FILE_RE.match(str(s.get("name") or "")) and re.fullmatch(r"[0-9a-f]{64}", sha) and s.get("url"))
    return {"version": version, "file": s.get("name") if ok else None, "sha256": sha if ok else None,
            "size": s.get("size") if ok else None, "url": s.get("url") if ok else None,
            "notes": str(j.get("notes") or "").strip()[:600], "page": RELEASES_PAGE, "mirror": not ok}


def _next_versions(v: str) -> list[str]:
    k = list(version_key(v)) + [0, 0, 0]
    major, minor, patch_ = k[:3]
    return [f"{major}.{minor}.{patch_ + 1}", f"{major}.{minor + 1}.0", f"{major + 1}.0.0"]


def probe_newer(current: str, timeout: float = 8, hosts=PROBE_HOSTS, steps: int = 6) -> tuple[str | None, bool]:
    """按 tag 試探下一個版本（1.0.4 → 試 1.0.5、1.1.0、2.0.0），找到就從那個版本接著試。
    jsDelivr 按 tag 取是即時的，不像"最新版"別名那樣會快取好幾個小時。返回 (最高版本或 None, 是否連上過)。"""
    from .patch import tag_for
    found, reached, v = None, False, current
    for _ in range(steps):
        hit = None
        for nxt in _next_versions(v):
            for host in hosts:
                try:
                    r = requests.get(f"https://{host}/gh/{GITHUB_REPO}@{tag_for(nxt)}/manifest.json",
                                     headers={"User-Agent": HEADERS["User-Agent"]}, timeout=timeout)
                except requests.RequestException:
                    continue
                reached = True
                if r.ok:
                    try:
                        if r.json().get("version") == nxt:
                            hit = nxt
                    except ValueError:
                        pass
                break  # 這個節點答覆了（有或沒有），不用再問別的節點
            if hit:
                break
        if not hit:
            break
        found = v = hit
    return found, reached


def check_mirror(current: str, timeout: float = 8, mirrors=VERSION_MIRRORS, probe_hosts=PROBE_HOSTS) -> dict | None:
    """GitHub 連不上時從映象查最新版本：按 tag 試探下一個版本，再讀各節點的"最新版"，取最高的。
    有新版本返回只帶下載頁的資訊（安裝包地址和 SHA-256 拿不到，增量更新另有清單校驗），沒有返回 None；
    映象都連不上時拋異常。"""
    from concurrent.futures import ThreadPoolExecutor

    def alias(url):
        r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=timeout)
        r.raise_for_status()
        m = _VERSION.search(r.text)
        if not m:
            raise ValueError("映象上的版本號讀不出來")
        return m.group(1)

    versions, last, reached = [], None, False
    # 試探 tag 和問各節點的"最新版"同時進行（各節點對"最新版"的快取不一樣，都問，取最高的）
    with ThreadPoolExecutor(max_workers=1 + len(mirrors)) as pool:
        probe = pool.submit(probe_newer, current, timeout, probe_hosts) if probe_hosts else None
        asks = [pool.submit(alias, url) for url in mirrors]
        for fut in asks:
            try:
                versions.append(fut.result())
                reached = True
            except (requests.RequestException, ValueError) as e:
                last = e
        if probe:
            probed, ok = probe.result()
            reached |= ok
            if probed:
                versions.append(probed)
    if not reached:
        raise last or requests.ConnectionError("沒有可用的映象")
    best = max(versions, key=version_key, default=None)
    if not best or not is_newer(best, current):
        return None
    return {"version": best, "file": None, "sha256": None, "size": None, "url": None,
            "notes": "", "page": RELEASES_PAGE, "mirror": True}


def version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4])


def is_newer(latest: str, current: str) -> bool:
    return bool(version_key(latest)) and version_key(latest) > version_key(current)


def _sha_from_sums(assets: list[dict], name: str, timeout: float) -> str | None:
    sums = next((a for a in assets if a.get("name") == SUMS), None)
    if not sums:
        return None
    r = requests.get(sums["browser_download_url"], headers={"User-Agent": HEADERS["User-Agent"]}, timeout=timeout)
    r.raise_for_status()
    for line in r.text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return None


def check(current: str, timeout: float = 8, strict: bool = False, api: str = API,
          mirrors=VERSION_MIRRORS, probe_hosts=PROBE_HOSTS, site: str | None = None,
          portable: bool | None = None) -> dict | None:
    """有新版本返回它的資訊，沒有或查不到返回 None。

    台服版只認自己倉庫的 GitHub Releases：aramhex.com 的 latest.json 公布的是
    國服（czgreat/aramhex）的版本，照著它更新會把台服版覆蓋成國服版，
    所以 site 預設為 None，不要傳入官網映象。"""
    if site:
        try:
            return check_site(current, min(timeout, 6), site)
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            log.info("官網查更新失敗，改查 GitHub：%s", e)
    try:
        r = requests.get(api, headers=HEADERS, timeout=timeout)
        if r.status_code == 404:
            return None  # 還沒有釋出過
        r.raise_for_status()
        rel = r.json()
        version = str(rel.get("tag_name") or "").lstrip("vV")
        if rel.get("draft") or rel.get("prerelease") or not is_newer(version, current):
            return None
        assets = rel.get("assets") or []
        # 便攜版要下載便攜版 ZIP；安裝版要下載安裝包。選錯了會把便攜版裝成安裝版。
        want_portable = is_portable() if portable is None else bool(portable)
        pattern = PORTABLE_RE if want_portable else FILE_RE
        label = "便攜版" if want_portable else "安裝包"
        asset = next((a for a in assets if pattern.match(a.get("name") or "")), None)
        if not asset and want_portable:
            # 便攜版不能改用安裝包：安裝程式會把程式裝進 Program Files，便攜性就沒了，
            # 而且程式目錄裡的 userdata 也不會被帶過去。這裡只回傳下載頁資訊，讓使用者自己下載。
            log.info("這個版本沒有便攜版 ZIP，便攜版改為手動下載")
            return {"version": version, "file": None, "sha256": None, "size": None, "url": None,
                    "notes": (rel.get("body") or "").strip()[:600], "page": rel.get("html_url") or RELEASES_PAGE,
                    "portable": True, "mirror": True}
        if not asset:
            raise ValueError("這個版本沒有安裝包")
        digest = str(asset.get("digest") or "")
        sha = digest[7:].lower() if digest.startswith("sha256:") else _sha_from_sums(assets, asset["name"], timeout)
        if not sha or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"這個版本的{label}沒有 SHA-256，不能安全下載")
    except requests.RequestException as e:  # 連不上 GitHub（或被限流）：換映象查版本號
        log.info("GitHub 查更新失敗，改查映象：%s", e)
        try:
            return check_mirror(current, timeout, mirrors, probe_hosts)
        except (requests.RequestException, ValueError) as e2:
            log.info("映象也查不到：%s", e2)
            if strict:
                raise e from e2
            return None
    except (ValueError, KeyError, TypeError) as e:
        log.info("檢查更新失敗：%s", e)
        if strict:
            raise
        return None
    return {"version": version, "file": asset["name"], "sha256": sha, "size": asset.get("size"),
            "url": asset["browser_download_url"], "notes": (rel.get("body") or "").strip()[:600],
            "page": rel.get("html_url") or RELEASES_PAGE, "portable": want_portable}


def download(info: dict, progress=None, folder: Path | None = None, slow_bps: float = SLOW_BPS,
             slow_after_s: float = SLOW_AFTER_S) -> Path:
    """下載安裝包並核對 SHA-256；不一致就刪掉並報錯。progress(已下載位元組, 總位元組)。
    下了 slow_after_s 秒平均速度還低於 slow_bps 就停下，拋 SlowDownload（國內連 GitHub 常見）。"""
    import time
    folder = Path(folder or Path(tempfile.gettempdir()) / "aramhex-update")
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / info["file"]
    h = hashlib.sha256()
    done = 0
    start = time.monotonic()
    with requests.get(info["url"], stream=True, timeout=(15, 30), headers={"User-Agent": HEADERS["User-Agent"]}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or info.get("size") or 0)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
                spent = time.monotonic() - start
                if slow_bps and spent >= slow_after_s and done / spent < slow_bps and done < total:
                    f.close()
                    dest.unlink(missing_ok=True)
                    raise SlowDownload(f"下載太慢（{done / spent / 1024:.0f}KB/s）")
    if h.hexdigest() != info["sha256"]:
        dest.unlink(missing_ok=True)
        raise ValueError("安裝包校驗失敗（下載不完整或檔案被改過）")
    return dest


def launch_installer(path: Path) -> None:
    """啟動安裝程式（顯示安裝進度，裝完自動重新開啟助手）。呼叫後助手應當馬上退出，讓出檔案。"""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"], close_fds=True,
                     creationflags=flags, cwd=os.path.dirname(str(path)))


# 便攜版整包更新：ZIP 裡的頂層目錄（AramHexTW-<版本>/）要剝掉，直接把內容疊到程式目錄。
USER_DATA = "userdata"          # 便攜版的設定、日誌、資料和截圖都在這裡：任何情況下都不碰
MARKER = "portable.txt"         # 便攜版標記：絕不刪除，否則程式會改用 %APPDATA%
EXE_NAMES = ("AramHexTW.exe", "AramHex.exe")


def portable_folder() -> Path:
    """便攜版下載與解壓用的暫存目錄（每次更新都清空，不與安裝版共用）。"""
    return Path(tempfile.gettempdir()) / "aramhex-update" / "portable"


def download_portable(info: dict, progress=None, folder: Path | None = None) -> Path:
    """下載便攜版 ZIP 並核對 SHA-256。

    與安裝包走同一套 download()：同樣的慢速中止、同樣的雜湊校驗、不一致就刪檔。
    多一層防護：只接受 .zip，避免把安裝包當成便攜版解壓。"""
    if not str(info.get("file") or "").lower().endswith(".zip"):
        raise ValueError("便攜版更新必須下載 ZIP")
    return download(info, progress, folder=folder or portable_folder())


def extract_portable(zip_path: Path, folder: Path | None = None) -> tuple[Path, list[str]]:
    """解壓便攜版 ZIP 到暫存目錄，剝掉唯一的頂層目錄，返回（暫存目錄, 相對路徑清單）。

    只接受「所有項目都在同一個頂層目錄下」的包：形狀不對就拋 ValueError，不做猜測——
    猜錯會把整包內容倒進程式目錄。路徑一律驗證，寫不出程式目錄以外的東西（ZIP slip）。"""
    import zipfile

    folder = Path(folder or portable_folder() / "staging")
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n and not n.endswith("/")]
        tops = {n.split("/", 1)[0] for n in names}
        if not names or len(tops) != 1 or not all("/" in n for n in names):
            raise ValueError("便攜版 ZIP 的目錄結構不對（應只有一個頂層目錄）")
        prefix = names[0].split("/", 1)[0] + "/"
        rels: list[str] = []
        for name in names:
            if not name.startswith(prefix):
                raise ValueError("便攜版 ZIP 的目錄結構不對")
            rel = name[len(prefix):]
            parts = rel.replace("\\", "/").split("/")
            if not rel or rel.startswith(("/", "\\")) or ".." in parts or ":" in rel:
                raise ValueError(f"便攜版 ZIP 含有不安全的路徑：{name}")
            dest = folder / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            rels.append(rel.replace("\\", "/"))
    return folder, rels


def _main_exe(root: Path) -> str | None:
    """程式目錄裡的主程式檔名：優先這次執行中的 exe，其次打包的預設名稱。"""
    running = Path(sys.executable).name if getattr(sys, "frozen", False) else ""
    for name in ([running] if running else []) + list(EXE_NAMES):
        if (root / name).is_file():
            return name
    return None


def _writable(folder: Path) -> bool:
    """程式目錄現在能不能寫（在 Program Files 下、或被設成唯讀時就不能無聲替換）。"""
    probe = folder / ".aramhex-write-test"
    try:
        probe.write_bytes(b"x")
        probe.unlink()
        return True
    except OSError:
        return False


def launch_portable_update(zip_path: Path, version: str, root: Path | None = None,
                           relaunch: str | None = None, pid: int | None = None,
                           progress=None) -> Path:
    """便攜版：解壓下載好的 ZIP，交給 patch.launch_apply 在助手退出後疊上新檔案。

    替換策略是「逐檔覆蓋」（overlay），不是先刪掉整個目錄：
      - 只把 ZIP 裡有的檔案換過去，其他東西（userdata、使用者自己放的檔案）一個都不動；
      - 每個舊檔案先移到 _update_old，全部換完才刪；任何一步失敗就全部移回去，留在舊版本；
      - userdata/* 和 portable.txt 永遠不在替換或刪除的清單裡；
      - 舊版本有、新版本沒有的檔案才算要刪（stale），同樣排除 userdata 和 portable.txt。

    這裡先做完整的前置檢查：解壓成功、找得到主程式、程式目錄可寫、暫存目錄建得起來。
    任何一項不成立就拋異常，呼叫端據此回報失敗——絕不啟動一個可能只換到一半的替換。"""
    from . import patch

    root = Path(root or program_dir())
    if not root.is_dir():
        raise ValueError(f"程式目錄不存在：{root}")
    staging, rels = extract_portable(zip_path)
    try:
        fresh = set(rels)
        exe = _main_exe(root) or next((n for n in EXE_NAMES if n in fresh), None)
        if not exe:
            raise ValueError("便攜版 ZIP 裡沒有主程式")
        if exe not in fresh and not (staging / exe).is_file():
            raise ValueError("便攜版 ZIP 裡沒有主程式")
        if not _writable(root):
            raise ValueError("程式目錄不能寫入，無法自動替換")
        changed = [r for r in rels if r != USER_DATA and not r.startswith(USER_DATA + "/")]
        if not changed:
            raise ValueError("便攜版 ZIP 是空的")
        # 舊版本有、新版本沒有的檔案：交給替換指令碼一併移除（仍排除使用者資料）
        stale = sorted(
            p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file()
            and p.relative_to(root).as_posix() not in fresh
            and not p.relative_to(root).as_posix().startswith((USER_DATA + "/", patch.STAGING + "/",
                                                               patch.BACKUP + "/"))
            and p.name != MARKER and p.relative_to(root).as_posix() != MARKER
        )
        # 把解壓好的檔案搬進程式目錄下的暫存目錄，助手退出後由指令碼搬進定位
        slot = root / patch.STAGING
        if slot.exists():
            shutil.rmtree(slot, ignore_errors=True)
        for rel in changed:
            dst = slot / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            (staging / rel).replace(dst)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(root / patch.STAGING, ignore_errors=True)  # 失敗不留暫存，原目錄原封不動
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return patch.launch_apply(root, changed, stale, version,
                              relaunch=relaunch or str(root / exe), pid=pid)






def auto_update(current: str, shutdown=None, timeout: float = 8) -> dict | None:
    """自動更新：查 GitHub Releases，有新版就下載、校驗、靜默安裝，然後結束本程式。

    shutdown 是「關閉助手」的 callback（存設定、關視窗、退出程序），
    傳 None 表示只下載不安裝（測試用）。回傳這次做了什麼：
      None                      沒有新版本
      {"action": "downloaded"}  下載好但沒安裝（沒給 shutdown）
      {"action": "installing"}  已啟動安裝程式，呼叫端應馬上結束
    任何失敗都回 None，交給呼叫端決定要不要提示使用者。
    """
    try:
        info = check(current, timeout=timeout)
    except Exception as e:  # 網路或格式問題：自動更新失敗不該影響使用
        log.info("自動更新檢查失敗：%s", e)
        return None
    if not info:
        return None
    portable = bool(info.get("portable"))
    try:
        path = download_portable(info) if portable else download(info)
    except Exception as e:
        log.info("自動更新下載失敗：%s", e)
        return None
    if shutdown is None:
        return {"action": "downloaded", "version": info.get("version"), "path": str(path)}
    shutdown()
    if portable:
        launch_portable_update(path, info.get("version") or "", pid=os.getpid())
    else:
        launch_installer(path)
    return {"action": "installing", "version": info.get("version")}
