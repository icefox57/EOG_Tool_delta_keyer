# EOG Delta Keyer

中文 | [English](#english)

轻量批量抠图与调色工具，面向绿幕角色图、AI 生成素材、游戏精灵图和宣传图合成工作流。它提供类似 DaVinci Resolve Delta Keyer 的低/高 matte 阈值控制，同时加入批处理、原图分辨率预览、多配置档、只调色模式等更适合日常素材生产的小工具能力。

## 项目由来

这个免费开源工具是在开发 **Echoes of Greed / Echoes of Desire - Chaos Void** 的美术素材管线时顺手做出来的。项目里有大量 AI 生成角色、绿幕抠图、宣传图合成和游戏素材整理工作，单独为了批量抠图与轻量调色反复打开大型视频软件并不高效，所以我们把这套流程做成了一个更轻、更直接的小工具。

如果这个工具帮到了你，也欢迎顺手关注和支持游戏项目：

- Patreon: [https://www.patreon.com/icefox57](https://www.patreon.com/icefox57)
- Itch.io: [https://icefoxlab.itch.io/echoes-of-greed](https://icefoxlab.itch.io/echoes-of-greed)
- F95Zone: [https://f95zone.to/threads/echoes-of-greed-v0-1-icefox.283306/](https://f95zone.to/threads/echoes-of-greed-v0-1-icefox.283306/)

也欢迎体验 **Echoes of Greed**，看看这个工具最初服务的游戏项目。

## 功能

- 批量读取单张图片或整个文件夹。
- 支持 PNG/JPG/WEBP/BMP/TIF 输入。
- 输出带 alpha 通道的 PNG，不覆盖原图。
- 抠图和调色是两个独立模块，可分别启用。
- 支持只抠图、只调色、抠图加调色。
- 默认 `dominance` 绿幕模式，避免暗色衣服被普通 RGB 距离误伤成半透明。
- 低/高阈值按 matte/alpha 逻辑处理。
- 支持边缘柔化和去溢色。
- 支持亮度、对比度、饱和度、Gamma 调色。
- 内置 `poster_soft`、`lighten`、`muted` 调色预设。
- 原图分辨率预览，可放大到 200%/400% 检查发丝、绿边和半透明边缘。
- 鼠标悬停参数时显示说明小窗。
- 支持多套配置档，例如“默认”“A配置”“B配置”，每套配置独立保存。

## 安装

需要 Python 3.10+，以及：

```bash
pip install pillow numpy
```

在 Codex 本地运行环境中，也可以直接使用 bundled Python：

```powershell
& "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" `
  "G:\12.Video\EOG\tools\delta_keyer\delta_keyer.py" --gui
```

## 打开图形界面

Windows 下可以双击：

```bat
run_delta_keyer_gui.cmd
```

或命令行启动：

```bash
python delta_keyer.py --gui
```

界面中可以设置：

- 顶部配置按钮：切换不同工作参数。
- 添加配置：用当前参数复制出一套新配置。
- 输入文件夹和输出文件夹。
- 是否启用抠图。
- 是否启用调色。
- 关键颜色，例如 `#00FF00`。
- 低阈值和高阈值，例如 `0.3` / `0.9`。
- 抠图模式，绿幕人物默认使用 `dominance`。
- 边缘柔化和去溢色。
- 调色预设与手动调色：亮度、对比度、饱和度、Gamma。
- 递归处理子文件夹。
- 输出文件名后缀。

参数会自动保存到 `delta_keyer_config.json`。下次打开工具时会恢复上次使用的配置档。

## 多配置档

工具顶部默认有“默认”配置。点击“添加配置”后输入名称，例如 `A配置`、`B配置`，顶部会新增对应按钮。

每套配置会独立保存：

- 输入/输出路径
- 是否启用抠图
- 是否启用调色
- 关键颜色
- 低/高阈值
- 抠图模式
- 边缘柔化
- 去溢色
- 调色预设
- 亮度、对比度、饱和度、Gamma
- 预览缩放
- 是否递归
- 输出后缀

切换配置时，工具会先保存当前配置，再载入目标配置。

## 调色建议

如果绿幕单绘人物抠完后比最终海报更深，可以先选 `poster_soft` 预设。它会把人物调得更亮、更柔，饱和度略低，适合贴近浅色海报或宣传图氛围。

常用旋钮含义：

- 亮度：整体变亮或变暗。
- 对比度：降低后黑色不那么死，整体更柔；提高后层次更硬。
- 饱和度：降低后颜色更淡，更接近纸面海报；提高后颜色更浓。
- Gamma：低于 `1` 会主要提亮中间调，适合人物整体偏暗但高光不想过曝的情况。

## 命令行批处理

抠图并应用调色预设：

```powershell
python delta_keyer.py `
  "G:\12.Video\EOG\zoya\zoya_front_idle" `
  -o "G:\12.Video\EOG\zoya\zoya_front_idle_keyed" `
  --color "#00FF00" `
  --low 0.3 `
  --high 0.9 `
  --metric dominance `
  --preset poster_soft
```

递归处理子文件夹：

```powershell
python delta_keyer.py `
  "G:\12.Video\EOG\zoya" `
  -o "G:\12.Video\EOG\zoya_keyed" `
  --color "#00FF00" `
  --low 0.3 `
  --high 0.9 `
  --metric dominance `
  --recursive `
  --brightness 1.18 `
  --contrast 0.82 `
  --saturation 0.88 `
  --gamma 0.86
```

只调色、不抠图：

```powershell
python delta_keyer.py `
  "G:\10.Pic\AIDraw\2026-06-13\main_V2.jpg" `
  -o "G:\10.Pic\AIDraw\2026-06-13\tone_only" `
  --no-key `
  --preset poster_soft
```

只抠图、不调色：

```powershell
python delta_keyer.py `
  "G:\10.Pic\AIDraw\2026-06-13\character.png" `
  -o "G:\10.Pic\AIDraw\2026-06-13\keyed" `
  --no-tone `
  --color "#00FF00" `
  --low 0.3 `
  --high 0.9
```

## 参数

| 参数 | 说明 |
| --- | --- |
| `input` | 输入图片或文件夹 |
| `-o`, `--output` | 输出文件夹 |
| `--no-key` | 关闭抠图，仅保留原始 alpha |
| `--no-tone` | 关闭调色 |
| `-c`, `--color` | 关键颜色，例如 `#00FF00` 或 `0,255,0` |
| `--low` | 低阈值，范围 `0-1` |
| `--high` | 高阈值，范围 `0-1` |
| `--soften` | alpha 边缘柔化半径，单位像素 |
| `--despill` | 去溢色强度，范围 `0-1` |
| `--metric` | 抠图模式：`dominance` 或 `rgb` |
| `--preset` | 调色预设：`none`、`poster_soft`、`lighten`、`muted` |
| `--brightness` | 亮度倍率 |
| `--contrast` | 对比度倍率 |
| `--saturation` | 饱和度倍率 |
| `--gamma` | Gamma；低于 `1` 会提亮中间调 |
| `-r`, `--recursive` | 递归处理子文件夹 |
| `--suffix` | 输出文件名后缀 |
| `--gui` | 打开图形界面 |

## 阈值逻辑

默认 `dominance` 模式适合绿幕/蓝幕。它先计算原始前景 alpha：像关键颜色的区域 alpha 越低，不像关键颜色的区域 alpha 越高。

随后按类似 DaVinci Resolve Delta Keyer 的 Matte Threshold 逻辑处理：

- 低于低阈值：压成黑色 matte，也就是透明。
- 高于高阈值：压成白色 matte，也就是不透明。
- 两者之间：保留平滑过渡 alpha。

`dominance` 模式判断关键颜色通道是否占主导，例如绿幕中绿色是否明显强于红色和蓝色。这能避免黑衣服、暗部、灰色区域因为普通 RGB 距离而被误伤成半透明。

`rgb` 模式会按每个像素和关键颜色的归一化 RGB 距离计算原始前景 alpha，然后使用同一套低/高阈值逻辑。

DaVinci Resolve Delta Keyer 的内部算法并非公开实现，因此本工具目标是提供相近的控制逻辑和实用结果，不保证逐像素一致。

## 输出

输出文件统一为 PNG：

```text
<原文件名><suffix>.png
```

默认后缀为：

```text
_keyed
```

示例：

```text
character.png -> character_keyed.png
```

---

## English

Lightweight batch keying and color-adjustment tool for green-screen character images, AI-generated assets, game sprites, and poster-compositing workflows. It provides low/high matte threshold controls similar in spirit to DaVinci Resolve Delta Keyer, plus practical production features such as batch processing, full-resolution preview, multiple profiles, and tone-only processing.

## Project Origin

This free and open-source tool was created while building the art-production pipeline for **Echoes of Greed / Echoes of Desire - Chaos Void**. The project involves a lot of AI-generated characters, green-screen keying, poster compositing, and game-asset cleanup. Opening a full video-editing suite just to batch-key images and do light tone matching felt too heavy, so this tool grew out of that workflow.

If the tool helps you, please consider checking out and supporting the game:

- Patreon: [https://www.patreon.com/icefox57](https://www.patreon.com/icefox57)
- Itch.io: [https://icefoxlab.itch.io/echoes-of-greed](https://icefoxlab.itch.io/echoes-of-greed)
- F95Zone: [https://f95zone.to/threads/echoes-of-greed-v0-1-icefox.283306/](https://f95zone.to/threads/echoes-of-greed-v0-1-icefox.283306/)

You are also very welcome to try **Echoes of Greed**, the game project this tool was originally made for.

## Features

- Process a single image or an entire folder.
- Supports PNG/JPG/WEBP/BMP/TIF input.
- Exports PNG files with alpha, without overwriting source images.
- Keying and tone adjustment are independent modules.
- Supports key-only, tone-only, and key-plus-tone workflows.
- Default `dominance` mode is optimized for green/blue screens and avoids making dark clothing semi-transparent.
- Low/high threshold controls operate on the matte/alpha.
- Optional edge soften and despill.
- Brightness, contrast, saturation, and Gamma controls.
- Built-in tone presets: `poster_soft`, `lighten`, and `muted`.
- Full-resolution preview with zoom for inspecting hair, green edges, and semi-transparent details.
- Hover tooltips for technical controls.
- Multiple saved profiles, such as `Default`, `Profile A`, and `Profile B`.

## Installation

Requires Python 3.10+:

```bash
pip install pillow numpy
```

## Launching The GUI

On Windows, double-click:

```bat
run_delta_keyer_gui.cmd
```

Or launch from a terminal:

```bash
python delta_keyer.py --gui
```

In the GUI, you can set:

- Profile buttons at the top for switching workflows.
- Add Profile, which copies the current settings into a new profile.
- Input and output folders.
- Whether keying is enabled.
- Whether tone adjustment is enabled.
- Key color, for example `#00FF00`.
- Low/high thresholds, for example `0.3` / `0.9`.
- Keying mode. Use `dominance` for green-screen characters by default.
- Edge soften and despill.
- Tone preset and manual controls: brightness, contrast, saturation, Gamma.
- Recursive folder processing.
- Output filename suffix.

Settings are saved to `delta_keyer_config.json` and restored on the next launch.

## Profiles

The GUI starts with a default profile. Click `Add Profile` and enter a name such as `Profile A` or `Profile B`; a new button will appear at the top.

Each profile stores:

- Input/output paths
- Keying enabled/disabled
- Tone enabled/disabled
- Key color
- Low/high thresholds
- Keying mode
- Edge soften
- Despill
- Tone preset
- Brightness, contrast, saturation, Gamma
- Preview zoom
- Recursive mode
- Output suffix

When switching profiles, the tool saves the current profile before loading the selected one.

## Tone Tips

If a green-screen character looks too dark after keying, start with the `poster_soft` preset. It brightens the character, lowers contrast, and slightly reduces saturation, which often fits soft poster-style compositions better.

Controls:

- Brightness: overall light/dark adjustment.
- Contrast: lowers or increases tonal hardness.
- Saturation: controls color intensity.
- Gamma: mainly affects midtones; values below `1` brighten midtones without pushing highlights as hard.

## CLI Examples

Key and apply a tone preset:

```bash
python delta_keyer.py "./input" \
  -o "./output" \
  --color "#00FF00" \
  --low 0.3 \
  --high 0.9 \
  --metric dominance \
  --preset poster_soft
```

Process subfolders recursively:

```bash
python delta_keyer.py "./input" \
  -o "./output" \
  --color "#00FF00" \
  --low 0.3 \
  --high 0.9 \
  --metric dominance \
  --recursive \
  --brightness 1.18 \
  --contrast 0.82 \
  --saturation 0.88 \
  --gamma 0.86
```

Tone only, no keying:

```bash
python delta_keyer.py "./poster.jpg" \
  -o "./tone_only" \
  --no-key \
  --preset poster_soft
```

Key only, no tone adjustment:

```bash
python delta_keyer.py "./character.png" \
  -o "./keyed" \
  --no-tone \
  --color "#00FF00" \
  --low 0.3 \
  --high 0.9
```

## CLI Options

| Option | Description |
| --- | --- |
| `input` | Input image or folder |
| `-o`, `--output` | Output folder |
| `--no-key` | Disable keying and keep the original alpha |
| `--no-tone` | Disable tone adjustment |
| `-c`, `--color` | Key color, for example `#00FF00` or `0,255,0` |
| `--low` | Low matte threshold, range `0-1` |
| `--high` | High matte threshold, range `0-1` |
| `--soften` | Alpha blur radius in pixels |
| `--despill` | Key-color spill suppression, range `0-1` |
| `--metric` | Keying mode: `dominance` or `rgb` |
| `--preset` | Tone preset: `none`, `poster_soft`, `lighten`, `muted` |
| `--brightness` | Brightness multiplier |
| `--contrast` | Contrast multiplier |
| `--saturation` | Saturation multiplier |
| `--gamma` | Gamma; values below `1` brighten midtones |
| `-r`, `--recursive` | Process subfolders |
| `--suffix` | Output filename suffix |
| `--gui` | Open the GUI |

## Threshold Logic

The default `dominance` mode is designed for green/blue screens. It first computes a raw foreground alpha: pixels that look like the key color get a lower alpha, while pixels that do not look like the key color get a higher alpha.

Then it applies matte threshold logic:

- Below the low threshold: forced to black matte, meaning transparent.
- Above the high threshold: forced to white matte, meaning opaque.
- Between the two thresholds: keeps a smooth alpha transition.

`dominance` checks whether the key-color channel dominates the other channels. For green screen, that means the green channel must clearly dominate red and blue. This avoids the common RGB-distance failure where dark clothing or gray areas become semi-transparent.

`rgb` mode computes raw foreground alpha using normalized RGB distance from the key color, then applies the same low/high threshold logic.

DaVinci Resolve Delta Keyer is not an open implementation, so this tool aims for similar control behavior and practical results, not pixel-perfect equivalence.

## Output

All outputs are PNG files:

```text
<source filename><suffix>.png
```

Default suffix:

```text
_keyed
```

Example:

```text
character.png -> character_keyed.png
```
