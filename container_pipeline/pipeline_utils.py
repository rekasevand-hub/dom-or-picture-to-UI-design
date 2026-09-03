# -*- coding: utf-8 -*-
"""pipeline_utils.py — View_fill 完整管线的独立工具函数。

从 container_borders_v1 / container_borders_v3 提取的、run_pipeline.py
实际用到的函数，封装到这里后完整管线不再依赖 v1/v3 包，便于在其他
项目复用（随 run_pipeline.py + container_borders_v2_4 + gestalt_group.py
一起拷贝即可）。
"""

import sys

import cv2
import numpy as np


def extract_box_lines_hv(image, canny_low=10, canny_high=30, line_len=22):
    """逐通道 Canny + 水平/垂直形态学开运算，分别返回水平/垂直线掩膜。

    源自 container_borders_v1.core（供 refine_groups 提取直线证据）。
    line_len 默认 22（2K 基准）：2K 下文字笔画 ~20-28px，22 是滤文字与
    保留小圆角按钮直边（~23px）的折中；1K 截图建议 20。
    """
    edges = np.zeros(image.shape[:2], dtype=bool)
    for c in range(3):
        edges |= cv2.Canny(image[:, :, c], canny_low, canny_high) > 0
    u8 = edges.astype(np.uint8)
    h = cv2.morphologyEx(u8, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (line_len, 1))) > 0
    v = cv2.morphologyEx(u8, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (1, line_len))) > 0
    return h, v


def _install_paddleocr_stub():
    """在 sys.modules 里给 paddleocr 装惰性桩，供 OmniParser 路径使用。

    源自 container_borders_v3.core。OmniParser 的 util/utils.py 模块级
    实例化的 PaddleOCR 只是占坑（check_ocr_box 走 use_paddleocr=False
    时从不调用），但 GPU 环境下 torch(CUDA) 与 paddlepaddle-gpu 的
    cudnn_cnn64_9.dll 同名不同版，同进程先后加载必有一方 WinError 127。
    装桩后该模块级实例化只记录参数、完全不碰 paddle；桩首次被真正使用
    时才导入真 paddleocr 并把自身"变成"真实例（__class__ 替换）。

    返回 True 表示装了桩；False 表示真 paddleocr 已被本进程加载
    （说明 paddle 先行加载成功，无需桩）。注意同一进程内 paddle 引擎与
    easyocr/omniparser（torch 系）引擎不可混用——DLL 冲突是双向的。
    """
    import types
    mod = sys.modules.get('paddleocr')
    if mod is not None:
        return False  # 真模块已加载
    stub = types.ModuleType('paddleocr')
    stub._v3_stub = True

    class _LazyPaddleOCR:
        def __init__(self, *args, **kwargs):
            self._v3_lazy_args = (args, kwargs)

        def _v3_realize(self):
            del sys.modules['paddleocr']
            from paddleocr import PaddleOCR as _Real
            real = _Real(*self._v3_lazy_args[0], **self._v3_lazy_args[1])
            self.__class__ = _Real
            self.__dict__.update(real.__dict__)

        def __getattr__(self, name):
            # 类上没有的属性/方法首次被访问时触发真初始化
            self._v3_realize()
            return getattr(self, name)

    stub.PaddleOCR = _LazyPaddleOCR
    sys.modules['paddleocr'] = stub
    return True


def _h_segments(h_mask, min_width=30):
    """水平线段的连通分量列表：[(y, x0, x1), ...]。

    源自 container_borders_v1.core（供 refine_groups 使用）。
    """
    n, lab = cv2.connectedComponents(h_mask.astype(np.uint8))
    segs = []
    for i in range(1, n):
        ys, xs = np.where(lab == i)
        if xs.max() - xs.min() + 1 >= min_width:
            segs.append(((int(ys.min()) + int(ys.max())) // 2,
                         int(xs.min()), int(xs.max())))
    return segs


def _v_segments(v_mask, min_height=8):
    """垂直线段的连通分量列表：[(x, y0, y1), ...]。

    源自 container_borders_v1.core（供 refine_groups 使用）。
    """
    n, lab = cv2.connectedComponents(v_mask.astype(np.uint8))
    segs = []
    for i in range(1, n):
        ys, xs = np.where(lab == i)
        if ys.max() - ys.min() + 1 >= min_height:
            segs.append(((int(xs.min()) + int(xs.max())) // 2,
                         int(ys.min()), int(ys.max())))
    return segs
