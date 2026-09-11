# 萝卜弹幕吃吃吃

<p align="center">
  <img src="cake.svg" width="112" alt="萝卜弹幕吃吃吃图标">
</p>

一个使用 Python、PyQt5 与 [blivedm](https://github.com/xfgryujk/blivedm) 开发的 B 站直播互动投喂小游戏。观众可以通过弹幕和礼物增减食物，主播则能在透明游戏区域中拖动食物、移动食用者以及使用圆形范围拾取。

> 本项目是非官方开源项目，与哔哩哔哩没有隶属或合作关系。

## 下载 Windows 版

不想配置 Python 环境时，可以前往 [GitHub Releases](https://github.com/luoboovo/radish-danmaku-eat/releases/latest) 下载：

- `*-setup.exe`：带中文安装向导、开始菜单快捷方式和卸载程序的安装版（推荐）。
- `*-windows.exe`：无需安装的单文件便携版。
- `*.sha256.txt`：对应安装包的 SHA-256 校验文件。

## 功能特色

- 白色极简直播控制台与纯透明置顶游戏窗口相互独立。
- 手动圈选游戏区域，可在浏览器、游戏或其他窗口前运行。
- 支持 PNG、JPG、WebP、BMP、SVG 和 GIF 食物/食用者贴图。
- 没有设置食物贴图时，默认使用内置胡萝卜。
- 食物支持自然下落、随机旋转、稳定堆积以及中间取走后向下补位。
- 食物从区域底部横向铺开并逐层向上自然堆积，数量足够时可堆满整个区域。
- 单个拖拽与圆形范围拾取；单次范围抓取上限默认 100，可在控制台修改。
- 食用者可以自由移动，食物、食用者和范围尺寸会自动适配显示器缩放。
- 可配置弹幕关键词，以及礼物增加、减少、乘以、除以食物数量的规则。
- 礼物可以限时开启圆形范围拾取，断线后自动重连。
- 独立透明文字展示框显示“已吃 / 剩余”，支持拖动和滚轮缩放。
- 直播互动日志只记录观众弹幕和礼物，不记录主播手动操作。
- 内置增加、减少、吃掉和礼物四种音效，也可分别上传、恢复默认和试听。
- 游戏运行期间可更换贴图、音效、排列模式及直播规则，点击“保存并应用”即可生效。

## 运行环境

- Windows 10/11
- Python 3.10 或 3.11
- PyQt5 5.15

## 安装与启动

```powershell
git clone https://github.com/luoboovo/radish-danmaku-eat.git
cd radish-danmaku-eat

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

项目在 `vendor/` 中包含从 blivedm 官方源码构建的 1.1.7 wheel，因此安装依赖时不需要本机 Git，也不会安装到同名的非官方 PyPI 包。

## 快速使用

1. 启动程序，先把直播间房间号留空进行离线测试。
2. 在“显示设置”中添加食物和食用者贴图，并设置尺寸、排列方式和圆形拾取规则。
3. 点击右上角“保存并圈选区域”，按住鼠标左键拖出游戏范围。
4. 在控制台使用 `+N`、`-N` 和“范围拾取”测试游戏。
5. 填写直播间房间号，在“直播互动”中配置弹幕与礼物规则。
6. 游戏运行中修改设置后，点击“保存并应用”即可即时更新。

普通模式下按住一个食物拖动，松手后食物会从当前位置自然下落。直接拖到食用者范围内，或从食用者上方让食物落下，都会完成投喂。

范围模式下可以按住食物抓取设定半径内的多个食物，也可以从透明空白处拖动，画出一个可视化圆形范围。命中数量超过设置上限时，会优先抓取离圆心最近的食物。

## 直播间连接

只填写直播间网址末尾的数字房间号，例如：

```text
https://live.bilibili.com/123456
                              └─ 房间号：123456
```

连接成功后，控制台顶部会显示连接状态。弹幕规则支持整句匹配和包含匹配；礼物名称需要与直播间显示名称一致。

### SESSDATA 是否必需

SESSDATA 不是必需项。留空仍然可以监听弹幕和礼物，但用户名可能脱敏，UID 也可能显示为 0。

如果需要未脱敏身份：

1. 在浏览器登录 B 站。
2. 按 `F12` 打开开发者工具。
3. 进入“应用（Application）→ Cookies → `https://www.bilibili.com`”。
4. 找到 `SESSDATA` 并复制它的值到控制台。

> SESSDATA 等同于登录凭据。不要截图、分享或提交包含它的 `config.json`。本仓库已通过 `.gitignore` 排除真实配置文件。

## 配置文件

程序首次保存时会在程序或 EXE 同目录生成 `config.json`。仓库中的 [`config.example.json`](config.example.json) 是不含账号凭据的配置示例。

主要配置包括：

- 食物与食用者贴图路径
- 初始数量、手动加减步长与显示尺寸
- 全宽重力分层堆积
- 弹幕关键词和加减数量
- 礼物加、减、乘、除规则
- 礼物范围拾取规则与持续时间
- 自定义音效路径
- 展示框位置、比例和可见状态

## OBS 采集

推荐使用 OBS 的“显示器采集”，透明游戏层可以覆盖在任意桌面窗口上，透明区域仍能点击后方程序。

如果必须使用“窗口采集”，请选择 `萝卜弹幕吃吃吃 [透明游戏区域]`，使用 Windows Graphics Capture 并启用透明度。部分 OBS 或显卡组合会把透明窗口显示为黑色，此时请改用“显示器采集”。不要最小化透明游戏窗口；被 Windows 最小化的窗口无法继续被采集。

## 项目结构

```text
radish-danmaku-eat/
├─ main.py                    # 程序入口与窗口/监听协调
├─ feeding_game/
│  ├─ bili_listener.py        # blivedm 弹幕和礼物监听
│  ├─ config.py               # JSON 配置、默认值与兼容处理
│  ├─ game_window.py          # 透明游戏层与拖拽/下落逻辑
│  ├─ media.py                # 静态图片和 GIF 加载
│  ├─ region_selector.py      # 桌面游戏区域圈选
│  ├─ settings_window.py      # 白色直播控制台
│  └─ sound.py                # 内置及自定义音效播放
├─ vendor/                    # blivedm 官方 wheel
├─ installer/
│  ├─ ChineseSimplified.isl   # 安装向导简体中文翻译
│  └─ ChineseSimplified.LICENSE.txt
├─ config.example.json        # 脱敏配置示例
├─ installer.iss              # Inno Setup 安装版构建脚本
├─ requirements.txt
├─ cake.svg / cake.ico        # 应用图标
└─ LICENSE
```

## 从源码打包 EXE

```powershell
pip install pyinstaller

pyinstaller --noconfirm --onefile --windowed `
  --name "萝卜弹幕吃吃吃" `
  --icon "cake.ico" `
  --add-data "cake.svg;." `
  --collect-all blivedm `
  main.py
```

生成结果位于 `dist/`。该目录默认不会提交到 Git 仓库，建议通过 GitHub Releases 分发打包版本。

## 构建 Windows 安装版

先按上一节生成便携版，并将文件命名为 `radish-danmaku-eat-v版本号-windows.exe`。安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php) 后执行：

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" `
  /DAppVersion=1.4.0 installer.iss
```

安装包输出到 `dist/radish-danmaku-eat-v1.4.0-setup.exe`。安装版采用当前用户安装方式，不要求管理员权限；个人配置会保存在安装目录中，卸载时默认保留。

## 参与贡献

欢迎提交 Issue 和 Pull Request。提交前请确认：

- 不包含自己的 `config.json`、SESSDATA、Cookie 或直播账号信息。
- Python 文件可通过 `python -m py_compile` 编译检查。
- 新增功能不破坏透明窗口、GIF 和高 DPI 显示。

## 开源许可

本项目使用 [MIT License](LICENSE) 开源。第三方依赖仍遵循各自的许可证；blivedm 同样采用 MIT License。
