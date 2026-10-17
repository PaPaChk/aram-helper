"""增量更新的收尾：替换失败时下次启动能知道；替换脚本会强制结束卡住的旧进程、挪文件会重试。"""
from lolhex import patch


def test_take_failure_reports_once_and_cleans(tmp_path):
    (tmp_path / patch.STAGING).mkdir()
    (tmp_path / "update-failed.txt").write_text("文件被占用", encoding="utf-8-sig")
    assert patch.take_failure(tmp_path) == "文件被占用"
    assert not (tmp_path / patch.STAGING).exists()
    assert patch.take_failure(tmp_path) is None


def test_apply_script_kills_stuck_process_and_retries():
    s = patch.apply_script(patch.Path("C:/x"), ["a.exe"], [], 1234, "9.9.9", "C:/x/a.exe")
    assert "Stop-Process -Id $pid0" in s and "Move-Retry" in s


def test_rank_by_speed_puts_fastest_first(monkeypatch):
    import time

    class Resp:
        def __init__(self, url):
            self.slow = "slow" in url
            self.status_code = 206

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_content(self, n):
            for _ in range(8):
                if self.slow:
                    time.sleep(0.05)
                yield b"x" * n
    monkeypatch.setattr(patch.requests, "get", lambda url, **kw: Resp(url))
    assert patch.rank_by_speed(["https://slow.example", "https://fast.example"], "a.exe")[0] == "https://fast.example"
