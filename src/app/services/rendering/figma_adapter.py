"""Figma Plugin API 适配器（通过本地 WebSocket 桥接）。"""
from __future__ import annotations

import json
import logging
from typing import Any

from src.app.services.rendering.adapter_base import PrototypeAdapter

logger = logging.getLogger(__name__)


class FigmaBridgeAdapter(PrototypeAdapter):
    """通过本地 WebSocket 桥接调用 Figma Plugin API。"""

    def __init__(self, bridge_url: str, timeout: int = 30):
        self.bridge_url = bridge_url
        self.timeout = timeout
        self.ws = None

        try:
            import websocket
            self._websocket = websocket
        except ImportError as exc:
            raise ImportError("websocket-client 未安装，请执行 pip install websocket-client") from exc

    def connect(self) -> None:
        if self.ws is not None:
            return
        url = self.bridge_url.rstrip("/") + "/command"
        self.ws = self._websocket.create_connection(url, timeout=self.timeout)
        logger.info(f"已连接到 Figma 桥接服务器: {url}")

    def disconnect(self) -> None:
        if self.ws is not None:
            self.ws.close()
            self.ws = None
            logger.info("已断开 Figma 桥接服务器")

    def _send(self, action: str, params: dict[str, Any]) -> Any:
        if self.ws is None:
            raise RuntimeError("未连接到 Figma 桥接服务器")
        payload = {"action": action, "params": params}
        self.ws.send(json.dumps(payload, ensure_ascii=False))
        response = self.ws.recv()
        logger.info(f"收到桥接响应: {response!r}")
        data = json.loads(response)
        if data.get("error"):
            raise RuntimeError(f"Figma 插件返回错误: {data['error']}")
        return data.get("result")

    def create_frame(self, spec: dict[str, Any]) -> str | None:
        return self._send("create_frame", spec)

    def create_rectangle(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        params = {**spec, "parentId": parent_id}
        return self._send("create_rectangle", params)

    def create_ellipse(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        params = {**spec, "parentId": parent_id}
        return self._send("create_ellipse", params)

    def create_text(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        params = {**spec, "parentId": parent_id}
        return self._send("create_text", params)

    def create_image(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        params = {**spec, "parentId": parent_id}
        return self._send("create_image", params)

    def flush(self) -> None:
        self.disconnect()
