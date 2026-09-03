# -*- coding: utf-8 -*-
"""a11y 路线：由 CDP Accessibility.getFullAXTree 构建 PageGraph（语义角色 + bounds）。"""
from __future__ import annotations

import json

from src.app.services.structure.capture import _ax_bounds
from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.providers.base import BaseProvider, ProviderContext

CONTAINER_AX_ROLES = {"banner", "navigation", "main", "region", "complementary",
                      "contentinfo", "group", "list", "tablist", "form"}
ELEMENT_AX_ROLES = {"button", "link", "textbox", "combobox", "checkbox", "radio",
                    "heading", "listitem", "img", "image", "text", "searchbox", "switch"}
TYPE_BY_ROLE = {"button": "button", "link": "link", "textbox": "input", "searchbox": "input",
                "combobox": "input", "checkbox": "input", "radio": "input", "switch": "input",
                "heading": "text", "text": "text", "listitem": "text",
                "img": "image", "image": "image"}


class A11yProvider(BaseProvider):
    name = "a11y"

    def run(self, ctx: ProviderContext) -> dict:
        with open(ctx.ax_path, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "a11y")
        for n in nodes:
            if n.get("ignored"):
                continue
            role = (n.get("role") or {}).get("value") or ""
            name = (n.get("name") or {}).get("value") or ""
            bbox = _ax_bounds(n.get("properties") or [])
            if not bbox:
                continue
            if role in CONTAINER_AX_ROLES:
                add_container(g, bbox, role=role, source=f"a11y:{role}")
            elif role in ELEMENT_AX_ROLES:
                add_element(g, bbox, type_=TYPE_BY_ROLE.get(role, "rectangle"),
                            text=name, role=role, source=f"a11y:{role}")
        return g
