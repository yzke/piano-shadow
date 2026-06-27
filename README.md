# Piano Shadow

Piano Shadow 是一个本地运行的桌面钢琴音符悬浮窗。它捕获系统正在播放的声音，
使用 Spotify Basic Pitch 转录钢琴音符，再把近期音符显示在透明 88 键键盘上。
它面向听音与键位联想，不是专业扒谱工具；不上传音频，也不调用云 API。

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
python main.py --chunk 0.5 --decay 1.4 --min-amp 0.008 --width 900 --height 160
```

左键拖动窗口可移动；右键菜单可调节整体透明度和窗口大小，并切换识别模型、位置
锁定、置顶、点击穿透和参数面板。所有操作均通过 UI 完成，不启用键盘快捷键。
锁定位置后仍可右键操作；开启点击穿透后需通过任务栏/窗口管理器恢复交互。

右上角常驻按钮从左到右为：识别模型、锁定/解锁、确保置顶、缩小、放大、透明度。
模型芯片未点亮表示 Basic Pitch，蓝色点亮表示 Piano GPU。未锁定时可直接
拖动窗口，无需单独的移动按钮。透明度按钮提供
20%、30%、40%、50%、60%、70%、80%、85%、90%、95%、100% 共 11 档，
到顶后回到 20%；右键滑杆支持 20%–100% 连续微调。窗口拖动优先使用桌面系统原生移动协议，
以改善 WSL/Wayland 下无边框窗口的拖动兼容性。
被按下琴键及其荧光的有效透明度最低为 50%；背景和未按琴键仍完全跟随用户设置。

模型芯片左侧使用对应琴键颜色显示固定唱名 `Do Re Mi Fa Sol La Si`，便于快速
建立颜色与音级的对应关系。

Windows 原生运行时置顶图标可直接开启或关闭置顶，并通过 Win32 API 切换，不会重建
窗口或改变双屏坐标。WSL/Wayland 下按钮保持为“确保置顶”，需要取消时使用右键菜单。
置顶开启时程序还会定期重新维护窗口层级，但不会抢占键盘焦点。

按钮图形由程序直接绘制为高 DPI 矢量图标，不依赖外部图片或图标字体。透明度也在
程序绘制层完成，因此 WSLg/Wayland 不支持窗口级透明度时仍然有效。

音符使用固定的 12 音级配色：同一音级跨八度保持一致，例如 C2、C4、C7 始终使用
同一种青色。升音使用相邻的独立色相；音名、琴键和残影共享同一配色。

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

诊断 WASAPI loopback、录制 2.5 秒并自检 Basic Pitch：

```powershell
& "$env:LOCALAPPDATA\PianoShadow\venv\Scripts\python.exe" `
  .\audio_diagnostics.py --record 2.5 --model
```

运行录制诊断时请让播放器持续播放声音；输出会显示捕获波形的 RMS 和峰值。

### 手动选择识别模型

右键窗口打开“识别模型”菜单，可在运行时切换：

- `Basic Pitch · 快速通用`：CPU/ONNX，延迟低，适用于一般音频。
- `Piano GPU · 钢琴高精度`：CUDA/PyTorch，使用 2 秒滚动上下文和 0.1 秒采集步进，
  面向纯钢琴的起音、结束时间、力度和踏板模型。

默认优先启动 `Piano GPU`。如果缺少 PyTorch、CUDA、兼容显卡或模型权重加载失败，
程序会自动切换到 `Basic Pitch`，UI 模型芯片也会同步恢复为未点亮状态。
状态栏仅显示模型名称，不显示具体 GPU 型号。按下时白键采用高饱和、高反差渐变，
黑键采用更柔和的玻璃染色；未按下时仍保持真实黑白键外观。

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
- **延迟**：模型只加载一次；当前 Windows 测试中复用后的推理约 31ms。默认 0.5 秒
  chunk 的稳定端到端延迟约 0.53 秒，首次模型预热约需 2 秒。Basic Pitch 需要先积累
  音频片段，因此无法达到几十毫秒级的实时演奏监听。

## 项目结构

```text
piano_shadow/
  main.py              启动、线程编排、demo
  audio_capture.py     monitor / WASAPI loopback 捕获
  transcription.py    Basic Pitch 推理与过滤
  note_model.py        MIDI、音名、88 键映射
  ui_overlay.py        PyQt6 透明窗、绘制与动效
  config.py            配置与命令行
```

运行核心映射测试：

```bash
python -m unittest discover -s tests -v
```
