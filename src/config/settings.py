"""
全局配置（环境变量 > 默认值）。
建议在项目根目录放置 .env 文件并加载。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """运行时可配置的参数。"""

    # --- 截图 ---
    capture_monitor: int = field(default_factory=lambda: int(os.getenv("CAPTURE_MONITOR", "0")))
    capture_region: str | None = field(default_factory=lambda: os.getenv("CAPTURE_REGION"))  # "x,y,w,h"
    screenshot_max_dim: int = field(default_factory=lambda: int(os.getenv("SCREENSHOT_MAX_DIM", "1600")))

    # --- LLM ---
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_api_key: str | None = field(default_factory=lambda: os.getenv("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o"))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.2")))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "4096")))
    llm_timeout: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT", "120")))

    # --- 新流程视觉/文本模型（acctoken 网关，OpenAI 兼容） ---
    vision_base_url: str = field(default_factory=lambda: os.getenv("VISION_BASE_URL", "https://www.acctoken.com/v1"))
    vision_api_key: str | None = field(default_factory=lambda: os.getenv("VISION_API_KEY"))
    vision_model: str = field(default_factory=lambda: os.getenv("VISION_MODEL", "qwen3-vl-plus"))
    vision_native_grounding: bool = field(default_factory=lambda: os.getenv("VISION_NATIVE_GROUNDING", "false").lower() in ("1", "true", "yes"))
    text_base_url: str = field(default_factory=lambda: os.getenv("TEXT_BASE_URL", "https://www.acctoken.com/v1"))
    text_api_key: str | None = field(default_factory=lambda: os.getenv("TEXT_API_KEY"))
    text_model: str = field(default_factory=lambda: os.getenv("TEXT_MODEL", "deepseek-v4-flash"))

    # --- 新流程路由与抓取 ---
    route_default: str = field(default_factory=lambda: os.getenv("ROUTE", "auto"))
    playwright_viewport_width: int = field(default_factory=lambda: int(os.getenv("PLAYWRIGHT_VIEWPORT_WIDTH", "1440")))
    playwright_viewport_height: int = field(default_factory=lambda: int(os.getenv("PLAYWRIGHT_VIEWPORT_HEIGHT", "900")))
    playwright_headless: bool = field(default_factory=lambda: os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() in ("1", "true", "yes"))
    device_scale_factor: int = field(default_factory=lambda: int(os.getenv("DEVICE_SCALE_FACTOR", "1")))
    enrich_visual: bool = field(default_factory=lambda: os.getenv("ENRICH_VISUAL", "false").lower() in ("1", "true", "yes"))
    wait_networkidle_timeout: int = field(default_factory=lambda: int(os.getenv("WAIT_NETWORKIDLE_TIMEOUT", "30000")))

    # --- 视觉提取 ---
    cv_resize_long_edge: int = field(default_factory=lambda: int(os.getenv("CV_RESIZE_LONG_EDGE", "1280")))
    cv_min_component_area: int = field(default_factory=lambda: int(os.getenv("CV_MIN_COMPONENT_AREA", "80")))
    cv_max_component_area_ratio: float = field(default_factory=lambda: float(os.getenv("CV_MAX_COMPONENT_AREA_RATIO", "0.95")))
    cv_canny_low: int = field(default_factory=lambda: int(os.getenv("CV_CANNY_LOW", "30")))
    cv_canny_high: int = field(default_factory=lambda: int(os.getenv("CV_CANNY_HIGH", "90")))

    # --- OCR（可选） ---
    ocr_engine: str = field(default_factory=lambda: os.getenv("OCR_ENGINE", "easyocr"))  # easyocr | tesseract | none
    ocr_lang: str = field(default_factory=lambda: os.getenv("OCR_LANG", "chi_sim+eng"))
    tesseract_cmd: str | None = field(default_factory=lambda: os.getenv("TESSERACT_CMD"))

    # --- OmniParser 本地服务 ---
    omniparser_enabled: bool = field(default_factory=lambda: os.getenv("OMNIPARSER_ENABLED", "false").lower() in ("1", "true", "yes"))
    omniparser_url: str = field(default_factory=lambda: os.getenv("OMNIPARSER_URL", "http://127.0.0.1:8000"))
    omniparser_timeout: int = field(default_factory=lambda: int(os.getenv("OMNIPARSER_TIMEOUT", "120")))
    omniparser_box_threshold: float = field(default_factory=lambda: float(os.getenv("OMNIPARSER_BOX_THRESHOLD", "0.05")))
    omniparser_iou_threshold: float = field(default_factory=lambda: float(os.getenv("OMNIPARSER_IOU_THRESHOLD", "0.7")))
    omniparser_use_paddleocr: bool = field(default_factory=lambda: os.getenv("OMNIPARSER_USE_PADDLEOCR", "false").lower() in ("1", "true", "yes"))
    omniparser_fallback: bool = field(default_factory=lambda: os.getenv("OMNIPARSER_FALLBACK", "true").lower() in ("1", "true", "yes"))

    # --- 红框标注（用户手动框选图片区） ---
    red_box_enabled: bool = field(default_factory=lambda: os.getenv("RED_BOX_ENABLED", "true").lower() in ("1", "true", "yes"))
    red_box_hue_low1: int = field(default_factory=lambda: int(os.getenv("RED_BOX_HUE_LOW1", "0")))
    red_box_hue_high1: int = field(default_factory=lambda: int(os.getenv("RED_BOX_HUE_HIGH1", "10")))
    red_box_hue_low2: int = field(default_factory=lambda: int(os.getenv("RED_BOX_HUE_LOW2", "170")))
    red_box_hue_high2: int = field(default_factory=lambda: int(os.getenv("RED_BOX_HUE_HIGH2", "180")))
    red_box_saturation_min: int = field(default_factory=lambda: int(os.getenv("RED_BOX_SATURATION_MIN", "100")))
    red_box_value_min: int = field(default_factory=lambda: int(os.getenv("RED_BOX_VALUE_MIN", "80")))
    red_box_min_area: int = field(default_factory=lambda: int(os.getenv("RED_BOX_MIN_AREA", "500")))
    red_box_max_fill_ratio: float = field(default_factory=lambda: float(os.getenv("RED_BOX_MAX_FILL_RATIO", "0.5")))
    red_box_shrink: int = field(default_factory=lambda: int(os.getenv("RED_BOX_SHRINK", "3")))
    red_box_overlap_threshold: float = field(default_factory=lambda: float(os.getenv("RED_BOX_OVERLAP_THRESHOLD", "0.5")))

    # --- 原型工具 ---
    prototype_tool: str = field(default_factory=lambda: os.getenv("PROTOTYPE_TOOL", "svg"))  # svg | figma | jsdesign | mockingbot
    figma_bridge_url: str = field(default_factory=lambda: os.getenv("FIGMA_BRIDGE_URL", "ws://localhost:8765"))
    jsdesign_api_base: str = field(default_factory=lambda: os.getenv("JSDESIGN_API_BASE", ""))
    jsdesign_token: str | None = field(default_factory=lambda: os.getenv("JSDESIGN_TOKEN"))
    mockingbot_api_base: str = field(default_factory=lambda: os.getenv("MOCKINGBOT_API_BASE", ""))
    mockingbot_token: str | None = field(default_factory=lambda: os.getenv("MOCKINGBOT_TOKEN"))

    # --- 输出 ---
    output_dir: Path = field(default_factory=lambda: Path(os.getenv("OUTPUT_DIR", "./output")))
    debug: bool = field(default_factory=lambda: os.getenv("DEBUG", "false").lower() in ("1", "true", "yes"))
    save_intermediate: bool = field(default_factory=lambda: os.getenv("SAVE_INTERMEDIATE", "true").lower() in ("1", "true", "yes"))

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    """从 .env 文件加载环境变量（如果存在），返回配置对象。"""
    env_path = Path(".env")
    if env_path.exists():
        # 简单解析 KEY=VALUE，不依赖 python-dotenv
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return Config()
