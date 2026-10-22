# -*- coding: utf-8 -*-
"""路径工具：把本地路径变成浏览器能加载的绝对 file:// URI。

`Path.as_uri()` 对相对路径直接抛 ValueError（"relative path can't be expressed
as a file URI"）。产线上输出目录经常是相对的（`.env` 默认 `OUTPUT_DIR=./output`、
命令行 `--output-dir output/xxx`），于是"直出稿栅格化"与"框选对照层"这类用
file:// 加载本地文件的辅助链路会整体失效——而且它们在主流程里是容错分支，只会打
一条 warning，很容易被忽略（第八轮 P15 文本基线微调就踩过：默认配置下它一次都没
生效）。这里统一先 `resolve()` 成绝对路径再转 URI。
"""
from __future__ import annotations

from pathlib import Path


def file_uri(path: str | Path) -> str:
    """返回 path 的绝对 file:// URI（相对路径按当前工作目录解析）。"""
    return Path(path).expanduser().resolve().as_uri()
