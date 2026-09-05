# -*- coding: utf-8 -*-
"""结构提供器包：DOM/Grounding/CV 各路线统一产出 PageGraph。"""
from __future__ import annotations

from src.app.services.structure.providers.base import ProviderContext, BaseProvider
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.providers.grounding import GroundingProvider
from src.app.services.structure.providers.cv import CVProvider

__all__ = ["ProviderContext", "BaseProvider", "DomProvider", "GroundingProvider", "CVProvider"]
