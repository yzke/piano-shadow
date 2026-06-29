# Piano Shadow

Piano Shadow 是一个本地运行的桌面钢琴音符悬浮窗。它捕获系统正在播放的声音，
使用 Spotify Basic Pitch 转录钢琴音符，再把近期音符显示在透明 88 键键盘上。
它面向听音与键位联想，不是专业扒谱工具；不上传音频，也不调用云 API。

## 界面预览

监听与音符识别：

![Piano Shadow 监听与音符识别](docs/screenshots/listening-overlay.png)

纯键盘透明悬浮模式：

![Piano Shadow 纯键盘模式](docs/screenshots/keyboard-only.png)

键盘与彩色高亮独立透明度：

![Piano Shadow 透明度调节](docs/screenshots/transparency-controls.png)

## 环境与安装

要求 Python 3.10+。建议使用独立虚拟环境：

```bash
cd piano_shadow
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
```

Basic Pitch 会安装 TensorFlow/ONNX 等较大的依赖，首次安装和首次推理可能较慢。
如果只想查看界面，可以只安装轻量依赖：

```bash
pip install -r requirements-demo.txt
python main.py --demo-mode
```

## 启动

```bash
python main.py --demo-mode
python main.py --demo-midi "60,64,67;62,65,69;59,63,67"
python main.py
python main.py --model piano-gpu
python main.py --model basic-pitch
python main.py --chunk 0.5 --decay 1.4 --min-amp 0.008 --width 900 --height 190
```

左键拖动窗口可移动；右键菜单可分别调节键盘和彩色高亮透明度及窗口大小，并切换识别模型、位置
锁定、置顶和参数面板。所有操作均通过 UI 完成，不启用键盘快捷键。
鼠标穿透无需单独设置：锁定时自动穿透，解锁时恢复交互；锁定后可从通知区域解锁。

右上角常驻按钮从左到右为：演奏模式、纯键盘模式、识别模型、锁定/解锁、确保置顶、缩小、
放大、键盘透明度、彩色高亮透明度。
模型芯片未点亮表示 Basic Pitch，蓝色点亮表示 Piano GPU。未锁定时可直接
拖动窗口，无需单独的移动按钮。键盘透明度提供 0%–100% 档位，控制毛玻璃和未按下
黑白键；彩色高亮透明度提供 30%–100% 档位，独立控制按下的七彩琴键、光晕、
动态音名/唱名和顶部彩色唱名。右键菜单提供两个独立滑杆。窗口拖动优先使用桌面系统原生移动协议，
以改善 WSL/Wayland 下无边框窗口的拖动兼容性。
动态音名与唱名使用同一音级颜色、亮度和透明度，并与激活琴键统一跟随彩色高亮设置。
默认窗口高度为 190px，
为动态音名与顶部控制区保留更充足的垂直间距。

模型芯片左侧使用对应琴键颜色显示固定唱名 `Do Re Mi Fa Sol La Si`，便于快速
建立颜色与音级的对应关系。

顶部的四角聚焦图标可进入“纯键盘模式”：自动锁定位置，隐藏毛玻璃背景、状态、
参数和其他控制按钮，只保留彩色唱名图例、键盘、动态音名/唱名及锁图标。点击唯一的锁
图标会退出该模式并恢复拖动；右键菜单也提供相同开关。

Windows 原生运行时置顶图标可直接开启或关闭置顶，并通过 Win32 API 切换，不会重建
窗口或改变双屏坐标。WSL/Wayland 下按钮保持为“确保置顶”，需要取消时使用右键菜单。
Windows 只在开启置顶时进入系统 TOPMOST 层，不再通过定时器反复抢占层级：普通应用
不会盖住悬浮窗，而任务栏、截图工具等后创建的系统置顶界面可以临时显示在其上方。
置顶与鼠标穿透彼此独立；所有设置和退出操作可从通知区域的 Piano Shadow 托盘图标
完成。双击托盘图标可显示或隐藏悬浮窗；托盘菜单可恢复默认设置。

程序会记忆窗口位置、大小、两类透明度、模型、置顶、锁定、纯键盘模式和参数面板
状态，下次启动自动恢复。若显示器布局发生变化，超出当前屏幕的旧位置不会恢复。

## 演奏模式

主界面的钢琴图标、右键菜单或托盘菜单可开启演奏功能，再次点击即可关闭。开启后不会
切换或重绘成另一套界面：原状态栏、设置、彩色唱名和控制按钮全部保留，并额外显示
键盘/MIDI 输入切换和演奏说明按钮。说明默认关闭，当前调号以对应音级颜色显示在
状态栏下方。

电脑键盘默认映射：

- `F1–F12`：C2–G3（前 7 键为一组音阶，后 5 键顺延高八度）
- `1–=`：C3–G4（`8、9、0、-、=` 顺延高八度）
- `Q–]`：C4–G5
- `A–'`：C5–F6
- `Z–/`：C6–E7
- `→`：沿五度圈顺时针进入下一个调；`←`：沿五度圈逆时针返回上一个调。
  相对大小调成对排列：`C大/A小 → G大/E小 → D大/B小 → … → F大/D小`，
  共覆盖 12 个大调和 12 个小调。界面直接显示当前调名。
- `↓`：升高八度；`↑`：降低八度
- `Shift`：临时升半音；`Ctrl`：临时降半音
- 按住 `Space`：延音；按住 `Enter`：休止并阻止新音符

每次进入演奏模式恢复 C 大调、默认八度、键盘输入和关闭延音。演奏期间暂停音频识别，
退出后自动恢复。Windows 默认通过系统 WinMM General MIDI 的 Acoustic Grand Piano
发声，不增加运行依赖。

物理 MIDI 输入使用 `python-rtmidi`，自动连接第一个设备，支持力度和 CC64 延音踏板。

演奏模式开启后，输入方式、说明和听音练习按钮独立显示在主功能区的下一排。听音练习
默认关闭，连续点击按钮依次切换 `1 音、3 音、5 音、7 音、关闭`。每题先播放一组音，
再等待使用电脑键盘或 MIDI 按原顺序复现；全部正确后自动进入下一题，答错则重播当前题。
题目跟随当前大小调：单音覆盖不同音级和音区，三音使用常见调内三和弦及转位，五音使用
大小调五声音阶材料，七音使用完整调式片段；音域、起始级数、方向和转位均带随机变化。
作答正确后，键盘上方会短暂显示整组音名与唱名；答错时会标出出错序号、
实际按下的音和正确音。正确答案沿用对应琴键的音级颜色及彩色高亮透明度，错误音使用
红色提示。

按钮图形由程序直接绘制为高 DPI 矢量图标，不依赖外部图片或图标字体。透明度也在
程序绘制层完成，因此 WSLg/Wayland 不支持窗口级透明度时仍然有效。

音符使用固定的 12 音级配色：同一音级跨八度保持同一基础色相，例如 C2、C4、C7
均使用柔玫瑰色。升音使用相邻的独立色相；音名、琴键和残影共享同一配色。

同一基础色还带有克制的音区明度偏移：C4 附近保持中性，低音区逐渐昏暗，高音区
逐渐清亮，钢琴全音域的最大明度偏移约为 ±10%，仍不会破坏音名的色彩识别。

音名的水平中心与对应琴键中心对齐；半音密集时自动分层避让，并使用低透明度
引导线连接琴键，便于直接建立“听到的音名—键盘位置”关联。
每个音名下方还显示固定唱名（Do、Re、Mi、Fa、Sol、La、Si）；升音唱名带 `♯`，
并与音名共享颜色和琴键锚点。
动态音名与唱名只显示彩色动态字，不绘制常驻灰色底字。自然音采用柔玫瑰、杏橙、
香槟金、薄荷绿、冰青、长春花蓝、兰花紫的近彩虹顺序；颜色针对液态玻璃界面降低
纯色感并统一亮度，升音使用相邻自然音之间的过渡色。
弹奏高亮使用 Screen 混合的中心光晕、键盘上方柔光柱、彩色边缘和顶部高光，静态
键盘本身不额外增亮。
中心光晕在黑白键全部绘制完成后统一叠加，避免黑键遮住相邻白键的荧光。黑白键
保持各自音级的色相与饱和度，只交换感知亮度关系：白键更亮，黑键更深。

每个分析块会按 Basic Pitch 给出的起音时间顺序显示：60ms 内的音符合并为和弦同时
点亮，其余音符按原始间隔依次出现。单块时序回放最多增加 0.65 秒延迟。

## Linux / PipeWire / PulseAudio

程序通过 `soundcard` 寻找默认输出设备对应的 monitor source。PipeWire 用户通常需要
`pipewire-pulse` 兼容层。先确认 monitor 存在：

```bash
pactl get-default-sink
pactl list short sources
```

输出列表中应出现类似 `alsa_output....monitor`。没有时请在 `pavucontrol` 的“录音”
页面为 Python 选择 “Monitor of ...”，并确认播放器正在输出声音。Wayland 合成器对
“全局置顶”和点击穿透的策略不同；X11 下兼容性通常更一致。

WSLg/Wayland 若输出 `This plugin does not support raise()`，说明当前合成器不允许
应用强制置顶。可优先尝试 WSLg 的 X11 后端：

```bash
QT_QPA_PLATFORM=xcb python main.py --demo-mode
```

如果系统缺少 xcb 运行库，或双屏坐标仍由 WSLg 重排，使用 Windows Python 直接启动
项目可获得最稳定的置顶和跨屏定位。

## Windows

程序使用 `soundcard` 的 WASAPI loopback，从默认扬声器捕获。请确保默认播放设备
有效，且应用与播放器运行在同一用户会话。某些蓝牙免提设备或独占模式播放器不提供
loopback；切回普通扬声器、关闭独占模式后重试。

GitHub Release 提供正式安装包 `PianoShadow-Setup-vX.Y.Z-Windows-x64.exe`，无需安装
Python。安装位置与可写数据分离：

- 程序：`%LOCALAPPDATA%\Programs\PianoShadow`
- GPU 模型：`%LOCALAPPDATA%\PianoShadow\models`
- 日志：`%LOCALAPPDATA%\PianoShadow\logs`

安装和升级时均可选择程序目录，也可选择桌面快捷方式和登录后自动启动。
升级或卸载程序默认保留已下载模型，
重新安装不需要再次下载。旧版本位于
`%USERPROFILE%\piano_transcription_inference_data` 的模型会在首次启动时自动迁移。

由于 CUDA PyTorch 运行时本身超过 4GB，标准安装包内置 Basic Pitch ONNX CPU，
不重复打包 GPU 运行时和模型。需要 Piano GPU 时执行下方 `setup-windows.ps1 -Gpu`
安装本机 CUDA 环境；安装版会自动检测并通过本地桥接进程调用。

推荐直接在 Windows PowerShell 中运行，这也能避开 WSLg 的置顶和双屏定位限制。
在项目目录打开 PowerShell，首次执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup-windows.ps1
```

脚本会自动寻找 Python 3.10/3.11，并把虚拟环境安装到
`%LOCALAPPDATA%\PianoShadow\venv`，不会写死用户名或项目路径。之后运行：

```powershell
.\run-windows.ps1 -Demo
.\run-windows.ps1
.\run-windows.ps1 --chunk 3.0 --min-amp 0.01
```

只安装界面依赖可使用 `.\setup-windows.ps1 -DemoOnly`；切换到真实识别时再执行一次
不带 `-DemoOnly` 的安装命令。

维护者可使用以下命令构建安装包，产物位于 `dist`：

```powershell
.\build-installer.ps1 -Version <版本号>
```

构建机需要 Inno Setup 6；最终用户不需要安装 Python、PyQt6 或 Inno Setup。

诊断 WASAPI loopback、录制 2.5 秒并自检 Basic Pitch：

```powershell
& "$env:LOCALAPPDATA\PianoShadow\venv\Scripts\python.exe" `
  .\audio_diagnostics.py --record 2.5 --model
```

运行录制诊断时请让播放器持续播放声音；输出会显示捕获波形的 RMS 和峰值。

### 手动选择识别模型

右键窗口打开“识别模型”菜单，可在运行时切换：

- `Basic Pitch · 快速通用`：CPU/ONNX，延迟低，适用于一般音频。
- `Piano GPU · 推荐 · 钢琴高精度`：CUDA/PyTorch，使用 2 秒滚动上下文和 0.1 秒采集步进，
  面向纯钢琴的起音、结束时间、力度和踏板模型。

默认优先启动 `Piano GPU`。如果缺少 PyTorch、CUDA、兼容显卡或模型权重加载失败，
程序会自动切换到 `Basic Pitch`，UI 模型芯片也会同步恢复为未点亮状态。
GPU 权重不打包进 EXE。切换 GPU 或下载模型前，程序会明确提示需要 NVIDIA 显卡、
可用驱动和 CUDA 版 PyTorch。检测到权重缺失时可直接自动下载、校验、安装到约定
目录；下载器依次尝试项目 GitHub Release、国内 GitHub 加速入口和 Zenodo。无论来源
如何，完整文件都必须通过固定 SHA-256 校验。也可选择浏览器下载后的本地 `.pth`
文件，程序会复制到模型目录并执行相同校验。
安装版会自动检测 `%LOCALAPPDATA%\PianoShadow\venv`：若其中已有可用 CUDA PyTorch，
程序通过无窗口本地子进程完成 GPU 推理并把音符事件传回悬浮窗，无需在 EXE 中重复
打包 4GB 以上的 CUDA 运行时。
托盘菜单提供“下载 Piano GPU 模型”入口。
状态栏仅显示模型名称，不显示具体 GPU 型号。按下时白键采用高饱和、高反差渐变，
黑键采用更柔和的玻璃染色；未按下时仍保持真实黑白键外观。

CPU 模式同样采用滚动时序：默认保留约 2 秒上下文、每 0.5 秒推进一次，只发布新增
起音，并按绝对时间合并窗口重叠检测。相比旧版独立分块，首次响应稍慢，但快速音阶的
顺序、跨块长音和重复按键更稳定。

GPU 模式需要额外安装 CUDA 版 PyTorch：

```powershell
.\setup-windows.ps1 -Gpu
# 或手动安装：
& "$env:LOCALAPPDATA\PianoShadow\venv\Scripts\python.exe" -m pip install `
  torch --index-url https://download.pytorch.org/whl/cu124
```

## 常见问题

- **提示未检测到输入**：检查 `pactl list short sources` 中的 monitor，或 Windows
  默认扬声器；软件会保持运行，可随时修复设备后重新启动。
- **Basic Pitch 安装慢/装不上**：先用 `requirements-demo.txt` 验证界面；建议使用
  Python 3.10/3.11，因为部分机器学习依赖对最新 Python 的支持可能滞后。
- **识别不准**：Basic Pitch 面向多音高转录，混响、鼓点和人声会产生误判。适当提高
  `--min-amp`、`--min-confidence` 或 `--min-velocity`，并使用干净的钢琴录音。
- **偶发高音/音符不消失**：程序默认抑制较弱的高次泛音，并限制相邻块重复刷新同一
  音符。仍有误识别时可尝试 `--min-confidence 0.58 --min-velocity 40`。
- **CPU 高**：增大 `--chunk`（如 3.5），关闭其他推理任务。UI 仅在动画存在时重绘，
  推理和采集均在后台线程。
- **延迟**：模型只加载一次。GPU 模式加载完成后按约 0.1 秒步进更新；CPU 模式首次
  需要积累约 2 秒滚动上下文，之后默认约每 0.5 秒推进一次，实际延迟还取决于 CPU
  推理耗时。该软件优先保证音符顺序和跨块稳定性，不定位为毫秒级演奏监听器。

## 项目结构

```text
piano_shadow/
  main.py              启动、线程编排、demo
  audio_capture.py     monitor / WASAPI loopback 捕获
  transcription.py    Basic Pitch CPU 滚动时序推理
  piano_transcription.py  Piano GPU 与安装版桥接管理
  gpu_bridge.py        本机 CUDA Python 音频/音符桥接进程
  note_model.py        MIDI、音名、88 键映射
  ui_overlay.py        PyQt6 透明窗、绘制与动效
  config.py            配置与命令行
  installer.iss        Windows 安装器定义
  build-installer.ps1  Windows 安装包构建脚本
```

运行核心映射测试：

```bash
python -m unittest discover -s tests -v
```
