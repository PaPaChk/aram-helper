"""更新失敗的兜底：整包下載太慢就停、網盤連結從官網讀、各種失敗都讓使用者去網盤下載。"""
import hashlib

import pytest

from lolhex import update


class Resp:
    def __init__(self, data=None, chunks=(), status=200, length=None):
        self.data, self.chunks, self.status_code = data, chunks, status
        self.headers = {"Content-Length": str(length)} if length else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise update.requests.HTTPError(str(self.status_code))

    def json(self):
        return self.data

    def iter_content(self, n):
        yield from self.chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_pan_links_from_cloud_config(monkeypatch, tmp_path):
    from lolhex import cloud
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    monkeypatch.setattr(cloud, "_cache", None)
    monkeypatch.setattr(cloud.requests, "get", lambda url, **k: Resp({"downloads": {"setup": "https://pan/s", "portable": ""}}))
    assert update.pan_links() == {"setup": "https://pan/s"}

    def boom(url, **k):
        raise cloud.requests.ConnectionError("x")
    monkeypatch.setattr(cloud.requests, "get", boom)
    monkeypatch.setattr(cloud, "_cache", None)
    assert update.pan_links() == {"setup": "https://pan/s"}  # 連不上：用上次存下的


def test_download_gives_up_when_slow(monkeypatch, tmp_path):
    clock = [0.0]
    import time

    def chunks():
        for _ in range(10):
            clock[0] += 5
            yield b"x" * 1024
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(update.requests, "get", lambda url, **k: Resp(chunks=chunks(), length=10 ** 8))
    info = {"file": "AramHex-Setup-9.exe", "url": "u", "sha256": "0" * 64, "size": 10 ** 8}
    with pytest.raises(update.SlowDownload):
        update.download(info, folder=tmp_path)
    assert not (tmp_path / info["file"]).exists()


def test_download_ok_when_fast(monkeypatch, tmp_path):
    body = b"y" * 4096
    monkeypatch.setattr(update.requests, "get", lambda url, **k: Resp(chunks=[body], length=len(body)))
    info = {"file": "AramHex-Setup-9.exe", "url": "u", "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
    assert update.download(info, folder=tmp_path).read_bytes() == body


def test_worker_offers_netdisk_on_failures(monkeypatch):
    pytest.importorskip("PySide6")
    from lolhex import patch
    from lolhex.ui import mainwindow

    monkeypatch.setattr(update, "pan_links", lambda: {"setup": "https://pan/s"})
    monkeypatch.setattr(mainwindow, "is_portable", lambda: False)
    info = {"version": "9.9.9", "url": "u", "file": "f", "sha256": "0" * 64}

    def run(prepare, download=None):
        got = []
        monkeypatch.setattr(patch, "prepare", prepare)
        if download:
            monkeypatch.setattr(update, "download", download)
        w = mainwindow.UpdateWorker("download", info=info)
        w.manual.connect(lambda reason, links: got.append((reason, links)))
        w.failed.connect(lambda m: got.append(("failed", m)))
        w.run()
        return got

    def need_full(*a, **k):
        raise patch.NeedFullInstall("第三方庫變了")

    def net_down(*a, **k):
        raise update.requests.ConnectionError("連不上")

    def slow(*a, **k):
        raise update.SlowDownload("慢")

    assert run(net_down) == [("更新檔案下載失敗。", {"setup": "https://pan/s"})]
    assert run(need_full, slow)[0][0] == "從 GitHub 下載太慢。"
    assert run(need_full, net_down)[0][0] == "從 GitHub 下載安裝包失敗。"
