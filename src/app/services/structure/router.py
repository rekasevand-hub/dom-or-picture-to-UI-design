# -*- coding: utf-8 -*-
"""路由决策：输入形态 × 用户选择 → 候选路线（显式=单候选+校验，auto=回退链）。"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import Config


_GROUNDING_UNAVAILABLE_TYPES = {
    "APIConnectionError",
    "APITimeoutError",
    "AuthenticationError",
    "InternalServerError",
    "RateLimitError",
    "ServiceUnavailableError",
    "TimeoutError",
    "ConnectionError",
    "ConnectionRefusedError",
    "GroundingUnavailableError",
}

#: 对外唯一官方路由名：截图 → 纯 CV 物理感知（RapidOCR + OmniParser + 容器）。
ROUTE_OMNI_CV = "omni-cv"
#: `--route` 的公开可选值。`--help` 里出现的就是这三个；`cv` / `grounding` 是
#: 内部实现策略名，不再作为对外入口。
PUBLIC_ROUTES = ("auto", "dom", ROUTE_OMNI_CV)
#: 兼容别名 → 规范名。只做映射，不进 `choices`，`--help` 里看不到。
ROUTE_ALIASES = {"physical": ROUTE_OMNI_CV}


def normalize_route(value: str | None, *, announce: bool = True) -> str | None:
    """Map a historical route name to its canonical one, announcing the move.

    `physical` was the stage-three name for exactly this chain; scripts and
    frozen regression commands still pass it.  It keeps working, but the CLI
    says so and points at the spelling the docs now use.
    """
    if not value:
        return value
    text = str(value).strip()
    canonical = ROUTE_ALIASES.get(text)
    if canonical is None:
        return text
    if announce:
        import sys

        print(
            f"[deprecated] --route {text} 已更名为 --route {canonical}"
            f"（别名本次仍生效，后续版本移除）",
            file=sys.stderr,
        )
    return canonical


def grounding_fallback_reason(exc: BaseException) -> str | None:
    """Return a CV-fallback reason only for Grounding service unavailability."""
    error_type = type(exc).__name__
    if error_type in _GROUNDING_UNAVAILABLE_TYPES:
        return "grounding-service-unavailable"
    text = str(exc or "").lower()
    if any(
        token in text
        for token in (
            "connection refused",
            "connection reset",
            "request timed out",
            "timed out",
            "temporarily unavailable",
            "service unavailable",
            "rate limit",
            "too many requests",
            "unauthorized",
            "401",
            "429",
            "502",
            "503",
            "504",
        )
    ):
        return "grounding-service-unavailable"
    return None


def route_order(
    input_kind: str, requested: str | None, cfg: "Config", have_dom: bool
) -> list[str]:
    # omni-cv = 三路物理分权感知（build_physical_plan），正式路线，不回退。
    # cv 是它带旧链路兜底的同一个 provider，只在 auto 链里用；grounding 是第一阶段
    # 的全图 VLM 路线，只在内部显式要求时使用：它绕开 physical_perception 与编译器，
    # 产出的稿子与阶段二不是一套东西。
    valid = {"dom", "grounding", "cv", ROUTE_OMNI_CV, *ROUTE_ALIASES}
    if requested and requested not in valid:
        raise ValueError(f"未知路线: {requested}")
    requested = normalize_route(requested)
    dom_ok = (input_kind == "url") and have_dom
    if requested:
        if requested in ("dom",) and not dom_ok:
            raise ValueError(
                f"路线 {requested} 需要网页 DOM 数据；当前输入为 {input_kind}，请改用 --url 或选 grounding/cv"
            )
        return [requested]
    if input_kind == "url" and have_dom:
        chain = ["dom", "physical"]
    else:
        # 截图没有 DOM，物理感知是唯一主链。grounding 不再进入自动链：它是旧的
        # 全图 VLM 路线，会把阶段二的三路分权与编译优化整段绕过去，而 CLI 上看
        # 不出区别——这正是"跑完发现 arrow-right/like/search 又回来了"的来源。
        chain = ["cv"]
    return chain
