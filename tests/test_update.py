"""程式更新：版本比較、GitHub Releases 介面解析、SHA-256 來源、下載校驗。"""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from lolhex import update

BODY = b"installer-bytes"


@pytest.fixture
def gh():
    """本地模擬 GitHub：/latest 返回 release JSON，/dl/<檔案> 返回內容。"""
    state = {"release": None, "files": {}}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/latest":
                if state["release"] is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps(state["release"]).encode()
            elif self.path.startswith("/dl/") and self.path[4:] in state["files"]:
                body = state["files"][self.path[4:]]
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state, base
    httpd.shutdown()


def _release(base, version="9.9.9", digest=True, sums=False):
    name = f"AramHex-Setup-{version}.exe"
    assets = [{"name": name, "size": len(BODY), "browser_download_url": f"{base}/dl/{name}",
               **({"digest": "sha256:" + hashlib.sha256(BODY).hexdigest()} if digest else {})},
              {"name": f"AramHex-Portable-{version}.zip", "size": 1, "browser_download_url": f"{base}/dl/p.zip"}]
    if sums:
        assets.append({"name": "SHA256SUMS.txt", "size": 1, "browser_download_url": f"{base}/dl/SHA256SUMS.txt"})
    return {"tag_name": f"v{version}", "body": "修了一些問題", "html_url": f"{base}/release",
            "draft": False, "prerelease": False, "assets": assets}, name


def test_version_compare():
    assert update.is_newer("0.3.18", "0.3.17") and update.is_newer("1.0.0", "0.9.99")
    assert update.is_newer("0.3.10", "0.3.9")
    assert not update.is_newer("0.3.17", "0.3.17") and not update.is_newer("0.3.16", "0.3.17")
    assert not update.is_newer("", "0.3.17")


def test_setup_asset_names_match_what_we_actually_build():
    """台服版的安裝包叫 AramHexTW-Setup-<版本>.exe，版本帶 '+'（1.0.0+tw.5）。
    這個正則先前只認 AramHex-Setup-...，會讓自動更新永遠找不到安裝包。"""
    assert update.FILE_RE.match("AramHexTW-Setup-1.0.0+tw.5.exe")
    assert update.FILE_RE.match("AramHexTW-Setup-1.0.0+tw.6.exe")
    assert update.FILE_RE.match("AramHex-Setup-1.1.0.exe")      # 上游國服版也照收
    assert not update.FILE_RE.match("AramHexTW-Portable-1.0.0.zip")
    assert not update.FILE_RE.match("AramHex-Setup-x.exe")
    assert not update.FILE_RE.match("evil.exe")


def test_check_and_download(gh, tmp_path):
    state, base = gh
    api = f"{base}/latest"
    assert update.check("1.0.0", api=api) is None  # 還沒釋出過
    state["release"], name = _release(base)
    state["files"][name] = BODY
    info = update.check("1.0.0", api=api)
    assert info["version"] == "9.9.9" and info["file"] == name and info["size"] == len(BODY)
    assert info["notes"] == "修了一些問題" and info["page"] == f"{base}/release"
    assert update.check("9.9.9", api=api) is None  # 已經是最新
    seen = []
    path = update.download(info, lambda d, t: seen.append((d, t)), tmp_path / "dl")
    assert path.read_bytes() == BODY and seen[-1] == (len(BODY), len(BODY))
    with pytest.raises(ValueError):  # 檔案和公佈的雜湊對不上：不裝
        update.download({**info, "sha256": "0" * 64}, folder=tmp_path / "dl")
    assert not (tmp_path / "dl" / name).exists()


def test_sha_from_sums_file_when_no_digest(gh):
    state, base = gh
    state["release"], name = _release(base, digest=False, sums=True)
    state["files"]["SHA256SUMS.txt"] = f"{hashlib.sha256(BODY).hexdigest()}  {name}\n".encode()
    assert update.check("1.0.0", api=f"{base}/latest")["sha256"] == hashlib.sha256(BODY).hexdigest()


def test_release_without_any_hash_is_refused(gh):
    state, base = gh
    state["release"], _ = _release(base, digest=False)
    assert update.check("1.0.0", api=f"{base}/latest") is None
    with pytest.raises(ValueError, match="SHA-256"):
        update.check("1.0.0", api=f"{base}/latest", strict=True)


def test_prerelease_is_ignored(gh):
    state, base = gh
    state["release"], _ = _release(base)
    state["release"]["prerelease"] = True
    assert update.check("1.0.0", api=f"{base}/latest") is None


def test_unreachable(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("連不上 GitHub")
    monkeypatch.setattr(update.requests, "get", boom)
    assert update.check("1.0.0", mirrors=[], probe_hosts=()) is None  # 自動檢查：靜默
    with pytest.raises(requests.ConnectionError):
        update.check("1.0.0", strict=True, mirrors=[], probe_hosts=())


@pytest.fixture
def mirror():
    """模擬 jsDelivr：返回最新 tag 裡的 lolhex/__init__.py。"""
    state = {"version": "9.9.9", "ok": True}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if not state["ok"]:
                self.send_response(503)
                self.end_headers()
                return
            body = f'"""x"""\n\n__version__ = "{state["version"]}"\n'.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield state, f"http://127.0.0.1:{httpd.server_address[1]}/lolhex/__init__.py"
    httpd.shutdown()


def test_github_unreachable_falls_back_to_mirror(mirror):
    state, url = mirror
    dead = "http://127.0.0.1:9/latest"
    info = update.check("1.0.0", api=dead, mirrors=["http://127.0.0.1:9/x", url], probe_hosts=())
    assert info["version"] == "9.9.9" and info["url"] is None and info["mirror"] is True  # 只給下載頁
    state["version"] = "1.0.0"
    assert update.check("1.0.0", api=dead, mirrors=[url], strict=True, probe_hosts=()) is None  # 映象說已是最新
    state["ok"] = False
    assert update.check("1.0.0", api=dead, mirrors=[url], probe_hosts=()) is None
    with pytest.raises(requests.RequestException):
        update.check("1.0.0", api=dead, mirrors=[url], strict=True, probe_hosts=())

class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    @property
    def ok(self):
        return self.status_code == 200

    def json(self):
        return self._body


def test_probe_follows_tags_to_newest(monkeypatch):
    """按 tag 試探：1.0.4 → 1.0.5 有 → 從 1.0.5 接著試 → 1.1.0 有 → 再往後都沒有，結果 1.1.0。"""
    published = {"1.0.5", "1.1.0"}
    asked = []

    def fake_get(url, **kw):
        asked.append(url)
        v = url.split("@updates-v")[1].split("/")[0]
        return _Resp(200, {"version": v}) if v in published else _Resp(404)
    monkeypatch.setattr(update.requests, "get", fake_get)
    assert update.probe_newer("1.0.4") == ("1.1.0", True)
    assert all("fastly.jsdelivr.net" in u for u in asked)  # 第一個節點答覆了就不再問別的節點
    info = update.check_mirror("1.0.4", mirrors=[])
    assert info["version"] == "1.1.0" and info["mirror"] is True


def test_probe_takes_max_with_latest_alias(monkeypatch):
    def fake_get(url, **kw):
        if "@updates-v" in url:
            return _Resp(404)
        class R:
            text = '__version__ = "1.2.0"\n'
            def raise_for_status(self):
                pass
        return R()
    monkeypatch.setattr(update.requests, "get", fake_get)
    assert update.check_mirror("1.0.4", mirrors=["https://x/@latest/lolhex/__init__.py"])["version"] == "1.2.0"
