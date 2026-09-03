import sys
import time

sys.path.insert(0, 'OmniParser/OmniParser-master')

start = time.time()
print('开始导入 util.omniparser...')
from util.omniparser import Omniparser
print(f'导入完成，耗时 {time.time()-start:.1f}s')

print('开始初始化 Omniparser...')
omni = Omniparser({
    'som_model_path': 'OmniParser/OmniParser-master/weights/icon_detect/model.pt',
    'caption_model_name': 'florence2',
    'caption_model_path': 'OmniParser/OmniParser-master/weights/icon_caption_florence',
    'device': 'cpu',
    'BOX_TRESHOLD': 0.05,
})
print(f'初始化完成，耗时 {time.time()-start:.1f}s')
