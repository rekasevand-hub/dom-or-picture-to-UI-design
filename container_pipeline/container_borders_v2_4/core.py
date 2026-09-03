"""
网页截图容器/按钮边框检测 v2.4 = v2.2 管线 + 可选 OCR 笔画级文字净化。

代码来源：View_fill 项目的 highlight_box_borders_v2_4.py（单文件原型，
勿改）；与 container_borders_v2 包（v2.2 无掩膜）并存。

动机：v2.2 有已知漏检模式——按钮内有竖直笔画文字且靠近圆角拐角时
（如分页"1"按钮），笔画会抢走拐角桥接导致轮廓敞开、该按钮漏检。
v2.4 在 Canny 之后、形态学之前插入内容级文字净化（移植自 v3 的方案）：

1. OCR 文字框（text_boxes，由调用方提供：OmniParser / easyocr /
   PaddleOCR 均可；View_fill 项目 container_borders_v3 包的
   detect_text_boxes 可直接产出）。包本身不依赖 OCR；
2. 笔画级掩膜：每个文字框内取四周环带中位色为背景、L2 距离 > fg_thresh
   的像素为笔画、膨胀 stroke_dilate px——只删真实字形像素，贴边边框线
   不受影响；
3. 长直线保护：>= protect_len 的水平/垂直线段及 1px 邻域豁免删除；
4. 缺边合成的证据边缘同样用净化后的——文字像素不再构成虚假 Canny 证据。

不传 text_boxes 时行为与 v2.2 逐像素一致（已回归验证）。

实测（2K 基准图 2k_pic.png，paddle 供框）：29 框 = v2.2 的 28 框全保留
+ 救回分页"1"按钮；tt_sys.png（1K 参数）115 框 vs 无掩膜 117——丢的
2 框是"操作"固定列表头：无掩膜版靠该列投影阴影的边缘充当缺边合成证据
（侥幸检出），掩膜净化阴影后暴露真实边框证据不足，属诚实漏检而非误伤。

默认参数以 2K 截图（~2544x1336）为基准（同 v2.2）：bridge_radius=32、
min_w=40、min_h=22、merge_lines=True；1K 截图传
bridge_radius=24, min_w=30, min_h=14。
净化参数：fg_thresh=40、stroke_dilate=2、protect_len=50。

依赖：numpy、opencv-python（Pillow 仅在传入图片路径时需要；
骨架化优先用 opencv-contrib 的 cv2.ximgproc.thinning，缺失时退化为
skimage.morphology.skeletonize，再缺失则跳过细化）。
"""

from pathlib import Path

import cv2
import numpy as np

GREEN = np.array([0, 200, 0], dtype=np.uint8)


def load_image(image):
    """接受 ndarray(RGB) 或图片路径，统一返回 (H, W, 3) uint8 RGB 数组。"""
    if isinstance(image, (str, Path)):
        from PIL import Image
        return np.array(Image.open(image).convert('RGB'))
    return np.asarray(image)


# ------------------------------------------------------------ 边缘与直线提取

def _raw_canny_edges(image, canny_low=10, canny_high=30):
    """逐通道 Canny 原始边缘（浅黄等弱边框在灰度上对比度低，逐通道才能捕获）。"""
    edges = np.zeros(image.shape[:2], dtype=bool)
    for c in range(3):
        edges |= cv2.Canny(image[:, :, c], canny_low, canny_high) > 0
    return edges


def hv_lines_from_edges(edges, line_len=20):
    """对边缘图做水平/垂直形态学开运算，分别返回水平/垂直线掩膜。"""
    u8 = edges.astype(np.uint8)
    h = cv2.morphologyEx(u8, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (line_len, 1))) > 0
    v = cv2.morphologyEx(u8, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (1, line_len))) > 0
    return h, v


def extract_box_lines_hv(image, canny_low=10, canny_high=30, line_len=20):
    """逐通道 Canny + 水平/垂直形态学开运算，分别返回水平/垂直线掩膜。"""
    return hv_lines_from_edges(_raw_canny_edges(image, canny_low, canny_high),
                               line_len)


# ------------------------------------------------------ 文字笔画净化（v2.4）

def build_text_stroke_mask(image, text_boxes, fg_thresh=40, dilate_px=2, pad=1):
    """文字框内提取实际字形笔画像素，生成布尔掩膜（True = 文字笔画）。

    背景色取框外扩 pad 后四周 1px 环带的中位色（文字框的环带几乎纯背景，
    深色底白字 / 浅色底黑字 / 彩色按钮白字均适用）；框内与背景色 L2 距离
    > fg_thresh 的像素视为笔画；最后整体膨胀 dilate_px 覆盖抗锯齿过渡带。
    只删笔画像素而非整框，因此贴近文字的边框线不受影响。
    """
    image = np.asarray(image)
    H, W = image.shape[:2]
    img = image.astype(np.int16)
    mask = np.zeros((H, W), dtype=bool)
    for (x0, y0, x1, y1) in text_boxes:
        x0, y0 = max(int(x0) - pad, 0), max(int(y0) - pad, 0)
        x1, y1 = min(int(x1) + pad + 1, W), min(int(y1) + pad + 1, H)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        crop = img[y0:y1, x0:x1]
        ring = np.concatenate([
            crop[0, :], crop[-1, :], crop[:, 0], crop[:, -1]], axis=0)
        bg = np.median(ring, axis=0)
        dist = np.sqrt(((crop - bg) ** 2).sum(axis=2))
        mask[y0:y1, x0:x1] |= dist > fg_thresh
    if dilate_px > 0:
        k = 2 * dilate_px + 1
        mask = cv2.dilate(mask.astype(np.uint8),
                          np.ones((k, k), np.uint8)) > 0
    return mask


def clean_edges(edges, stroke_mask, protect_len=50):
    """从边缘图删除文字笔画像素：笔画掩膜中扣除长直线保护区。

    长直线保护：>= protect_len 的水平/垂直连续线段及其 1px 邻域豁免删除，
    防止笔画掩膜与边框线真正相贴时误伤边框主干。
    返回 (净化后的边缘图, 被删除的像素掩膜)。
    """
    u8 = edges.astype(np.uint8)
    hp = cv2.morphologyEx(u8, cv2.MORPH_OPEN,
                          cv2.getStructuringElement(cv2.MORPH_RECT,
                                                    (protect_len, 1)))
    vp = cv2.morphologyEx(u8, cv2.MORPH_OPEN,
                          cv2.getStructuringElement(cv2.MORPH_RECT,
                                                    (1, protect_len)))
    protected = (hp | vp) > 0
    protected = cv2.dilate(protected.astype(np.uint8),
                           np.ones((3, 3), np.uint8)) > 0
    deletion = stroke_mask & ~protected
    return edges & ~deletion, deletion


# ------------------------------------------------------------- 线段工具

def _h_segments(h_mask, min_width=30):
    """水平线段的连通分量列表：[(y, x0, x1), ...]。"""
    n, lab = cv2.connectedComponents(h_mask.astype(np.uint8))
    segs = []
    for i in range(1, n):
        ys, xs = np.where(lab == i)
        if xs.max() - xs.min() + 1 >= min_width:
            segs.append(((int(ys.min()) + int(ys.max())) // 2,
                         int(xs.min()), int(xs.max())))
    return segs


def _v_segments(v_mask, min_height=8):
    """垂直线段的连通分量列表：[(x, y0, y1), ...]。"""
    n, lab = cv2.connectedComponents(v_mask.astype(np.uint8))
    segs = []
    for i in range(1, n):
        ys, xs = np.where(lab == i)
        if ys.max() - ys.min() + 1 >= min_height:
            segs.append(((int(xs.min()) + int(xs.max())) // 2,
                         int(ys.min()), int(ys.max())))
    return segs


# --------------------------------------------------------- v2.2 管线主体

def bridge_corner_gaps(h_mask, v_mask, radius=18, min_seg=20, snap_tol=6,
                       collinear_gap=12):
    """端点桥接 + T 型吸附 + 同向断线桥接。

    端点桥接：把水平线段端点与半径内的最近垂直线段端点连线，补上圆角缺口。
    只考虑“端点对端点”：圆角缺口处总是一横一竖两个自由端点；文字笔画的
    T/X 交叉是线段中部相交，端点不在附近，不会被误连。

    T 型吸附：横线端点紧贴某竖线半腰（|dx| <= snap_tol 且 y 落在竖线段
    范围内）时，把横线端点延长吸附到竖线上；竖线端点同理。专治边框线
    “差几像素没碰上”（抗锯齿/提取损耗导致的几像素缺口）。

    同向断线桥接：同 x（±2）的竖线段端点间隙 <= collinear_gap 时直连，
    横线同理。专治提取损耗造成的共线断线（如侧边栏边缘竖线断成两截）。

    返回：(桥接后的线图掩膜, 桥接条数)。
    """
    hsegs = _h_segments(h_mask, min_width=min_seg)   # [(y, x0, x1), ...]
    vsegs = _v_segments(v_mask, min_height=min_seg)  # [(x, y0, y1), ...]
    out = (h_mask | v_mask).astype(np.uint8)

    v_ends = []
    for x, y0, y1 in vsegs:
        v_ends.append((x, y0))
        v_ends.append((x, y1))

    n_bridges = 0
    r2 = radius * radius
    for y, x0, x1 in hsegs:
        for hx in (x0, x1):
            # T 型吸附：端点紧贴竖线半腰，延长到竖线
            snapped = False
            for x, ya, yb in vsegs:
                if abs(x - hx) <= snap_tol and ya - snap_tol <= y <= yb + snap_tol:
                    cv2.line(out, (hx, y), (x, y), 1, 1)
                    n_bridges += 1
                    snapped = True
                    break
            if snapped:
                continue
            # 端点对端点：补圆角缺口
            best, best_d2 = None, r2
            for vx, vy in v_ends:
                d2 = (hx - vx) ** 2 + (y - vy) ** 2
                if d2 <= best_d2:
                    best_d2, best = d2, (vx, vy)
            if best is not None:
                cv2.line(out, (hx, y), best, 1, 1)
                n_bridges += 1
    # 竖线端点紧贴横线半腰的反向 T 型吸附
    for x, y0, y1 in vsegs:
        for vy in (y0, y1):
            for y, xa, xb in hsegs:
                if abs(y - vy) <= snap_tol and xa - snap_tol <= x <= xb + snap_tol:
                    cv2.line(out, (x, vy), (x, y), 1, 1)
                    n_bridges += 1
                    break
    # 同向断线桥接：共线的两段直连
    for x1, ya1, yb1 in vsegs:
        for x2, ya2, yb2 in vsegs:
            if abs(x1 - x2) > 2:
                continue
            if 0 < ya2 - yb1 <= collinear_gap:
                cv2.line(out, (x1, yb1), (x2, ya2), 1, 1)
                n_bridges += 1
    for y1, xa1, xb1 in hsegs:
        for y2, xa2, xb2 in hsegs:
            if abs(y1 - y2) > 2:
                continue
            if 0 < xa2 - xb1 <= collinear_gap:
                cv2.line(out, (xb1, y1), (xa2, y2), 1, 1)
                n_bridges += 1
    return out > 0, n_bridges


def synthesize_missing_sides(h_mask, v_mask, edges, min_pair_w=50, corner_tol=8,
                             max_height=300, evidence_ratio=0.5, band=2, scan=8,
                             gap_tol=6):
    """缺边合成：配对水平线，把两侧边接到真实/证据充分的竖线位置上。

    判定：两条水平线段 y 间距 8~max_height、x 跨度相近（端点差 <= corner_tol
    且重叠 >= 70%）即构成一对。对每一侧（左/右）确定侧边 x：
    - 附近已有延伸到两条水平线的竖线 → 吸附到该竖线的 x；
    - 无竖线 → 在 sx±scan 内扫描原始 Canny 边缘，取行覆盖率最高且
      >= evidence_ratio、且最长无证据行段 <= gap_tol 的 x（弱边框边缘零碎、
      没挺过形态学，且因抗锯齿横线端点常比真实边角靠内几像素，固定查 sx
      容易漏证据；连续性约束防止把几段互不相干的短边拼算成一条长边）；
    - 两者都无 → 整对放弃（防止两条紧贴的分隔线围出幻影框）。

    配对成立时，按两侧边 x 重画两条水平线并补画两侧竖线，保证闭合。

    返回：(合成后的线图掩膜, 合成侧边的对数)。
    """
    hsegs = [s for s in _h_segments(h_mask) if s[2] - s[1] + 1 >= min_pair_w]
    vsegs = _v_segments(v_mask)
    out = (h_mask | v_mask).astype(np.uint8)

    def side_x(sx, y0, y1):
        """该侧可用的竖线 x：优先吸附已有竖线，其次 Canny 证据扫描；无则 None。"""
        cands = [x for x, ya, yb in vsegs
                 if abs(x - sx) <= corner_tol
                 and ya <= y0 + corner_tol and yb >= y1 - corner_tol]
        if cands:
            return min(cands, key=lambda x: abs(x - sx))
        best_x, best_cov = None, evidence_ratio
        for x in range(max(sx - scan, 0), min(sx + scan + 1, edges.shape[1])):
            col = edges[y0:y1 + 1, max(x - band, 0):x + band + 1]
            if col.shape[0] == 0:
                continue
            rows = col.any(axis=1)
            cov = rows.mean()
            if cov < best_cov:
                continue
            # 连续性：最长无证据行段不能超过 gap_tol
            gaps = np.diff(np.flatnonzero(np.concatenate(([True], rows, [True])))) - 1
            if gaps.max(initial=0) > gap_tol:
                continue
            best_cov, best_x = cov, x
        return best_x

    n_pairs = 0
    for y0, xa0, xb0 in hsegs:
        for y1, xa1, xb1 in hsegs:
            if y1 <= y0:
                continue
            height = y1 - y0
            if height < 8 or height > max_height:
                continue
            if abs(xa0 - xa1) > corner_tol or abs(xb0 - xb1) > corner_tol:
                continue
            overlap = min(xb0, xb1) - max(xa0, xa1) + 1
            if overlap < 0.7 * max(xb0 - xa0 + 1, xb1 - xa1 + 1):
                continue

            xl = side_x((xa0 + xa1) // 2, y0, y1)
            xr = side_x((xb0 + xb1) // 2, y0, y1)
            if xl is None or xr is None or xr - xl < min_pair_w:
                continue
            cv2.line(out, (xl, y0), (xr, y0), 1, 1)
            cv2.line(out, (xl, y1), (xr, y1), 1, 1)
            cv2.line(out, (xl, y0), (xl, y1), 1, 1)
            cv2.line(out, (xr, y0), (xr, y1), 1, 1)
            n_pairs += 1
    return out > 0, n_pairs


def find_closed_boxes(lines_mask, min_w=30, min_h=14,
                      min_rect_ratio=0.5, approx_eps=None):
    """闭合轮廓验证：只保留“像容器框”的闭合轮廓。

    过滤条件：
    - 虚拟外框本身（整图轮廓）剔除；
    - 外接框宽 >= min_w 且高 >= min_h（字符级小闭合如“口”直接排除）；
    - 轮廓面积 >= min_rect_ratio * 外接框面积（排除细枝/碎线围出的假轮廓）；
    - 多边形逼近顶点数 4~8（矩形 4；圆角矩形桥接切角后 ~8；圆形/图标 >8 排除）。
      逼近 eps 取 max(2, 0.1*min(w,h))：若按周长比例取值，宽扁框的 eps 会
      比框高还大，矩形被压成 2 个顶点而误杀（banner、表格行都是这种形状）。

    1px 闭环的内外两侧会各产生一条轮廓，按外接框去重只保留一条。

    返回：[{'x','y','w','h','contour'}, ...]，坐标为原图坐标。
    """
    H, W = lines_mask.shape
    canvas = np.zeros((H + 2, W + 2), np.uint8)
    canvas[1:-1, 1:-1] = lines_mask.astype(np.uint8)
    cv2.rectangle(canvas, (0, 0), (W + 1, H + 1), 1, 1)  # 虚拟外框，帮贴边容器闭合

    contours, _ = cv2.findContours(canvas, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= W - 1 and h >= H - 1:
            continue  # 虚拟外框本身
        if w < min_w or h < min_h:
            continue
        if cv2.contourArea(c) < min_rect_ratio * w * h:
            continue
        eps = approx_eps if approx_eps is not None else max(2.0, 0.10 * min(w, h))
        approx = cv2.approxPolyDP(c, eps, True)
        if not (4 <= len(approx) <= 8):
            continue
        # 去重：同一闭环的内/外轮廓外接框几乎相同
        if any(abs(x - b['_cx']) <= 2 and abs(y - b['_cy']) <= 2
               and abs(w - b['w']) <= 4 and abs(h - b['h']) <= 4 for b in boxes):
            continue
        boxes.append({
            'x': max(x - 1, 0), 'y': max(y - 1, 0), 'w': w, 'h': h,
            '_cx': x, '_cy': y,  # canvas 坐标，仅供去重比较
            'contour': c - 1,
        })
    for b in boxes:
        b.pop('_cx')
        b.pop('_cy')
    return boxes


def crop_color_boundaries(boxes, image, bg_dist=26, low_frac=0.35, high_frac=0.6,
                          min_rows=18, probe_bottom=0.15, probe_top=0.30,
                          side_margin=0.08, min_keep=22, verbose=False):
    """按背景色一致性裁剪误并框：侧边栏把标题栏/logo 区并入框顶、或页脚色块
    并入框底时，把顶/底裁到“本容器背景色真正开始/结束”的颜色突变行。

    思路：
      1. 取框中下部探针区的主色（量化众数）作为容器背景色；
      2. 逐行统计与主色接近（通道最大差 <= bg_dist）的像素占比 frac；
      3. 顶部：找第一个 frac 持续 >= high_frac 的行 t；若 [0,t) 内低占比行数
         >= min_rows 且低占比区水平方向非均匀（排除纯色卡片头带），把顶裁到 t；
      4. 底部：对称处理。

    返回：裁剪后的新 boxes 列表（不修改入参）。
    """
    if image is None or not boxes:
        return boxes
    img = load_image(image)
    img32 = img.astype(np.int32)
    out = []
    for b in boxes:
        x, y, w, h = b['x'], b['y'], b['w'], b['h']
        nb = dict(b)
        if h < min_rows * 4 + 20 or w < 30:
            out.append(nb)
            continue
        p0 = y + int(h * probe_bottom)
        p1 = y + int(h * probe_top)
        p1 = max(p0 + 5, p1)
        xs0 = x + int(w * side_margin)
        xs1 = x + w - int(w * side_margin)
        if xs1 - xs0 < 12:
            out.append(nb)
            continue
        samples = img32[p0:p1, xs0:xs1:3].reshape(-1, 3)
        q = (samples // 16) * 16
        colors, counts = np.unique(q, axis=0, return_counts=True)
        dom = colors[np.argmax(counts)].astype(np.int32)
        cols = np.arange(xs0, xs1, 3)
        strip = img32[y:y + h][:, cols]
        diff = np.abs(strip - dom).max(axis=2)
        frac = (diff <= bg_dist).mean(axis=1)
        k = min(5, max(3, h // 12)) | 1
        frac_s = np.convolve(frac, np.ones(k) / k, mode='same')
        row_std = strip.std(axis=1)

        # --- 顶部 ---
        t = None
        for i in range(min_rows, h - min_rows):
            if frac_s[i] >= high_frac and frac_s[min(i + 10, h - 1)] >= high_frac:
                low_above = int((frac_s[:i] < low_frac).sum())
                if low_above >= min_rows and np.median(row_std[:i]) >= 12:
                    t = i
                break
        if t is not None:
            new_h = h - t
            if new_h >= min_keep:
                nb['y'] = y + t
                nb['h'] = new_h
                h = new_h
                frac_s = frac_s[t:]
                row_std = row_std[t:]
        # --- 底部 ---
        if h >= min_rows * 2:
            t = None
            for i in range(h - min_rows, min_rows, -1):
                if frac_s[i] >= high_frac and frac_s[max(i - 10, 0)] >= high_frac:
                    low_below = int((frac_s[i + 1:] < low_frac).sum())
                    if low_below >= min_rows and np.median(row_std[i + 1:]) >= 12:
                        t = i
                    break
            if t is not None and t + 1 >= min_keep:
                nb['h'] = t + 1
        out.append(nb)
    if verbose:
        n = sum(1 for a, b in zip(boxes, out)
                if a['y'] != b['y'] or a['h'] != b['h'])
        print(f'背景色裁剪: {n} 个框调整')
    return out




def thin_lines(mask):
    """线条细化（骨架化）为 1px 中心线。

    优先 cv2.ximgproc.thinning（opencv-contrib）；缺失时退化
    skimage.morphology.skeletonize；都不可用则原样返回。
    """
    try:
        thinning = cv2.ximgproc.thinning  # noqa: F401
    except AttributeError:
        thinning = None
    if thinning is not None:
        return thinning(mask.astype(np.uint8) * 255) > 0
    try:
        from skimage.morphology import skeletonize
        return skeletonize(mask)
    except ImportError:
        return mask


def merge_double_edges(lines, iterations=1):
    """合并 Canny 在同一条边框两侧产生的平行双线：膨胀并线 + 骨架化。

    2K/高分辨率截图下边框线 ~2px 且带抗锯齿，Canny 在一条边框两侧各出
    一条边缘，形成间距 2~3px 的平行双线；轮廓验证时闭环退化成
    0 面积/多顶点的锯齿形而被误杀，或双线各自成环产生近重复框。
    dilate(3x3, iterations) 把双线并成一条粗线，骨架化回 1px 中心线后
    闭环恢复干净。坐标会随膨胀外扩 ~1px/次，对容器定位无影响。
    """
    merged = cv2.dilate(lines.astype(np.uint8),
                        np.ones((3, 3), np.uint8), iterations=iterations)
    return thin_lines(merged)


# ---------------------------------------------------------------- 主接口

def highlight_box_borders_v2_4(image, border_color=GREEN, bridge_radius=32,
                               min_w=40, min_h=22, merge_lines=True,
                               text_boxes=None, fg_thresh=40, stroke_dilate=2,
                               protect_len=50, color_crop=True, verbose=False):
    """识别图像中的容器/按钮边框并涂色（v2.4 = v2.2 + 可选文字笔画净化）。

    默认参数以 2K 截图（~2544x1336）为基准；1K（~1900 宽）截图建议
    resize 后使用，或传 bridge_radius=24, min_w=30, min_h=14。

    参数：
        bridge_radius: 端点桥接半径（圆角缺口补连的最大距离）。
        min_w, min_h: 保留框的最小宽/高（40 过滤滚动条，22 过滤文字假框）。
        merge_lines: 是否执行双线合并（膨胀 + 骨架化），高分辨率截图建议开。
        text_boxes: OCR 文字框 [(x0,y0,x1,y1), ...]（像素）。传入后先在
            Canny 边缘图上删除文字笔画（笔画级掩膜 + 长直线保护），根治
            按钮内竖笔画抢拐角桥接导致的漏检；None 时行为与 v2.2 完全一致。
        fg_thresh: 笔画判定的颜色距离阈值（L2）。
        stroke_dilate: 笔画掩膜膨胀半径（覆盖抗锯齿）。
        protect_len: 长直线保护阈值（>= 该长度的直线段豁免删除）。
        color_crop: 是否做背景色一致性裁剪（默认开），修正侧边栏把标题栏/logo
            区并入框顶、或页脚色块并入框底的误并框。

    返回：
        overlay: 原图上边框被涂色的图像。
        boundaries: 白底彩色边框图。
        boxes_mask: 布尔矩阵，True 表示识别到的边框像素。
        boxes: [{'x','y','w','h'}, ...] 外接框列表（按从上到下、从左到右排序）。
    """
    image = load_image(image)

    # 0. 文字笔画净化（可选）：边缘图删除文字笔画，长直线豁免
    edges = _raw_canny_edges(image)
    if text_boxes is not None:
        stroke_mask = build_text_stroke_mask(image, text_boxes,
                                             fg_thresh, stroke_dilate)
        edges, _ = clean_edges(edges, stroke_mask, protect_len)

    # 1. 提取水平/垂直直线（长笔画文字需靠第 0 步的内容级净化滤除）
    h_mask, v_mask = hv_lines_from_edges(edges)

    # 2. 端点桥接 + T 型吸附：补上圆角缺口和“差几像素”的断口
    lines, n_bridges = bridge_corner_gaps(h_mask, v_mask, radius=bridge_radius)

    # 3. 缺边合成：在净化后的原始线图上配对水平线（避免桥接线段干扰分段；
    #    文字像素已被删除，不会构成虚假 Canny 证据），结果并入桥接后的线图
    synth, n_pairs = synthesize_missing_sides(h_mask, v_mask, edges)
    lines |= synth

    # 4. 双线合并：膨胀并线 + 骨架化，消除平行双线造成的退化轮廓/近重复框
    if merge_lines:
        lines = merge_double_edges(lines)

    # 5. 闭合轮廓验证：只有闭合且像容器框的轮廓被保留，文字碎片自动丢弃
    boxes = find_closed_boxes(lines, min_w=min_w, min_h=min_h)

    # 5.5 背景色一致性裁剪：修正“把标题栏/logo 区并入侧边栏框顶”等误并框
    if color_crop:
        boxes = crop_color_boundaries(boxes, image, verbose=verbose)

    # 6. 边框涂色：叠加原图 + 白底边框图（按裁剪后的框裁剪轮廓点）
    boxes_mask = np.zeros(image.shape[:2], dtype=np.uint8)
    for b in boxes:
        pts = np.asarray(b.get('contour', []), dtype=np.int32).reshape(-1, 2)
        if pts.size:
            keep = ((pts[:, 0] >= b['x']) & (pts[:, 0] <= b['x'] + b['w']) &
                    (pts[:, 1] >= b['y']) & (pts[:, 1] <= b['y'] + b['h']))
            pts = pts[keep]
        if pts.size:
            cv2.drawContours(boxes_mask, [pts.reshape(-1, 1, 2)], -1, 1, 1)
    boxes_mask = boxes_mask > 0

    overlay = image.copy()
    overlay[boxes_mask] = border_color
    boundaries = np.ones_like(image) * 255
    boundaries[boxes_mask] = border_color

    boxes_out = sorted(({'x': b['x'], 'y': b['y'], 'w': b['w'], 'h': b['h']}
                        for b in boxes), key=lambda b: (b['y'], b['x']))
    if verbose:
        print(f"桥接条数: {n_bridges}, 合成侧边对数: {n_pairs}, "
              f"闭合容器/按钮框: {len(boxes_out)}")
    return overlay, boundaries, boxes_mask, boxes_out
