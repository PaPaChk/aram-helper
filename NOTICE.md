# 第三方组件与数据

安装包和便携版里带了下面这些组件，各自遵循自己的协议：

| 组件 | 用途 | 协议 |
|---|---|---|
| [Qt for Python (PySide6)](https://www.qt.io/qt-for-python) | 界面 | LGPL-3.0（以独立的动态库形式随程序分发，可自行替换） |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) 及其 PaddleOCR 模型 | 文字识别 | Apache-2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | 运行识别模型 | MIT |
| [OpenCV](https://opencv.org/) | 图像处理 | Apache-2.0 |
| [NumPy](https://numpy.org/) | 计算 | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | 图像处理 | MIT-CMU |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | 名称模糊匹配 | MIT |
| [python-mss](https://github.com/BoboTiG/python-mss) | 截屏 | MIT |
| [Requests](https://requests.readthedocs.io/) | 网络请求 | Apache-2.0 |
| [PyInstaller](https://pyinstaller.org/) | 打包 | GPL-2.0（带 bootloader 例外，不影响本程序的协议） |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | 安装程序 | Inno Setup License |

数据：
- `lolhex/data/bundled/`：自采统计数据，来自 [czgreat/aramhex-data](https://github.com/czgreat/aramhex-data)，协议为 CC BY-NC 4.0。
- `lolhex/data/hero_aliases.json`：英雄别名，整理自 Hexdata（hexdata.com.cn）。
- `lolhex/data/hero_nicknames.json`：网上常见的英雄外号，人工整理。
- 运行时从腾讯官方公开接口（game.gtimg.cn、mlol.qt.qq.com）获取英雄、海克斯、装备资料以及官方出装和加点，从 CommunityDragon 补全个别海克斯的中文名。这些数据不随程序分发，版权归原权利人所有。
