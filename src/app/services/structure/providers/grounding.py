# -*- coding: utf-8 -*-
"""grounding 路线：VLM 直接看图输出容器/元素 bbox -> PageGraph。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.app.services.structure.backends.grounding_base import GroundingBackend
from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.providers.base import BaseProvider, ProviderContext

if TYPE_CHECKING:
    from src.config import Config


def _default_backend(cfg) -> GroundingBackend:
    from src.app.services.structure.backends.grounding_vlm import GroundingVLM
    return GroundingVLM(cfg)


class GroundingProvider(BaseProvider):
    name = "grounding"

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg

    def run(self, ctx: ProviderContext) -> dict:
        backend = _default_backend(self.cfg)
        raw = backend.ground(ctx.image_path, ctx.image_w, ctx.image_h)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "grounding")
        for c in raw["containers"]:
            add_container(g, c["bbox"], role=c["role"], source="grounding")
        for e in raw["elements"]:
            add_element(g, e["bbox"], type_=e["type"], text=e["text"], source="grounding")
        return g
