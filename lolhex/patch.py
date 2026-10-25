"""增量更新：只下載新版本里變了的幾個檔案（通常是程式本體和內建資料，約 10–20MB），不用重下完整安裝包。

發版時 GitHub Actions 把新版本的檔案清單和"會變的檔案"推到本倉庫的 updates 分支：
    manifest.json        {"schema_version": 1, "version", "encoding": "gzip", "files": {相對路徑: {sha256, size}},
                          "patchable": [相對路徑]}
    files/<相對路徑>.gz   patchable 裡的檔案（AramHex.exe、_internal/base_library.zip、_internal/lolhex/**）的 gzip 壓縮版。
                          jsDelivr 不給下 .exe（403），壓縮後就可以；SHA-256 校驗的是解壓後的原檔案。
    files/<相對路徑>      原檔案，給 1.0.3（只認原檔案）從 GitHub 下載用
GitHub 和 jsDelivr 都能讀這個分支，國內連不上 GitHub 時走 jsDelivr（單個檔案 ≤20MB，整個分支 ≤150MB）。

程式這邊：
1. 讀清單，確認版本號就是要更新到的版本（jsDelivr 有快取，舊清單就換下一個地址）；
2. 和本機檔案逐個比 SHA-256。變了的檔案都在 patchable 裡就能增量更新；
   第三方庫也變了（例如升級 Qt）就不行，退回下載完整安裝包；
3. 下載變了的檔案到程式目錄下的 _update_new，逐個校驗；
4. 助手退出後，由一個 PowerShell 小指令碼替換檔案：先把舊檔案挪到 _update_old，任何一步失敗就全部挪回去，
   最後重新開啟助手。安裝版和便攜版都能用（程式目錄都在使用者目錄下，不需要管理員許可權）。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from . import GITHUB_REPO, MIRROR
from .config import program_dir

log = logging.getLogger(__name__)
BRANCH = "updates"
JSD_HOSTS = ("fastly.jsdelivr.net", "gcore.jsdelivr.net", "cdn.jsdelivr.net")


def tag_for(version: str) -> str:
    """發版時給這一版的增量更新檔案打的 tag。jsDelivr 對分支名的解析會快取好幾個小時（推送後還拿到舊清單），
    按 tag 取則立即是新的，所以下載一律按 tag。"""
    return f"updates-v{version}"


def sources_for(version: str) -> list[str]:
    """增量更新的來源。台服版一律取自本倉庫：上游的 MIRROR 是 aramhex.com，
    那裡放的是國服版的檔案，版本號對得上也不該用。"""
    from . import cloud
    tag = tag_for(version)
    extra = [u.replace("{version}", version).rstrip("/") for u in cloud.mirrors("update")]
    return (extra + [f"https://raw.githubusercontent.com/{GITHUB_REPO}/{tag}"]
            + [f"https://{host}/gh/{GITHUB_REPO}@{tag}" for host in JSD_HOSTS]
            # 分支地址兜底（1.0.3 釋出時還沒有 tag）；清單版本對不上會被跳過
            + [f"https://raw.githubusercontent.com/{GITHUB_REPO}/{BRANCH}"]
            + [f"https://{host}/gh/{GITHUB_REPO}@{BRANCH}" for host in JSD_HOSTS])


SOURCES = sources_for("0")  # 只用作預設值的形狀；實際按要更新到的版本取 sources_for(version)
# 會隨我們發版變化的檔案；其餘都是第三方庫（Qt、OpenCV、識別模型……），變了就要完整安裝包
# 主程式 exe 的名字：台服版是 AramHexTW.exe（packaging/lolhex.spec 的 name="AramHexTW"），
# 上游國服版是 AramHex.exe。兩個都要算可增量更新，否則 exe 本身永遠不會被替換，
# 版本號更新了但跑起來還是舊的外殼。
PATCHABLE_EXES = ("AramHexTW.exe", "AramHex.exe")
PATCHABLE_PREFIXES = ("_internal/base_library.zip", "_internal/lolhex/")
STAGING, BACKUP = "_update_new", "_update_old"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{1107079E-6C48-46FD-938D-04B1C3EA9A72}_is1"
HEADERS = {"User-Agent": "aramhex"}


class NeedFullInstall(Exception):
    """這次更新不能增量完成（第三方庫變了、清單拿不到等），要下載完整安裝包。"""


def is_patchable(rel: str) -> bool:
    # 第三方庫的 *.dist-info/ 是安裝記錄（RECORD 等），每次重新 pip install 內容都會變，但不影響執行；
    # 一共只有約 0.3MB，也放進增量更新，免得因為它們就要重下完整安裝包
    return (rel in PATCHABLE_EXES or rel.startswith(PATCHABLE_PREFIXES)
            or ".dist-info/" in rel)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path, version: str) -> dict:
    """發版用：掃描打包好的程式目錄，生成清單。"""
    root = Path(root)
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            files[rel] = {"sha256": sha256_file(p), "size": p.stat().st_size}
    return {"schema_version": 1, "version": version, "files": files,
            "patchable": [rel for rel in files if is_patchable(rel)]}


def check_manifest(m: dict, version: str) -> dict:
    if not isinstance(m, dict) or m.get("schema_version") != 1 or m.get("version") != version:
        raise NeedFullInstall(f"更新清單不是 {version} 的")
    for rel in m.get("files") or {}:
        if rel.startswith(("/", "\\")) or ".." in rel.split("/") or rel.startswith((STAGING, BACKUP)):
            raise NeedFullInstall(f"更新清單裡有不合法的路徑：{rel}")
    if not set(m.get("patchable") or []) <= set(m.get("files") or {}):
        raise NeedFullInstall("更新清單不完整")
    return m


def fetch_manifest(version: str, sources=SOURCES, timeout: float = 15) -> tuple[dict, str]:
    """依次試每個地址，返回 (清單, 地址)。版本對不上（如 jsDelivr 快取還是舊的）就換下一個。"""
    errors = []
    for base in sources:
        try:
            r = requests.get(f"{base}/manifest.json", headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return check_manifest(r.json(), version), base
        except (requests.RequestException, ValueError, NeedFullInstall) as e:
            errors.append(f"{base.split('/')[2]}：{e}")
    raise NeedFullInstall("拿不到更新清單：" + "；".join(errors))


def plan(manifest: dict, root: Path) -> tuple[list[str], list[str]]:
    """和本機檔案比較，返回 (要下載的檔案, 要刪掉的檔案)。有第三方庫變了就拋 NeedFullInstall。"""
    root = Path(root)
    files, patchable = manifest["files"], set(manifest["patchable"])
    changed = []
    for rel, f in files.items():
        p = root / rel
        if p.is_file() and p.stat().st_size == f["size"] and sha256_file(p) == f["sha256"]:
            continue
        if rel not in patchable:
            raise NeedFullInstall(f"{rel} 也變了，要用完整安裝包")
        changed.append(rel)
    stale = [p.relative_to(root).as_posix() for p in (root / "_internal" / "lolhex").rglob("*")
             if p.is_file() and p.relative_to(root).as_posix() not in files] if (root / "_internal" / "lolhex").is_dir() else []
    return changed, stale


def download(manifest: dict, changed: list[str], root: Path, sources=SOURCES, progress=None,
             timeout: float = 30) -> Path:
    """下載變了的檔案到 <root>/_update_new，逐個校驗 SHA-256。返回暫存目錄。"""
    from .data import http
    staging = Path(root) / STAGING
    shutil.rmtree(staging, ignore_errors=True)
    gz = manifest.get("encoding") == "gzip"
    packed = manifest.get("packed") or {}
    # 進度按實際要下載的位元組算：有壓縮版就按壓縮後的大小（清單裡有記錄時）
    share = {rel: (packed.get(rel) if gz and packed.get(rel) else manifest["files"][rel]["size"]) for rel in changed}
    total = sum(share.values())
    finished = 0  # 已經下完的檔案的位元組數

    def report(n_in_file):
        if progress:
            progress(min(finished + n_in_file, total), total)
    try:
        for rel in changed:
            want = manifest["files"][rel]
            body, errors = None, []
            # 優先下壓縮版（.gz）：jsDelivr 不給下 .exe，壓縮後也更小；沒有壓縮版的舊清單下原檔案
            suffixes = [".gz", ""] if gz else [""]
            for base in sources:
                for suffix in suffixes:
                    got = [0]

                    def on_bytes(n):
                        got[0] += n
                        report(got[0])
                    try:
                        raw = http.fetch(f"{base}/files/{rel}{suffix}", headers=HEADERS, timeout=timeout,
                                         on_bytes=on_bytes)
                        data = gzip.decompress(raw) if suffix else raw
                        if len(data) != want["size"] or hashlib.sha256(data).hexdigest() != want["sha256"]:
                            raise ValueError("校驗不對")
                        body = data
                        finished += share[rel]
                        break
                    except (requests.RequestException, ValueError, OSError, EOFError) as e:
                        errors.append(f"{base.split('/')[2]}{suffix}：{e}")
                if body is not None:
                    break
            if body is None:
                raise NeedFullInstall(f"{rel} 下載失敗：" + "；".join(errors))
            out = staging / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)
            report(0)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def apply_script(root: Path, changed: list[str], stale: list[str], pid: int, version: str,
                 relaunch: str | None) -> str:
    """生成替換檔案的 PowerShell 指令碼：等助手退出 → 舊檔案挪到 _update_old → 新檔案挪進來 →
    刪掉新版本里沒有的舊檔案；任何一步失敗就全部挪回去。最後重新開啟助手。"""
    def q(s: str) -> str:
        return "'" + str(s).replace("'", "''") + "'"
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$root = {q(Path(root))}",
        f"$new = Join-Path $root {q(STAGING)}",
        f"$old = Join-Path $root {q(BACKUP)}",
        f"$changed = @({', '.join(q(r) for r in changed)})",
        f"$stale = @({', '.join(q(r) for r in stale)})",
        # 等助手退出；30 秒還沒退（例如卡在某個網路請求上）就結束它——只結束我們自己的這個程序
        f"$pid0 = {int(pid)}",
        "try { Wait-Process -Id $pid0 -Timeout 30 -ErrorAction Stop } catch { }",
        "if (Get-Process -Id $pid0 -ErrorAction SilentlyContinue) {"
        " Stop-Process -Id $pid0 -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }",
        "Start-Sleep -Milliseconds 500",
        # 檔案剛釋放時偶爾還被佔著（防毒軟體掃描等）：每次挪檔案最多重試 10 次
        "function Move-Retry($from, $to) { for ($i = 0; $i -lt 10; $i++) {"
        " try { Move-Item -LiteralPath $from $to -Force -ErrorAction Stop; return } catch { if ($i -eq 9) { throw }"
        " Start-Sleep -Seconds 1 } } }",
        "if (Test-Path $old) { Remove-Item -Recurse -Force $old }",
        "$moved = @()",
        "try {",
        "  foreach ($rel in $changed + $stale) {",
        "    $dst = Join-Path $root $rel",
        "    if (Test-Path -LiteralPath $dst) {",
        "      $bak = Join-Path $old $rel",
        "      New-Item -ItemType Directory -Force (Split-Path $bak) | Out-Null",
        "      Move-Retry $dst $bak",
        "      $moved += $rel",
        "    }",
        "  }",
        "  foreach ($rel in $changed) {",
        "    $dst = Join-Path $root $rel",
        "    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null",
        "    Move-Retry (Join-Path $new $rel) $dst",
        "  }",
        # 「應用」列表裡的版本號：現在的安裝包只裝給當前使用者（HKCU）；早期可能選過"所有使用者"（HKLM，沒管理員許可權改不了，忽略）
        f"  foreach ($hive in 'HKCU:\\', 'HKLM:\\') {{ try {{ $k = $hive + {q(UNINSTALL_KEY)}; "
        f"if (Test-Path $k) {{ Set-ItemProperty -Path $k -Name DisplayVersion -Value {q(version)} -ErrorAction Stop }} }} "
        "catch { } }",
        "  Remove-Item -Recurse -Force $old -ErrorAction SilentlyContinue",
        "} catch {",
        "  foreach ($rel in $changed) { $dst = Join-Path $root $rel; if (Test-Path -LiteralPath $dst) {"
        " Remove-Item -LiteralPath $dst -Force -ErrorAction SilentlyContinue } }",
        "  foreach ($rel in $moved) { $dst = Join-Path $root $rel;"
        " New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null;"
        " Move-Item -LiteralPath (Join-Path $old $rel) $dst -Force -ErrorAction SilentlyContinue }",
        "  Set-Content -LiteralPath (Join-Path $root 'update-failed.txt') -Value $_.ToString() -Encoding UTF8",
        "}",
        "Remove-Item -Recurse -Force $new -ErrorAction SilentlyContinue",
    ]
    if relaunch:
        lines.append(f"Start-Process -FilePath {q(relaunch)} -WorkingDirectory $root")
    lines.append("Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue")
    return "\n".join(lines) + "\n"


def launch_apply(root: Path, changed: list[str], stale: list[str], version: str,
                 relaunch: str | None = None, pid: int | None = None, wait: bool = False) -> Path:
    """寫出並啟動替換指令碼。呼叫後助手應當馬上退出，讓出檔案。"""
    script = Path(tempfile.gettempdir()) / f"aramhex-apply-{version}-{os.getpid()}.ps1"
    body = apply_script(root, changed, stale, pid or os.getpid(), version, relaunch)
    script.write_text(body, encoding="utf-8-sig")  # Windows PowerShell 5.1 要 BOM 才按 UTF-8 讀中文路徑
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(script)]
    if wait:
        subprocess.run(args, check=False, timeout=180)
    else:
        # 不能用 DETACHED_PROCESS：PowerShell 沒有控制檯時會直接退出。用 CREATE_NO_WINDOW 隱藏視窗，
        # 新程序組讓它在助手退出後繼續執行
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(args, close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return script


def take_failure(root: Path | None = None) -> str | None:
    """上次增量更新沒裝上（已還原成舊版本）時返回原因，並清理留下的臨時目錄；沒有返回 None。"""
    root = root or install_root()
    if root is None:
        return None
    for d in (STAGING, BACKUP):
        shutil.rmtree(Path(root) / d, ignore_errors=True)
    f = Path(root) / "update-failed.txt"
    if not f.exists():
        return None
    try:
        reason = f.read_text(encoding="utf-8-sig", errors="replace").strip()
    finally:
        f.unlink(missing_ok=True)
    return reason or "未知原因"


def install_root() -> Path | None:
    """打包後的程式目錄；原始碼執行時沒有，不做增量更新。"""
    return program_dir() if getattr(sys, "frozen", False) else None


RANK_MIN_BYTES = 3 * 1024 * 1024  # 要下載的超過這麼多才測速挑線路


def rank_by_speed(sources: list[str], rel: str, sample: int = 256 * 1024, timeout: float = 6) -> list[str]:
    """幾條線路同時下載同一個檔案的前 256KB，按速度從快到慢排。連不上的排最後。
    實測 172 上：GitHub 32KB/s，jsDelivr 的 gcore 節點 207KB/s——不能"GitHub 能連上就一直用它"。"""
    import time
    from concurrent.futures import ThreadPoolExecutor

    def probe(base):
        start = time.monotonic()
        got = 0
        try:
            with requests.get(f"{base}/files/{rel}", headers={**HEADERS, "Range": f"bytes=0-{sample - 1}"},
                              timeout=timeout, stream=True) as r:
                if r.status_code not in (200, 206):
                    return 0.0
                for chunk in r.iter_content(32 * 1024):
                    got += len(chunk)
                    if got >= sample or time.monotonic() - start > timeout:
                        break
        except requests.RequestException:
            return 0.0
        return got / max(time.monotonic() - start, 1e-3)

    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        speeds = list(pool.map(probe, sources))
    order = sorted(range(len(sources)), key=lambda i: -speeds[i])
    log.info("線路測速（KB/s）：%s", "，".join(f"{sources[i].split('/')[2]} {speeds[i] / 1024:.0f}" for i in order))
    return [sources[i] for i in order]


def prepare(version: str, progress=None, root: Path | None = None, sources=None,
            phase=None) -> tuple[list[str], list[str]]:
    """查清單、比較、下載。成功返回 (變了的檔案, 要刪的檔案)，下一步調 launch_apply；不能增量就拋 NeedFullInstall。"""
    sources = sources or sources_for(version)
    root = root or install_root()
    if root is None:
        raise NeedFullInstall("原始碼執行，不做增量更新")
    say = phase or (lambda text: None)  # 介面顯示當前在做什麼
    say("檢查更新檔案…")
    manifest, base = fetch_manifest(version, sources)
    say("比對本機檔案…")
    changed, stale = plan(manifest, root)
    if not changed and not stale:
        raise NeedFullInstall("本機檔案已經和新版本一樣")
    log.info("增量更新到 %s：%d 個檔案要換（%.1f MB），清單來自 %s", version, len(changed),
             sum(manifest["files"][r]["size"] for r in changed) / 1e6, base)
    say("下載更新…")
    order = [base] + [s for s in sources if s != base]
    size = sum(manifest["files"][r]["size"] for r in changed)
    if len(order) > 1 and changed and size >= RANK_MIN_BYTES:  # 小更新直接用拿到清單的線路，測速反而更慢
        say("挑選最快的下載線路…")
        order = rank_by_speed(order, max(changed, key=lambda r: manifest["files"][r]["size"]))
    download(manifest, changed, root, order, progress)
    return changed, stale


def main(argv=None) -> int:
    """發版用：python -m lolhex.patch <程式目錄> <版本> <輸出目錄>，生成 updates 分支的內容。"""
    argv = sys.argv[1:] if argv is None else argv
    root, version, out = Path(argv[0]), argv[1], Path(argv[2])
    m = {**build_manifest(root, version), "encoding": "gzip"}
    shutil.rmtree(out, ignore_errors=True)
    packed = 0
    for rel in m["patchable"]:
        dst = out / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
        gz = gzip.compress((root / rel).read_bytes(), 9, mtime=0)
        if len(gz) > 20 * 1024 * 1024:
            raise SystemExit(f"{rel} 壓縮後仍超過 jsDelivr 的 20MB 上限")
        dst.with_name(dst.name + ".gz").write_bytes(gz)
        m.setdefault("packed", {})[rel] = len(gz)  # 壓縮後大小：程式據此算下載進度
        packed += len(gz)
    (out / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                       encoding="utf-8")
    size = sum(m["files"][r]["size"] for r in m["patchable"])
    print(f"updates 分支內容：{len(m['patchable'])} 個檔案，原始 {size / 1e6:.1f} MB，壓縮後 {packed / 1e6:.1f} MB → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
