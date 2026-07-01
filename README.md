# Piano Shadow

[English](README.en.md) | 简体中文

Piano Shadow 是一个本地运行的桌面音乐可视化与演奏工具。它最初是透明钢琴音符悬浮窗：捕获系统正在播放的声音，使用 Piano GPU 或 Spotify Basic Pitch 转录钢琴音符，再把近期音符显示到透明 88 键键盘上。现在它也包含电脑键盘/MIDI 演奏模式、可切换音色与音源、听音练习、钢琴键位/唱名联想，以及仍在探索中的 Erhu Shadow 二胡实时音高可视化。它面向听音、键位联想和演奏辅助，不是专业扒谱工具；不上传音频，也不调用云 API。

当前版本：`0.7.2`

## 主要功能

### 钢琴识别可视化

- 透明悬浮窗显示完整 88 键钢琴。
- 从系统音频 loopback / monitor 捕获正在播放的声音。
- 支持两套钢琴识别后端：
  - `Piano GPU`：面向纯钢琴，高精度，优先使用本机 CUDA 环境。
  - `Basic Pitch`：CPU/ONNX 通用模式，安装包内置，作为默认回退。
- 音名、固定唱名、琴键高亮、残影和光柱共享同一套 12 音级颜色。
- 同一音级跨八度保持同色，低音略暗、高音略亮。
- 支持独立调节毛玻璃/键盘透明度和彩色高亮透明度。
- 支持纯键盘模式、置顶、锁定、鼠标穿透、托盘显示/隐藏和恢复默认设置。

### 钢琴演奏模式

- 可用电脑键盘或 MIDI 键盘直接演奏。
- 键盘映射按音阶顺延，适合双手：
  - `F1–F12`：低音区
  - `1–=`：中低音区，`8 9 0 - =` 顺延到下一八度
  - `Q–]`、`A–'`、`Z–/`：继续向上排列
- `← / →` 按五度圈切换全部大调及关系小调：`C大/A小 → G大/E小 → D大/B小 ...`
- `↑ / ↓` 调整整体八度。
- `Shift` 临时升半音，`Ctrl` 临时降半音。
- `Space` 延音/揉弦，`Enter` 休止，`Alt+目标音` 可用于支持滑音的音色。
- 钢琴演奏模式会在键盘上标出当前调的电脑按键锚点：
  - C 调显示 `Q/C4`
  - G 调显示 `Q/G4`
  - 其它音区显示 `F1`、`1`、`A`、`Z` 等行首按键
  - 上下八度后标记跟随移动，避免切调后迷路。
- 演奏模式第二排提供紧凑方向键组：左右切换五度圈调式，上下调整八度。

### 音色与音源

- 默认使用 Windows WinMM General MIDI，不需要额外音源。
- 演奏模式第二排提供上一音色、当前音色、下一音色、恢复默认和音源管理。
- 内置常用钢琴、电钢琴、风琴、吉他、贝斯、弦乐、铜管、萨克斯、长笛、合成器和近似二胡音色。
- 可在界面内下载 GeneralUser GS SoundFont 到：

```text
%LOCALAPPDATA%\PianoShadow\soundfonts\GeneralUser-GS.sf2
```

- 下载带进度、备用来源、SHA-256 校验和 `.part` 原子安装。
- 安装后可在 `WIN` 与 `SF2` 之间切换。

### 听音练习

- 演奏模式下提供听音练习按钮。
- 连续点击切换：`1 音 → 3 音 → 5 音 → 7 音 → 关闭`。
- 每题先播放示范，再监听用户按键。
- 用户按对后自动进入下一题；答错会标出错在第几个音、实际按下的音和正确音。
- 示范播放时不会点亮琴键，只有用户作答时才显示高亮。
- 示范结束两秒后若没有开始作答，会自动重播当前题。
- 题目跟随当前调式，包含单音、调内三和弦/转位、五声音阶和完整调式片段。

### Staff Shadow / 五线谱轨迹

- 钢琴模式第二排提供五线谱轨迹开关，默认关闭。
- 打开后在 88 键下方显示双排五线谱：高音谱表 + 低音谱表。
- 识别到的音符从右侧进入、向左流动，用于快速观察音高轮廓。
- 目前不做严格节奏排版，也不把模型输出的时值当作正式谱面，只作为实时视觉轨迹。
- 谱线、谱号和背景透明度跟随键盘透明度；音符和拖尾颜色跟随对应音级颜色与高亮透明度。
- 键盘包裹层和五线谱底盘使用同一套毛玻璃样式，可在黑毛玻璃与白毛玻璃之间切换。
- 纯键盘/鼠标穿透模式下，若五线谱已开启，会保留谱线和音符，同时保持五线谱区域不拦截鼠标。

### Erhu Shadow / 二胡实时音高可视化

- 这是探索性功能：目前可以展示连续音高走势和大致弦位，但识别准确度还不稳定，不能当作可靠扒谱或真实二胡指法判断。
- 右上角“钢/胡”按钮或右键菜单可在钢琴模式与二胡模式间切换。
- 二胡模式不依赖 Basic Pitch 的 NoteEvent，而使用实时 Pitch Tracker 追踪连续主频。
- 标准二胡定弦：
  - 内弦 D4
  - 外弦 A4
- 光点位置表示绝对音高在对应弦上的把位：
  - 空弦为 0
  - 每升高 1 个半音，位置 +1
  - 每根弦显示 0–18 位
- 支持横向/竖向显示、历史音轨迹、琴托和上方横杆显隐、镜像视角。
- 竖向模式当前采用“越往下音越高”的显示逻辑。
- 选弦状态机避免 A4 等重叠音域在内外弦之间疯狂跳动：
  - 默认保持上一根弦
  - 低置信度不更新
  - 另一根弦必须连续更优才换弦
  - 空弦带容差，略低/略高的 D4、A4 也能稳定高亮空弦
- 调式显示支持自动、D、G、F、Bb、C、A。调式只影响简谱文字，不影响光点物理位置。

## 界面截图

下面几张图是开发过程中的截图，不一定代表最新界面的每一个细节，但能说明功能形态。

### 听音练习

![听音练习开发截图](docs/screenshots/ear-training.png)

### Staff Shadow / 五线谱轨迹

![五线谱轨迹开发截图](docs/screenshots/staff-shadow.png)

### 毛玻璃底盘样式

![白毛玻璃五线谱效果](docs/screenshots/glass-light-staff.png)

![黑毛玻璃五线谱效果](docs/screenshots/glass-dark-staff.png)

### Erhu Shadow

![Erhu Shadow 开发截图](docs/screenshots/erhu-shadow.png)

仓库里还保留了早期钢琴识别与透明度控制截图：

![钢琴监听开发截图](docs/screenshots/listening-overlay.png)

![纯键盘开发截图](docs/screenshots/keyboard-only.png)

![透明度控制开发截图](docs/screenshots/transparency-controls.png)

## Windows 安装

推荐直接下载 GitHub Release 里的安装包：

```text
PianoShadow-Setup-v0.7.2-Windows-x64.exe
```

安装包不要求用户安装 Python。默认路径：

- 程序：`%LOCALAPPDATA%\Programs\PianoShadow`
- 模型：`%LOCALAPPDATA%\PianoShadow\models`
- 音源：`%LOCALAPPDATA%\PianoShadow\soundfonts`
- 日志：`%LOCALAPPDATA%\PianoShadow\logs`

安装时可选择桌面快捷方式和登录后自动启动。升级或卸载默认保留已下载模型和音源。

### Windows 使用建议

1. 确保播放器从默认扬声器输出声音。
2. 启动 Piano Shadow。
3. 钢琴识别默认进入钢琴模式；点击“胡”切到二胡模式。
4. 二胡模式加载完成后状态会显示 `Listening · Pitch Tracker`。
5. 如果窗口看不见，可从托盘图标显示/隐藏或恢复默认设置。

某些蓝牙免提设备、独占模式播放器或虚拟声卡不提供 WASAPI loopback。遇到无输入时，先切回普通扬声器并关闭播放器独占模式。

### Windows 源码运行

如果需要从源码运行，在 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup-windows.ps1
.\run-windows.ps1
```

只看界面或演示：

```powershell
.\setup-windows.ps1 -DemoOnly
.\run-windows.ps1 -Demo
```

需要 Piano GPU 时安装 CUDA 版 PyTorch：

```powershell
.\setup-windows.ps1 -Gpu
```

安装版会自动检测 `%LOCALAPPDATA%\PianoShadow\venv` 中的 CUDA 环境，并通过本地桥接进程调用 GPU 推理；不会把 4GB 以上的 CUDA 运行时打进 EXE。

### Windows 构建

维护者构建安装包：

```powershell
.\build-installer.ps1 -Version 0.7.2
```

需要 Inno Setup 6。产物在 `dist`：

```text
PianoShadow-v0.7.2-Windows-x64.exe
PianoShadow-Setup-v0.7.2-Windows-x64.exe
```

## Linux / WSL / 源码运行

Linux 下使用 `soundcard` 寻找默认输出设备对应的 monitor source。PipeWire 用户通常需要 `pipewire-pulse` 兼容层。

```bash
pactl get-default-sink
pactl list short sources
```

输出中应出现类似：

```text
alsa_output....monitor
```

源码运行：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
python main.py
```

只看界面：

```bash
pip install -r requirements-demo.txt
python main.py --demo-mode
```

二胡演示：

```bash
python main.py --demo-midi "62;64;66;67;69;71;72;74"
```

WSLg/Wayland 对无边框窗口、置顶和点击穿透的支持不完全一致。如果出现 `This plugin does not support raise()`，说明合成器不允许应用强制置顶。可以尝试：

```bash
QT_QPA_PLATFORM=xcb python main.py --demo-mode
```

如果需要最稳定的置顶和双屏定位，建议直接使用 Windows 安装版或 Windows Python 启动。

## 常见问题

- 没有声音输入：检查默认扬声器、播放器输出设备、Windows 独占模式或 Linux monitor source。
- 钢琴识别延迟：CPU 模式需要滚动上下文；GPU 模式加载后更新更快。
- 二胡识别不准确：这是当前预期限制。二胡模式仍在探索，使用实时音高跟踪而不是专门训练的二胡模型；环境底噪、伴奏、人声、揉弦、滑音和混响都会影响主频估计。
- 二胡空弦不亮：0.6.2 起已加入空弦容差与更快确认逻辑；请确认版本不低于 0.6.2。
- 听音练习示范不亮键：这是设计，示范只发声，用户作答才点亮。

## 项目结构

```text
main.py                 启动、托盘、线程编排、demo
audio_capture.py        系统音频 loopback / monitor 捕获
transcription.py        Basic Pitch CPU 推理
piano_transcription.py  Piano GPU 推理与桥接
erhu_pitch_tracker.py   二胡/单旋律实时 pitch tracker
erhu_model.py           二胡两弦映射与选弦状态机
performance.py          演奏模式、键盘映射、听音练习、音源控制
note_model.py           MIDI、音名、88 键模型
ui_overlay.py           PyQt6 透明窗、绘制、菜单、动画
config.py               配置与命令行
installer.iss           Windows 安装器定义
```

运行测试：

```bash
python -m unittest discover -s tests -v
```
