# AramHex 台服版

以 [czgreat/aramhex](https://github.com/czgreat/aramhex) 為基礎移植的英雄聯盟「海克斯大亂鬥」桌面助手。

台服版保留上游的國服自採勝率，介面與卡片名稱改用繁體中文及台服官方譯名。勝率資料會明確標示為「國服樣本」；英雄、增幅與裝備名稱由 Riot 台服靜態資料覆寫。

## 已完成

- 台服英雄、增幅、裝備名稱與描述。
- 繁體中文 UI、錯誤訊息與設定頁。
- 保留國服、台服、英文名稱及玩家別名搜尋。
- OCR 以台服三選一卡片名稱建立匹配字典。
- 台服版使用獨立資料目錄 `%APPDATA%\AramHexTW`。
- 停用會覆蓋台服版的上游程式自動更新。
- 保留國服勝率統計與分段，來源標示為「國服樣本」。

## 從原始碼執行

Windows 10/11 64 位、Python 3.13：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m lolhex
.venv\Scripts\python -m pytest
```

## 台服靜態資料

`lolhex/data/bundled/tw-catalog.json` 由專案根目錄的 `data/generated/catalog.json` 匯入，包含：

- 250 位英雄
- 450 個海克斯增幅
- 870 件裝備
- 台服 zh-TW 名稱、描述與圖示路徑

重新產生資料後，將新 catalog 複製到上述位置即可。

## 資料來源與限制

- 勝率：上游 `aramhex-data` 的國服自採樣本（CC BY-NC 4.0）。
- 靜態名稱：Riot CommunityDragon 台服資料。
- 機制與聯動結論：本工作區的 ARAM Helper 資料庫，只採集指定 Bilibili 創作者的實測內容。

OCR 卡牌位置仍使用上游校準值。台服文字已納入匹配；若實際用戶端布局不同，需用台服三選一截圖重新校正位置。

## 授權

程式碼沿用上游 MIT 授權，統計資料為 CC BY-NC 4.0。詳見 [LICENSE](LICENSE) 與 [NOTICE.md](NOTICE.md)。

本專案為非官方工具，與 Riot Games、騰訊無關。
