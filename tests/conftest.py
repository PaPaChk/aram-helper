"""測試夾具：騰訊官方資料用 2026-09-25 實抓並裁剪過的真實資料；統計資料用一份小的合成資料，離線構建 PublicStore。"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

BANDS = ("casual", "mid", "high", "top")


def fixture(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _hero(games, wins, rank=1):
    return {"name": None, "title": None, "games": games, "wins": wins, "win_rate": round(wins / games, 6),
            "pick_rate": 0.01, "rank": rank}


def _aug(games, win):
    wins = round(games * win)
    return {"games": games, "wins": wins, "win_rate": round(wins / games, 6), "low_sample": games < 3000}


# 提莫（17）：騰訊把熾燃利息（2128）排黃金第 1，但帶虛幻武器（1029）的勝率明顯更高
TEEMO = {"2128": _aug(30000, 0.52), "1029": _aug(40000, 0.60), "1373": _aug(20000, 0.55)}


def make_dataset(folder: Path, snapshot_at="2026-10-13T11:56:47+08:00", patch="16.20", bands=True,
                 heroes=None, hero_augments=None, seq=0) -> dict:
    """在 folder 寫一份公開資料（和資料倉儲同格式），返回清單。"""
    heroes = heroes or {"17": _hero(400000, 212000, 1), "1": _hero(300000, 147000, 2)}
    hero_augments = hero_augments or {"17": dict(TEEMO), "1": {"1029": _aug(5000, 0.47)}}
    files = {"heroes.json": heroes, "hero_augments.json": hero_augments,
             "meta.json": {"schema_version": 1, "patch": patch, "mode": "normal",
                           "matches": {"collected": 72000, "valid": 70000, "excluded": 2000},
                           "window": {"start": "2026-10-09T08:14:00+08:00", "end_exclusive": "2026-10-13T10:00:00+08:00"},
                           "regions": ["艾歐尼亞"]}}
    if bands:
        for i, b in enumerate(BANDS):  # 分段越高，提莫越強，便於斷言
            files[f"bands/{b}/heroes.json"] = {"17": _hero(1000 * (4 - i), int(1000 * (4 - i) * (0.50 + 0.02 * i))),
                                               "1": _hero(1000, 500)}
            files[f"bands/{b}/hero_augments.json"] = {"17": {"1029": _aug(500, 0.50 + 0.03 * i)}}
    manifest = {"schema_version": 1, "patch": patch, "path": f"patches/{patch}", "snapshot_at": snapshot_at,
                "window": files["meta.json"]["window"], "matches": 70000, "bands": bands, "files": {}, "seq": seq}
    for name, obj in files.items():
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        p = folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        manifest["files"][name] = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
    (folder / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("測試中不應聯網")
    monkeypatch.setattr("lolhex.data.http.get", boom)
    monkeypatch.setattr("lolhex.data.http.head_ok", boom)
    monkeypatch.setattr("requests.get", boom)


@pytest.fixture
def store(tmp_path, no_network):
    """離線 PublicStore：官方靜態資料、提莫的單英雄官方資料、一份內建統計資料都已就緒，且禁止聯網。"""
    from lolhex.data import tencent
    from lolhex.data.public import PublicStore

    now = time.time()
    root = tmp_path / "data"
    root.mkdir()
    static = {
        "fetched_at": now, "patch": "16.20", "versions": [{"name": "16.20"}],
        "heroes": tencent.parse_hero_list(fixture("tencent_hero_list.json")),
        "augments": tencent.parse_kiwi_augments(fixture("tencent_kiwi_augments.json")),
        "items": tencent.parse_items(fixture("tencent_items.json")),
        "spells": tencent.parse_summoner_spells(fixture("tencent_summoner_spells.json")),
    }
    hero17 = tencent.parse_hero_hex(fixture("tencent_hero17.json"))
    hero17.update(spells=tencent.parse_hero_spells(fixture("tencent_hero17_spells.json")),
                  fetched_at=now, patch="16.20", splash=None)
    (root / "static.json").write_text(json.dumps(static, ensure_ascii=False), encoding="utf-8")
    (root / "hero").mkdir()
    (root / "hero" / "17.json").write_text(json.dumps(hero17, ensure_ascii=False), encoding="utf-8")
    bundled = tmp_path / "bundled"
    make_dataset(bundled)
    return PublicStore(root, bundled=bundled, check_updates=False)


@pytest.fixture(autouse=True)
def _no_site(monkeypatch, request):
    """測試不連真的官網映象；要測映象的用例自己給地址（標記 site）。"""
    if "site" in request.keywords:
        return
    from lolhex import update

    def offline(*a, **k):
        raise update.requests.ConnectionError("測試不連官網")
    monkeypatch.setattr(update, "check_site", offline)


def pytest_configure(config):
    config.addinivalue_line("markers", "site: 允許連（假的）官網映象")
