# -*- coding: utf-8 -*-
"""站点 Profile：页面/框架级特化以数据形式存在，核心默认路径不依赖。

Profile 只允许影响：1) 给 Interpreter 的提示词；2) DOM overlay 判定的可选参数覆盖。
本模块不承载任何核心逻辑分支；文件位于仓库根 site_profiles/<host>.json。
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]          # 仓库根
_PROFILES_DIR = _ROOT / "site_profiles"


@dataclass
class SiteProfile:
    domains: list[str]
    icon_aria_labels: dict[str, str] = field(default_factory=dict)
    overlay: dict | None = None

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


def load_profile(url: str | None) -> SiteProfile | None:
    """按 URL 主机名加载 site_profiles/<host>.json；无匹配返回 None。"""
    if not url:
        return None
    host = (url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]).lower()
    fp = _PROFILES_DIR / (host + ".json")
    if not fp.is_file():
        return None
    data = json.loads(fp.read_text(encoding="utf-8"))
    return SiteProfile(
        domains=[str(d) for d in data.get("domains", [host])],
        icon_aria_labels={str(k): str(v)
                          for k, v in data.get("icon_aria_labels", {}).items()},
        overlay=data.get("overlay"))
