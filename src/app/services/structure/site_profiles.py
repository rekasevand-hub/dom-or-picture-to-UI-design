# -*- coding: utf-8 -*-
"""站点 Profile：页面/框架级特化以数据形式存在，核心默认路径不依赖。

Profile 只影响两类东西，**不承载任何核心逻辑分支**：

1) 给 VLM 语义生成的提示词（`icon_aria_labels`）；
2) DOM 采集 / 直出里的**经验阈值**（`dom` / `direct_design` 两段）。这些数是"猜"出来的，
   换一套页面（不同组件库、不同密度）可能就不合适，所以做成可覆盖的数据。
   不带 profile 时用的就是 `DEFAULTS` 里的核心默认值，与当初写死时逐位一致。

**核心算法不在这里开口子**：等价变换（共线分隔线合并、形状夹进裁剪矩形、画布裁剪）、
几何规则、绘制序这些没有"档位"可调——改它们等于改语义，只能改代码并重跑像素回归。

文件位于仓库根 `site_profiles/<host>.json`：

```json
{
  "domains": ["example.com"],
  "icon_aria_labels": {"search": "搜索"},
  "dom": {"container_min_area": 3000, "label_max_len": 30},
  "direct_design": {"merge_dividers": false}
}
```

旧版的顶层 `overlay` 段（`min_area` / `min_overlap_px` / `min_overlap_w` / `min_overlap_h`）
仍然接受，解析时映射到 `dom.overlay_*`；同名的 `dom` 键优先。
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[4]          # 仓库根
_PROFILES_DIR = _ROOT / "site_profiles"

# 经验阈值的**单一定义点**：核心路径不带 profile 时用的就是这些数。
# 键名 = <所属模块>.<参数名>，改这里等于改默认行为，改 profile 只影响那个站点。
DEFAULTS: dict[str, dict] = {
    "dom": {
        "overlay_min_area": 800,          # 小于此面积的不进浮层判定（图标/角标装饰）
        "overlay_min_overlap_px": 1500,   # 与文档序在前内容的最小重叠像素面积
        "overlay_min_overlap_w": 30,      # 重叠最小宽（px）
        "overlay_min_overlap_h": 15,      # 重叠最小高（px）
        "container_min_area": 2000,       # "大区块"容器候选的最小面积（px²）
        "container_min_span_ratio": 0.5,  # 大区块还要求占画布宽或高的这个比例
        "edge_max_thickness": 8,          # 超过此宽度的单边边框不当分隔线（避免画成色块）
        "canvas_min_size": 2,             # 小于此尺寸的节点当残渣丢掉
        "label_max_len": 20,              # Figma 图层名的标签截断长度
    },
    "direct_design": {
        "merge_dividers": True,           # 共线分隔线合并（像素等价的并集）
        "min_style_coverage": 0.5,        # 样式覆盖率低于此比例就不走直出
    },
}

_LEGACY_OVERLAY = {"min_area": "overlay_min_area",
                   "min_overlap_px": "overlay_min_overlap_px",
                   "min_overlap_w": "overlay_min_overlap_w",
                   "min_overlap_h": "overlay_min_overlap_h"}


@dataclass
class SiteProfile:
    domains: list[str]
    icon_aria_labels: dict[str, str] = field(default_factory=dict)
    overlay: dict | None = None          # 兼容保留：load_profile 已摊平进 dom
    dom: dict = field(default_factory=dict)
    direct_design: dict = field(default_factory=dict)

    def matches(self, url: str) -> bool:
        if not url:
            return False
        host = (url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]).lower()
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def hint_text(self) -> str:
        if not self.icon_aria_labels:
            return ""
        lines = ["站点图标语义（仅当条目 aria-label 以图标前缀开头时参考）："]
        for token, label in self.icon_aria_labels.items():
            lines.append("  " + token + " -> " + label)
        return "\n".join(lines)

    def with_rules(self, section: str, values: dict):
        """返回把 `section` 下若干键覆盖掉的新 profile（原对象不动）。

        给闭环搜索用：一次进程里试多组阈值，每次都拿到一个独立 profile，
        不必落盘、也不必改全局状态。
        """
        if section not in DEFAULTS:
            raise KeyError(f"未知 section: {section}（可选 {sorted(DEFAULTS)}）")
        cur = dict(self.dom if section == "dom" else self.direct_design)
        cur.update(values)
        return replace(self, **{section: cur})

    def dom_overrides(self) -> dict:
        """只回"这家站点显式改过哪些 dom 键"（与默认值不同的那些），给人看的。"""
        return {k: v for k, v in self.dom.items()
                if k in DEFAULTS["dom"] and v != DEFAULTS["dom"][k]}

    def rule(self, section: str, key: str):
        """取该 profile 对某个经验阈值的覆盖值；缺省或不合法就用核心默认值。

        profile 是手写 JSON，打错一个字母不应该让整页结果悄悄变样：类型转不过去
        （或布尔值写成字符串）时记一条 warning 再退回默认。
        """
        default = DEFAULTS[section][key]
        raw = (self.dom if section == "dom" else self.direct_design).get(key)
        if raw is None:
            return default
        if isinstance(default, bool):
            if isinstance(raw, bool):
                return raw
        else:
            try:
                return type(default)(raw)
            except (TypeError, ValueError):
                pass
        logger.warning("site profile 的 %s.%s = %r 不是 %s，改用默认值 %r",
                       section, key, raw, type(default).__name__, default)
        return default


def rule(profile: "SiteProfile | None", section: str, key: str):
    """取值入口：没有 profile 就是核心默认值，调用点不必写 if。"""
    return profile.rule(section, key) if profile is not None else DEFAULTS[section][key]


def load_profile(url: str | None) -> SiteProfile | None:
    """按 URL 主机名加载 site_profiles/<host>.json；无匹配或读不动返回 None。"""
    if not url:
        return None
    host = (url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]).lower()
    fp = _PROFILES_DIR / (host + ".json")
    if not fp.is_file():
        return None
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("site profile %s 读不动（%s），按无 profile 处理", fp, exc)
        return None
    dom = dict(data.get("dom") or {})
    legacy = data.get("overlay") or {}
    for old, new_key in _LEGACY_OVERLAY.items():      # 老文件继续可用；dom 段优先
        if old in legacy and new_key not in dom:
            dom[new_key] = legacy[old]
    return SiteProfile(
        domains=[str(d) for d in data.get("domains", [host])],
        icon_aria_labels={str(k): str(v)
                          for k, v in data.get("icon_aria_labels", {}).items()},
        overlay=data.get("overlay"),
        dom=dom,
        direct_design=dict(data.get("direct_design") or {}))
