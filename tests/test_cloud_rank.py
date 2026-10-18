"""雲控配置和查分客戶端。"""
import pytest

from lolhex import cloud, rank


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise cloud.requests.HTTPError(str(self.status_code))

    def json(self):
        if self.data is None:
            raise ValueError("not json")
        return self.data


@pytest.fixture(autouse=True)
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    monkeypatch.setattr(cloud, "_cache", None)


def test_cloud_defaults_and_bad_values(monkeypatch):
    assert cloud.get()["rank"]["enabled"] is True
    monkeypatch.setattr(cloud.requests, "get", lambda url, **k: Resp({"rank": {"enabled": False, "message": "維護中", "evil": {"x": 1}},
                                                                      "notice": "不是字典", "min_version": "1.2.0"}))
    cfg = cloud.refresh()
    assert cfg["rank"]["enabled"] is False and "evil" not in cfg["rank"] and cfg["notice"] == {} and cfg["min_version"] == "1.2.0"


def test_rank_lookup_paths(monkeypatch):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append(headers)
        rid = params["id"]
        if rid == "a#1":
            return Resp({"as_of": "2026-10-16", "results": [{"region": "HN1", "region_name": "艾歐尼亞", "top": 0.031,
                                                              "band": "high", "band_name": "高分", "games": 120}]})
        if rid == "slow#1":
            return Resp({"error": "查得太快了，請一分鐘後再試"}, 429)
        if rid == "down#1":
            return Resp(None, 502)
        return Resp({"error": "沒有查到"}, 404)
    monkeypatch.setattr(rank.requests, "get", get)
    res = rank.lookup("a#1")
    assert calls[0]["X-AramHex"] and rank.describe(res).startswith("前 3.1%（高分）· 艾歐尼亞") and "截至 10-16" in rank.describe(res)
    for rid, msg in (("slow#1", "一分鐘"), ("down#1", "暫時不可用"), ("x#1", "沒有查到"), ("沒編號", "名字#編號")):
        with pytest.raises(rank.RankError, match=msg):
            rank.lookup(rid)
    cloud._cache = cloud._merge({"rank": {"enabled": False, "message": "查詢維護中"}})
    with pytest.raises(rank.RankError, match="維護中"):
        rank.lookup("a#1")


def test_rank_unreachable(monkeypatch):
    def boom(*a, **k):
        raise rank.requests.ConnectionError("x")
    monkeypatch.setattr(rank.requests, "get", boom)
    with pytest.raises(rank.RankError, match="連不上"):
        rank.lookup("a#1")


def test_cloud_mirrors_go_first(monkeypatch):
    from lolhex import patch
    monkeypatch.setattr(cloud.requests, "get", lambda url, **k: Resp({"mirrors": {
        "update": ["https://new.example/u/{version}/", "http://insecure.example/x"], "data": ["https://new.example/u/data"]},
        "features": {"autoshot": False}}))
    cloud.refresh()
    src = patch.sources_for("1.2.3")
    assert src[0] == "https://new.example/u/1.2.3" and not any("insecure" in s for s in src)
    assert cloud.mirrors("data") == ["https://new.example/u/data"]
    assert cloud.feature("autoshot") is False and cloud.feature("other") is True


def test_community_list_is_sanitized(monkeypatch):
    monkeypatch.setattr(cloud.requests, "get", lambda url, **k: Resp({"community": [
        {"name": "QQ 群", "text": "123456", "url": "https://qm.qq.com/q/x", "qr": "https://aramhex.com/img/qq.png", "primary": True},
        {"name": "B 站", "url": "javascript:alert(1)"},
        {"text": "沒有名字"}, "不是字典",
        {"name": "贊助", "url": "https://afdian.com/a/x", "qr": "http://insecure/qr.png"},
    ]}))
    cloud.refresh()
    c = cloud.community()
    assert [x["name"] for x in c] == ["QQ 群", "B 站", "贊助"]
    assert c[1]["url"] == "" and c[2]["qr"] == ""
    assert cloud.primary_link()["url"] == "https://qm.qq.com/q/x"
