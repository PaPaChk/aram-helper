"""執行配置與本地目錄。

配置檔案：%APPDATA%\\AramHex\\config.json（可用環境變數 ARAMHEX_HOME 改目錄）。
便攜版：程式目錄裡有 portable.txt 時，配置、日誌和資料都放在程式目錄的 userdata 下，不寫 %APPDATA%。
首次執行會寫出預設值，之後手改即可；未知鍵保留不動。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_DIR_NAME = "AramHexTW"
# 識別頻率：各種掃描間隔乘以這個倍數。電腦配置低時放慢，省 CPU
SPEEDS = {
    "standard": ("標準（推薦）", 1.0),
    "saver": ("省電：識別稍慢", 2.0),
    "low": ("低配電腦：識別更慢，最省 CPU", 4.0),
}


def program_dir() -> Path:
    """程式所在目錄（打包後是 exe 旁邊，原始碼執行時是倉庫根目錄）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    return (program_dir() / "portable.txt").is_file()


def app_home() -> Path:
    env = os.environ.get("ARAMHEX_HOME")
    if env:
        home = Path(env)
    elif is_portable():
        home = program_dir() / "userdata"
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        home = Path(base) / APP_DIR_NAME
    home.mkdir(parents=True, exist_ok=True)
    return home


@dataclass
class Settings:
    # 舊設定保留相容；台服手動版不使用自動英雄識別。
    use_liveclient: bool = False
    # 在懸浮層與主介面顯示勝率數值。關掉後只顯示評級與排名。
    show_winrate: bool = True
    # 騰訊官方資料（英雄、海克斯字典、出裝、加點）的重新整理間隔（小時）。
    refresh_hours: float = 6.0
    # 啟動時檢查資料倉儲有沒有新的統計資料，有就下載（按 SHA-256 校驗）。
    check_data_updates: bool = True
    # 自動檢查 GitHub Releases 有沒有新版本，有就自動下載並安裝（裝完自動重開）。
    # 關掉後只剩手動「檢查更新」按鈕。
    auto_update: bool = True
    # 自動更新的檢查間隔（小時）。預設 6 小時，避免太頻繁打 GitHub API。
    auto_update_hours: float = 6.0
    # 已校準時，檢查三張卡標題區域的間隔（毫秒）。
    scan_interval_ms: int = 300
    # 未校準時，整塊中部區域檢測+識別的間隔（秒）。單次約 0.3–0.5s CPU。
    bootstrap_interval_s: float = 3.0
    # 海克斯名稱模糊匹配的最低分（0–100）。
    match_threshold: float = 72.0
    # 模式未知時是否也掃描。
    scan_when_mode_unknown: bool = True
    # 小樣本平滑強度：先驗場次 k。
    smoothing_games: int = 300
    # 懸浮層開關（--headless 也會關閉）。
    overlay: bool = True
    # 懸浮按鈕的位置：top-right / top-left。
    overlay_corner: str = "top-right"
    # 參考資料的分數段：""=全體（預設），casual/mid/high/top=娛樂/中分/高分/頂尖。
    data_band: str = ""
    # 識別頻率（見 SPEEDS）：standard / saver / low。
    speed: str = "standard"
    # 錄屏、截圖時顯示浮窗（直播、做影片用）。預設不顯示：畫面乾淨，也不會識別到自己畫的字。
    allow_capture: bool = False
    # 自動截圖：海克斯三選一和選英雄時自動儲存整屏截圖（含浮窗），存在 <程式資料目錄>/screenshots。
    auto_screenshot: bool = False
    # 查分：自己的「名字#編號」和上次查到的結果（{"as_of", "results", "queried_at"}）
    riot_id: str = ""
    my_rank: dict = field(default_factory=dict)
    # 雲控公告：已經彈過的公告 id
    seen_notice: str = ""
    # 上次執行的版本：變了說明剛更新過，提示一次「已更新到 x」
    last_version: str = ""
    # 第一次開啟時的「請把遊戲設成無邊框」提示，看過就不再彈
    seen_welcome: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or app_home() / "config.json"
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in data.items() if k in known and k != "extra"})
        s.extra = {k: v for k, v in data.items() if k not in known}
        s.fresh_install = not data  # 沒有設定檔案：第一次裝（用來區分「剛安裝」和「剛更新」）
        if not path.exists():
            s.save(path)
        return s

    @property
    def speed_factor(self) -> float:
        return SPEEDS.get(self.speed, SPEEDS["standard"])[1]

    def save(self, path: Path | None = None) -> None:
        path = path or app_home() / "config.json"
        data = asdict(self)
        extra = data.pop("extra", {}) or {}
        data.update(extra)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
