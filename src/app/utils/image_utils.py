"""图像加载、保存、编码、缩放等工具函数。"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np
from PIL import Image

try:
    import mss
except Exception:
    mss = None

try:
    import pyautogui
except Exception:
    pyautogui = None

logger = logging.getLogger(__name__)


def load_image(path: str | Path) -> np.ndarray:
    """读取图片文件并返回 OpenCV BGR 格式 ndarray。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"图片不存在: {path}")
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"无法读取图片: {path}")
    return frame


def save_image(frame: np.ndarray, path: Path) -> None:
    """保存 OpenCV BGR 图像到文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)
    logger.info(f"图像已保存: {path}")


def resize_frame(frame: np.ndarray, long_edge: int) -> np.ndarray:
    """保持宽高比缩放，长边不超过指定像素。"""
    frame_h, frame_w = frame.shape[:2]
    if max(frame_h, frame_w) <= long_edge:
        return frame
    scale = long_edge / max(frame_h, frame_w)
    new_w = int(frame_w * scale)
    new_h = int(frame_h * scale)
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)


def encode_image_base64(frame: np.ndarray, fmt: str = ".png", quality: int = 95) -> str:
    """OpenCV BGR 图像 -> base64 字符串，默认 PNG 无损。"""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    buf = io.BytesIO()
    if fmt.lower() in (".jpg", ".jpeg"):
        pil_img.save(buf, format="JPEG", quality=quality)
    else:
        pil_img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _parse_region(region: str | None) -> dict | None:
    if not region:
        return None
    try:
        left, top, width, height = map(int, region.split(","))
        return {"left": left, "top": top, "width": width, "height": height}
    except Exception as exc:
        logger.warning(f"区域解析失败: {exc}")
        return None


def capture_screen(
    monitor: int = 0,
    region: str | None = None,
    max_dim: int | None = None,
) -> np.ndarray:
    """截取屏幕并返回 OpenCV BGR 格式 ndarray。"""
    bbox = _parse_region(region)
    img = None

    if mss is not None:
        try:
            with mss.mss() as sct:
                if bbox is None:
                    monitors = sct.monitors
                    if monitor < 0 or monitor >= len(monitors):
                        raise IndexError(f"monitor index {monitor} 越界，可用 {len(monitors)}")
                    bbox = monitors[monitor]
                raw = sct.grab(bbox)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except Exception as exc:
            logger.warning(f"mss 截图失败，尝试 pyautogui: {exc}")

    if img is None and pyautogui is not None:
        try:
            if bbox is not None:
                img = pyautogui.screenshot(
                    region=(bbox["left"], bbox["top"], bbox["width"], bbox["height"])
                )
            else:
                img = pyautogui.screenshot()
        except Exception as exc:
            logger.warning(f"pyautogui 截图失败: {exc}")

    if img is None:
        raise RuntimeError("屏幕截图失败，请检查 mss 或 pyautogui 是否已安装")

    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    if max_dim and max(frame.shape[:2]) > max_dim:
        frame = resize_frame(frame, max_dim)
    return frame


def draw_debug_overlay(frame: np.ndarray, components: list) -> np.ndarray:
    """在图像上绘制检测框与标签，用于人工校验。"""
    out = frame.copy()
    colors = {
        "button": (0, 128, 255),
        "text": (255, 255, 0),
        "input": (0, 255, 0),
        "image": (255, 0, 255),
        "container": (128, 128, 128),
        "avatar": (0, 255, 255),
        "divider": (0, 0, 255),
        "unknown": (200, 200, 200),
    }
    for comp in components:
        x, y, w, h = comp.bbox
        color = colors.get(comp.comp_type, (200, 200, 200))
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
        label = f"{comp.comp_type}:{comp.id}"
        if comp.text:
            label += f" {comp.text[:10]}"
        cv2.putText(out, label, (x, max(y - 5, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return out
