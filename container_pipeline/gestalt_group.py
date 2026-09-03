"""gestalt_group.py — 格式塔感知分组原型（报告第 5 节）.





输入：


  - v2 容器框（container_borders_v2 输出）


  - OmniParser 图标元素（GPU 实跑）


  - easyocr 文本元素（中文，代理 OmniParser+PaddleOCR 文本输出）





流程：


  1. 连通性：中心点落在 v2 容器内的元素归入该容器，不再参与分组；


  2. 邻近性：对未归属元素做 DBSCAN（欧氏距离 eps 聚类）；


  3. 对齐链式合并：单点/散簇沿行/列对齐链式合并（相似性+连续性）；


  4. 组框过滤 + 与 v2 容器去重叠；


  5. 按包含关系建层级（parent/depth）。





输出：合并后的容器列表 JSON + 叠加图 + 覆盖率对比。


"""


import json, sys


import numpy as np





GREEN = (0, 200, 0)


ORANGE = (0, 150, 255)


BLUE = (255, 120, 0)








def load_boxes(path):


    return json.load(open(path, encoding='utf-8'))








def center(b):


    return (b['x'] + b['w'] / 2, b['y'] + b['h'] / 2)








def inside_box(b, x, y):


    return b['x'] <= x <= b['x'] + b['w'] and b['y'] <= y <= b['y'] + b['h']








def dbscan(elems, eps, min_pts=1):


    """简易 DBSCAN：返回簇索引列表 [[idx,...], ...]"""


    n = len(elems)


    visited = np.zeros(n, bool)


    clusters = []


    for i in range(n):


        if visited[i]:


            continue


        # BFS


        stack = [i]; visited[i] = True; comp = []


        while stack:


            a = stack.pop(); comp.append(a)


            ax, ay = center(elems[a])


            for j in range(n):


                if visited[j]:


                    continue


                bx, by = center(elems[j])


                if (ax - bx) ** 2 + (ay - by) ** 2 <= eps * eps:


                    visited[j] = True; stack.append(j)


        if len(comp) >= min_pts:


            clusters.append(comp)


    return clusters








def bbox_of(elems, idxs, pad=4):


    xs0 = min(elems[i]['x'] for i in idxs); ys0 = min(elems[i]['y'] for i in idxs)


    xs1 = max(elems[i]['x'] + elems[i]['w'] for i in idxs)


    ys1 = max(elems[i]['y'] + elems[i]['h'] for i in idxs)


    return {'x': xs0 - pad, 'y': ys0 - pad,


            'w': xs1 - xs0 + 2 * pad, 'h': ys1 - ys0 + 2 * pad}








def iou(a, b):


    ix = max(0, min(a['x'] + a['w'], b['x'] + b['w']) - max(a['x'], b['x']))


    iy = max(0, min(a['y'] + a['h'], b['y'] + b['h']) - max(a['y'], b['y']))


    inter = ix * iy


    union = a['w'] * a['h'] + b['w'] * b['h'] - inter


    return inter / union if union else 0








def gestalt_group(v2_boxes, elements, eps=44, min_elems=2,


                   row_gap=34, col_gap=120, col_x_tol=40):


    """????????? + ???(DBSCAN) + ?/???????."""


    uncontained = []


    contained = []


    for el in elements:


        cx, cy = center(el)


        if any(inside_box(b, cx, cy) for b in v2_boxes):


            contained.append(el)


        else:


            uncontained.append(el)


    print(f'???: {len(elements)} | ??? v2 ??: {len(contained)} | ???: {len(uncontained)}')





    used = [False] * len(uncontained)


    groups = []





    def mark(idx_list):


        for i in idx_list:


            used[i] = True





    # 1) ???????(y ???)?????????????/???/????


    band_src = sorted(range(len(uncontained)), key=lambda i: center(uncontained[i])[1])


    bands = []


    for i in band_src:


        cy = center(uncontained[i])[1]


        if bands and cy - bands[-1]["cy"] <= row_gap:


            bands[-1]["idxs"].append(i)


            bands[-1]["cy"] = cy


        else:


            bands.append({"cy": cy, "idxs": [i]})


    for band in bands:
        if len(band["idxs"]) < 2:
            continue
        mem = [uncontained[i] for i in band["idxs"]]
        span = max(e["y"] + e["h"] for e in mem) - min(e["y"] for e in mem)
        hs = sorted(e["h"] for e in mem); ws = sorted(e["w"] for e in mem)
        med_h = hs[len(hs) // 2]; med_w = ws[len(ws) // 2]
        split_gap = max(100, 2 * med_w)
        order = sorted(band["idxs"], key=lambda i: center(uncontained[i])[0])
        gaps = [uncontained[k]["x"] - (uncontained[p]["x"] + uncontained[p]["w"])
                for p, k in zip(order, order[1:])]
        max_gap = max(gaps) if gaps else 0
        if span > max(2.0 * med_h, 60) or max_gap > split_gap:
            subs = [[order[0]]]
            for k in order[1:]:
                prev = uncontained[subs[-1][-1]]; cur = uncontained[k]
                gap_x = cur["x"] - (prev["x"] + prev["w"])
                if gap_x > split_gap:
                    subs.append([])
                subs[-1].append(k)
            for s in subs:
                if len(s) >= 2:
                    groups.append(bbox_of(uncontained, s))
                    mark(s)
        else:
            groups.append(bbox_of(uncontained, band["idxs"]))
            mark(band["idxs"])

    print(f'???: {sum(1 for b in bands if len(b["idxs"])>=2)}')


    # 2) DBSCAN ??????????????????????????


    rem = [i for i in range(len(uncontained)) if not used[i]]


    clusters = dbscan([uncontained[i] for i in rem], eps)


    for c in clusters:


        if len(c) >= min_elems:


            groups.append(bbox_of(uncontained, [rem[k] for k in c]))


            mark([rem[k] for k in c])


    print(f'DBSCAN ?: {len(groups)}')








    # 3) ???????(x ??)???????????????/???


    rem = [i for i in range(len(uncontained)) if not used[i]]


    merged = True


    while merged:


        merged = False


        for a in range(len(rem)):


            for b in range(a + 1, len(rem)):


                ea, eb = uncontained[rem[a]], uncontained[rem[b]]


                cxa = ea['x'] + ea['w'] / 2; cxb = eb['x'] + eb['w'] / 2


                x_overlap = not (ea['x'] + ea['w'] < eb['x'] or eb['x'] + eb['w'] < ea['x'])


                gap_ok = x_overlap or abs(cxa - cxb) <= col_x_tol


                ya, yb = center(ea)[1], center(eb)[1]


                if gap_ok and abs(ya - yb) <= col_gap and abs(ya - yb) >= 8:


                    groups.append(bbox_of(uncontained, [rem[a], rem[b]]))


                    used[rem[a]] = used[rem[b]] = True


                    rem = [i for k, i in enumerate(rem) if k not in (a, b)]


                    merged = True


                    break


            if merged:


                break


    print(f'????: {len(groups)} ? (??)')





    # 4) ????????????/???????


    changed = True


    while changed:


        changed = False


        for i in [i for i in range(len(uncontained)) if not used[i]]:


            el = uncontained[i]


            ex, ey = center(el)


            best, best_key = None, None


            for g in groups:


                gx, gy = g['x'] + g['w'] / 2, g['y'] + g['h'] / 2


                row_like = abs(ey - gy) <= 26 and abs(ex - gx) <= 400


                col_like = abs(ex - gx) <= 40 and abs(ey - gy) <= 200


                if row_like or col_like:


                    d = (ex - gx) ** 2 + (ey - gy) ** 2


                    if best is None or d < best_key:


                        best, best_key = g, d


            if best is not None:


                best['x'] = min(best['x'], el['x']); best['y'] = min(best['y'], el['y'])


                best['w'] = max(best['x'] + best['w'], el['x'] + el['w']) - best['x']


                best['h'] = max(best['y'] + best['h'], el['y'] + el['h']) - best['y']


                used[i] = True


                changed = True


                break





    # 5) ?? + ????? + ? v2 ???


    groups = [g for g in groups if g['w'] >= 30 and g['h'] >= 22]


    merged_groups = True


    while merged_groups:


        merged_groups = False


        for i in range(len(groups)):


            for j in range(i + 1, len(groups)):


                if iou(groups[i], groups[j]) > 0.5:


                    a, b = groups[i], groups[j]


                    groups[i] = {'x': min(a['x'], b['x']), 'y': min(a['y'], b['y']),


                                 'w': max(a['x'] + a['w'], b['x'] + b['w']) - min(a['x'], b['x']),


                                 'h': max(a['y'] + a['h'], b['y'] + b['h']) - min(a['y'], b['y'])}


                    groups.pop(j); merged_groups = True


                    break


            if merged_groups:


                break


    final = [g for g in groups if not any(iou(g, v) > 0.7 for v in v2_boxes)]


    # 6) ????????????????????


    kept = []


    def _contains(a, b, pad=6):


        return (a['x']-pad <= b['x'] and a['y']-pad <= b['y'] and


                b['x']+b['w'] <= a['x']+a['w']+pad and b['y']+b['h'] <= a['y']+a['h']+pad)


    for g in sorted(final, key=lambda g: -g['w']*g['h']):


        if any(_contains(h, g) for h in kept):


            continue


        kept.append(g)


    # 7) ???????x ??????y ?????????????/???


    merged2 = True


    while merged2:


        merged2 = False


        for i in range(len(kept)):


            for j in range(i+1, len(kept)):


                a, b = kept[i], kept[j]


                xov = min(a['x']+a['w'], b['x']+b['w']) - max(a['x'], b['x'])


                ygap = max(a['y'], b['y']) - min(a['y']+a['h'], b['y']+b['h'])


                if xov >= 0.8 * min(a['w'], b['w']) and ygap <= 24:


                    kept[i] = {'x': min(a['x'], b['x']), 'y': min(a['y'], b['y']),


                               'w': max(a['x']+a['w'], b['x']+b['w']) - min(a['x'], b['x']),


                               'h': max(a['y']+a['h'], b['y']+b['h']) - min(a['y'], b['y'])}


                    kept.pop(j); merged2 = True


                    break


            if merged2:


                break


    final = kept


    leftover = sum(1 for i in range(len(uncontained)) if not used[i])


    print(f'??+??????: {len(final)} | ???????: {leftover}')


    return final, {'uncontained': len(uncontained), 'contained': len(contained),


                   'clusters': len(clusters), 'singletons': leftover}, uncontained











def refine_groups(groups, uncontained, h_mask, v_mask, img_shape,


                  margin=60, cover=0.5, pct=(0.05, 0.85)):


    """??????????????????? + ???? + ???/????."""


    from pipeline_utils import _h_segments, _v_segments


    H, W = img_shape[:2]


    hsegs = _h_segments(h_mask, min_width=100)


    vsegs = _v_segments(v_mask, min_height=100)





    def members_of(g):


        return [el for el in uncontained


                if g['x'] <= el['x'] + el['w'] / 2 <= g['x'] + g['w']


                and g['y'] <= el['y'] + el['h'] / 2 <= g['y'] + g['h']]





    out = []


    for g in groups:


        mem = members_of(g)


        if len(mem) >= 2:


            # ???????h > 2.5x ????????????? icon ??


            hs_all = sorted(el["h"] for el in mem)


            med_h = hs_all[len(hs_all) // 2]


            mem = [el for el in mem if el["h"] <= max(2.5 * med_h, 60)]


            xs = sorted(el['x'] for el in mem)


            xt = sorted(el['x'] + el['w'] for el in mem)


            ys = sorted(el['y'] for el in mem)


            yt = sorted(el['y'] + el['h'] for el in mem)


            # ???????h > 2.5x ????????????? icon ??


            hs_all = sorted(el["h"] for el in mem)


            med_h = hs_all[len(hs_all) // 2]


            mem = [el for el in mem if el["h"] <= max(2.5 * med_h, 60)]


            k0 = max(int(len(xs) * pct[0]) - 1, 0)


            k1 = min(int(len(xs) * pct[1]), len(xs) - 1)


            x0, y0 = xs[k0], ys[k0]


            x1, y1 = xt[k1], yt[k1]


        else:


            x0, y0, x1, y1 = g['x'], g['y'], g['x'] + g['w'], g['y'] + g['h']


        bw, bh = x1 - x0, y1 - y0


        # ??


        cand = [s for s in hsegs if abs(s[0] - y0) <= margin and (s[2] - s[1] + 1) >= cover * bw]


        if y0 <= 6:


            y0 = 0


        elif cand:
            ny0 = min(cand, key=lambda s: abs(s[0] - y0))[0] + 1
            if ny0 < y1:
                y0 = ny0


        # ??


        cand = [s for s in hsegs if abs(s[0] - y1) <= margin and (s[2] - s[1] + 1) >= cover * bw]


        if H - y1 <= 6:


            y1 = H


        elif cand:
            ny1 = min(cand, key=lambda s: abs(s[0] - y1))[0]
            if ny1 > y0:
                y1 = ny1


        bh = y1 - y0


        # ??


        cand = [s for s in vsegs if abs(s[0] - x0) <= margin and (s[2] - s[1] + 1) >= cover * bh]


        if x0 <= 6:


            x0 = 0


        elif cand:
            nx0 = min(cand, key=lambda s: abs(s[0] - x0))[0] + 1
            if nx0 < x1:
                x0 = nx0


        # ??


        cand = [s for s in vsegs if abs(s[0] - x1) <= margin and (s[2] - s[1] + 1) >= cover * bh]


        if W - x1 <= 6:


            x1 = W


        elif cand:
            nx1 = min(cand, key=lambda s: abs(s[0] - x1))[0]
            if nx1 > x0:
                x1 = nx1


        # ???????? > 85% ?? -> ??


        if (x1 - x0) >= 0.85 * W:


            x0, x1 = 0, W


        if x1 > x0 and y1 > y0:


            out.append({'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0})


    # 顶/底通栏合并：同一结构行(y0/y1 对齐)且合并跨度>=85%宽 -> 全宽（顶栏/底栏）
    if len(out) >= 2:
        def _yrow(g):
            y0 = 0 if g["y"] <= 20 else g["y"]
            y1 = H if g["y"] + g["h"] >= H - 20 else g["y"] + g["h"]
            return y0, y1
        merged_rows = True
        while merged_rows:
            merged_rows = False
            for i in range(len(out)):
                for j in range(i + 1, len(out)):
                    a, b = out[i], out[j]
                    ya0, ya1 = _yrow(a); yb0, yb1 = _yrow(b)
                    if abs(ya0 - yb0) <= 4 and abs(ya1 - yb1) <= 4:
                        x0 = min(a["x"], b["x"])
                        x1 = max(a["x"] + a["w"], b["x"] + b["w"])
                        if (x1 - x0) >= 0.85 * W and (ya0 <= 20 or ya1 >= H - 20):
                            out[i] = {"x": 0, "y": ya0, "w": W, "h": ya1 - ya0}
                            out.pop(j)
                            merged_rows = True
                            break
                if merged_rows:
                    break

    return out








def resolve_overlaps(groups, v2_boxes, thin=18):


    """? v2 ?????????????????????."""


    kept = [dict(g) for g in groups]


    for g in kept:


        for v in v2_boxes:


            ix = min(g['x'] + g['w'], v['x'] + v['w']) - max(g['x'], v['x'])


            iy = min(g['y'] + g['h'], v['y'] + v['h']) - max(g['y'], v['y'])


            if ix <= 0 or iy <= 0:


                continue


            if ix >= 0.5 * min(g['w'], v['w']) and iy <= thin:


                # ??????g ? v ??????????


                if g['y'] + g['h'] <= v['y'] + v['h']:


                    g['h'] -= (g['y'] + g['h'] - v['y'])


                else:


                    g['y'] = v['y'] + v['h']


                    g['h'] = (g['y'] + g['h'] - v['y'])


            elif iy >= 0.5 * min(g['h'], v['h']) and ix <= thin:


                if g['x'] + g['w'] <= v['x'] + v['w']:


                    g['w'] -= (g['x'] + g['w'] - v['x'])


                else:


                    g['x'] = v['x'] + v['w']


                    g['w'] = (g['x'] + g['w'] - v['x'])


            if g['w'] <= 0 or g['h'] <= 0:


                break


    return [g for g in kept if g['w'] > 0 and g['h'] > 0]








def build_hierarchy(containers):


    """按包含关系建 parent/depth"""


    for c in containers:


        c['depth'] = 0; c['parent'] = None


    for a in containers:


        cands = [b for b in containers


                 if b is not a and b['x'] <= a['x'] and b['y'] <= a['y']


                 and a['x'] + a['w'] <= b['x'] + b['w'] + 1


                 and a['y'] + a['h'] <= b['y'] + b['h'] + 1]


        if cands:


            p = min(cands, key=lambda b: b['w'] * b['h'])


            a['parent'] = p; a['depth'] = p['depth'] + 1


    return containers








if __name__ == '__main__':

    import sys as _sys

    IMG = _sys.argv[1] if len(_sys.argv) > 1 else r'D:\LLM-Data\View_fill\user_test.png'

    PREFIX = _sys.argv[2] if len(_sys.argv) > 2 else 'gestalt'


    v2 = load_boxes(r'D:\LLM-Data\View_fill\_uied_out\v2_boxes.json')


    omni = load_boxes(r'D:\LLM-Data\View_fill\_omniparser_elements.json')


    # 文本元素：easyocr 中文（OmniParser 英文 OCR 的替代）


    import cv2, easyocr


    img = cv2.imread(IMG)


    reader = easyocr.Reader(['ch_sim', 'en'], gpu=True)


    res = reader.readtext(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), text_threshold=0.5)


    texts = []


    for p, t, c in res:


        x0, y0 = int(p[0][0]), int(p[0][1]); x1, y1 = int(p[2][0]), int(p[2][1])


        if (x1 - x0) >= 8 and (y1 - y0) >= 6:


            texts.append({'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0, 'type': 'text', 'content': t})


    omni_norm = [{'x': e['bbox'][0], 'y': e['bbox'][1],


                   'w': e['bbox'][2] - e['bbox'][0], 'h': e['bbox'][3] - e['bbox'][1],


                   'type': e['type'], 'content': e.get('content')} for e in omni]


    elements = omni_norm + texts


    print(f'元素池构成: OmniParser {len(omni)} + easyocr {len(texts)} = {len(elements)}')





    groups, stats, uncontained = gestalt_group(v2, elements)


    # ?????????? + ?????? + ? v2 ?????


    from pipeline_utils import extract_box_lines_hv


    h_mask, v_mask = extract_box_lines_hv(img, line_len=22)


    h_mask[:3, :] = h_mask[-3:, :] = h_mask[:, :3] = h_mask[:, -3:] = False


    v_mask[:3, :] = v_mask[-3:, :] = v_mask[:, :3] = v_mask[:, -3:] = False


    groups = refine_groups(groups, uncontained, h_mask, v_mask, img.shape)


    groups = resolve_overlaps(groups, v2)


    print('=== ???????????? ===')


    for g in groups:


        print(f'  新容器 ({g["x"]},{g["y"]}) {g["w"]}x{g["h"]}')





    # 覆盖率对比（以 easyocr 文本为基准）


    def covered(bs):


        return sum(1 for t in texts


                   if any(inside_box(b, *center(t)) for b in bs))


    before = covered(v2)


    after = covered(v2 + groups)


    print(f'OCR 文本覆盖: 仅 v2 {before}/{len(texts)} ({100*before/len(texts):.0f}%)'


          f' -> v2+格式塔组 {after}/{len(texts)} ({100*after/len(texts):.0f}%)')


    print('v2 ??????:', [t['content'] for t in texts


                               if not any(inside_box(b, *center(t)) for b in v2)])


    print('v2+? ????:', [t['content'] for t in texts


                              if not any(inside_box(b, *center(t)) for b in v2 + groups)])





    containers = build_hierarchy(v2 + groups)


    json.dump(containers, open(f'D:\\LLM-Data\\View_fill\\_{PREFIX}_containers.json', 'w',


                               encoding='utf-8'), ensure_ascii=False, indent=1)





    # 叠加图


    board = img.copy()


    for b in v2:


        cv2.rectangle(board, (b['x'], b['y']), (b['x'] + b['w'], b['y'] + b['h']), GREEN, 2)


    for g in groups:


        cv2.rectangle(board, (g['x'], g['y']), (g['x'] + g['w'], g['y'] + g['h']), ORANGE, 3)


    for el in elements:


        cv2.rectangle(board, (el['x'], el['y']), (el['x'] + el['w'], el['y'] + el['h']), BLUE, 1)


    cv2.imwrite(f'D:\\LLM-Data\\View_fill\\_{PREFIX}_overlay.png', board)


    print(f'saved _{PREFIX}_containers.json / _{PREFIX}_overlay.png')
