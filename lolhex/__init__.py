"""AramHex 海克斯大亂鬥助手：螢幕識別 + 自採統計資料 + 騰訊官方資料。"""

__version__ = "1.0.0+tw.9"
APP_NAME = "AramHex 臺服版"
# 自己維護的台服版：更新來源指向本倉庫的 Releases。
APP_UPDATES_ENABLED = True
# 上游（國服）雲控的 min_version 是國服版本號（1.1.0），拿來和 1.0.0+tw.x 比會誤判成
# 太舊，並把使用者引導去下載國服版。台服版一律不採用上游的版本門檻。
UPSTREAM_MIN_VERSION_ENABLED = False
UPSTREAM_REPO = "czgreat/aramhex"

GITHUB_REPO = "PaPaChk/aram-helper"
DATA_REPO = "czgreat/aramhex-data"
# 統計資料仍取自上游資料倉儲（國服樣本），資料鏡像繼續用 aramhex.com。
WEBSITE = "https://aramhex.com"
HELP_PAGE = f"{WEBSITE}/#faq"
MIRROR = f"{WEBSITE}/u"
HOMEPAGE = f"https://github.com/{GITHUB_REPO}"
RELEASES_PAGE = f"{HOMEPAGE}/releases"
# 程式更新與下載一律走本倉庫，絕不連回上游的網盤或官網下載區。
DOWNLOAD_PAGE = RELEASES_PAGE
DATA_HOMEPAGE = f"https://github.com/{DATA_REPO}"
