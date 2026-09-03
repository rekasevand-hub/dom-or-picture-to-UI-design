"""
OmniParser 本地 HTTP 包装服务。

不改动 OmniParser-master 源码，通过 sys.path 引入 util.omniparser.Omniparser，
在其外层套一个更稳的 FastAPI 服务：
- 模型只在启动时加载一次
- 推理在线程池执行，不阻塞事件循环
- 关闭 uvicorn reload
- 增加 /health 健康检查
- 统一异常处理

启动前请确保：
1. 已激活 OmniParser 所需环境（Python 3.12 + OmniParser/requirements.txt）
2. 已下载权重到 OmniParser/OmniParser-master/weights/

用法（从项目根目录执行）：
    python -m src.app.services.omniparser.omniparser_server \
        --omniparser-root OmniParser/OmniParser-master \
        --som-model-path OmniParser/OmniParser-master/weights/icon_detect/model.pt \
        --caption-model-path OmniParser/OmniParser-master/weights/icon_caption_florence \
        --device cuda \
        --box-threshold 0.05
"""
from __future__ import annotations

import os

# 避免 transformers / huggingface_hub 在加载 Florence-2 远程代码时尝试联网下载
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# 当前环境没有 CUDA，无法安装 flash_attn；让 transformers 认为 flash_attn 不可用，
# 从而回退到标准 attention 实现。
import importlib
import transformers.utils.import_utils as _import_utils

_import_utils.is_flash_attn_2_available = lambda: False
_import_utils.is_flash_attn_greater_or_equal_2_10 = lambda: False

import argparse
import asyncio
import base64
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# 避免 transformers 在加载 Florence-2 远程代码时尝试联网下载
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import uvicorn

logger = logging.getLogger("omniparser_server")

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OmniParser HTTP wrapper server")
    parser.add_argument(
        "--omniparser-root",
        type=str,
        default="OmniParser/OmniParser-master",
        help="OmniParser 仓库根目录，用于加入 PYTHONPATH",
    )
    parser.add_argument(
        "--som-model-path",
        type=str,
        default="OmniParser/OmniParser-master/weights/icon_detect/model.pt",
        help="YOLO 图标检测模型路径",
    )
    parser.add_argument(
        "--caption-model-name",
        type=str,
        default="florence2",
        help="图标描述模型名称",
    )
    parser.add_argument(
        "--caption-model-path",
        type=str,
        default="OmniParser/OmniParser-master/weights/icon_caption_florence",
        help="图标描述模型路径",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda",
        help="运行设备：cuda 或 cpu",
    )
    parser.add_argument(
        "--box-threshold",
        type=float,
        default=0.05,
        help="检测框置信度阈值",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="服务监听地址",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="服务监听端口",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="日志级别",
    )
    return parser.parse_args()


ARGS = _parse_args()


# ---------------------------------------------------------------------------
# 将 OmniParser 加入 PYTHONPATH 并导入
# ---------------------------------------------------------------------------

_omni_root = Path(ARGS.omniparser_root).resolve()
if str(_omni_root) not in sys.path:
    sys.path.insert(0, str(_omni_root))

# 把 Florence-2 远程代码目录加入 PYTHONPATH，使 config.json 中的 auto_map
# （configuration_florence2.Florence2Config / modeling_florence2...）能被解析
_florence_root = Path(ARGS.caption_model_path).resolve()
if str(_florence_root) not in sys.path:
    sys.path.insert(0, str(_florence_root))

# ---------------------------------------------------------------------------
# 兼容 PaddleOCR 3.x + 规避 torch/paddle GPU 版 cuDNN DLL 冲突：
#
# OmniParser 的 util/utils.py 模块级实例化 PaddleOCR，但 check_ocr_box 走
# use_paddleocr=False，该实例从不被使用。GPU 环境下 torch(CUDA) 与
# paddlepaddle-gpu 各自打包了同名不同版的 cudnn_cnn64_9.dll，同一进程
# 先后加载必有一方 WinError 127（util/utils.py 先 import easyocr 拉起
# torch，再实例化 PaddleOCR 就会炸）。因此这里在导入 OmniParser 前往
# sys.modules 里装 paddleocr 惰性桩：模块级实例化只记录参数、完全不加载
# paddle；桩首次被真正使用时才导入真 paddleocr（并把 2.x 参数过滤为 3.x
# 兼容参数）并"变身"为真实例。
#
# 若真 paddleocr 已被本进程先行加载（说明 paddle 已加载成功），桩装不上，
# 退用原来的参数过滤补丁。
# ---------------------------------------------------------------------------


def _patch_paddleocr_params() -> None:
    """参数过滤兜底：只保留 paddleocr 3.x 兼容参数（OmniParser 源码用的是
    2.x 风格参数，如 use_gpu、max_batch_size 等，3.x 已移除）。"""
    try:
        from paddleocr import PaddleOCR

        if getattr(PaddleOCR.__init__, "_patched_for_omniparser", False):
            return
        _original_paddleocr_init = PaddleOCR.__init__

        def _patched_paddleocr_init(self, *args, **kwargs):
            allowed = {"lang", "use_angle_cls"}
            filtered = {k: v for k, v in kwargs.items() if k in allowed}
            return _original_paddleocr_init(self, *args, **filtered)

        _patched_paddleocr_init._patched_for_omniparser = True
        PaddleOCR.__init__ = _patched_paddleocr_init
    except Exception:
        pass


def _install_paddleocr_stub() -> bool:
    """往 sys.modules 装 paddleocr 惰性桩；真模块已加载则返回 False。"""
    import types

    if sys.modules.get("paddleocr") is not None:
        return False
    stub = types.ModuleType("paddleocr")

    class _LazyPaddleOCR:
        def __init__(self, *args, **kwargs):
            self._lazy_args = (args, kwargs)

        def _realize(self):
            del sys.modules["paddleocr"]
            _patch_paddleocr_params()  # 真初始化前先打参数过滤补丁
            from paddleocr import PaddleOCR as _Real

            real = _Real(*self._lazy_args[0], **self._lazy_args[1])
            self.__class__ = _Real
            self.__dict__.update(real.__dict__)

        def __getattr__(self, name):
            # 类上没有的属性/方法首次被访问时触发真初始化
            self._realize()
            return getattr(self, name)

    stub.PaddleOCR = _LazyPaddleOCR
    sys.modules["paddleocr"] = stub
    return True


if not _install_paddleocr_stub():
    _patch_paddleocr_params()

try:
    from util.omniparser import Omniparser  # type: ignore
except Exception as exc:  # pragma: no cover
    logger.exception("导入 OmniParser 失败，请检查 --omniparser-root 和依赖环境")
    raise


# ---------------------------------------------------------------------------
# 模型实例（在 lifespan 中初始化）
# ---------------------------------------------------------------------------

_omniparser: Omniparser | None = None


def _build_omniparser_config() -> dict[str, Any]:
    return {
        "som_model_path": ARGS.som_model_path,
        "caption_model_name": ARGS.caption_model_name,
        "caption_model_path": ARGS.caption_model_path,
        "device": ARGS.device,
        "BOX_TRESHOLD": ARGS.box_threshold,
    }


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _omniparser
    logger.info("正在加载 OmniParser 模型，首次启动较慢...")
    try:
        loop = asyncio.get_running_loop()
        _omniparser = await loop.run_in_executor(None, _init_omniparser)
        logger.info("OmniParser 模型加载完成")
    except Exception as exc:
        logger.exception("模型加载失败: %s", exc)
        raise
    yield
    logger.info("服务关闭")


def _init_omniparser() -> Omniparser:
    return Omniparser(_build_omniparser_config())


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

app = FastAPI(
    title="OmniParser HTTP Wrapper",
    description="Wrap OmniParser as a local HTTP service without modifying its source.",
    version="0.1.0",
    lifespan=_lifespan,
)


class ParseRequest(BaseModel):
    base64_image: str = Field(..., description="Base64 编码的 PNG/JPG 图片")


class ParseResponse(BaseModel):
    som_image_base64: str = Field(..., description="带编号标注框的 base64 PNG")
    parsed_content_list: list[dict] = Field(..., description="解析出的元素列表")
    latency: float = Field(..., description="推理耗时（秒）")


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        model_loaded=_omniparser is not None,
    )


@app.post("/parse", response_model=ParseResponse)
async def parse(request: ParseRequest) -> ParseResponse:
    if _omniparser is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OmniParser model not loaded yet",
        )

    # 简单校验 base64
    try:
        base64.b64decode(request.base64_image, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid base64_image: {exc}",
        ) from exc

    start = time.time()
    try:
        loop = asyncio.get_running_loop()
        labeled_img, parsed_list = await loop.run_in_executor(
            None, _omniparser.parse, request.base64_image
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("OmniParser 推理失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OmniParser inference failed: {exc}",
        ) from exc

    latency = time.time() - start
    logger.info("完成一次解析，耗时 %.3fs，检出 %d 个元素", latency, len(parsed_list))
    return ParseResponse(
        som_image_base64=labeled_img,
        parsed_content_list=parsed_list,
        latency=latency,
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=getattr(logging, ARGS.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    uvicorn.run(
        "src.app.services.omniparser.omniparser_server:app",
        host=ARGS.host,
        port=ARGS.port,
        reload=False,
        log_level=ARGS.log_level,
    )


if __name__ == "__main__":
    main()
