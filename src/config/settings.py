"""
应用配置。

普通应用设置从环境变量/.env 读取；Figma bridge 与默认 client 设置从根目录
figma_bridge.config.json 读取。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.services.contracts import DeliveryProfile


def _env_opt(name: str) -> str | None:
    """读取可选字符串环境变量：未设置或空白一律返回 None。"""
    value = os.getenv(name)
    return value if value and value.strip() else None


def _vision_base_urls_default() -> tuple[str, ...]:
    configured = os.getenv("VISION_BASE_URLS", "")
    if configured.strip():
        values = tuple(
            item.strip().rstrip("/") for item in configured.split(",") if item.strip()
        )
        if values:
            return values
    return (
        os.getenv("VISION_BASE_URL", "https://www.acctoken.com/v1").strip().rstrip("/"),
    )


def _bridge_url_default() -> str:
    from src.app.services.bridge_config import load_bridge_config

    bridge_config = load_bridge_config()
    if bridge_config.allow_env_overrides:
        configured = os.getenv("FIGMA_BRIDGE_URL", "").strip()
        if configured:
            return configured
    return bridge_config.client.url


def _delivery_profile_default() -> DeliveryProfile:
    value = (os.getenv("DELIVERY_PROFILE") or "legacy").strip() or "legacy"
    if value not in {"legacy", "contract-v2"}:
        raise ValueError("DELIVERY_PROFILE must be one of: legacy, contract-v2")
    return value  # type: ignore[return-value]


def _image_enrichment_mode_default() -> str:
    value = (os.getenv("IMAGE_ENRICHMENT_MODE") or "off").strip().lower()
    if value not in {"off", "analyze", "apply"}:
        raise ValueError("IMAGE_ENRICHMENT_MODE must be one of: off, analyze, apply")
    return value


def _grounding_fidelity_mode_default() -> str:
    value = os.getenv("GROUNDING_FIDELITY_MODE") or "off"
    if value not in {"off", "high"}:
        raise ValueError("GROUNDING_FIDELITY_MODE must be one of: off, high")
    return value


@dataclass(frozen=True)
class Config:
    """运行时可配置的参数。"""

    # --- 截图 ---
    capture_monitor: int = field(
        default_factory=lambda: int(os.getenv("CAPTURE_MONITOR", "0"))
    )
    capture_region: str | None = field(
        default_factory=lambda: os.getenv("CAPTURE_REGION")
    )  # "x,y,w,h"
    screenshot_max_dim: int = field(
        default_factory=lambda: int(os.getenv("SCREENSHOT_MAX_DIM", "1600"))
    )

    # --- LLM（仅旧流程 ReconstructAgent / call_vision_llm 使用） ---
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    )
    llm_api_key: str | None = field(default_factory=lambda: _env_opt("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o"))
    llm_temperature: float = field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.2"))
    )
    llm_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "4096"))
    )
    llm_timeout: int = field(
        default_factory=lambda: int(os.getenv("LLM_TIMEOUT", "120"))
    )

    # --- 新流程视觉/文本模型（acctoken 网关，OpenAI 兼容） ---
    vision_base_url: str = field(
        default_factory=lambda: os.getenv(
            "VISION_BASE_URL", "https://www.acctoken.com/v1"
        )
    )
    vision_base_urls: tuple[str, ...] = field(default_factory=_vision_base_urls_default)
    vision_api_key: str | None = field(
        default_factory=lambda: _env_opt("VISION_API_KEY")
    )
    vision_model: str = field(
        default_factory=lambda: os.getenv("VISION_MODEL", "qwen3-vl-plus")
    )
    vision_native_grounding: bool = field(
        default_factory=lambda: os.getenv("VISION_NATIVE_GROUNDING", "false").lower()
        in ("1", "true", "yes")
    )
    vision_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("VISION_MAX_TOKENS", "16000"))
    )
    vision_timeout: int = field(
        default_factory=lambda: int(os.getenv("VISION_TIMEOUT", "120"))
    )
    vision_tile_max_height: int = field(
        default_factory=lambda: int(os.getenv("VISION_TILE_MAX_HEIGHT", "4096"))
    )
    vision_tile_overlap: int = field(
        default_factory=lambda: int(os.getenv("VISION_TILE_OVERLAP", "256"))
    )
    vision_max_image_bytes: int = field(
        default_factory=lambda: int(
            os.getenv("VISION_MAX_IMAGE_BYTES", str(25 * 1024 * 1024))
        )
    )
    vision_max_response_bytes: int = field(
        default_factory=lambda: int(
            os.getenv("VISION_MAX_RESPONSE_BYTES", str(5 * 1024 * 1024))
        )
    )
    vision_max_attempts: int = field(
        default_factory=lambda: int(os.getenv("VISION_MAX_ATTEMPTS", "3"))
    )
    vision_retry_base_ms: int = field(
        default_factory=lambda: int(os.getenv("VISION_RETRY_BASE_MS", "250"))
    )
    vision_max_backoff_ms: int = field(
        default_factory=lambda: int(os.getenv("VISION_MAX_BACKOFF_MS", "4000"))
    )
    vision_jitter_ratio: float = field(
        default_factory=lambda: float(os.getenv("VISION_JITTER_RATIO", "0.25"))
    )
    vision_breaker_failure_threshold: int = field(
        default_factory=lambda: int(os.getenv("VISION_BREAKER_FAILURE_THRESHOLD", "3"))
    )
    vision_breaker_cooldown_seconds: float = field(
        default_factory=lambda: float(
            os.getenv("VISION_BREAKER_COOLDOWN_SECONDS", "30")
        )
    )
    vision_cache_max_entries: int = field(
        default_factory=lambda: int(os.getenv("VISION_CACHE_MAX_ENTRIES", "64"))
    )
    vision_cache_ttl_seconds: float = field(
        default_factory=lambda: float(os.getenv("VISION_CACHE_TTL_SECONDS", "300"))
    )
    vision_cache_namespace: str = field(
        default_factory=lambda: os.getenv("VISION_CACHE_NAMESPACE", "default")
    )
    # D: reproducibility contract.  A deterministic request plus a persistent
    # content-addressed cache makes two full reruns of the same image produce
    # the same perception artefacts.
    vision_temperature: float = field(
        default_factory=lambda: float(os.getenv("VISION_TEMPERATURE", "0.1"))
    )
    vision_seed: int = field(
        default_factory=lambda: int(os.getenv("VISION_SEED", "20261108"))
    )
    vision_send_seed: bool = field(
        default_factory=lambda: os.getenv("VISION_SEND_SEED", "false").lower()
        in ("1", "true", "yes")
    )
    vision_persistent_cache: bool = field(
        default_factory=lambda: os.getenv("VISION_PERSISTENT_CACHE", "true").lower()
        in ("1", "true", "yes")
    )
    vision_persistent_cache_dir: str = field(
        default_factory=lambda: os.getenv(
            "VISION_PERSISTENT_CACHE_DIR", ".vision_cache"
        )
    )
    text_base_url: str = field(
        default_factory=lambda: os.getenv(
            "TEXT_BASE_URL", "https://www.acctoken.com/v1"
        )
    )
    text_api_key: str | None = field(default_factory=lambda: _env_opt("TEXT_API_KEY"))
    text_model: str = field(
        default_factory=lambda: os.getenv("TEXT_MODEL", "deepseek-v4-flash")
    )
    text_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("TEXT_MAX_TOKENS", "16000"))
    )
    text_timeout: int = field(
        default_factory=lambda: int(os.getenv("TEXT_TIMEOUT", "120"))
    )
    image_generation_model: str = field(
        default_factory=lambda: os.getenv("IMAGE_GENERATION_MODEL", "gpt-image-1")
    )
    image_generation_base_url: str | None = field(
        default_factory=lambda: _env_opt("IMAGE_GENERATION_BASE_URL")
    )
    image_generation_api_key: str | None = field(
        default_factory=lambda: _env_opt("IMAGE_GENERATION_API_KEY")
    )
    image_generation_timeout: int = field(
        default_factory=lambda: int(os.getenv("IMAGE_GENERATION_TIMEOUT", "20"))
    )
    image_enrichment_mode: str = field(default_factory=_image_enrichment_mode_default)
    grounding_fidelity_mode: str = field(
        default_factory=_grounding_fidelity_mode_default
    )
    grounding_repair_max_rounds: int = field(
        default_factory=lambda: int(os.getenv("GROUNDING_REPAIR_MAX_ROUNDS", "3"))
    )
    grounding_repair_max_extra_calls: int = field(
        default_factory=lambda: int(os.getenv("GROUNDING_REPAIR_MAX_EXTRA_CALLS", "6"))
    )
    grounding_repair_min_region_gain: float = field(
        default_factory=lambda: float(
            os.getenv("GROUNDING_REPAIR_MIN_REGION_GAIN", "0.5")
        )
    )
    grounding_region_regression_tolerance: float = field(
        default_factory=lambda: float(
            os.getenv("GROUNDING_REGION_REGRESSION_TOLERANCE", "0.2")
        )
    )

    # --- SoM -> DesignSpec 分批生成（长页面防截断；每批 60-100 个 id 推荐） ---
    som_batch_enabled: bool = field(
        default_factory=lambda: os.getenv("SOM_BATCH_ENABLED", "true").lower()
        in ("1", "true", "yes")
    )
    som_batch_size: int = field(
        default_factory=lambda: int(os.getenv("SOM_BATCH_SIZE", "80"))
    )
    som_batch_max_rounds: int = field(
        default_factory=lambda: int(os.getenv("SOM_BATCH_MAX_ROUNDS", "3"))
    )
    som_batch_min_coverage: float = field(
        default_factory=lambda: float(os.getenv("SOM_BATCH_MIN_COVERAGE", "0.9"))
    )
    # 像素级颜色校正（预留接口，默认关；实现见 llm_service.backfill_colors_from_screenshot）
    som_color_backfill: bool = field(
        default_factory=lambda: os.getenv("SOM_COLOR_BACKFILL", "false").lower()
        in ("1", "true", "yes")
    )
    # --- 新流程路由与抓取 ---
    route_default: str = field(default_factory=lambda: os.getenv("ROUTE", "auto"))
    playwright_browser: str = field(
        default_factory=lambda: os.getenv("PLAYWRIGHT_BROWSER", "chromium")
    )
    playwright_viewport_width: int = field(
        default_factory=lambda: int(os.getenv("PLAYWRIGHT_VIEWPORT_WIDTH", "1440"))
    )
    playwright_viewport_height: int = field(
        default_factory=lambda: int(os.getenv("PLAYWRIGHT_VIEWPORT_HEIGHT", "900"))
    )
    playwright_headless: bool = field(
        default_factory=lambda: os.getenv("PLAYWRIGHT_HEADLESS", "true").lower()
        in ("1", "true", "yes")
    )
    playwright_locale: str = field(
        default_factory=lambda: os.getenv("PLAYWRIGHT_LOCALE", "zh-CN")
    )
    playwright_timezone: str = field(
        default_factory=lambda: os.getenv("PLAYWRIGHT_TIMEZONE", "Asia/Shanghai")
    )
    playwright_storage_state: str | None = field(
        default_factory=lambda: _env_opt("PLAYWRIGHT_STORAGE_STATE")
    )
    # 真实浏览器会话降级：持久化用户目录优先（可复用已登录/已过验证的会话），
    # 其次 storage_state，最后退回全新有头 Chromium。验证码/人机验证不自动破解。
    playwright_user_data_dir: str | None = field(
        default_factory=lambda: _env_opt("PLAYWRIGHT_USER_DATA_DIR")
    )
    playwright_headed_fallback: bool = field(
        default_factory=lambda: os.getenv("PLAYWRIGHT_HEADED_FALLBACK", "true").lower()
        in ("1", "true", "yes")
    )
    device_scale_factor: int = field(
        default_factory=lambda: int(os.getenv("DEVICE_SCALE_FACTOR", "1"))
    )
    wait_networkidle_timeout: int = field(
        default_factory=lambda: int(os.getenv("WAIT_NETWORKIDLE_TIMEOUT", "30000"))
    )

    # --- 渲染输出 ---
    delivery_profile: DeliveryProfile = field(default_factory=_delivery_profile_default)
    # SVG 文本兜底字体栈（DesignSpec 里带 fontFamily 时优先用节点自身的）。
    # 留空/未设置时用 svg_adapter.DEFAULT_FONT_STACK。
    svg_font_stack: str | None = field(
        default_factory=lambda: _env_opt("SVG_FONT_STACK")
    )
    # 文本基线的像素级微调（±1px）：渲染一遍 → 与截图逐元素比 → 只接受明确变好的
    # 1px 位移并重渲染（见 services/rendering/text_align.py）；置 0 关闭。
    text_align: bool = field(
        default_factory=lambda: os.getenv("TEXT_ALIGN", "true").lower()
        in ("1", "true", "yes")
    )
    dom_text_model_v2: bool = field(
        default_factory=lambda: os.getenv("DOM_TEXT_MODEL_V2", "true").lower()
        in ("1", "true", "yes")
    )
    dom_semantic_components: bool = field(
        default_factory=lambda: os.getenv("DOM_SEMANTIC_COMPONENTS", "true").lower()
        in ("1", "true", "yes")
    )
    dom_semantic_component_instances: bool = field(
        default_factory=lambda: os.getenv(
            "DOM_SEMANTIC_COMPONENT_INSTANCES", "true"
        ).lower()
        in ("1", "true", "yes")
    )
    dom_network_asset_recovery: bool = field(
        default_factory=lambda: os.getenv("DOM_NETWORK_ASSET_RECOVERY", "false").lower()
        in ("1", "true", "yes")
    )
    dom_route_quality_strict: bool = field(
        default_factory=lambda: os.getenv("DOM_ROUTE_QUALITY_STRICT", "false").lower()
        in ("1", "true", "yes")
    )

    # --- 视觉提取 ---
    cv_resize_long_edge: int = field(
        default_factory=lambda: int(os.getenv("CV_RESIZE_LONG_EDGE", "1280"))
    )
    cv_min_component_area: int = field(
        default_factory=lambda: int(os.getenv("CV_MIN_COMPONENT_AREA", "80"))
    )
    cv_max_component_area_ratio: float = field(
        default_factory=lambda: float(os.getenv("CV_MAX_COMPONENT_AREA_RATIO", "0.95"))
    )
    cv_canny_low: int = field(
        default_factory=lambda: int(os.getenv("CV_CANNY_LOW", "30"))
    )
    cv_canny_high: int = field(
        default_factory=lambda: int(os.getenv("CV_CANNY_HIGH", "90"))
    )

    # --- OCR（可选） ---
    ocr_engine: str = field(
        default_factory=lambda: os.getenv("OCR_ENGINE", "easyocr")
    )  # easyocr | tesseract | none
    ocr_lang: str = field(default_factory=lambda: os.getenv("OCR_LANG", "chi_sim+eng"))
    tesseract_cmd: str | None = field(
        default_factory=lambda: os.getenv("TESSERACT_CMD")
    )

    # --- OmniParser 本地服务 ---
    omniparser_enabled: bool = field(
        default_factory=lambda: os.getenv("OMNIPARSER_ENABLED", "false").lower()
        in ("1", "true", "yes")
    )
    omniparser_url: str = field(
        default_factory=lambda: os.getenv("OMNIPARSER_URL", "http://127.0.0.1:8000")
    )
    omniparser_timeout: int = field(
        default_factory=lambda: int(os.getenv("OMNIPARSER_TIMEOUT", "120"))
    )
    omniparser_box_threshold: float = field(
        default_factory=lambda: float(os.getenv("OMNIPARSER_BOX_THRESHOLD", "0.05"))
    )
    omniparser_iou_threshold: float = field(
        default_factory=lambda: float(os.getenv("OMNIPARSER_IOU_THRESHOLD", "0.7"))
    )
    omniparser_use_paddleocr: bool = field(
        default_factory=lambda: os.getenv("OMNIPARSER_USE_PADDLEOCR", "false").lower()
        in ("1", "true", "yes")
    )
    omniparser_fallback: bool = field(
        default_factory=lambda: os.getenv("OMNIPARSER_FALLBACK", "true").lower()
        in ("1", "true", "yes")
    )

    # --- 红框标注（用户手动框选图片区） ---
    red_box_enabled: bool = field(
        default_factory=lambda: os.getenv("RED_BOX_ENABLED", "true").lower()
        in ("1", "true", "yes")
    )
    red_box_hue_low1: int = field(
        default_factory=lambda: int(os.getenv("RED_BOX_HUE_LOW1", "0"))
    )
    red_box_hue_high1: int = field(
        default_factory=lambda: int(os.getenv("RED_BOX_HUE_HIGH1", "10"))
    )
    red_box_hue_low2: int = field(
        default_factory=lambda: int(os.getenv("RED_BOX_HUE_LOW2", "170"))
    )
    red_box_hue_high2: int = field(
        default_factory=lambda: int(os.getenv("RED_BOX_HUE_HIGH2", "180"))
    )
    red_box_saturation_min: int = field(
        default_factory=lambda: int(os.getenv("RED_BOX_SATURATION_MIN", "100"))
    )
    red_box_value_min: int = field(
        default_factory=lambda: int(os.getenv("RED_BOX_VALUE_MIN", "80"))
    )
    red_box_min_area: int = field(
        default_factory=lambda: int(os.getenv("RED_BOX_MIN_AREA", "500"))
    )
    red_box_max_fill_ratio: float = field(
        default_factory=lambda: float(os.getenv("RED_BOX_MAX_FILL_RATIO", "0.5"))
    )
    red_box_shrink: int = field(
        default_factory=lambda: int(os.getenv("RED_BOX_SHRINK", "3"))
    )
    red_box_overlap_threshold: float = field(
        default_factory=lambda: float(os.getenv("RED_BOX_OVERLAP_THRESHOLD", "0.5"))
    )

    # --- 原型工具 ---
    prototype_tool: str = field(
        default_factory=lambda: os.getenv("PROTOTYPE_TOOL", "svg")
    )  # svg | figma | jsdesign | mockingbot | axure
    figma_bridge_url: str = field(default_factory=_bridge_url_default)
    jsdesign_api_base: str = field(
        default_factory=lambda: os.getenv("JSDESIGN_API_BASE", "")
    )
    jsdesign_token: str | None = field(
        default_factory=lambda: os.getenv("JSDESIGN_TOKEN")
    )
    mockingbot_api_base: str = field(
        default_factory=lambda: os.getenv("MOCKINGBOT_API_BASE", "")
    )
    mockingbot_token: str | None = field(
        default_factory=lambda: os.getenv("MOCKINGBOT_TOKEN")
    )

    # --- 输出 ---
    output_dir: Path = field(
        default_factory=lambda: Path(os.getenv("OUTPUT_DIR", "./output"))
    )
    debug: bool = field(
        default_factory=lambda: os.getenv("DEBUG", "false").lower()
        in ("1", "true", "yes")
    )
    save_intermediate: bool = field(
        default_factory=lambda: os.getenv("SAVE_INTERMEDIATE", "true").lower()
        in ("1", "true", "yes")
    )

    def __post_init__(self) -> None:
        if self.grounding_fidelity_mode not in {"off", "high"}:
            raise ValueError("GROUNDING_FIDELITY_MODE must be one of: off, high")
        if (
            self.grounding_fidelity_mode == "high"
            and self.image_enrichment_mode != "apply"
        ):
            raise ValueError(
                "GROUNDING_FIDELITY_MODE=high requires " "IMAGE_ENRICHMENT_MODE=apply"
            )
        if self.grounding_repair_max_rounds <= 0:
            raise ValueError("grounding_repair_max_rounds must be positive")
        if self.grounding_repair_max_extra_calls <= 0:
            raise ValueError("grounding_repair_max_extra_calls must be positive")
        if self.grounding_repair_min_region_gain <= 0:
            raise ValueError("grounding_repair_min_region_gain must be positive")
        if self.grounding_region_regression_tolerance < 0:
            raise ValueError(
                "grounding_region_regression_tolerance must be non-negative"
            )

    def repair_round_budget(self) -> int:
        """Return the effective round budget, capped by the product contract."""
        return min(int(self.grounding_repair_max_rounds), 3)

    def repair_call_budget(self) -> int:
        """Return the effective local-call budget, capped at six."""
        return min(int(self.grounding_repair_max_extra_calls), 6)

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
