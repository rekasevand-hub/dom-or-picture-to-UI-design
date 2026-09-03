# -*- coding: utf-8 -*-
"""结构提供器包：DOM/A11Y/Grounding/CV 各路线统一产出 PageGraph。"""
from __future__ import annotations

from src.app.services.structure.providers.base import ProviderContext, BaseProvider
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.providers.a11y import A11yProvider

__all__ = ["ProviderContext", "BaseProvider", "DomProvider", "A11yProvider"]
