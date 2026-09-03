"""即时设计适配器（桩）。"""
from __future__ import annotations

from typing import Any

from src.app.services.rendering.adapter_base import PrototypeAdapter


class JSDesignAdapter(PrototypeAdapter):
    """即时设计适配器（桩）。"""

    def __init__(self, api_base: str, token: str | None):
        self.api_base = api_base
        self.token = token

    def connect(self) -> None:
        raise NotImplementedError("即时设计适配器尚未实现，请接入官方 Plugin/REST API")

    def disconnect(self) -> None:
        pass

    def create_frame(self, spec: dict[str, Any]) -> str | None:
        raise NotImplementedError

    def create_rectangle(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        raise NotImplementedError

    def create_ellipse(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        raise NotImplementedError

    def create_text(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        raise NotImplementedError

    def create_image(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        raise NotImplementedError

    def flush(self) -> None:
        pass
