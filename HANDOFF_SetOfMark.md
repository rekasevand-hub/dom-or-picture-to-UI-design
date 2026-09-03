# 网页截图 UI 结构理解：Set-of-Mark 方案交接文档

> 用途：在另一个项目中延续本方案时，把本文档交给 Kimi Code（或其他协作者）即可恢复全部上下文。
> 撰写时间：2026-07-29（2026-07-30 更新：新增 v3，见 3.3 节；2026-08-19 更新：omni 环境换 GPU 构建，见 3.3 节末尾）
> 来源项目：`D:\LLM-Data\View_fill`

---

## 1. 一句话目标

输入一张网页/App 截图，自动产出 **Set-of-Mark 标注图 + 配套结构化 JSON**，一起喂给多模态大模型，使其理解页面的**布局容器结构**和**可交互元素**，并能引用精确坐标（用于 UI 代码生成、自动化操作等下游任务）。

## 2. 方案总览（已确定的管线）

分两层检测，再合并：

```
截图
 ├── 容器层：container_borders_v1 / v2 包（本项目产出）
 │    └── 检测布局容器：侧边栏、顶栏、卡片、面板、按钮框 → bbox 列表
 └── 元素层：OmniParser（另一个项目已有）
      └── 检测可交互元素 + 图标 + OCR 文本 → bbox + text + type + interactivity

合并（Set-of-Mark 挂接，待实现）：
    元素按 bbox 包含关系挂进容器树 → 双编号标注图 + 层级 JSON → 大模型
```

为什么两层都要：

- OmniParser 只给元素级标注（图标、按钮、文本块），**不知道布局容器**——哪些元素属于同一张卡片、侧边栏边界在哪、区块嵌套关系如何；
- 本项目的容器检测只给容器骨架，**不管框里装的是什么**；
- 合并后大模型既知道"有哪些按钮、写什么字"，也知道"这些元素在哪个容器里、容器之间什么关系"。容器层级还能把 OmniParser 密集标注（如表格行）按容器分组，比几十个平铺编号清晰得多。

## 3. 容器检测包（本项目产出，可直接导入）

两个包互有取舍，**最终用哪个待实际效果对比后决定**。两个包自包含、互不依赖，把整个目录拷到目标项目即可 `import`。

公共依赖：`numpy`、`opencv-python`（`Pillow` 仅在传入图片路径时需要）。

### 3.1 `container_borders_v1` —— 直线提取 + 外接框重建 + 圆角补全

- 管线：逐通道 Canny(10/30) → 形态学开运算提水平/垂直长直线（文字笔画被滤除）→ 清四边 3px 伪线 → 13×13 膨胀分组、每组重绘外接矩形 → 圆角补全（配对水平线 + 两端竖线 → 画闭合矩形）。
- **优点**：召回偏高，断开的边能强行重建为矩形。
- **缺点**：可能把相邻元素合并成大框、可能重建出幻影框；`boxes` 由边框掩膜的连通分量导出，**相连/重叠的框会合并为一个**；大号汉字的"口"类闭合笔画会被重建成小假框。
- **默认参数以 2K 截图（~2544×1336）为基准**（v1.1，2026-07-29 调定）：`line_len=22`（2K 文字笔画 ~20-28px，22 是滤文字与保小按钮直边的折中）、`corner_tol=20`、`max_height=670`、`min_w=40`、`min_h=28`。实测 2K 下检出 18 框、无文字碎片；固有行为：间距 <13px 的相邻按钮合并为一个组框（分页三按钮合一），最外层页面框架连通为一个近全图大框。1K 截图建议 resize 后使用，或在 core 层传 `line_len=20, corner_tol=15` + `detect_boxes(min_w=30, min_h=14)`。
- 局限：小圆角按钮（~47px、直边 ~23px）与文字笔画长度接近，参数上无法两头兼顾——分开检出小按钮和滤除文字碎片只能二选一（当前选择滤文字，分页按钮以组合框形式保留）。需要精确小按钮框用 v2。

### 3.2 `container_borders_v2` —— 端点桥接 + 缺边合成 + 双线合并 + 闭合轮廓验证

- 管线：提取水平/垂直直线 → 端点桥接（圆角断角一横一竖两个自由端点互连）+ T 型吸附（端点差几像素没碰上的延长吸附）+ 同向断线桥接 → 缺边合成（水平线配对后，缺失竖边若有 ≥50% Canny 行覆盖证据则补画）→ 双线合并（膨胀并线 + 骨架化，消除高分辨率下 Canny 双边退化轮廓和近重复框）→ `findContours` 闭合轮廓验证（只保留闭合、近似 4~8 边形、尺寸达标、面积占比合理的轮廓）。
- **优点**：文字碎片/幻影框自动剔除，框坐标直接来自轮廓外接框，精度高。
- **缺点**：召回偏保守，实在闭不上的框（缺边且无 Canny 证据）会被丢弃。
- **默认参数以 2K 截图（~2544×1336）为基准**（v2.2，2026-07-29 在 `2k_pic.png` 上调定）：`bridge_radius=32`（2K 圆角缺口 ~30px，原 24 连不上）、`min_w=40`（过滤 32px 宽滚动条）、`min_h=22`（过滤文字笔画与边框围出的扁假框）、`merge_lines=True`（双线合并）。实测 2K 下检出 28 框（banner、高亮按钮、状态标签、分页箭头齐全，无滚动条/假框）；1K 截图直接用 2K 参数框数不变、坐标漂移 ≤3px，也可显式传旧参数 `bridge_radius=24, min_w=30, min_h=14`。
- **v2.4（2026-08-11）= v2.2 + 可选文字笔画净化，独立包 `container_borders_v2_4`**（本包保持 v2.2 无掩膜行为；`highlight_box_borders_v2_4.py` 为单文件参考源）：传入 OCR 文字框（`text_boxes`，由调用方提供，包本身零 OCR 依赖）即在 Canny 边缘图上先删文字笔画——移植自 v3 的笔画级掩膜（框内环带中位色为背景、L2 距离 > `fg_thresh=40` 判笔画、膨胀 `stroke_dilate=2`px）+ 长直线保护（≥ `protect_len=50`px 线段及 1px 邻域豁免）；缺边合成的证据边缘同样用净化后的（文字不再构成虚假证据）。不传 `text_boxes` 时与 v2.2 逐像素一致（已回归验证）。命令行 demo：`python highlight_box_borders_v2_4.py [paddle|easyocr|auto|none]`（OCR 借 `highlight_box_borders_v3.detect_text_boxes`）。**v2.3 版本号跳过**（反向桥接 + 泛洪营救方案曾回退，见下）。
- v2.4 实测（paddle OCR 供框）：`2k_pic.png` 29 框 = v2.2 的 28 框全保留 + **救回分页"1"按钮**（竖笔画抢拐角桥接的漏检已根治）；`truly_test.png` 26 框与无掩膜完全相同（无副作用）；`tt_sys.png`（1K 参数）115 框 vs 无掩膜 117——丢的 2 框是"操作"固定列表头单元格：无掩膜版靠该列**投影阴影的边缘**充当缺边合成证据（侥幸检出），掩膜把阴影边缘当笔画删掉后暴露出真实边框证据不足，属诚实漏检而非误伤（该竖边本身在笔画掩膜外，未被删除）。
- 已知漏检模式（v2.2 无掩膜）：按钮内有**竖直笔画文字**且靠近圆角拐角时（如分页"1"按钮），笔画会抢走拐角桥接导致轮廓敞开、该按钮漏检。**用 v2.4 传 text_boxes 可消除**。曾实现反向桥接 + 泛洪营救修复（能检出"1"），但引入图标误检等边界问题，已回退。
- 骨架化依赖：优先 opencv-contrib 的 `cv2.ximgproc.thinning`，缺失自动退化 `skimage.morphology.skeletonize`，再缺失跳过细化（高分辨率截图会因此丢框，建议装 opencv-contrib-python）。
- 存档基线参数提醒：`tt_sys_v2_boxes.json`（118 框）是 v2.2 之前用 1K 时代参数（`bridge_radius=24, min_w=30, min_h=14`、无双线合并）跑出的；用包默认 2K 参数跑 `tt_sys.png` 得 104 框（2K 参数下 min_w=40 等会滤掉小格），非代码回退。`2k_pic_v2_boxes.json`（28 框）与包默认参数完全一致。

### 3.3 `container_borders_v3` / `highlight_box_borders_v3.py` —— v1 管线 + OCR 笔画级文字掩膜

- 动机：v1/v2 的"文字滤除"只靠形态学（保留 ≥ line_len 的直线段），长笔画（如分页"1"竖笔）滤不掉、短边框与文字一起被误杀；而整框 OCR 掩膜又会误杀贴近文字的边框线。v3 在 v1 管线的 Canny 之后、形态学之前插入内容级文字净化：
  1. **OCR 文字框**（`ocr_engine` 四选）：`'auto'` 优先调项目内 OmniParser 的 `check_ocr_box`——其 `util/utils.py` 模块级按 paddleocr 2.x 参数实例化 PaddleOCR 与 3.x 不兼容，参照 Figma_auto_agent 的 `omniparser_server` 脚本，导入前对 `PaddleOCR.__init__` 打参数过滤补丁（不改 OmniParser 源码）即可正常导入，失败自动回退直接调 easyocr（两者同为 easyocr 运行时，结果一致）；`'easyocr'` 直调；`'paddle'` 用 PaddleOCR(lang='ch')，中文/小字检测更好（2K 全页直接检出分页"1"，easyocr 首轮漏检）。**CPU 构建的 paddle 必须传 `enable_mkldnn=False`**：paddlepaddle(CPU) 3.3.1 + Windows oneDNN 在 PIR 属性转换处必崩（`NotImplementedError: ConvertPirAttribute2RuntimeAttribute`），关 mkldnn 即正常——注意环境变量 `FLAGS_use_mkldnn`/`FLAGS_use_onednn` 实测**无效**，只有构造参数有效；代价是 CPU 慢（2K 全页 ~40s vs easyocr ~7s）。**2026-08-19 起 omni 环境已换 GPU 构建**（RTX 4060 Laptop，驱动 572.83/CUDA 12.8；`paddlepaddle-gpu==3.3.1` cu126 + `torch 2.12.1+cu126`，paddle 官方 wheel 自带 cuDNN 9.5 等运行时、无需另装 CUDA 工具包）：`_get_paddle_reader` 自动检测并传 `device='gpu'`（`enable_mkldnn=False` 保留、GPU 下无影响），easyocr 经 `gpu=torch.cuda.is_available()` 自动上 GPU。GPU 实测（2K 全页）：v3+paddle 全流程 ~11s（CPU 时仅 OCR 就 ~44s）、easyocr ~10s（CPU ~19s）；回归与 CPU 存档一致（v3 paddle 21 框、v2.4 掩膜版 29 框逐框相同、v3 easyocr 23 框）。此解法同样适用于 Figma_auto_agent 的 wrapper 服务（给 OmniParser 的 `check_ocr_box` 传 `use_paddleocr=True` 前需先解决其实例化参数与 mkldnn 问题）。**GPU 构建引入的新坑（2026-08-19 已修）**：torch(CUDA) 与 paddlepaddle-gpu 同进程会因同名 `cudnn_cnn64_9.dll` 版本不同（torch 自带 vs paddle wheel 自带 9.5.1.17）互踩，先加载的一方赢、另一方 `WinError 127`——`util/utils.py` 先 `import easyocr`（拉起 torch）再实例化 PaddleOCR，原来的参数过滤补丁不足以应付；现改为 `detect_text_boxes` 在 OmniParser 路径优先装**惰性桩**（`_install_paddleocr_stub`：sys.modules 里的假 paddleocr 模块，模块级实例化只记录参数不加载 paddle，首次被真正调用才导入真模块并 __class__ 替换为真实例），补丁仅在真 paddleocr 已被先行加载时兜底。推论：**同一进程内 paddle 引擎与 easyocr/omniparser（torch 系）引擎不可混用**（DLL 冲突双向）；Figma_auto_agent 的 wrapper 若要给 `check_ocr_box` 传 `use_paddleocr=True` 走 GPU，须与同进程的 torch 模型隔离（分进程）。**该惰性桩修复已同步到 Figma_auto_agent 的 `src/app/services/omniparser/omniparser_server.py`（2026-08-19，替换原参数过滤补丁，补丁降级为桩装不上时的兜底）**，其 OmniParser HTTP 服务已实测恢复启动（`--device cuda`，YOLO+Florence+easyocr 全部真正跑上 GPU，2K 截图 /parse 延迟 ~4s）。
  2. **笔画级掩膜**：每个文字框内取四周环带中位色为背景、L2 距离 > `fg_thresh=40` 的像素为笔画、膨胀 2px——只删真实字形像素，贴边边框线不受影响（深色底白字、蓝按钮白字、浅黄 banner 深字均实测干净）。
  3. **长直线保护**：≥ `protect_len=50`px 的水平/垂直线段及 1px 邻域豁免删除。
  4. **二次定向 OCR（`second_pass_ocr`，默认 None=按引擎自动）**：首轮后幸存的孤立短竖线段（22~60px、不碰任何水平线，多为漏网文字笔画或图标竖边）裁窗 3× 放大重 OCR，三重确认（识别置信度 ≥0.5 + 纵向覆盖线段 ≥50% + 线段落在识别框中部 60%）才补掩——防圆角弧线被误识为 "("（easyocr conf 0.36 被阈值挡下）后误掩边框。**paddle 引擎下默认关闭**：paddle 首轮检出率高不需要保险，且其对标点形状的高置信误识（把圆角边框认作 "["，conf>0.5）会突破确认门槛、实测 12 处误掩边框（banner/选中行/创建按钮边被吃掉）；easyocr 系默认开启。
- 实测（`2k_pic.png`，2K）：v1 的 18 框全部保留（IoU≥0.5 对照 0 丢失），原先 API 卡片里"文字桥接粘连"的大框被拆成正确的小元素框；分页"1"按钮检出。easyocr 引擎：23 框（v1 全量 + 侧边栏图标×2 + 复制图标×1 + 进度条×2），~19s CPU；paddle 引擎：21 框（v1 全量 + 侧边栏图标×1 + 进度条×2——paddle 把图标误识为文字掩掉，噪声更少），"1"首轮即掩，~44s CPU。
- 已知行为：easyocr 下图标会被框出（图标笔画挺过形态学且 OCR 不确认其为文字）——对 Set-of-Mark 而言可留可滤，待定；easyocr 对微小孤立字符（如分页"1"）首轮检测不到，但 2K 下其竖笔 ~21px < `line_len=22` 天然被形态学滤除，不构成 v2 那种拐角桥接干扰。**网格密集型页面（如 ERP 全框线表格 `tt_sys.png`）会触发 v1  lineage 的固有合并**：整张表格的框线全连通 → 13×13 分组链成一体 → 只产出一个近全图巨框（叠加图边框全绿、视觉正常，但框列表只 23 个，单元格/工具栏按钮全被并入巨框；同图 v2 产出 118 框含逐单元格）。此类页面应选 v2；v3 的文字掩膜预处理与管线解耦，**另有 v2 血统的移植版 `container_borders_v2_4` 包（见 3.2 节 v2.4）**。
- API（包 `detect_boxes` 与 v1/v2 统一，见 3.4 节）：`highlight_box_borders(image, text_boxes=None, ocr_engine='auto', second_pass_ocr=None, ...) -> (overlay, boundaries, boxes_mask)`；已有 OCR 结果时传 `text_boxes=[(x0,y0,x1,y1),...]`（像素）跳过内置 OCR；`boxes_from_mask(boxes_mask)` 导出 xywh 框列表（连通分量、不膨胀，`min_side=6` 滤退化线残段）；`detect_text_boxes(image, engine=..., omniparser_dir=...)` 单独做 OCR。命令行 demo：`python highlight_box_borders_v3.py [auto|easyocr|paddle|omniparser] [--second-pass|--no-second-pass]`。
- 依赖：`numpy`、`opencv-python`；OCR 全部懒加载（不跑 OCR 只传 text_boxes 时无需任何 OCR 库）：`easyocr`（默认引擎）、`paddleocr` 可选（仅 `ocr_engine='paddle'` 时需要，需 paddlepaddle 已装且传 `enable_mkldnn=False`）、OmniParser 可选（`'auto'/'omniparser'`，包内默认指向项目根 `OmniParser/OmniParser-master`，整目录拷贝后不存在则自动回退 easyocr）。
- 状态：**已打包 `container_borders_v3`（2026-08-11）**，打包回归通过——同一份 text_boxes 下包与原型脚本逐框/逐像素一致（paddle 21 框），auto/omniparser 端到端 23 框与存档一致；OCR 依赖懒加载已验证（import 包不拉起 easyocr/paddleocr）。

### 3.4 统一 API（v1/v2/v3 包一致）

```python
from container_borders_v2 import detect_boxes   # 或 container_borders_v1 / container_borders_v3

result = detect_boxes('screenshot.png')   # 也接受 (H, W, 3) RGB ndarray
result['boxes']       # [{'x': int, 'y': int, 'w': int, 'h': int}, ...]
                      # 像素坐标，原点左上，按从上到下、从左到右排序
result['overlay']     # 边框涂色叠加图（ndarray）
result['boundaries']  # 白底边框图（ndarray）
result['boxes_mask']  # 边框像素布尔掩膜
```

v2 额外参数：`bridge_radius`（端点桥接半径，默认 32）、`merge_lines`（双线合并，默认 True）、`verbose=True` 打印统计。

v2.4（`container_borders_v2_4`）在 v2 参数之上另有：`text_boxes`（可选 OCR 文字框，传入即做笔画级边缘净化，见 3.2 节 v2.4）、`fg_thresh` / `stroke_dilate` / `protect_len`（净化微调）。

v3 额外参数：`text_boxes` / `ocr_engine`（`'auto'/'omniparser'/'easyocr'/'paddle'`，默认 `'auto'`）/ `second_pass_ocr`（None=按引擎自动）/ `omniparser_dir` / `min_side`（框导出最小边，默认 6）/ `fg_thresh` / `dilate_px` / `protect_len` / `return_debug` / `verbose`。

底层函数也可单独导入做自定义管线，见各包 `__init__.py` 的 `__all__`。

## 4. 待实现：Set-of-Mark 合并脚本（`som_annotate.py`）

这是下一步的核心工作。设计已讨论确定，分五步：

### 4.1 输入对齐

- 两条管线必须跑在**同一张截图**上，坐标系天然一致。
- 容器框：`detect_boxes` 的 `result['boxes']`（像素坐标）。
- OmniParser 输出：它的 parsed content list。**需先确认其坐标格式**（像素还是 0~1 归一化），归一化则乘图像宽高还原。

### 4.2 挂接：元素 → 容器树

- 元素中心点落在哪个**最小**容器内，就挂到那个容器下（中心点法比 IoU 简单且够用——元素可能部分超出容器边）。
- 容器之间按 bbox 包含关系建树（也可复用来源项目 `recursive_layer_fill.py` 的嵌套树思路）。
- 没被任何容器罩住的元素挂到根节点（页面级）。
- 跨容器边界的元素（如弹窗）挂到中心点所在容器，并标记 `overflow: true`。

### 4.3 双编号标注图

- **元素框**：细实线 + 编号 `1, 2, 3...`（OmniParser 惯例）。
- **容器框**：粗线/不同色相 + 编号 `C1, C2...`，颜色按嵌套深度渐变。
- 编号标签放框左上角外侧，小色块衬底（风格参照 OmniParser 输出图）。
- 编号按视觉阅读顺序（先上后下、先左后右）重排，大模型读起来更顺。

### 4.4 配套 JSON

```json
{
  "image": "screenshot.png",
  "size": [1867, 1280],
  "containers": [
    {"id": "C1", "bbox": [0, 0, 312, 366], "depth": 0, "parent": null,
     "elements": [12, 13]}
  ],
  "elements": [
    {"id": 12, "bbox": [1580, 301, 78, 33], "text": "创建",
     "type": "button", "interactable": true, "container": "C1"}
  ]
}
```

- `bbox` 统一为 `[x, y, w, h]` 像素坐标。
- 元素字段直接沿用 OmniParser 输出（`text`、`type`、`interactable`），不重复造轮子。

### 4.5 Prompt 模板（随图和 JSON 一起给大模型）

> 截图中有两类标注框：编号框（1,2,3...）是可交互元素/文本，C 开头编号（C1,C2...）是布局容器。JSON 中 `elements` 按 id 对应图上编号，`container` 字段表示元素所属容器；`containers` 的 `parent`/`depth` 表示嵌套关系。

## 5. 待决策 / 待确认事项

1. **v1 / v2 / v3**：在目标项目的真实截图上各跑一遍，对比召回/误检后选定（预期 v2 更准、v1 更全）。**2026-07-29 尺度实测已倾向 v2**：截图放大 1.34 倍时 v1 框数 12→34（拆碎），v2 仅 26→27，且 v2 框坐标直接来自轮廓验证。除非 v2 在真实截图上漏检关键容器，否则选 v2。**2026-07-30 新增 v3**（3.3 节）：若页面文字对检测干扰大（文字桥接粘框、长笔画假线段），或计划下调 `line_len` 捞更小元素，优先评估 v3——代价是引入 OCR 依赖与耗时。**2026-08-11 v2.4 后基本定型选 v2**：v3 的文字净化已有 v2 血统移植版（包 `container_borders_v2_4`），v2 唯一的已知漏检模式（按钮内竖笔画抢拐角）可用它根治；v3 仍受 v1 lineage 固有合并所限（网格密集页产出巨框），已于同日打包 `container_borders_v3` 备用（OCR 懒加载，文字干扰大的普通页面仍可选用）。文字净化需 OCR 供框（推荐 paddle，easyocr 会漏微小孤立字符）；不想引入 OCR 时直接用 `container_borders_v2` 包（v2.2 无掩膜）。
2. **OmniParser 输出格式**：确认坐标是像素还是归一化、字段名（`bbox`/`content`/`type`/`interactivity`），决定 4.1 的适配代码。
3. **下游任务优先级**：布局理解问答 / UI 代码生成 / 自动化操作——决定 JSON 里哪些字段是必需的（见第 7 节取舍）。

## 6. 已知限制（容器检测）

- **尺度敏感（v2.2 / v1.1 已大幅缓解）**：管线参数是绝对像素值。v2.2 与 v1.1 起默认参数均以 2K（~2544 宽）为基准；v2.2 另加双线合并（膨胀 + 骨架化）解决高分辨率下 Canny 双边导致的退化轮廓/近重复框。实测：同一界面 1890×882 与 2544×1336 截图，v2.2 检出结构一致（1K 下坐标漂移 ≤3px）。**极端尺寸差异仍建议 resize 到 ~2544 宽再检测。**
- 面向**轴对齐矩形框**；斜线/圆形元素不适用（圆形图标轮廓顶点数 >8，v2 会主动排除）。
- 边界接触/交叉的容器会被合并成一个连通体，嵌套树可能出错。
- 深色背景上对比度极低的边框可能挺不过 Canny + 形态学，v2 无证据不合成，会漏检。
- v1 的汉字"口/台"类闭合笔画会产生 ~20px 假框（v2 已解决）。

## 7. 按下游场景的取舍

| 下游任务 | 最小需求 |
|---------|---------|
| 理解页面布局、回答"这个页面有什么" | 标注图 + 简化 JSON（id + bbox） |
| 生成 UI 代码 / 还原页面结构 | JSON 为主（bbox + 容器层级），标注图辅助 |
| 自动化操作（点按钮、填表单） | 标注图 + JSON（id + bbox + OCR 文本 + interactable） |

## 8. 来源项目文件索引（`D:\LLM-Data\View_fill`）

| 文件 | 说明 |
|------|------|
| `container_borders_v1/` | v1 检测包（自包含，可整目录拷贝导入） |
| `container_borders_v2/` | v2 检测包 v2.2（自包含，可整目录拷贝导入；无掩膜，零 OCR 依赖） |
| `container_borders_v2_4/` | v2.4 检测包（自包含，可整目录拷贝导入；v2.2 + 可选 `text_boxes` 文字净化，零 OCR 依赖） |
| `highlight_box_borders_v2_4.py` | v2.4 单文件原型（`container_borders_v2_4` 的代码来源，勿改；带命令行 demo） |
| `container_borders_v3/` | v3 检测包（自包含，可整目录拷贝导入；OCR 懒加载，不跑 OCR 仅需 numpy+opencv） |
| `highlight_box_borders_v3.py` | v3 单文件原型（包的代码来源，勿改；见 3.3 节） |
| `highlight_box_borders.py` | v1 原始脚本（包的代码来源，勿改） |
| `highlight_box_borders_v2.py` | v2 原始脚本（包的代码来源，勿改） |
| `OmniParser/OmniParser-master/` | OmniParser 源码（v3 经 `PaddleOCR.__init__` 参数过滤补丁后正常导入其 `check_ocr_box`；补丁思路见 Figma_auto_agent 的 omniparser_server 脚本） |
| `truly_test.png` | 测试截图（CloseAI 控制台页面，1890×882，1K） |
| `truly_test_v2_boxes.json` | v2 在该截图上的框输出样例（26 个框） |
| `truly_test_v2_borders.png` | v2 边框叠加效果样例 |
| `2k_pic.png` | 2K 基准测试截图（2544×1336，v2.2/v1.1 参数调定用） |
| `2k_pic_v2_boxes.json` | v2.2 在 2K 基准图上的框输出（28 个框） |
| `2k_pic_v2_borders.png` | v2.2 边框叠加效果样例（2K） |
| `2k_pic_v1_boxes.json` | v1.1 在 2K 基准图上的框输出（18 个框） |
| `2k_pic_v1_borders.png` | v1.1 边框叠加效果样例（2K） |
| `2k_pic_v3_boxes.json` | v3(paddle) 在 2K 基准图上的框输出（21 框；easyocr 引擎为 23 框 = v1 全量 + 5 个真实小元素，该存档已被 paddle 版覆盖，见 3.3 节） |
| `2k_pic_v3_borders.png` | v3 边框叠加效果样例（2K） |
| `2k_pic_v3_textmask.png` | v3 笔画掩膜调试图（红=被净化的文字笔画，可核对贴边边框零误伤） |
| `2k_pic_v2m_boxes.json` / `2k_pic_v2m_borders.png` / `2k_pic_v2m_boundaries.png` | v2.4 掩膜版（paddle 供框）在 2K 基准图上的输出：29 框 = v2.2 全量 28 + 分页"1"按钮（见 3.2 节 v2.4） |
| `tt_sys.png` | ERP 网格密集测试截图（2544×1336，全框线表格 + 右侧固定列带投影） |
| `tt_sys_v2_boxes.json` / `tt_sys_v2_borders.png` | v2 用 **1K 时代参数**在 `tt_sys.png` 上的输出（118 框含逐单元格；包默认 2K 参数跑出 104 框，见 3.2 节参数提醒） |
| `tt_sys_v2m_boxes.json` / `tt_sys_v2m_borders.png` / `tt_sys_v2m_boundaries.png` | v2.4 掩膜版（paddle 供框，1K 参数）在 `tt_sys.png` 上的输出：115 框（丢的 2 框为固定列表头阴影侥幸证据被净化，见 3.2 节） |
| `tt_sys_v3_boxes.json` / `tt_sys_v3_borders.png` / `tt_sys_v3_textmask.png` | v3(paddle) 在 ERP 网格密集页 `tt_sys.png` 上的输出（23 框；表格全连通并入巨框，见 3.3 已知行为） |
| `recursive_layer_fill.py` | 边界嵌套树 + 逐层填充（容器层级建树思路可参考） |
| `PLAN_recursive_layer_fill.md` | 填充算法的完整设计文档 |
