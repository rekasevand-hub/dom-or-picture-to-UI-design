# -*- coding: utf-8 -*-
"""run_pipeline.py — 对新截图跑完整管线：v2.4 掩膜容器 + OmniParser(GPU) 元素 + easyocr 文本 + 格式塔分组 + 直线精修."""
import os, sys, json, time, base64, io
ROOT = os.path.dirname(os.path.abspath(__file__))
_omni_cand = [os.path.join(ROOT, 'OmniParser', 'OmniParser-master'),
              os.path.join(os.path.dirname(ROOT), 'OmniParser', 'OmniParser-master')]
OMNI = next((p for p in _omni_cand if os.path.isdir(p)), _omni_cand[0])
sys.path.insert(0, OMNI)
sys.path.insert(0, ROOT)
import cv2, numpy as np

IMG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'user_test2.png')
PREFIX = sys.argv[2] if len(sys.argv) > 2 else 'test2'

img = cv2.imread(IMG)
print(f'image: {IMG} {img.shape[1]}x{img.shape[0]}')

# 1) easyocr 文本（先跑，供 v2.4 笔画级文字净化使用）
import easyocr
reader = easyocr.Reader(['ch_sim', 'en'], gpu=True)
t0 = time.time()
res = reader.readtext(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), text_threshold=0.5)
texts = []
for p, t, c in res:
    x0, y0 = int(p[0][0]), int(p[0][1]); x1, y1 = int(p[2][0]), int(p[2][1])
    if (x1-x0) >= 8 and (y1-y0) >= 6:
        texts.append({'x': x0, 'y': y0, 'w': x1-x0, 'h': y1-y0, 'type': 'text', 'content': t})
print(f'[easyocr] {len(texts)} texts, {time.time()-t0:.1f}s')

# 2) v2.4 掩膜容器（笔画净化：文字笔画不再构成 Canny/桥接的虚假证据）
from container_borders_v2_4 import detect_boxes as d2
tb = [(t['x'], t['y'], t['x']+t['w'], t['y']+t['h']) for t in texts]
t0 = time.time()
r2 = d2(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), text_boxes=tb)
v2 = r2['boxes']
print(f'[v2.4] {len(v2)} boxes, {time.time()-t0:.1f}s')

# 3) OmniParser 元素（GPU + 惰性桩）
from pipeline_utils import _install_paddleocr_stub
_install_paddleocr_stub()
from util.omniparser import Omniparser
from PIL import Image as PILImage
config = {
    'som_model_path': os.path.join(OMNI, 'weights', 'icon_detect', 'model.pt'),
    'caption_model_name': 'florence2',
    'caption_model_path': os.path.join(OMNI, 'weights', 'icon_caption_florence'),
    'device': 'cuda', 'BOX_TRESHOLD': 0.05,
}
t0 = time.time()
op = Omniparser(config)
with open(IMG, 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
som_img, parsed = op.parse(b64)
dt = time.time() - t0
W, H = PILImage.open(IMG).size
omni = []
for it in parsed:
    b = it.get('bbox')
    if b:
        b = [float(v) for v in b]
        if max(b) <= 1.0 and min(b) >= 0:
            b = [b[0]*W, b[1]*H, b[2]*W, b[3]*H]
        omni.append({'x': int(b[0]), 'y': int(b[1]), 'w': int(b[2]-b[0]), 'h': int(b[3]-b[1]),
                     'type': it.get('type'), 'content': str(it.get('content'))[:20]})
print(f'[OmniParser] {len(omni)} elements ({time.time()-t0:.1f}s)')

# 4) 格式塔分组 + 精修
from gestalt_group import (gestalt_group, refine_groups, resolve_overlaps,
                           build_hierarchy, inside_box, center)
from pipeline_utils import extract_box_lines_hv
elements = omni + texts
groups, stats, uncontained = gestalt_group(v2, elements)
h_mask, v_mask = extract_box_lines_hv(img, line_len=22)
h_mask[:3,:]=h_mask[-3:,:]=h_mask[:,:3]=h_mask[:,-3:]=False
v_mask[:3,:]=v_mask[-3:,:]=v_mask[:,:3]=v_mask[:,-3:]=False
groups = refine_groups(groups, uncontained, h_mask, v_mask, img.shape)
groups = resolve_overlaps(groups, v2)
print('=== 新增容器（精修后）===')
for g in groups:
    print(f'  ({g["x"]},{g["y"]}) {g["w"]}x{g["h"]}')

def covered(bs):
    return sum(1 for t in texts if any(inside_box(b, *center(t)) for b in bs))
before, after = covered(v2), covered(v2 + groups)
print(f'OCR 覆盖: 仅 v2 {before}/{len(texts)} ({100*before/len(texts):.0f}%)'
      f' -> v2+组 {after}/{len(texts)} ({100*after/len(texts):.0f}%)')
print('v2 未覆盖:', [t['content'] for t in texts if not any(inside_box(b, *center(t)) for b in v2)])
print('仍未覆盖:', [t['content'] for t in texts if not any(inside_box(b, *center(t)) for b in v2+groups)])

# 5) 输出
containers = build_hierarchy(v2 + groups)
json.dump(containers, open(os.path.join(ROOT, f'_{PREFIX}_containers.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
board = img.copy()
for b in v2:
    cv2.rectangle(board, (b['x'], b['y']), (b['x']+b['w'], b['y']+b['h']), (0, 200, 0), 2)
for g in groups:
    cv2.rectangle(board, (g['x'], g['y']), (g['x']+g['w'], g['y']+g['h']), (0, 150, 255), 3)
cv2.imwrite(os.path.join(ROOT, f'_{PREFIX}_overlay.png'), board)
# 深度配色干净图
depth_colors = {0: (255,200,0), 1: (0,200,0), 2: (0,160,255), 3: (200,0,255)}
clean = img.copy()
for b in containers:
    cv2.rectangle(clean, (b['x'], b['y']), (b['x']+b['w'], b['y']+b['h']),
                  depth_colors.get(b.get('depth', 0), (255,255,255)), 2)
cv2.imwrite(os.path.join(ROOT, f'_{PREFIX}_clean.png'), clean)
print(f'saved _{PREFIX}_containers.json / _{PREFIX}_overlay.png / _{PREFIX}_clean.png')
