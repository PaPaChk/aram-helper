# 開發與發版

## 目錄

```
lolhex/
  __main__.py          入口（python -m lolhex）
  engine.py            排程：視窗狀態、選人識別、三選一識別、推薦
  config.py            配置檔案和目錄（安裝版 %APPDATA%\AramHexTW，便攜版 程式目錄\userdata）
  update.py            程式更新：查 GitHub Releases 有沒有新版本（連不上時查 jsDelivr）
  patch.py             增量更新：只下載變了的檔案（updates 分支，GitHub / jsDelivr），退出後替換，失敗還原
  recommend.py         三選一評分
  panel.py             單英雄面板（勝率、出裝、加點、海克斯表）
  data/
    store.py           騰訊官方資料（執行時獲取，落盤快取）
    public.py          自採統計資料：內建 + 從資料倉儲下載更新，逐檔案校驗 SHA-256；分數段切換
    tencent.py         騰訊介面和解析
    bundled/           內建統計資料（scripts/update_data.py 生成，不要手改）
  vision/              截圖、選人介面識別、三選一識別、OCR
  ui/                  主視窗、托盤、遊戲內浮窗
scripts/update_data.py 把資料倉儲最新的一份放進 lolhex/data/bundled/
packaging/             PyInstaller、Inno Setup、打包指令碼
```

## 原則

- **不接入客戶端（LCU）、不讀記憶體、不注入、不模擬按鍵或滑鼠**。只截圖識別、顯示資料。
  - 浮窗點完以後把前臺還給遊戲，只呼叫 `SetForegroundWindow`，不發任何輸入。
  - 遊戲內 2999 介面是 Riot 官方的只讀介面，預設關閉。
- 統計資料只用資料倉儲的公開格式，見 `lolhex/data/public.py` 頂部說明。改格式要升 `schema_version`，並且兩個倉庫一起改。
- 網路失敗不能影響使用：官方資料用上次的快取，統計資料用內建的那份，檢查更新失敗時不打擾使用者。

## 測試

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python -m pytest
```

測試不聯網（`conftest.py` 的 `no_network`）。需要 HTTP 的測試在本機起臨時服務。

## 打包

需要 Inno Setup 6（`winget install --id JRSoftware.InnoSetup -e`）：

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-build.txt
.venv\Scripts\python scripts\update_data.py          # 更新內建資料
pwsh -NoProfile -File packaging\build.ps1
```

輸出在 `build/release/`：
- `AramHex-Setup-<版本>.exe`
- `AramHex-Portable-<版本>.zip`
- `SHA256SUMS.txt`

打包時會先校驗內建資料，再用真實的 Windows 視窗外掛跑一遍 Qt 自檢，自檢不過不生成安裝包。

## 發版

1. 更新內建資料：`python scripts/update_data.py`，然後提交。
2. 改 `lolhex/__init__.py` 的 `__version__`，在 `CHANGELOG.md` 寫這一版的說明。
   - 說明是寫給玩家看的（釋出頁和軟體裡的「有新版本」提示都顯示它）：一兩句大白話，只寫更新了什麼、修了什麼問題，比如「更新時能看到下載進度了」「修復：……」。不寫技術細節、檔名、數字口徑。
3. 提交，然後打 tag 並推送：`git tag v1.2.3 && git push origin v1.2.3`。
4. GitHub Actions（`.github/workflows/release.yml`）自動完成：
   - 跑測試、打包；
   - 核對 tag 和 `__version__` 一致；
   - 把增量更新的清單和檔案（另有 .gz 壓縮版，jsDelivr 不給下 .exe）推到 `updates` 分支，並打 tag `updates-v<版本>`（先於建 Release）；
   - 建 Release，上傳安裝版、便攜版和 `SHA256SUMS.txt`；
   - Release 說明取 `CHANGELOG.md` 裡這一版的內容。
5. 已安裝的助手啟動時、再次開啟時、每 30 分鐘查一次 Releases 的 latest，有新版本就提示。

只更新統計資料、不改程式時，不用發版：資料倉儲更新後，助手會自己下載新資料。
定期發版只是為了讓新下載的使用者拿到較新的內建資料。

## 國內連不上 GitHub 時

- jsDelivr 按分支名（`@main`、`@updates`）取檔案會快取好幾個小時，重新整理也不一定生效；按 tag 取是即時的。所以：
  - 程式：發版打 tag `updates-v<版本>`；助手按"下一個版本號"（補丁、次版本、主版本各加 1）試探這個 tag 是否存在，找到後從 tag 下載增量更新。
  - 統計資料：資料倉儲每次更新打 tag `data-v<序號>`（`latest.json` 的 `seq`）；助手按"下一個序號"試探。
- jsDelivr 單個檔案不能超過 20MB，整個分支或 tag 不能超過 150MB；`.exe` 檔案會被拒絕（403），所以增量更新檔案都另存一份 `.gz`。
- 完整安裝包（86MB）放不進 jsDelivr，只能從 GitHub 下載，或者手動下載。
