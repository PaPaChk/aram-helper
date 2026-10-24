"""程式更新：查 GitHub Releases 有沒有新版本；使用者點了才下載安裝，從不自己裝。

    GET https://api.github.com/repos/<倉庫>/releases/latest
      tag_name  版本（v1.2.3）
      body      更新說明
      assets    AramHex-Setup-<版本>.exe（安裝版）、AramHex-Portable-<版本>.zip（便攜版）、SHA256SUMS.txt

安裝包的 SHA-256 優先用 GitHub 給每個 asset 算的 digest（"sha256:..."），沒有時讀 SHA256SUMS.txt。
下載後核對 SHA-256，不一致就刪掉並報錯。匿名介面每個 IP 每小時 60 次，啟動、再次開啟、每 30 分鐘各查一次足夠。
便攜版不能替換自己：有新版本時只開啟下載頁。

國內常常連不上 GitHub：查不到時改從 jsDelivr 讀最新版本號（取最新 tag 裡的 lolhex/__init__.py）。
這條路拿不到安裝包和 SHA-256，所以只提示有新版本、開啟下載頁，不在程式裡直接安裝。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests

from . import DOWNLOAD_PAGE, GITHUB_REPO, MIRROR, RELEASES_PAGE, WEBSITE

log = logging.getLogger(__name__)
API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
FILE_RE = re.compile(r"^AramHex(?:TW)?-Setup-[0-9][0-9A-Za-z.+\-]*\.exe$")
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
          mirrors=VERSION_MIRRORS, probe_hosts=PROBE_HOSTS, site: str | None = None) -> dict | None:
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
        setup = next((a for a in assets if FILE_RE.match(a.get("name") or "")), None)
        if not setup:
            raise ValueError("這個版本沒有安裝包")
        digest = str(setup.get("digest") or "")
        sha = digest[7:].lower() if digest.startswith("sha256:") else _sha_from_sums(assets, setup["name"], timeout)
        if not sha or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("這個版本的安裝包沒有 SHA-256，不能安全下載")
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
    return {"version": version, "file": setup["name"], "sha256": sha, "size": setup.get("size"),
            "url": setup["browser_download_url"], "notes": (rel.get("body") or "").strip()[:600],
            "page": rel.get("html_url") or RELEASES_PAGE}


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
    try:
        path = download(info)
    except Exception as e:
        log.info("自動更新下載失敗：%s", e)
        return None
    if shutdown is None:
        return {"action": "downloaded", "version": info.get("version"), "path": str(path)}
    try:
        shutdown()
    finally:
        launch_installer(path)
    return {"action": "installing", "version": info.get("version")}
