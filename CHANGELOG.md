# Changelog

## 1.0.0+tw.7

### Fixed

- **The app no longer claims it is out of date.** `1.0.0+tw.6` re-enabled the
  upstream `min_version` check, so a fresh install greeted you with
  "需要更新 / 當前版本 1.0.0+tw.6 太舊" on startup even though nothing was wrong.
  The Taiwan build no longer adopts the upstream (mainland) version threshold,
  which compares against a different version number and always looked newer.
- **Update and download links no longer send you to the mainland/CN build.**
  Every update prompt, the "download" button and the setting that opens the
  release page now point at this repository's Releases
  (`PaPaChk/aram-helper/releases`), not at `aramhex.com`. Installing the CN
  build over this one would replace it with a version that cannot read your
  Taiwan data.

## 1.0.0+tw.6

### Added

- **Automatic updates.** The app now checks its own GitHub Releases and, when a
  newer version exists, downloads it, verifies the SHA-256, installs it silently
  and relaunches. Controlled by the "automatically update the app" checkbox in
  settings and the `auto_update` setting (on by default). It never updates while
  you are in a match, and never while the main window is hidden in the tray.
- **arammayhem.com/zh-tw as the primary build-data source.** Per-champion builds,
  skill order and item pick/win rates now come from the website, which covers
  champions the Tencent statistics never had data for. Tencent plus the bundled
  snapshot remain the fallback, and still supply the three things the website
  does not publish: per-augment win rates, ARAM stat adjustments, and augment
  combinations.
- `lolhex/data/arammayhem.py`: cached client for that site (24-hour refresh).

### Fixed

- **Augment catalog was incomplete.** The bundled `tw-catalog.json` held 450 of
  594 augments, so cards like `血色鈷石` (id 3088) were silently unmatched.
  Rebuilt from CommunityDragon (594 augments, none dropped) and the official
  zh-TW name is now accepted as an alias on top of the existing ones.
- **ARAM adjustment arrows pointed the wrong way.** Percentage fields are
  multipliers around 1.0, not deltas from 0, so `↓ 治療效果 -10%` used to render
  as `↑`.
- **Percentages were shown 100× too large** (`5675.0%`), and pick rate was
  rendered as a fabricated `出場 100.0%`.
- Overlay section bodies were clipped to a single line; each now sizes to its
  content.
- All eight overlay sections default to expanded, and empty ones show `暫無資料`
  instead of rendering blank.

### Changed

- Update source, installer publisher and links now point at
  `PaPaChk/aram-helper`. The `aramhex.com` update channel is deliberately
  bypassed: it publishes the upstream CN build, which would overwrite this TW
  build.
- Fixed the setup-asset regex, which only matched `AramHex-Setup-*` and so could
  never match the `AramHexTW-Setup-1.0.0+tw.5.exe` this project actually builds.

## 1.0.0+tw.5

- 修正台服版誤把國服最低版本提示當成自身更新，啟動時不再跳出錯誤的「需要更新」警告。
- 更新內建統計資料。

## 1.0.0+tw.4

- 英雄改為手動搜尋選取，不再掃描選人畫面或下載整批英雄頭像，啟動明顯加快。
- 手動選英雄後先立即顯示本地勝率；出裝與加點改在背景下載，不再阻塞介面。
- 首次啟動即可用內建台服英雄名稱搜尋，不必等待騰訊靜態資料。

## 1.0.0+tw.3

- 修正 Windows 深色模式下，狀態與英雄卡片變成白底白字、內容看不清楚的問題。

## 1.0.0+tw.2

- 海克斯三選一改用動態 OCR 校準，不再依賴固定卡牌位置；不同解析度與 UI 縮放都能重新偵測。
- 已用台服實機 4K、2K、1080p 及金色、銀色三選一畫面驗證。
- 補齊台服海克斯名稱後備，騰訊資料暫時缺項時仍能正確識別。

## 1.0.0

- 第一個正式版本。
- 選英雄時自動識別你和隊友的英雄，顯示勝率和評級。
- 海克斯三選一時，給出這個英雄拿每個海克斯的勝率和排名，推薦選哪個。
- 顯示官方出裝（多套）和加點。
- 可以切換娛樂、中分、高分、頂尖局的資料。
- 設定裡可以查自己的水平（區內前百分之幾），自動選對應分段。
