# UI 自动还原 Agent 后续优化计划

> 基于 `test_02.png` 的 Figma 还原测试，direct-render 模式已能跑通完整链路并保留红框区域。步骤 1（EasyOCR）和步骤 2（图片真实插入）已实现，当前剩余重点优化方向为步骤 3 和步骤 4。

---

## 当前状态

- ✅ OmniParser 本地服务可启动并稳定运行
- ✅ 红框标注区域可被检测并作为 `image` 组件跳过解析
- ✅ `--direct-render` 模式可跳过 LLM，直接渲染 OmniParser 检测组件到 Figma
- ✅ EasyOCR 引擎已接入，可替换 Tesseract 提升中文识别
- ✅ 图片/头像/红框区域可通过 base64 真实插入 Figma，不再是纯色占位
- ⚠️ 大容器/卡片背景检测不足，页面缺少区块感
- ⚠️ 组件类型分类有误（如侧边栏菜单被标为 `input`）

---

## 四步优化计划

### 步骤 1：换用更优 OCR 引擎（EasyOCR） ✅ 已完成

- **目标**：提升中文 UI 文字识别准确率，减少乱码和漏识别。
- **当前问题**：`OCR_ENGINE=tesseract` 对复杂 UI 里的小字、彩色背景文字识别较弱。
- **借鉴人工经验**：人工描图时能直接读出截图文字，程序需要同等准确的中文 OCR。
- **实现位置**：
  - `src/app/services/ocr/easyocr_engine.py`：EasyOCR 引擎实现，含字符级拆分 fallback
  - `src/app/services/ocr/ocr_service.py`：根据 `OCR_ENGINE` 选择 easyocr/tesseract
  - `src/app/services/ocr/base.py`：空识别结果时保留 OmniParser 原文字
- **验证方式**：`--ocr-engine easyocr` 运行，检查按钮文字、状态标签、表格内容是否更完整。

---

### 步骤 2：图标/图片区域真实提取并插入 Figma ✅ 已完成

- **目标**：让红框标注的图片区域、检测到的 avatar/icon 区域在 Figma 中显示真实图像，而不是纯色占位。
- **当前问题**：
  - 红框区域被识别为 `image` 但只渲染为空矩形/椭圆
  - 头像、Logo、功能图标丢失或变成色块
- **借鉴人工经验**：人工描图时知道 Logo、头像、图标是图片，会直接保留原图区域。
- **实现位置**：
  1. `src/app/models/component.py`：`meta` 字段可记录 `source_bbox` 等扩展信息
  2. `src/app/services/detection/red_box_detector.py`：红框区域转为 `image` 组件并写入 `source_bbox`
  3. `src/app/services/rendering/figma_adapter.py`：`create_image` 方法发送 base64 数据
  4. `src/app/services/rendering/adapter_base.py`：`render_design` 对 `image`/`avatar` 类型调用 `create_image`
  5. `src/app/agents/reconstruct_agent.py`：`_components_to_design` 从原图裁剪 ROI 并编码为 base64
  6. `figma_bridge/code.js`：`createImage` 命令使用 `figma.createImage` + `IMAGE` fill；`avatar` 类型设置圆角半径为 width/2 实现圆形蒙版
- **验证方式**：运行 `--direct-render` 后检查 Figma 中红框、Logo、头像是否显示真实图像。

---

### 步骤 3：优化容器/卡片背景检测

- **目标**：增强大区块（侧边栏、卡片、面板、表格行背景）的检测，让页面有更强的结构和区块感。
- **当前问题**：OmniParser 主要检测图标和文字，大背景容器常被忽略，导致元素"飘"在画布上。
- **借鉴人工经验**：人工描图时先看整体布局分层（侧边栏、header、主卡片、表格），再填细节。
- **操作**：
  1. 实现**分层检测策略**：
     - 第一层：检测页面级大背景（侧边栏、主内容区、header）
     - 第二层：检测卡片/面板（API 信息卡片、表格卡片）
     - 第三层：检测文字、按钮、输入框等小组件
  2. 在 `src/app/services/detection/container_detector.py` 中强化 `detect_containers()`：
     - 调整 K-Means 颜色量化参数（k 从 3 增大到 5-8）
     - 降低最小面积阈值，允许检测 500px² 以上的容器
     - 增加常见卡片背景色白名单：纯白 `#FFFFFF`、浅灰 `#F3F4F6`、米黄 `#FFFBEB`、浅蓝 `#EFF6FF`
  3. 对 direct-render 模式，确保 `container` 类型被正确绘制为背景矩形
  4. 在 `detect_components_with_omniparser()` 中增加后处理：
     - 如果某个区域内组件密度高但缺少大背景，自动补一个 `container`
     - 表格区域根据行内组件的 y 坐标一致性推断表格行背景
- **预期效果**：侧边栏、卡片、表格行背景完整，整体布局更贴近原图。
- **工作量**：大
- **优先级**：P2

---

### 步骤 4：LLM 后处理优化布局和类型

- **目标**：减少组件类型分类错误，补全缺失背景，优化元素层级和间距。
- **当前问题**：
  - 侧边栏菜单被分类为 `input`
  - 部分文字组件缺少对应背景矩形
  - LLM 模式会大量丢弃/合并组件
- **借鉴人工经验**：人工描图时根据**位置 + 形状 + 颜色 + 上下文**判断类型，不是只看单个组件。
- **操作**：
  1. 重写 `src/app/services/llm/llm_service.py` 中的 `_system_prompt()`，加入明确规则：
     - **先分层**：必须先输出页面级容器（侧边栏、header、主卡片、表格）
     - **再填细节**：每个可见文本必须有对应背景元素
     - **类型规则**：
       - 左侧深色竖条内的文字 → `button`
       - 顶部 header 内的链接 → `text`
       - 黄色/蓝色背景长条 → `container`
       - 圆角小矩形 + 操作动词 → `button`
       - 带边框的浅色矩形 + 灰色占位文字 → `input`
       - 小尺寸彩色块 + 状态词 → `container`
     - **文字颜色规则**：
       - 深色背景用 `#FFFFFF`
       - 浅色背景用 `#111827`
       - 蓝色/绿色/红色背景用对应浅色
     - **禁止合并**：同一区域内的多个独立文字必须分别输出
  2. 在 `parse_design_json()` 后增加 `_postprocess_design()`：
     - 对 `x < 260` 的 `input`/`text` 修正为 `button`，文字色改为白色
     - 对细长条（宽高比 > 4）且带文字的 `input` 修正为 `button`
     - 对小尺寸彩色背景组件识别为状态标签 `container`
     - 对没有背景色的 `text` 组件，根据其周围是否有容器决定是否补背景
  3. 在 `_components_to_design()` 中也应用类似后处理规则，让 direct-render 更智能
  4. 对比 `--direct-render` 和 LLM 路线效果，逐步让 LLM 路线达到可用水平
- **预期效果**：LLM 路线输出更完整、类型更准确，最终可作为默认流程。
- **工作量**：大
- **优先级**：P2

---

## 推荐执行顺序

```
步骤 1（EasyOCR）✅ 已完成
步骤 2（图片插入）✅ 已完成
当前推进：步骤 3（容器检测） → 步骤 4（LLM 后处理）
```

前两项已稳定落地，当前重点推进容器/卡片背景检测与 LLM 后处理，以提升整体布局还原度和类型准确性。

---

## 验证标准

每完成一步，用同一张 `uploads/test_02.png` 运行：

```powershell
conda run -n omni python -m src.main --image uploads/test_02.png --tool figma --direct-render
```

对比 Figma 输出：
- 文字完整度
- 图标/图片是否真实显示
- 卡片/背景区块是否完整
- 整体布局是否接近原图

---

*创建时间：2026-07-14*

*更新时间：2026-07-17（已标记步骤 1、2 为已完成）*
