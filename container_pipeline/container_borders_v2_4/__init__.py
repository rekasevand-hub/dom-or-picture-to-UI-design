"""
container_borders_v2_4：网页截图容器/按钮边框检测（v2.4 方案）。

方案：v2.2 管线（端点桥接 + 缺边合成 + 双线合并 + 闭合轮廓验证）
+ 可选 OCR 笔画级文字净化（笔画级掩膜 + 长直线保护，移植自 v3）。
在 Canny 之后、形态学之前删除文字笔画，根治 v2.2 的已知漏检模式
（按钮内竖直笔画抢拐角桥接，如分页"1"按钮），且文字像素不再构成
缺边合成的虚假 Canny 证据。

与 container_borders_v2（v2.2 无掩膜）并存：本包多了 text_boxes 等
净化参数；不传 text_boxes 时行为与 v2.2 逐像素一致。包本身零 OCR
依赖——文字框由调用方提供（OmniParser / easyocr / PaddleOCR；
同项目 container_borders_v3.detect_text_boxes 可直接产出）。

默认参数以 2K 截图（~2544x1336）为基准：bridge_radius=32、min_w=40、
min_h=22、merge_lines=True。1K（~1900 宽）截图建议 resize 到 ~2544
宽后使用，或显式传 bridge_radius=24, min_w=30, min_h=14。

用法：
    from container_borders_v2_4 import detect_boxes

    result = detect_boxes('screenshot.png')   # 或传入 (H, W, 3) RGB ndarray
    boxes = result['boxes']        # [{'x','y','w','h'}, ...]，按从上到下、从左到右排序
    result['overlay']              # 边框涂色后的叠加图（ndarray）
    result['boundaries']           # 白底边框图（ndarray）
    result['boxes_mask']           # 边框像素布尔掩膜

    # 有 OCR 文字框时（OmniParser / easyocr / PaddleOCR 产出）：
    result = detect_boxes('screenshot.png', text_boxes=[(x0,y0,x1,y1), ...])

依赖：numpy、opencv-python（Pillow 仅在传入图片路径时需要；
双线合并的骨架化优先用 opencv-contrib 的 cv2.ximgproc.thinning，
缺失时退化为 skimage.morphology.skeletonize，再缺失则跳过细化）。
"""

from .core import (
    GREEN,
    bridge_corner_gaps,
    build_text_stroke_mask,
    clean_edges,
    extract_box_lines_hv,
    find_closed_boxes,
    highlight_box_borders_v2_4,
    hv_lines_from_edges,
    load_image,
    merge_double_edges,
    synthesize_missing_sides,
    thin_lines,
)

__all__ = [
    'detect_boxes',
    'highlight_box_borders_v2_4',
    'extract_box_lines_hv',
    'hv_lines_from_edges',
    'build_text_stroke_mask',
    'clean_edges',
    'bridge_corner_gaps',
    'synthesize_missing_sides',
    'merge_double_edges',
    'thin_lines',
    'find_closed_boxes',
    'load_image',
    'GREEN',
]

__version__ = '2.4.0'


def detect_boxes(image, border_color=GREEN, bridge_radius=32,
                 min_w=40, min_h=22, merge_lines=True,
                 text_boxes=None, fg_thresh=40, stroke_dilate=2,
                 protect_len=50, color_crop=True, verbose=False):
    """统一入口：识别容器/按钮边框，返回坐标与可视化结果。

    参数：
        image: (H, W, 3) RGB ndarray 或图片路径。
        border_color: 可视化时的边框涂色。
        bridge_radius: 端点桥接半径（圆角缺口补连的最大距离）。2K 基准 32，
                       1K（~1900 宽）截图建议 24。
        min_w, min_h: 保留框的最小宽/高。2K 基准 40/22（40 过滤滚动条，
                       22 过滤文字假框）；1K 建议 30/14。
        merge_lines: 是否执行双线合并（膨胀 + 骨架化），高分辨率截图建议开。
        text_boxes: OCR 文字框 [(x0,y0,x1,y1), ...]（像素）。
                       传入后先删除文字笔画再检测；None 时与 v2.2 一致。
        fg_thresh / stroke_dilate / protect_len: 笔画净化参数，默认即可。
        verbose: 是否打印桥接/合成/框数统计。
        color_crop: 是否做背景色一致性裁剪（默认开），修正侧边栏把标题栏/logo 区并入框顶。

    返回：dict
        boxes: [{'x','y','w','h'}, ...] 外接框列表（像素坐标，原点左上），
               按从上到下、从左到右排序。
        overlay: 原图上边框被涂色的图像（ndarray）。
        boundaries: 白底边框图（ndarray）。
        boxes_mask: 边框像素布尔掩膜。
    """
    image = load_image(image)
    overlay, boundaries, boxes_mask, boxes = highlight_box_borders_v2_4(
        image, border_color=border_color, bridge_radius=bridge_radius,
        min_w=min_w, min_h=min_h, merge_lines=merge_lines,
        text_boxes=text_boxes, fg_thresh=fg_thresh,
        stroke_dilate=stroke_dilate, protect_len=protect_len,
        color_crop=color_crop, verbose=verbose)
    return {
        'boxes': boxes,
        'overlay': overlay,
        'boundaries': boundaries,
        'boxes_mask': boxes_mask,
    }

