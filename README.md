# AramHex TW

Taiwan-server build of [AramHex](https://github.com/czgreat/aramhex): a Windows companion overlay for League of Legends ARAM Mayhem ("海克斯大亂鬥") that reads the augment choice off the screen and shows a champion build panel.

## Features

- **Augment choice overlay.** When the three augment cards appear, each card gets a label (first pick / viable / consider a reroll) with the augment's rank and win rate on your champion.
- **Build panel.** A panel docked to the top-right or top-left of the game window with eight collapsible sections: ARAM stat adjustments, recommended augments, augment combos, skill priority, starting items, boots, core build, and other completed items. A section with nothing to show displays a "no data" placeholder instead of an empty box.
- **Skill priority** is shown as `Q > E > W` (most-maxed first) with that ordering's pick rate and win rate.
- **Champion select.** During champion select the client window is read (pixels only): ally champions and the bench (up to 10 champions) are annotated in place with a grade (S–D, from the win-rate percentile) and win rate, and the bench is also summarised in the main window and overlay. Your own champion is selected by hand — search by Chinese name, English name, title, or common player nickname. Local statistics appear immediately; the official build and skill order are filled in by a background download.
- **Traditional Chinese UI** and zh-TW champion, augment and item names from a bundled Riot catalog (250 champions, 594 augments, 870 items).
- **Screen reading only.** The app captures pixels; it does not connect to the LCU API, read game memory, inject, or send input.
- Tray icon, single instance, optional start with Windows, and optional automatic screenshots. The overlay is hidden from screenshots and recordings by default so it cannot read its own pixels.

The overlay can only draw on top of the game in borderless or windowed mode.

## Data sources (and the honest gaps)

1. **arammayhem.com (zh-TW)** — per-champion builds: starting items, boots, core build and other completed items with pick and win rates; max skill order with pick and win rate; the champion / augment / item dictionary used for name resolution. Responses are cached on disk (24 h) and the site is rate-limited to one request every 0.6 s.
2. **Tencent public endpoints** (`game.gtimg.cn`, `mlol.qt.qq.com`) — champion list, augment dictionary, per-champion official build and skill leveling, summoner spells.
3. **Bundled statistics snapshot** — self-collected match statistics from [czgreat/aramhex-data](https://github.com/czgreat/aramhex-data) (CC BY-NC 4.0), shipped inside the build. Augment win rates and rankings come from this snapshot, and the UI labels them as a CN-server sample ("國服樣本") with the patch number.
4. **`lolhex/data/bundled/aram_adjust.json`** — per-champion ARAM modifiers (damage dealt/taken, healing, ability haste, and so on), taken from the `aram` sub-table of the League of Legends Wiki `Module:ChampionData/data` under CC BY-SA 3.0. See [NOTICE.md](NOTICE.md).

Gaps, stated plainly:

- arammayhem.com does not publish per-augment win rates, ARAM adjustment values, or augment combinations. Those three come from the sources above, not from the site.
- There is still no augment-combination data source, so the augment combos section always shows its "no combo data" placeholder rather than inventing one.
- Augment and champion statistics are a sample of collected matches, not full-server data. Rows with few games fluctuate; the UI marks low-sample results.
- Site parsing depends on the current HTML. If a fetch or parse fails, the previous cache is used, and without a cache the section stays empty — the app does not fabricate values.
- The statistics are from the CN server. Only names, descriptions and item data are localised to zh-TW.
- Champion recognition reads screen pixels at fixed proportions of the client window, measured on a 1920×1080 client and validated on TW-client captures at 1080p, 2K and 4K. A client layout that differs substantially from the measured one can defeat it.

## Installation

Windows 10/11 x64. No Python installation is required.

**Portable**

1. Download `AramHexTW-Portable-<version>.zip` from the [releases page](https://github.com/PaPaChk/aram-helper/releases).
2. Extract it anywhere and run `AramHexTW.exe`.
3. Config, logs, downloaded data and caches live in the `userdata` folder next to the exe. Nothing is written to `%APPDATA%`. Delete the folder to uninstall.

**Installer**

1. Download `AramHexTW-Setup-<version>.exe`.
2. Run it. It installs per user to `%LOCALAPPDATA%\Programs\AramHexTW`, so no administrator rights are needed, and the wizard is in Traditional Chinese. A desktop shortcut is optional.
3. Config and data go to `%APPDATA%\AramHexTW`.

Both downloads come with `SHA256SUMS.txt`; verify the hash before running. Set `ARAMHEX_HOME` to relocate the data directory.

For the overlay to appear over the game, set the game to borderless or windowed mode. If the capture comes back black, the app tells you to switch away from exclusive fullscreen.

## Auto-update

The build is published under its own repository (`PaPaChk/aram-helper`), so the app checks **its own** GitHub Releases:

1. `GET https://api.github.com/repos/PaPaChk/aram-helper/releases/latest`, skipping drafts and pre-releases, comparing against `lolhex.__version__`.
2. It takes the release's setup installer asset and its SHA-256 from the GitHub asset digest, falling back to `SHA256SUMS.txt`.
3. The installer is downloaded, its SHA-256 verified (a mismatch deletes the file and aborts), then launched silently with `/SILENT /CLOSEAPPLICATIONS /NORESTART`. The app exits so its files are released, and the installer relaunches it.

This is controlled by the **auto update** checkbox in Settings and by the `auto_update` setting, which defaults to `true`. Updates are checked at startup, when the app is reopened, and periodically while it runs.

Deliberate limitations:

- If a game is in progress, or the window is in the tray, the automatic install is skipped rather than interrupting play.
- The portable build cannot replace itself; it opens the download page instead.
- The aramhex.com update channel is intentionally **not** used. It publishes the upstream CN build, and following it would overwrite this TW build. Upstream minimum-version notices are ignored for the same reason.
- Downloads that are too slow (under 150 KB/s after 12 s) are abandoned rather than left hanging.

## Configuration

Settings live in `config.json` inside the data directory (`%APPDATA%\AramHexTW`, `userdata\` in the portable build, or `$ARAMHEX_HOME`). The file is created with defaults on first run and can be edited by hand; unknown keys are preserved. Most values are also editable in the Settings tab.

| Key | Default | Meaning |
|---|---|---|
| `overlay` | `true` | Show the in-game overlay panel |
| `overlay_corner` | `top-right` | `top-right` or `top-left` |
| `show_winrate` | `true` | Show win-rate numbers; off shows only grade and rank |
| `speed` | `standard` | Scan rate: `standard`, `saver`, `low` |
| `auto_update` | `true` | Check, download and install new releases from GitHub |
| `check_data_updates` | `true` | Sync the statistics dataset (SHA-256 verified) |
| `refresh_hours` | `6.0` | Tencent static-data refresh interval (hours) |
| `match_threshold` | `72.0` | Minimum fuzzy-match score (0–100) for augment OCR |
| `data_band` | `""` | Statistics band; empty means all players |
| `scan_interval_ms` | `300` | Card-title scan interval once calibrated |
| `allow_capture` | `false` | Let the overlay appear in screenshots and recordings |
| `auto_screenshot` | `false` | Save full-screen captures on champion select and augment choice |
| `riot_id` | `""` | `Name#Tag` used by the rank lookup |

`aramhex.log` for the current run is written next to `config.json`.

## Building from source

Windows 10/11 x64 with Python 3.13:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python scripts\update_data.py    # refresh the bundled statistics snapshot
pwsh -NoProfile -File packaging\build.ps1
```

`build.ps1` runs PyInstaller (`packaging/lolhex.spec`, onedir, no console), then executes the packaged `AramHexTW.exe --self-test-gui` so that Qt, window hooks and OCR are proven to work before anything is shipped, then compiles `packaging/LolHex.iss` with Inno Setup 6. Inno Setup must be installed (`winget install --id JRSoftware.InnoSetup -e`) or passed via `-InnoCompiler`.

Output in `build/release/`:

- `AramHexTW-Setup-<version>.exe`
- `AramHexTW-Portable-<version>.zip` (the same program directory plus `portable.txt`)
- `SHA256SUMS.txt`

To run from source instead:

```powershell
.venv\Scripts\python -m lolhex
```

Useful flags: `--headless` (recognition without UI), `--refresh` (refresh data and print status), `--scan-image <file>` with optional `--hero <name>` (test augment recognition on a screenshot), `--debug`.

Releases are cut by pushing a `v*` tag; `.github/workflows/release.yml` requires the tag to match `__version__`, refreshes the statistics snapshot, runs the tests, builds both artifacts and creates the GitHub Release.

## Tests

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python -m pytest
```

The test suite runs offline: network access is blocked by fixtures, and Tencent responses and dataset snapshots are local fixtures. OCR tests use real TW-client captures at 1080p, 2K and 4K, plus prismatic, gold and silver augment screens. CI (`.github/workflows/ci.yml`) runs the same suite on Windows with Python 3.13.

## Credits and attribution

- Upstream project: [czgreat/aramhex](https://github.com/czgreat/aramhex) — this build is a Taiwan-server port of it and keeps its MIT license and copyright notice.
- Statistics data: [czgreat/aramhex-data](https://github.com/czgreat/aramhex-data), CC BY-NC 4.0.
- zh-TW champion, augment and item names and icons: Riot CommunityDragon `zh_TW` static data, bundled as `lolhex/data/bundled/tw-catalog.json`.
- Champion builds, skill order and item pick/win rates: [arammayhem.com](https://arammayhem.com).
- ARAM champion adjustments: League of Legends Wiki `Module:ChampionData/data` (`aram` sub-table), CC BY-SA 3.0.
- Hero aliases: Hexdata (hexdata.com.cn); common player nicknames compiled manually.
- Third-party components and their licenses — PySide6 (LGPL-3.0), RapidOCR and its PaddleOCR models (Apache-2.0), ONNX Runtime (MIT), OpenCV (Apache-2.0), NumPy (BSD-3-Clause), Pillow (MIT-CMU), RapidFuzz (MIT), python-mss (MIT), Requests (Apache-2.0), PyInstaller (GPL-2.0 with bootloader exception), Inno Setup, OpenCC (Apache-2.0) — are listed in [NOTICE.md](NOTICE.md).

## License

Source code: MIT, Copyright (c) 2026 czgreat. See [LICENSE](LICENSE).

Statistics data is CC BY-NC 4.0. The ARAM adjustment data and `aram_adjust.json` are CC BY-SA 3.0: if you redistribute or adapt that data, the derived work must carry the same license. The rest of the project is unaffected by that share-alike term. Full terms are in [NOTICE.md](NOTICE.md).

This is an unofficial tool. It is not affiliated with Riot Games or Tencent.
