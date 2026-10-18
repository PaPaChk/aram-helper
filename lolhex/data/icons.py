"""裝備、召喚師技能的小圖示：按需從騰訊 CDN 下載到本地，介面用本地檔案顯示。

介面執行緒只查本地檔案，不等網路：沒有就先返回 None（介面先顯示文字），同時交給後臺執行緒下載；
下載完成後 version 加一，介面據此重新渲染。
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import http

log = logging.getLogger(__name__)
MAX_AGE_S = 14 * 86400  # 圖示很少變；兩週後順手重下一次，跟上版本改圖


class IconCache:
    def __init__(self, folder: Path, workers: int = 4):
        self.folder = folder
        self.version = 0
        self._pending: set[str] = set()
        self._failed: dict[str, float] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="icons")

    def local(self, kind: str, key: str, url: str | None) -> str | None:
        """本地圖示路徑（給 Qt 富文字 <img> 用），還沒有就後臺下載並返回 None。"""
        if not key:
            return None
        path = self.folder / kind / f"{key}.png"
        fresh = path.exists() and time.time() - path.stat().st_mtime < MAX_AGE_S
        if not fresh and url:
            self._fetch(path, url)
        return path.as_posix() if path.exists() else None

    def _fetch(self, path: Path, url: str) -> None:
        tag = str(path)
        with self._lock:
            if tag in self._pending or time.time() - self._failed.get(tag, 0) < 600:
                return
            self._pending.add(tag)
        self._pool.submit(self._download, path, url, tag)

    def _download(self, path: Path, url: str, tag: str) -> None:
        try:
            if url.startswith("//"):
                url = "https:" + url
            r = http._session.get(url, timeout=15)
            if r.status_code != 200 or not r.content.startswith(b"\x89PNG"):
                raise ValueError(f"HTTP {r.status_code}")
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            tmp.replace(path)
            with self._lock:
                self.version += 1
        except Exception as e:
            log.info("圖示下載失敗 %s：%s", url, e)
            with self._lock:
                self._failed[tag] = time.time()
        finally:
            with self._lock:
                self._pending.discard(tag)
