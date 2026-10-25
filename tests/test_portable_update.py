"""便攜版自我更新：選對 asset、下載後整包替換、userdata 絕不被動到。"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from lolhex import patch, update


def _release(assets):
    return {"tag_name": "v9.9.9", "body": "notes", "html_url": "https://example.test/rel",
            "draft": False, "prerelease": False, "assets": assets}


def _asset(name, sha):
    return {"name": name, "size": 10, "digest": f"sha256:{sha}",
            "browser_download_url": f"https://example.test/{name}"}


SHA_A = "a" * 64
SHA_B = "b" * 64


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture()
def fake_release(monkeypatch):
    """讓 check() 看到一個同時有安裝包與便攜版 ZIP 的版本。"""
    assets = [_asset("AramHexTW-Setup-9.9.9.exe", SHA_A),
              _asset("AramHexTW-Portable-9.9.9.zip", SHA_B)]
    payload = _release(assets)

    def fake_get(url, **kw):
        return _Resp(payload)

    monkeypatch.setattr(update.requests, "get", fake_get)
    return payload


def test_portable_build_picks_the_zip(fake_release):
    info = update.check("1.0.0", portable=True)
    assert info is not None
    assert info["file"] == "AramHexTW-Portable-9.9.9.zip"
    assert info["portable"] is True
    assert info["sha256"] == SHA_B


def test_installed_build_picks_the_setup_exe(fake_release):
    info = update.check("1.0.0", portable=False)
    assert info is not None
    assert info["file"] == "AramHexTW-Setup-9.9.9.exe"
    assert info["portable"] is False
    assert info["sha256"] == SHA_A


def test_portable_never_falls_back_to_the_installer(monkeypatch):
    """這個版本沒放便攜版 ZIP 時，便攜版不能改用安裝包。

    安裝程式會裝進 Program Files，便攜性就沒了，程式目錄裡的 userdata 也不會被帶過去。
    正確行為是回報「有新版本但沒有可自動安裝的檔案」，讓呼叫端退回下載頁。"""
    payload = _release([_asset("AramHexTW-Setup-9.9.9.exe", SHA_A)])
    monkeypatch.setattr(update.requests, "get", lambda url, **kw: _Resp(payload))
    info = update.check("1.0.0", portable=True)
    assert info is not None
    assert info["portable"] is True
    assert info["url"] is None          # 沒有可自動下載的檔案
    assert info["file"] is None
    assert info["page"]                 # 仍然給得出下載頁


def _make_zip(path: Path, top: str, files: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for rel, data in files.items():
            z.writestr(f"{top}/{rel}", data)
    return path


def test_extract_portable_strips_the_top_directory(tmp_path):
    z = _make_zip(tmp_path / "p.zip", "AramHexTW-9.9.9",
                  {"AramHexTW.exe": b"exe", "_internal/a.dll": b"dll", "portable.txt": b"p"})
    out, rels = update.extract_portable(z, tmp_path / "stage")
    assert sorted(rels) == ["AramHexTW.exe", "_internal/a.dll", "portable.txt"]
    assert (out / "AramHexTW.exe").read_bytes() == b"exe"
    assert (out / "_internal" / "a.dll").read_bytes() == b"dll"
    # 頂層目錄被剝掉：不應存在巢狀的 AramHexTW-9.9.9
    assert not (out / "AramHexTW-9.9.9").exists()


def test_extract_portable_rejects_zip_slip(tmp_path):
    """含有 .. 的路徑要直接拒絕整個包，而不是靜靜跳過那一項。

    靜默跳過很危險：呼叫端會以為解壓完整，實際上有檔案沒拿到，
    之後按清單替換就把程式目錄換成殘缺的一套。寧可整個更新失敗、留在舊版本。"""
    z = _make_zip(tmp_path / "evil.zip", "top", {"../escape.txt": b"x", "ok.txt": b"y"})
    with pytest.raises(ValueError):
        update.extract_portable(z, tmp_path / "stage")
    assert not (tmp_path / "escape.txt").exists()


def test_extract_portable_rejects_a_flat_zip(tmp_path):
    """沒有單一頂層目錄的包也拒絕：猜錯會把整包內容倒進程式目錄。"""
    flat = tmp_path / "flat.zip"
    with zipfile.ZipFile(flat, "w") as z:
        z.writestr("a.txt", b"a")
        z.writestr("b.txt", b"b")
    with pytest.raises(ValueError):
        update.extract_portable(flat, tmp_path / "stage")


def test_swap_never_touches_userdata(tmp_path):
    """解壓後把檔案疊進程式目錄時，userdata 一定不在替換清單裡。"""
    root = tmp_path / "app"
    root.mkdir()
    (root / "portable.txt").write_text("portable", encoding="utf-8")
    userdata = root / "userdata"
    userdata.mkdir()
    (userdata / "config.json").write_text('{"keep": true}', encoding="utf-8")
    shots = userdata / "shots"
    shots.mkdir()
    (shots / "offer.jpg").write_bytes(b"\xff\xd8\xff")

    # ZIP 裡就算混進 userdata，也必須被排除
    z = _make_zip(tmp_path / "p.zip", "AramHexTW-9.9.9",
                  {"AramHexTW.exe": b"newexe", "userdata/config.json": b'{"keep": false}'})

    scripts: list[str] = []
    orig = patch.launch_apply

    def spy(root_, changed, stale, version, relaunch=None, pid=None, wait=False):
        scripts.append(list(changed))
        return tmp_path / "apply.ps1"

    patch.launch_apply = spy
    try:
        update.launch_portable_update(z, "9.9.9", root=root)
    finally:
        patch.launch_apply = orig

    assert scripts, "launch_apply was not called"
    changed = scripts[0]
    assert "AramHexTW.exe" in changed
    assert not any(c == "userdata" or c.startswith("userdata/") for c in changed), changed
    # 使用者資料原封不動
    assert (userdata / "config.json").read_text(encoding="utf-8") == '{"keep": true}'
    assert (shots / "offer.jpg").exists()


def test_hash_mismatch_deletes_download(tmp_path, monkeypatch):
    """下載到的最後雜湊不符時必須刪檔並報錯，不能拿去替換。"""
    info = {"version": "9.9.9", "file": "x.zip", "sha256": SHA_A, "url": "https://example.test/x.zip"}

    class FakeStream:
        status_code = 200
        headers = {"Content-Length": "3"}

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b"abc"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(update.requests, "get", lambda *a, **kw: FakeStream())
    folder = tmp_path / "dl"
    with pytest.raises(ValueError):
        update.download(info, folder=folder)
    assert not (folder / "x.zip").exists()
