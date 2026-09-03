"""Figma Plugin WebSocket 桥接服务端。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

try:
    import websockets
    import websockets.server
except ImportError as exc:
    raise ImportError("websockets 未安装，请执行 pip install websockets") from exc

logger = logging.getLogger(__name__)

_plugin_ws: websockets.server.WebSocketServerProtocol | None = None
_plugin_inbox: asyncio.Queue[str] = asyncio.Queue()


async def _plugin_handler(websocket: websockets.server.WebSocketServerProtocol) -> None:
    """处理 Figma 插件连接。"""
    global _plugin_ws
    _plugin_ws = websocket
    logger.info("Figma 插件已连接")
    try:
        async for message in websocket:
            logger.info(f"收到插件消息: {message[:200]}")
            await _plugin_inbox.put(message)
    finally:
        _plugin_ws = None
        logger.info("Figma 插件已断开")


async def _command_handler(websocket: websockets.server.WebSocketServerProtocol) -> None:
    """处理 Python 适配器连接。"""
    global _plugin_ws
    async for message in websocket:
        logger.info(f"收到 Python 命令: {message[:200]}")
        if _plugin_ws is None:
            logger.warning("插件未连接，拒绝命令")
            await websocket.send(json.dumps({"error": "Figma 插件未连接"}))
            continue

        try:
            logger.info("转发命令给插件...")
            await _plugin_ws.send(message)
            logger.info("等待插件响应...")
            response = await asyncio.wait_for(_plugin_inbox.get(), timeout=30)
            logger.info(f"拿到插件响应 (len={len(response)}): {response!r}")
            await websocket.send(response)
            logger.info("响应已发回 Python")
        except asyncio.TimeoutError:
            logger.warning("等待插件响应超时")
            await websocket.send(json.dumps({"error": "等待 Figma 插件响应超时"}))
        except Exception as exc:
            logger.exception("命令处理异常")
            await websocket.send(json.dumps({"error": str(exc)}))


async def _route(websocket: websockets.server.WebSocketServerProtocol) -> None:
    """根据 path 路由到不同处理器。"""
    path = websocket.request.path
    if path == "/plugin":
        await _plugin_handler(websocket)
    elif path == "/command":
        await _command_handler(websocket)
    else:
        await websocket.close(code=4001, reason="未知路径")


async def _run(host: str, port: int) -> None:
    """异步启动桥接服务器并永远运行。"""
    logger.info(f"启动 Figma 桥接服务器: ws://{host}:{port}")
    async with websockets.serve(_route, host, port):
        await asyncio.Future()


def start(host: str = "localhost", port: int = 8765) -> None:
    """启动桥接服务器（阻塞）。"""
    try:
        asyncio.run(_run(host, port))
    except KeyboardInterrupt:
        logger.info("收到中断信号，桥接服务器已停止")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    start()
