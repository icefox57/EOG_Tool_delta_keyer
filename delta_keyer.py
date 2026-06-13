from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageFilter, ImageTk


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
CONFIG_PATH = Path(__file__).with_name("delta_keyer_config.json")


@dataclass(frozen=True)
class KeyerSettings:
    enable_keying: bool = True
    enable_tone: bool = True
    key_color: tuple[int, int, int] = (0, 255, 0)
    low: float = 0.30
    high: float = 0.90
    soften: float = 0.0
    despill: float = 0.0
    metric: str = "dominance"
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0


TONE_PRESETS: dict[str, dict[str, float]] = {
    "none": {"brightness": 1.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0},
    "poster_soft": {"brightness": 1.18, "contrast": 0.82, "saturation": 0.88, "gamma": 0.86},
    "lighten": {"brightness": 1.16, "contrast": 0.96, "saturation": 1.0, "gamma": 0.90},
    "muted": {"brightness": 1.04, "contrast": 0.86, "saturation": 0.78, "gamma": 1.0},
}


def parse_color(value: str) -> tuple[int, int, int]:
    text = value.strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 6:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    parts = [p.strip() for p in value.replace(";", ",").split(",")]
    if len(parts) == 3:
        rgb = tuple(int(p) for p in parts)
        if all(0 <= c <= 255 for c in rgb):
            return rgb  # type: ignore[return-value]
    raise ValueError(f"Invalid color '{value}'. Use #00FF00 or 0,255,0.")


def color_to_hex(color: tuple[int, int, int]) -> str:
    return f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"


def smoothstep(x: np.ndarray) -> np.ndarray:
    return x * x * (3.0 - 2.0 * x)


def apply_tone(rgb: np.ndarray, settings: KeyerSettings) -> np.ndarray:
    gamma = max(float(settings.gamma), 0.05)
    brightness = max(float(settings.brightness), 0.0)
    contrast = max(float(settings.contrast), 0.0)
    saturation = max(float(settings.saturation), 0.0)

    adjusted = np.clip(rgb, 0.0, 1.0)
    adjusted = np.power(adjusted, gamma)
    adjusted = adjusted * brightness
    adjusted = (adjusted - 0.5) * contrast + 0.5
    luminance = (
        adjusted[..., 0:1] * 0.2126
        + adjusted[..., 1:2] * 0.7152
        + adjusted[..., 2:3] * 0.0722
    )
    adjusted = luminance + (adjusted - luminance) * saturation
    return np.clip(adjusted, 0.0, 1.0)


def apply_threshold(raw_alpha: np.ndarray, low: float, high: float) -> np.ndarray:
    matte = np.clip((raw_alpha - low) / (high - low), 0.0, 1.0)
    return smoothstep(matte)


def calculate_matte(rgb: np.ndarray, key: np.ndarray, low: float, high: float, metric: str) -> np.ndarray:
    if metric == "rgb":
        raw_alpha = np.linalg.norm(rgb - key, axis=2) / np.sqrt(3.0)
        return apply_threshold(raw_alpha, low, high)

    dominant = int(np.argmax(key))
    others = [idx for idx in range(3) if idx != dominant]
    key_strength = float(key[dominant] - max(key[others[0]], key[others[1]]))
    if key_strength <= 0.05:
        raw_alpha = np.linalg.norm(rgb - key, axis=2) / np.sqrt(3.0)
        return apply_threshold(raw_alpha, low, high)

    channel_sum = np.sum(rgb, axis=2)
    key_share = float(key[dominant] / max(float(np.sum(key)), 1e-6))
    dominant_mask = rgb[..., dominant] >= np.maximum(rgb[..., others[0]], rgb[..., others[1]])
    channel_share = rgb[..., dominant] / np.maximum(channel_sum, 1e-6)
    similarity = np.where(dominant_mask, channel_share / max(key_share, 1e-6), 0.0)
    similarity = np.clip(similarity, 0.0, 1.0)
    raw_alpha = 1.0 - similarity
    return apply_threshold(raw_alpha, low, high)


def key_image(image: Image.Image, settings: KeyerSettings) -> Image.Image:
    if settings.enable_keying and settings.high <= settings.low:
        raise ValueError("High threshold must be greater than low threshold.")
    if settings.enable_keying and not (0 <= settings.low <= 1 and 0 <= settings.high <= 1):
        raise ValueError("Thresholds must be in the 0-1 range.")

    rgba = image.convert("RGBA")
    arr = np.asarray(rgba).astype(np.float32)
    rgb = arr[..., :3] / 255.0
    original_alpha = arr[..., 3] / 255.0
    key = np.array(settings.key_color, dtype=np.float32) / 255.0

    if settings.enable_keying:
        matte = calculate_matte(rgb, key, settings.low, settings.high, settings.metric)
        alpha = matte * original_alpha

        if settings.soften > 0:
            alpha_img = Image.fromarray(np.clip(alpha * 255.0, 0, 255).astype(np.uint8), "L")
            alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(settings.soften))
            alpha = np.asarray(alpha_img).astype(np.float32) / 255.0

        if settings.despill > 0:
            # Pull pixels near the keyed color away from the key hue. This is tuned
            # for green-screen work while still honoring arbitrary key colors.
            spill_strength = (1.0 - matte)[..., None] * np.clip(settings.despill, 0.0, 1.0)
            key_axis = key / max(float(np.linalg.norm(key)), 1e-6)
            projection = np.sum(rgb * key_axis, axis=2, keepdims=True) * key_axis
            neutral = np.mean(rgb, axis=2, keepdims=True)
            corrected = rgb - projection * spill_strength + neutral * key_axis * spill_strength
            rgb = np.clip(corrected, 0.0, 1.0)
    else:
        alpha = original_alpha

    if settings.enable_tone:
        rgb = apply_tone(rgb, settings)

    out = np.empty_like(arr)
    out[..., :3] = np.clip(rgb * 255.0, 0, 255)
    out[..., 3] = np.clip(alpha * 255.0, 0, 255)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def iter_images(input_path: Path, recursive: bool) -> Iterable[Path]:
    if input_path.is_file() and input_path.suffix.lower() in IMAGE_EXTS:
        yield input_path
        return
    pattern = "**/*" if recursive else "*"
    for path in sorted(input_path.glob(pattern)):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            yield path


def output_path_for(src: Path, input_root: Path, output_root: Path, suffix: str) -> Path:
    if input_root.is_file():
        rel_parent = Path()
    else:
        rel_parent = src.parent.relative_to(input_root)
    name = f"{src.stem}{suffix}.png"
    return output_root / rel_parent / name


def process_path(
    input_path: Path,
    output_root: Path,
    settings: KeyerSettings,
    recursive: bool = False,
    suffix: str = "_keyed",
) -> tuple[int, list[str]]:
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    output_root.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    count = 0
    for src in iter_images(input_path, recursive):
        try:
            with Image.open(src) as im:
                keyed = key_image(im, settings)
            dst = output_path_for(src, input_path, output_root, suffix)
            dst.parent.mkdir(parents=True, exist_ok=True)
            keyed.save(dst)
            count += 1
        except Exception as exc:  # noqa: BLE001 - batch tool should continue.
            errors.append(f"{src}: {exc}")
    return count, errors


def make_checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    w, h = size
    y, x = np.indices((h, w))
    board = ((x // cell + y // cell) % 2).astype(np.uint8)
    arr = np.where(board[..., None] == 0, 208, 152).astype(np.uint8)
    return Image.fromarray(np.repeat(arr, 3, axis=2), "RGB")


def composite_preview(image: Image.Image, settings: KeyerSettings, max_size: tuple[int, int]) -> Image.Image:
    keyed = key_image(image, settings)
    keyed.thumbnail(max_size, Image.Resampling.LANCZOS)
    board = make_checkerboard(keyed.size)
    board.paste(keyed, (0, 0), keyed)
    return board


def full_preview_pair(image: Image.Image, settings: KeyerSettings) -> Image.Image:
    before = image.convert("RGBA")
    after = key_image(image, settings)
    before_board = make_checkerboard(before.size)
    before_board.paste(before, (0, 0), before)
    after_board = make_checkerboard(after.size)
    after_board.paste(after, (0, 0), after)
    gap = max(24, before.width // 32)
    label_h = 32
    out = Image.new("RGB", (before.width + after.width + gap, max(before.height, after.height) + label_h), (36, 36, 40))
    out.paste(before_board, (0, label_h))
    out.paste(after_board, (before.width + gap, label_h))
    return out


def load_config() -> dict[str, object]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict[str, object]) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def run_gui() -> None:
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

    root = tk.Tk()
    root.title("EOG Delta Keyer")
    stored_config = load_config()
    if isinstance(stored_config.get("profiles"), dict):
        profiles: dict[str, dict[str, object]] = {
            str(name): dict(value)
            for name, value in stored_config["profiles"].items()
            if isinstance(value, dict)
        }
        if not profiles:
            profiles = {"默认": {}}
        active_profile = {"name": str(stored_config.get("active_profile", next(iter(profiles))))}
        if active_profile["name"] not in profiles:
            active_profile["name"] = next(iter(profiles))
        config = profiles[active_profile["name"]]
    else:
        profiles = {"默认": dict(stored_config)}
        active_profile = {"name": "默认"}
        config = profiles["默认"]
    root.geometry(str(config.get("geometry", "1120x820")))

    input_var = tk.StringVar(value=str(config.get("input", str(Path.cwd()))))
    output_var = tk.StringVar(value=str(config.get("output", str(Path.cwd() / "_keyed_output"))))
    saved_language = str(config.get("language", "中文"))
    language_var = tk.StringVar(value="English" if saved_language in {"en", "English"} else "中文")
    enable_keying_var = tk.BooleanVar(value=bool(config.get("enable_keying", True)))
    enable_tone_var = tk.BooleanVar(value=bool(config.get("enable_tone", True)))
    color_var = tk.StringVar(value=str(config.get("color", "#00FF00")))
    low_var = tk.DoubleVar(value=float(config.get("low", 0.30)))
    high_var = tk.DoubleVar(value=float(config.get("high", 0.90)))
    soften_var = tk.DoubleVar(value=float(config.get("soften", 0.0)))
    despill_var = tk.DoubleVar(value=float(config.get("despill", 0.0)))
    metric_var = tk.StringVar(value=str(config.get("metric", "dominance")))
    preset_var = tk.StringVar(value=str(config.get("preset", "none")))
    brightness_var = tk.DoubleVar(value=float(config.get("brightness", 1.0)))
    contrast_var = tk.DoubleVar(value=float(config.get("contrast", 1.0)))
    saturation_var = tk.DoubleVar(value=float(config.get("saturation", 1.0)))
    gamma_var = tk.DoubleVar(value=float(config.get("gamma", 1.0)))
    zoom_var = tk.DoubleVar(value=float(config.get("zoom", 1.0)))
    recursive_var = tk.BooleanVar(value=bool(config.get("recursive", False)))
    suffix_var = tk.StringVar(value=str(config.get("suffix", "_keyed")))
    selected_image: dict[str, Path | None] = {"path": None}
    preview_photo: dict[str, ImageTk.PhotoImage | None] = {"image": None}
    preview_base: dict[str, Image.Image | None] = {"image": None}

    tooltips: list[object] = []
    ui_text_widgets: list[tuple[tk.Widget, str]] = []
    help_text = {
        "zh": {
            "input": "读取单张图片或整个文件夹。支持 PNG/JPG/WEBP/BMP/TIF。",
            "output": "输出带 alpha 的 PNG，不覆盖原图。批处理会保留子目录结构。",
            "profile": "配置档会保存当前所有参数。切换配置前会自动保存当前配置，然后载入目标配置。",
            "add_profile": "新增一套配置档。新配置会复制当前参数作为起点，之后可以独立调整。",
            "language": "切换界面语言。语言选择会随当前配置保存。",
            "enable_keying": "控制是否执行抠图。关闭后不会生成透明背景，只保留原图 alpha，可单独使用调色功能。",
            "enable_tone": "控制是否执行调色。关闭后只做抠图；打开后可单独或配合抠图调整亮度、对比度、饱和度和 Gamma。",
            "color": "抠图关键颜色。EOG 绿幕通常用 #00FF00；如果 AI 生成的绿幕偏暗，仍可先保留这个颜色并使用 dominance 模式。",
            "low": "低阈值作用在最终 matte/alpha 上：低于它的区域会压成透明。提高它可以清掉更多灰边和绿幕残留。",
            "high": "高阈值作用在最终 matte/alpha 上：高于它的区域会压成不透明。降低它可以让主体边缘更快变实。",
            "soften": "边缘柔化会对 alpha 做轻微模糊。适合软化锯齿，但过高会让边缘发虚。",
            "despill": "去溢色会削弱边缘的绿幕染色。绿色反光明显时提高一点，通常 0.1-0.4 就够。",
            "metric": "dominance 适合绿幕/蓝幕：看关键色通道是否明显占主导。rgb 是旧的 RGB 距离模式，容易误伤暗色衣服，只在特殊抠色时用。",
            "preset": "调色预设会同时设置亮度、对比度、饱和度和 Gamma。poster_soft 适合接近浅色柔和海报感。",
            "brightness": "亮度控制整体明暗。人物抠完太黑时先提高它。",
            "contrast": "对比度控制黑白层次硬不硬。降低后黑色不那么死，画面更柔。",
            "saturation": "饱和度控制颜色浓淡。降低后更淡、更接近纸面海报；提高后颜色更浓。",
            "gamma": "Gamma 主要影响中间调。低于 1 会提亮中间调，适合人物整体偏暗但高光不想过曝的情况。",
            "recursive": "开启后会处理输入文件夹里的所有子文件夹。",
            "suffix": "输出文件名后缀。例如 _keyed 会生成 name_keyed.png。",
            "zoom": "预览缩放只影响查看，不影响输出。预览使用原图分辨率渲染，放大到 200%/400% 可检查发丝、绿边和半透明边缘。",
        },
        "en": {
            "input": "Read a single image or a folder. Supports PNG/JPG/WEBP/BMP/TIF.",
            "output": "Exports PNG files with alpha and does not overwrite source images. Batch mode preserves subfolders.",
            "profile": "Profiles save all current parameters. Switching profiles saves the current one before loading the target profile.",
            "add_profile": "Create a new profile by copying the current settings. You can tune it independently afterward.",
            "language": "Switch the interface language. The language choice is saved with the current profile.",
            "enable_keying": "Enable or disable keying. Turn this off to keep the original alpha and use tone adjustment only.",
            "enable_tone": "Enable or disable tone adjustment. Use it alone or together with keying.",
            "color": "Key color. EOG green-screen assets usually use #00FF00. For darker AI green screens, keep this color and use dominance mode.",
            "low": "Low threshold on the final matte/alpha. Pixels below it become transparent. Increase it to remove more fringe or residue.",
            "high": "High threshold on the final matte/alpha. Pixels above it become opaque. Lower it to make subject edges become solid sooner.",
            "soften": "Softens the alpha edge with a small blur. Useful for jagged edges, but too much makes edges fuzzy.",
            "despill": "Reduces key-color spill around edges. Use a small value such as 0.1-0.4 when green spill is visible.",
            "metric": "dominance is best for green/blue screens. rgb uses RGB distance and can make dark clothes semi-transparent.",
            "preset": "Tone presets set brightness, contrast, saturation, and Gamma together. poster_soft is useful for soft poster-style matching.",
            "brightness": "Controls overall brightness. Raise it when the keyed character looks too dark.",
            "contrast": "Controls tonal hardness. Lower values make dark areas less crushed and the image softer.",
            "saturation": "Controls color intensity. Lower values make colors more muted; higher values make colors stronger.",
            "gamma": "Mostly affects midtones. Values below 1 brighten midtones without pushing highlights as hard.",
            "recursive": "Process all subfolders inside the input folder.",
            "suffix": "Output filename suffix. For example, _keyed creates name_keyed.png.",
            "zoom": "Preview zoom only affects display, not output. The preview renders from original resolution for edge inspection.",
        },
    }
    labels = {
        "zh": {
            "profile_label": "配置",
            "add_profile": "添加配置",
            "language_label": "语言",
            "input": "输入文件夹",
            "output": "输出文件夹",
            "browse": "浏览",
            "key_frame": "抠图",
            "enable_keying": "启用抠图",
            "color": "关键颜色",
            "pick": "拾取",
            "low": "低阈值",
            "high": "高阈值",
            "soften": "边缘柔化",
            "despill": "去溢色",
            "metric": "抠图模式",
            "tone_frame": "调色",
            "enable_tone": "启用调色",
            "preset": "调色预设",
            "brightness": "亮度",
            "contrast": "对比度",
            "saturation": "饱和度",
            "gamma": "Gamma",
            "recursive": "递归处理子文件夹",
            "suffix": "输出后缀",
            "refresh": "刷新列表",
            "process": "开始批量抠图",
            "preview_header": "左：原图  /  右：处理结果预览",
            "fit": "适合窗口",
            "zoom": "预览缩放",
            "add_profile_title": "添加配置",
            "add_profile_prompt": "请输入配置名称：",
            "profile_exists_title": "配置已存在",
            "profile_exists_msg": "已经有名为“{name}”的配置。",
            "input_dialog": "选择输入文件夹",
            "output_dialog": "选择输出文件夹",
            "preview_failed": "预览失败: {error}",
            "param_error": "参数错误",
            "processing": "开始批量处理...",
            "done_log": "完成: 输出 {count} 张 PNG 到 {output}",
            "error_prefix": "错误: ",
            "done_title": "完成",
            "done_msg": "已输出 {count} 张 PNG。",
            "process_failed": "处理失败: {error}",
        },
        "en": {
            "profile_label": "Profile",
            "add_profile": "Add Profile",
            "language_label": "Language",
            "input": "Input Folder",
            "output": "Output Folder",
            "browse": "Browse",
            "key_frame": "Keying",
            "enable_keying": "Enable Keying",
            "color": "Key Color",
            "pick": "Pick",
            "low": "Low Threshold",
            "high": "High Threshold",
            "soften": "Edge Soften",
            "despill": "Despill",
            "metric": "Keying Mode",
            "tone_frame": "Tone",
            "enable_tone": "Enable Tone",
            "preset": "Tone Preset",
            "brightness": "Brightness",
            "contrast": "Contrast",
            "saturation": "Saturation",
            "gamma": "Gamma",
            "recursive": "Process Subfolders",
            "suffix": "Output Suffix",
            "refresh": "Refresh List",
            "process": "Start Batch Processing",
            "preview_header": "Left: Source  /  Right: Processed Preview",
            "fit": "Fit",
            "zoom": "Preview Zoom",
            "add_profile_title": "Add Profile",
            "add_profile_prompt": "Enter profile name:",
            "profile_exists_title": "Profile Exists",
            "profile_exists_msg": "A profile named \"{name}\" already exists.",
            "input_dialog": "Select Input Folder",
            "output_dialog": "Select Output Folder",
            "preview_failed": "Preview failed: {error}",
            "param_error": "Parameter Error",
            "processing": "Starting batch processing...",
            "done_log": "Done: wrote {count} PNG file(s) to {output}",
            "error_prefix": "Error: ",
            "done_title": "Done",
            "done_msg": "Wrote {count} PNG file(s).",
            "process_failed": "Processing failed: {error}",
        },
    }

    def lang() -> str:
        return "en" if language_var.get() in {"en", "English"} else "zh"

    def tr(key: str, **kwargs: object) -> str:
        text = labels[lang()].get(key, labels["zh"].get(key, key))
        return text.format(**kwargs)

    class Tooltip:
        def __init__(self, widget: tk.Widget, text: str) -> None:
            self.widget = widget
            self.text = text
            self.tip: tk.Toplevel | None = None
            self.after_id: str | None = None
            widget.bind("<Enter>", self.schedule, add="+")
            widget.bind("<Leave>", self.hide, add="+")
            widget.bind("<ButtonPress>", self.hide, add="+")

        def schedule(self, _event: object | None = None) -> None:
            self.cancel()
            self.after_id = self.widget.after(450, self.show)

        def cancel(self) -> None:
            if self.after_id is not None:
                self.widget.after_cancel(self.after_id)
                self.after_id = None

        def show(self) -> None:
            if self.tip is not None:
                return
            tooltip_text = help_text[lang()].get(self.text, self.text)
            x = self.widget.winfo_rootx() + 18
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                self.tip,
                text=tooltip_text,
                justify="left",
                wraplength=360,
                background="#fff8d8",
                foreground="#202020",
                relief="solid",
                borderwidth=1,
                padx=8,
                pady=6,
            )
            label.pack()

        def hide(self, _event: object | None = None) -> None:
            self.cancel()
            if self.tip is not None:
                self.tip.destroy()
                self.tip = None

    def add_tooltip(widget: tk.Widget, key: str) -> tk.Widget:
        if key in help_text["zh"]:
            tooltips.append(Tooltip(widget, key))
        return widget

    def help_label(parent: tk.Widget, text: str, key: str) -> tk.Widget:
        label = ttk.Label(parent, text=tr(key))
        ui_text_widgets.append((label, key))
        add_tooltip(label, key)
        label.pack(anchor="w")
        return label

    def bind_text(widget: tk.Widget, key: str) -> tk.Widget:
        widget.configure(text=tr(key))
        ui_text_widgets.append((widget, key))
        return widget

    def refresh_language() -> None:
        for widget, key in ui_text_widgets:
            try:
                widget.configure(text=tr(key))
            except Exception:
                pass
        save_current_config()

    def settings_from_ui() -> KeyerSettings:
        return KeyerSettings(
            enable_keying=bool(enable_keying_var.get()),
            enable_tone=bool(enable_tone_var.get()),
            key_color=parse_color(color_var.get()),
            low=float(low_var.get()),
            high=float(high_var.get()),
            soften=float(soften_var.get()),
            despill=float(despill_var.get()),
            metric=metric_var.get(),
            brightness=float(brightness_var.get()),
            contrast=float(contrast_var.get()),
            saturation=float(saturation_var.get()),
            gamma=float(gamma_var.get()),
        )

    def current_config() -> dict[str, object]:
        return {
            "geometry": root.geometry(),
            "input": input_var.get(),
            "output": output_var.get(),
            "language": lang(),
            "enable_keying": bool(enable_keying_var.get()),
            "enable_tone": bool(enable_tone_var.get()),
            "color": color_var.get(),
            "low": float(low_var.get()),
            "high": float(high_var.get()),
            "soften": float(soften_var.get()),
            "despill": float(despill_var.get()),
            "metric": metric_var.get(),
            "preset": preset_var.get(),
            "brightness": float(brightness_var.get()),
            "contrast": float(contrast_var.get()),
            "saturation": float(saturation_var.get()),
            "gamma": float(gamma_var.get()),
            "zoom": float(zoom_var.get()),
            "recursive": bool(recursive_var.get()),
            "suffix": suffix_var.get(),
        }

    def save_current_config() -> None:
        profiles[active_profile["name"]] = current_config()
        save_config({"active_profile": active_profile["name"], "profiles": profiles})

    def apply_config(profile_config: dict[str, object]) -> None:
        input_var.set(str(profile_config.get("input", str(Path.cwd()))))
        output_var.set(str(profile_config.get("output", str(Path.cwd() / "_keyed_output"))))
        saved_profile_language = str(profile_config.get("language", "中文"))
        language_var.set("English" if saved_profile_language in {"en", "English"} else "中文")
        enable_keying_var.set(bool(profile_config.get("enable_keying", True)))
        enable_tone_var.set(bool(profile_config.get("enable_tone", True)))
        color_var.set(str(profile_config.get("color", "#00FF00")))
        low_var.set(float(profile_config.get("low", 0.30)))
        high_var.set(float(profile_config.get("high", 0.90)))
        soften_var.set(float(profile_config.get("soften", 0.0)))
        despill_var.set(float(profile_config.get("despill", 0.0)))
        metric_var.set(str(profile_config.get("metric", "dominance")))
        preset_var.set(str(profile_config.get("preset", "none")))
        brightness_var.set(float(profile_config.get("brightness", 1.0)))
        contrast_var.set(float(profile_config.get("contrast", 1.0)))
        saturation_var.set(float(profile_config.get("saturation", 1.0)))
        gamma_var.set(float(profile_config.get("gamma", 1.0)))
        zoom_var.set(float(profile_config.get("zoom", 1.0)))
        recursive_var.set(bool(profile_config.get("recursive", False)))
        suffix_var.set(str(profile_config.get("suffix", "_keyed")))

    profile_buttons: dict[str, tk.Button] = {}

    def refresh_profile_buttons() -> None:
        for child in profile_buttons_frame.winfo_children():
            child.destroy()
        profile_buttons.clear()
        for name in profiles:
            is_active = name == active_profile["name"]
            button = tk.Button(
                profile_buttons_frame,
                text=name,
                command=lambda n=name: switch_profile(n),
                width=max(8, min(len(name) + 2, 16)),
                background="#D7ECFF" if is_active else "#F0F0F0",
                activebackground="#C4E2FF" if is_active else "#E5E5E5",
                foreground="#102A43" if is_active else "#202020",
                relief="sunken" if is_active else "raised",
                borderwidth=2 if is_active else 1,
                padx=6,
                pady=2,
            )
            add_tooltip(button, "profile")
            button.pack(side="left", padx=(0, 6))
            profile_buttons[name] = button

    def switch_profile(name: str) -> None:
        if name == active_profile["name"]:
            return
        save_current_config()
        active_profile["name"] = name
        apply_config(profiles[name])
        refresh_language()
        refresh_profile_buttons()
        refresh_file_list()
        save_current_config()

    def add_profile() -> None:
        name = simpledialog.askstring(tr("add_profile_title"), tr("add_profile_prompt"), parent=root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in profiles:
            messagebox.showwarning(tr("profile_exists_title"), tr("profile_exists_msg", name=name))
            return
        save_current_config()
        profiles[name] = dict(current_config())
        active_profile["name"] = name
        refresh_profile_buttons()
        save_current_config()

    def log(text: str) -> None:
        log_box.insert("end", text + "\n")
        log_box.see("end")

    def refresh_file_list() -> None:
        list_box.delete(0, "end")
        path = Path(input_var.get())
        if not path.exists():
            return
        files = list(iter_images(path, recursive_var.get()))
        for item in files[:500]:
            list_box.insert("end", str(item))
        if files:
            list_box.selection_set(0)
            selected_image["path"] = files[0]
            update_preview()

    def browse_input() -> None:
        folder = filedialog.askdirectory(title=tr("input_dialog"))
        if folder:
            input_var.set(folder)
            if output_var.get().endswith("_keyed_output"):
                output_var.set(str(Path(folder) / "_keyed_output"))
            save_current_config()
            refresh_file_list()

    def browse_output() -> None:
        folder = filedialog.askdirectory(title=tr("output_dialog"))
        if folder:
            output_var.set(folder)
            save_current_config()

    def choose_color() -> None:
        current = color_var.get()
        _, picked = colorchooser.askcolor(color=current, title="选择抠图关键颜色")
        if picked:
            color_var.set(picked.upper())
            color_swatch.configure(background=picked)
            update_preview()

    def apply_preset(_event: object | None = None) -> None:
        preset = TONE_PRESETS.get(preset_var.get(), TONE_PRESETS["none"])
        brightness_var.set(preset["brightness"])
        contrast_var.set(preset["contrast"])
        saturation_var.set(preset["saturation"])
        gamma_var.set(preset["gamma"])
        update_preview()

    def on_list_select(_event: object | None = None) -> None:
        selected = list_box.curselection()
        if selected:
            selected_image["path"] = Path(list_box.get(selected[0]))
            update_preview()

    def render_preview_canvas() -> None:
        image = preview_base["image"]
        if image is None:
            return
        zoom = max(0.25, min(float(zoom_var.get()), 8.0))
        w = max(1, int(image.width * zoom))
        h = max(1, int(image.height * zoom))
        resized = image.resize((w, h), Image.Resampling.LANCZOS)
        preview_photo["image"] = ImageTk.PhotoImage(resized)
        preview_canvas.delete("all")
        preview_canvas.create_image(0, 0, image=preview_photo["image"], anchor="nw")
        preview_canvas.configure(scrollregion=(0, 0, w, h))

    def update_preview(_event: object | None = None) -> None:
        try:
            settings = settings_from_ui()
            color_swatch.configure(background=color_to_hex(settings.key_color))
            path = selected_image["path"]
            if not path:
                return
            with Image.open(path) as im:
                combined = full_preview_pair(im, settings)
            preview_base["image"] = combined
            render_preview_canvas()
            save_current_config()
        except Exception as exc:  # noqa: BLE001
            log(tr("preview_failed", error=exc))

    def set_zoom(value: float) -> None:
        zoom_var.set(value)
        render_preview_canvas()
        save_current_config()

    def on_preview_wheel(event: object) -> None:
        delta = getattr(event, "delta", 0)
        direction = 1 if delta > 0 else -1
        set_zoom(max(0.25, min(float(zoom_var.get()) * (1.15 if direction > 0 else 1 / 1.15), 8.0)))

    def process() -> None:
        try:
            settings = settings_from_ui()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(tr("param_error"), str(exc))
            return

        input_path = Path(input_var.get())
        output_root = Path(output_var.get())
        suffix = suffix_var.get() or "_keyed"
        save_current_config()

        def worker() -> None:
            try:
                log(tr("processing"))
                count, errors = process_path(input_path, output_root, settings, recursive_var.get(), suffix)
                log(tr("done_log", count=count, output=output_root))
                for err in errors:
                    log(tr("error_prefix") + err)
                messagebox.showinfo(tr("done_title"), tr("done_msg", count=count))
            except Exception as exc:  # noqa: BLE001
                log(tr("process_failed", error=exc))
                messagebox.showerror(tr("process_failed", error=""), str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_close() -> None:
        save_current_config()
        root.destroy()

    top_bar = ttk.Frame(root, padding=(12, 10, 12, 0))
    top_bar.pack(fill="x")
    profile_label = ttk.Label(top_bar)
    bind_text(profile_label, "profile_label")
    profile_label.pack(side="left", padx=(0, 8))
    profile_buttons_frame = ttk.Frame(top_bar)
    profile_buttons_frame.pack(side="left", fill="x", expand=True)
    language_label = ttk.Label(top_bar)
    bind_text(language_label, "language_label")
    add_tooltip(language_label, "language")
    language_label.pack(side="left", padx=(10, 6))
    language_box = ttk.Combobox(
        top_bar,
        textvariable=language_var,
        values=("中文", "English"),
        state="readonly",
        width=6,
    )
    add_tooltip(language_box, "language")
    language_box.pack(side="left", padx=(0, 10))
    language_box.bind("<<ComboboxSelected>>", lambda _event: refresh_language())
    add_profile_button = ttk.Button(top_bar, command=add_profile)
    bind_text(add_profile_button, "add_profile")
    add_tooltip(add_profile_button, "add_profile")
    add_profile_button.pack(side="right")
    refresh_profile_buttons()

    main = ttk.Frame(root, padding=12)
    main.pack(fill="both", expand=True)
    controls_outer = ttk.Frame(main, width=390)
    controls_outer.pack(side="left", fill="y", padx=(0, 12))
    controls_outer.pack_propagate(False)
    controls_canvas = tk.Canvas(controls_outer, width=370, highlightthickness=0)
    controls_scrollbar = ttk.Scrollbar(controls_outer, orient="vertical", command=controls_canvas.yview)
    controls = ttk.Frame(controls_canvas)
    controls_window = controls_canvas.create_window((0, 0), window=controls, anchor="nw")
    controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
    controls_canvas.pack(side="left", fill="both", expand=True)
    controls_scrollbar.pack(side="right", fill="y")
    controls.bind("<Configure>", lambda event: controls_canvas.configure(scrollregion=controls_canvas.bbox("all")))
    controls_canvas.bind("<Configure>", lambda event: controls_canvas.itemconfigure(controls_window, width=event.width))
    controls_canvas.bind("<MouseWheel>", lambda event: controls_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
    preview = ttk.Frame(main)
    preview.pack(side="right", fill="both", expand=True)

    help_label(controls, "输入文件夹", "input")
    row = ttk.Frame(controls)
    row.pack(fill="x", pady=(2, 8))
    input_entry = ttk.Entry(row, textvariable=input_var, width=38)
    add_tooltip(input_entry, "input")
    input_entry.pack(side="left", fill="x", expand=True)
    input_button = ttk.Button(row, command=browse_input)
    bind_text(input_button, "browse")
    add_tooltip(input_button, "input")
    input_button.pack(side="left", padx=(6, 0))

    help_label(controls, "输出文件夹", "output")
    row = ttk.Frame(controls)
    row.pack(fill="x", pady=(2, 8))
    output_entry = ttk.Entry(row, textvariable=output_var, width=38)
    add_tooltip(output_entry, "output")
    output_entry.pack(side="left", fill="x", expand=True)
    output_button = ttk.Button(row, command=browse_output)
    bind_text(output_button, "browse")
    add_tooltip(output_button, "output")
    output_button.pack(side="left", padx=(6, 0))

    key_frame = ttk.LabelFrame(controls)
    bind_text(key_frame, "key_frame")
    key_frame.pack(fill="x", pady=(4, 10), padx=(0, 2))
    enable_keying_check = ttk.Checkbutton(key_frame, variable=enable_keying_var, command=update_preview)
    bind_text(enable_keying_check, "enable_keying")
    add_tooltip(enable_keying_check, "enable_keying")
    enable_keying_check.pack(anchor="w", padx=8, pady=(8, 6))

    help_label(key_frame, "关键颜色", "color")
    row = ttk.Frame(key_frame)
    row.pack(fill="x", pady=(2, 8))
    color_entry = ttk.Entry(row, textvariable=color_var, width=14)
    add_tooltip(color_entry, "color")
    color_entry.pack(side="left")
    color_swatch = tk.Label(row, width=4, relief="sunken", background=color_var.get())
    add_tooltip(color_swatch, "color")
    color_swatch.pack(side="left", padx=6)
    color_button = ttk.Button(row, command=choose_color)
    bind_text(color_button, "pick")
    add_tooltip(color_button, "color")
    color_button.pack(side="left")

    matte_controls = (
        ("低阈值", low_var, "low"),
        ("高阈值", high_var, "high"),
        ("边缘柔化", soften_var, "soften"),
        ("去溢色", despill_var, "despill"),
    )
    for text, var, key in matte_controls:
        help_label(key_frame, text, key)
        row = ttk.Frame(key_frame)
        row.pack(fill="x", pady=(2, 8))
        scale_to = 8.0 if text == "边缘柔化" else 1.0
        scale = ttk.Scale(row, from_=0.0, to=scale_to, variable=var, command=update_preview)
        add_tooltip(scale, key)
        scale.pack(side="left", fill="x", expand=True)
        value_label = ttk.Label(row, textvariable=var, width=6)
        add_tooltip(value_label, key)
        value_label.pack(side="left")

    help_label(key_frame, "抠图模式", "metric")
    metric_box = ttk.Combobox(
        key_frame,
        textvariable=metric_var,
        values=("dominance", "rgb"),
        state="readonly",
        width=18,
    )
    add_tooltip(metric_box, "metric")
    metric_box.pack(anchor="w", pady=(2, 8))
    metric_box.bind("<<ComboboxSelected>>", update_preview)

    tone_frame = ttk.LabelFrame(controls)
    bind_text(tone_frame, "tone_frame")
    tone_frame.pack(fill="x", pady=(4, 10), padx=(0, 2))
    enable_tone_check = ttk.Checkbutton(tone_frame, variable=enable_tone_var, command=update_preview)
    bind_text(enable_tone_check, "enable_tone")
    add_tooltip(enable_tone_check, "enable_tone")
    enable_tone_check.pack(anchor="w", padx=8, pady=(8, 6))

    help_label(tone_frame, "调色预设", "preset")
    preset_box = ttk.Combobox(
        tone_frame,
        textvariable=preset_var,
        values=("none", "poster_soft", "lighten", "muted"),
        state="readonly",
        width=18,
    )
    add_tooltip(preset_box, "preset")
    preset_box.pack(anchor="w", pady=(2, 8))
    preset_box.bind("<<ComboboxSelected>>", apply_preset)

    tone_controls = (
        ("亮度", brightness_var, 0.2, 2.2),
        ("对比度", contrast_var, 0.2, 2.0),
        ("饱和度", saturation_var, 0.0, 2.0),
        ("Gamma", gamma_var, 0.4, 2.2),
    )
    tone_help_keys = {"亮度": "brightness", "对比度": "contrast", "饱和度": "saturation", "Gamma": "gamma"}
    for text, var, scale_from, scale_to in tone_controls:
        key = tone_help_keys[text]
        help_label(tone_frame, text, key)
        row = ttk.Frame(tone_frame)
        row.pack(fill="x", pady=(2, 8))
        scale = ttk.Scale(row, from_=scale_from, to=scale_to, variable=var, command=update_preview)
        add_tooltip(scale, key)
        scale.pack(side="left", fill="x", expand=True)
        value_label = ttk.Label(row, textvariable=var, width=6)
        add_tooltip(value_label, key)
        value_label.pack(side="left")

    recursive_check = ttk.Checkbutton(controls, variable=recursive_var, command=refresh_file_list)
    bind_text(recursive_check, "recursive")
    add_tooltip(recursive_check, "recursive")
    recursive_check.pack(anchor="w", pady=(0, 8))

    help_label(controls, "输出后缀", "suffix")
    suffix_entry = ttk.Entry(controls, textvariable=suffix_var, width=16)
    add_tooltip(suffix_entry, "suffix")
    suffix_entry.pack(anchor="w", pady=(2, 12))
    refresh_button = ttk.Button(controls, command=refresh_file_list)
    bind_text(refresh_button, "refresh")
    refresh_button.pack(fill="x")
    process_button = ttk.Button(controls, command=process)
    bind_text(process_button, "process")
    process_button.pack(fill="x", pady=8)

    list_box = tk.Listbox(controls, width=46, height=10)
    list_box.pack(fill="both", expand=False, pady=(8, 8))
    list_box.bind("<<ListboxSelect>>", on_list_select)

    log_box = tk.Text(controls, width=46, height=8)
    log_box.pack(fill="both", expand=True)

    preview_header = ttk.Frame(preview)
    preview_header.pack(fill="x")
    preview_header_label = ttk.Label(preview_header)
    bind_text(preview_header_label, "preview_header")
    preview_header_label.pack(side="left")
    fit_button = ttk.Button(preview_header, command=lambda: set_zoom(1.0))
    bind_text(fit_button, "fit")
    add_tooltip(fit_button, "zoom")
    fit_button.pack(side="right", padx=(4, 0))
    zoom_400_button = ttk.Button(preview_header, text="400%", command=lambda: set_zoom(4.0))
    add_tooltip(zoom_400_button, "zoom")
    zoom_400_button.pack(side="right", padx=(4, 0))
    zoom_200_button = ttk.Button(preview_header, text="200%", command=lambda: set_zoom(2.0))
    add_tooltip(zoom_200_button, "zoom")
    zoom_200_button.pack(side="right", padx=(4, 0))
    zoom_100_button = ttk.Button(preview_header, text="100%", command=lambda: set_zoom(1.0))
    add_tooltip(zoom_100_button, "zoom")
    zoom_100_button.pack(side="right", padx=(4, 0))

    zoom_row = ttk.Frame(preview)
    zoom_row.pack(fill="x", pady=(8, 0))
    zoom_label = ttk.Label(zoom_row)
    bind_text(zoom_label, "zoom")
    add_tooltip(zoom_label, "zoom")
    zoom_label.pack(side="left")
    zoom_scale = ttk.Scale(zoom_row, from_=0.25, to=4.0, variable=zoom_var, command=lambda _value: (render_preview_canvas(), save_current_config()))
    add_tooltip(zoom_scale, "zoom")
    zoom_scale.pack(side="left", fill="x", expand=True, padx=8)
    zoom_value_label = ttk.Label(zoom_row, textvariable=zoom_var, width=6)
    add_tooltip(zoom_value_label, "zoom")
    zoom_value_label.pack(side="left")

    preview_canvas_frame = ttk.Frame(preview)
    preview_canvas_frame.pack(fill="both", expand=True, pady=(8, 0))
    preview_canvas = tk.Canvas(preview_canvas_frame, background="#242428", highlightthickness=0)
    preview_x_scroll = ttk.Scrollbar(preview_canvas_frame, orient="horizontal", command=preview_canvas.xview)
    preview_y_scroll = ttk.Scrollbar(preview_canvas_frame, orient="vertical", command=preview_canvas.yview)
    preview_canvas.configure(xscrollcommand=preview_x_scroll.set, yscrollcommand=preview_y_scroll.set)
    preview_canvas.grid(row=0, column=0, sticky="nsew")
    preview_y_scroll.grid(row=0, column=1, sticky="ns")
    preview_x_scroll.grid(row=1, column=0, sticky="ew")
    preview_canvas_frame.columnconfigure(0, weight=1)
    preview_canvas_frame.rowconfigure(0, weight=1)
    preview_canvas.bind("<MouseWheel>", on_preview_wheel)

    for var in (color_var, low_var, high_var, soften_var, despill_var, metric_var, brightness_var, contrast_var, saturation_var, gamma_var):
        try:
            var.trace_add("write", update_preview)
        except Exception:
            pass

    refresh_file_list()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch color keyer with DeltaKey-style low/high thresholds.")
    parser.add_argument("input", nargs="?", help="Input image file or folder. Omit with --gui.")
    parser.add_argument("-o", "--output", help="Output folder. Default: <input>/_keyed_output")
    parser.add_argument("--no-key", action="store_true", help="Disable keying and keep the original alpha.")
    parser.add_argument("--no-tone", action="store_true", help="Disable tone/color adjustment.")
    parser.add_argument("-c", "--color", default="#00FF00", help="Key color, for example #00FF00 or 0,255,0.")
    parser.add_argument("--low", type=float, default=0.30, help="Low threshold in 0-1 range.")
    parser.add_argument("--high", type=float, default=0.90, help="High threshold in 0-1 range.")
    parser.add_argument("--soften", type=float, default=0.0, help="Optional alpha blur radius in pixels.")
    parser.add_argument("--despill", type=float, default=0.0, help="Optional key-color spill suppression, 0-1.")
    parser.add_argument(
        "--metric",
        choices=("dominance", "rgb"),
        default="dominance",
        help="Keying metric. dominance is best for green/blue screens; rgb keeps the old RGB-distance behavior.",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(TONE_PRESETS),
        default="none",
        help="Tone preset: none, poster_soft, lighten, or muted.",
    )
    parser.add_argument("--brightness", type=float, default=None, help="Tone brightness multiplier. 1 keeps the source.")
    parser.add_argument("--contrast", type=float, default=None, help="Tone contrast multiplier. 1 keeps the source.")
    parser.add_argument("--saturation", type=float, default=None, help="Tone saturation multiplier. 1 keeps the source.")
    parser.add_argument("--gamma", type=float, default=None, help="Tone gamma. Lower than 1 brightens midtones.")
    parser.add_argument("-r", "--recursive", action="store_true", help="Process subfolders.")
    parser.add_argument("--suffix", default="_keyed", help="Output filename suffix.")
    parser.add_argument("--gui", action="store_true", help="Open the graphical interface.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.gui or not args.input:
        run_gui()
        return 0

    input_path = Path(args.input)
    output = Path(args.output) if args.output else (input_path.parent if input_path.is_file() else input_path) / "_keyed_output"
    preset = TONE_PRESETS[args.preset]
    settings = KeyerSettings(
        enable_keying=not args.no_key,
        enable_tone=not args.no_tone,
        key_color=parse_color(args.color),
        low=args.low,
        high=args.high,
        soften=args.soften,
        despill=args.despill,
        metric=args.metric,
        brightness=args.brightness if args.brightness is not None else preset["brightness"],
        contrast=args.contrast if args.contrast is not None else preset["contrast"],
        saturation=args.saturation if args.saturation is not None else preset["saturation"],
        gamma=args.gamma if args.gamma is not None else preset["gamma"],
    )
    count, errors = process_path(input_path, output, settings, args.recursive, args.suffix)
    for err in errors:
        print("ERROR:", err, file=sys.stderr)
    print(f"Done. Wrote {count} PNG file(s) to {output}")
    return 1 if errors and count == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
