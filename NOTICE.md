# 第三方元件與資料

安裝包和便攜版裡帶了下面這些元件，各自遵循自己的協議：

| 元件 | 用途 | 協議 |
|---|---|---|
| [Qt for Python (PySide6)](https://www.qt.io/qt-for-python) | 介面 | LGPL-3.0（以獨立的動態庫形式隨程式分發，可自行替換） |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) 及其 PaddleOCR 模型 | 文字識別 | Apache-2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | 執行識別模型 | MIT |
| [OpenCV](https://opencv.org/) | 影象處理 | Apache-2.0 |
| [NumPy](https://numpy.org/) | 計算 | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | 影象處理 | MIT-CMU |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | 名稱模糊匹配 | MIT |
| [python-mss](https://github.com/BoboTiG/python-mss) | 截圖 | MIT |
| [Requests](https://requests.readthedocs.io/) | 網路請求 | Apache-2.0 |
| [PyInstaller](https://pyinstaller.org/) | 打包 | GPL-2.0（帶 bootloader 例外，不影響本程式的協議） |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | 安裝程式 | Inno Setup License |
| [OpenCC](https://github.com/BYVoid/OpenCC) | 簡繁轉換 | Apache-2.0 |

資料：
- `lolhex/data/bundled/`：自採統計資料，來自 [czgreat/aramhex-data](https://github.com/czgreat/aramhex-data)，協議為 CC BY-NC 4.0。此資料樣本來自國服，介面標示為「國服樣本」。
- `lolhex/data/bundled/tw-catalog.json`：台服英雄、增幅與裝備名稱，來自 Riot CommunityDragon zh_TW 靜態資料，隨台服版分發。
- `lolhex/data/hero_aliases.json`：英雄別名，整理自 Hexdata（hexdata.com.cn）。
- `lolhex/data/hero_nicknames.json`：網上常見的英雄外號，人工整理。
- 執行時從騰訊官方公開介面（game.gtimg.cn、mlol.qt.qq.com）獲取官方出裝、加點與勝率所需靜態資料。國服名稱會保留為搜尋別名，顯示名稱由 tw-catalog.json 覆寫為台服譯名。
- 統計勝率與官方靜態資料的版權歸原權利人所有；本專案不宣稱與 Riot Games 或騰訊有官方關係。

## ARAM 英雄調整（CC BY-SA 3.0）

`lolhex/data/bundled/aram_adjust.json`（ARAM 專屬的英雄增減益數值，例如「造成傷害 +5%」「承受傷害 -10%」「技能急速 +10」）並非本專案原創，來源如下：

- 來源：[League of Legends Wiki](https://wiki.leagueoflegends.com/en-us/Module:ChampionData/data)，頁面 `Module:ChampionData/data` 中的 `["aram"]` 子表。
- 擷取網址：<https://wiki.leagueoflegends.com/en-us/api.php?action=parse&page=Module%3AChampionData%2Fdata&prop=wikitext&format=json&formatversion=2>
- 授權：[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)（姓名標示—相同方式分享）。
- 產生方式：`.cache/build_aram.py`（僅重新排列與篩選欄位，未修改數值）。

**授權範圍差異：** 這份 ARAM 調整資料及其衍生的 `aram_adjust.json` 採用 CC BY-SA 3.0，屬於「相同方式分享」——若轉載或改作這份資料，衍生作品必須以相同授權釋出。本專案其餘程式碼與其他資料不受此條款影響，仍依各自原本的授權釋出。CC BY-SA 3.0 與本專案其他部分的授權彼此獨立，互不擴散。
