import json
from collections import Counter

with open('output/03_features.json', encoding='utf-8') as f:
    data = json.load(f)
comps = data.get('components', [])
print(f'总组件数: {len(comps)}')
types = Counter(c.get('type') for c in comps)
print('OpenCV/OmniParser 类型分布:', dict(types))

with open('output/05_design.json', encoding='utf-8') as f:
    design = json.load(f)
elems = design.get('elements', [])
print(f'LLM 输出元素数: {len(elems)}')
types2 = Counter(e.get('type') for e in elems)
print('LLM 类型分布:', dict(types2))
