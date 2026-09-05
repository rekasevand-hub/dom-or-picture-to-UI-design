# 通用 UI 复刻 Agent：方向修正设计（DOM 真值 + 单解释器内核）

- 日期：2026-09-05
- 状态：已评审通过（brainstorming），待写实施计划
- 目标仓库：`D:\LLM-Data\Figma_auto_agent`（分支 `feature/precise-agent-router`）
- 前序设计：`docs/superpowers/specs/2026-09-03-precise-replica-agent-router-design.md`（本设计对其做**方向修正**，冲突处以本设计为准）

## 1. 背景与为什么需要修正方向

前序设计把结构来源做成"三种可插拔路线并列 + 自动路由"（DOM / a11y / grounding / CV）。经过多轮实现与单页（flexweaver MOM 查询页）打磨后，项目出现明显漂移：

1. **页面/框架知识进入核心 provider**：antd 固定列 overlay 阈值、`图标: form → 编辑` 图标映射、fixed-wrapper 裁图等特判被打进 `providers/dom.py`、`som/direct_design.py` 等核心模块。
2. **语义解释权在代码而非模型**：本该由理解层判断的事（按钮该叫什么、是否浮层、怎么归组）变成一段段硬编码。
3. **grounding 停在半成品**：尺寸缩放未闭环；a11y 作为第三并列源分散了精力。
4. **单页验证导致过拟合**：所有优化都在同一条页面上验证，特化补丁"在这页都有效"，互相强化成脚本感。

结论：项目长成了"这本页面的复刻脚本"，而不是"通用 UI 复刻 Agent"。本设计修正总方向，但保留已有进度（DOM 采集、PageGraph、SoM、渲染适配器、llm_service 稳定性机制）作为资产。

## 2. 定位决策

- **最终定位 = A：通用跨站 UI 复刻 Agent**：任意网页/截图开箱即用；结构正确、可编辑优先，不承诺单一站点像素级。
- **路线 = C：通用内核 + 站点适配 Profile（可选）**：特化不删除，但收进独立 Profile 资产，核心保持零页面知识。
- **删除 a11y 路线**：不做 AX/CDP 语义路线。图标/控件语义只依赖 DOM 中已采集的 `aria-label`/`title` 字段，由理解层模型裁决。
- **远期（不在本期架构内）**：生成 + 视觉比对 critic 回路（builder/critic 迭代自检），仅作为后续可选阶段。

## 3. 目标架构（三层 + 单解释器 + 三结构源）

```
采集层 Capture   —— 通用、标准、零页面知识
   URL → Playwright：整页截图 + DOM JSON（几何/style/aria/position/zIndex/交互性）
规整层 Normalize —— 只做结构保真，不做语义理解
   DOM JSON → PageGraph（容器聚合仅用纯几何/纯样式通用规则）
理解层 Interpreter —— 唯一的"脑子" = 多模态模型（MLLM）
   SoM 标注图 + PageGraph JSON → DesignSpec
结构源（dom / grounding / cv 三条可显式调用的独立接口；auto 时按序择优）
   dom：浏览器真实结构（默认推荐）
   grounding：VLM 视觉理解（可直接作为主处理方向，适合纯截图输入）
   cv：OmniParser 纯像素（可直接作为主处理方向，无语义）
渲染层 Render
   DesignSpec → Figma（主）/ SVG（预览）
```

关键转向：

1. **DOM 是默认真值源**；grounding/cv **不是兜底层专属**，而是与 DOM 并列保留为可直接调用的独立接口——用户显式选择 `grounding`/`cv` 时它们就是主处理方向；仅在 `auto` 路由下才承担回退职责。
2. **语义理解全部收敛到 Interpreter**：DOM 直出（`direct_design` 规则拼装）默认取消，改为由模型统一产出 DesignSpec；保留 `--fast` 实验开关做"几何直出 + 模型只改语义"。
3. **代码只做采集与规整**：可见文本是事实数据（透传），推断语义（命名、文案、归组、浮层语义）是模型的职责。

## 4. 模块映射与职责边界

### 保留（通用资产）
| 模块 | 说明 |
|---|---|
| `services/structure/capture.py` | 保留 DOM 采集；**删除** CDP AX 采集（`_inject_ax_bounds`/`_read_ax_style`/`ax_style` 参数/AX JSON 产物） |
| `services/structure/graph.py` | PageGraph 容器/元素中间结构不变 |
| `services/structure/router.py` | 回退链逻辑保留，**删除 a11y** 分支 |
| `services/structure/providers/grounding.py` + `backends/grounding_vlm.py` | 视觉 grounding 独立接口（可直接作为主处理方向）；需在实施中修复 bbox 尺寸缩放对齐 |
| `services/structure/providers/cv.py`（OmniParser） | 纯像素独立接口（可直接作为主处理方向），auto 下作为最后兜底 |
| `services/som/annotate.py` | SoM 标注不变 |
| `services/rendering/*` + `bridge_server`/`figma_bridge` | 渲染适配器复用 |
| `services/llm/llm_service.py` | JSON 解析重试、截断自检、分批生成等稳定性机制复用 |

### 瘦身（语义特判移出核心）
| 位置 | 处理 |
|---|---|
| `providers/dom.py` overlay 阈值、图标 aria 映射 | 迁出核心：作为站点 Profile 数据按 URL/框架加载，核心默认路径不依赖（见下） |
| `som/direct_design.py` fixed-wrapper 特判 | 只作为 `--fast` 实验路径内部实现；默认不参与主链 |

### 删除（本次范围内）
- `providers/a11y.py`、providers 注册/导出、`route` 枚举中的 `a11y`
- capture 中全部 AX/CDP 相关逻辑与 `00_ax.json` 产物
- a11y 相关配置项、测试、README/`docs/api.md` 说明

### 站点适配 Profile（可选资产，不进核心）
- 形态：数据 + 提示词（如某框架的图标名→中文文案映射表、某站点浮层判定提示），按 URL/域名/框架探测加载。
- 规则：Profile 只能**影响给模型的输入与可选归一化参数**，不改变核心逻辑分支；核心仓库零页面字面量。

### PageGraph schema 调整
- `element` 增加语义候选字段：`ariaLabel`、`title`（DOM 原样透传，可空）。
- `text` 只存可见文本；代码不得把"推断语义"写入 `text`，最终文案由 Interpreter 裁决。
- 冲突约束：模型输出的语义文本与 DOM 可见文本冲突时，以可见文本为准（保真优先）。

## 5. 路由与回退

- **显式接口（一等公民）**：`route=dom` / `route=grounding` / `route=cv` 均可作为独立主处理方向直接调用；grounding/cv 不是 dom 的附属兜底，尤其 `--image` 输入时 grounding/cv 是常规选择。
- **auto 回退链**：URL 输入 `dom → grounding → cv`；纯图片输入 `grounding → cv`。仅在 auto 模式下，后面的来源才承担兜底职责。
- 三条显式路线都汇入**同一个 Interpreter** 产出 DesignSpec（理解层唯一）。
- auto 下任一层失败按回退链降级，逐条记录到 `manifest.provenance.fallbacks`；全失败给出明确错误并保留诊断产物。

## 6. 产物与 CLI 契约变化

产物目录结构不变，去掉 a11y 相关产物：

```
00_screenshot.png / 00_dom.json
10_pagegraph.json
11_som.png / 11_som.json
12_design.json          # 仅由 Interpreter 产出（默认）
prototype.svg / <figma> # 预览 / 最终原型
manifest.json           # route 枚举去 a11y
```

- CLI `--route` 可选项为 `auto/dom/grounding/cv`；`dom`/`grounding`/`cv` 三者均为可直接调用的主处理方向，auto 仅表示“按序择优降级”。
- 新增 `--fast`（实验）：仅 DOM 路线，几何直出基线 + 模型只做语义校正，默认关闭。
- DOM 可见文本、几何、样式由代码透传保真；语义命名由模型输出，但仍受第 4 节冲突约束。

## 7. 错误处理与保真约束

- 沿用现有 llm_service：JSON 解析失败自动重试、超时退避、分批生成 + 截断自检。
- Interpreter 输入必须同时含图（SoM）与结构化 JSON；任一缺失按第 5 节降级或报错。
- 所有几何坐标以原图像素整数为唯一坐标系，禁止模型缩放猜测（grounding 缩放 bug 必须在实施中修复并用单测锁住）。

## 8. 评测与反过拟合

- 新增 `samples/` 回归语料：3–5 个不同框架页面（至少含 antd、element/原生、简单后台/移动端变体），每个存"截图 + DOM JSON 快照"。
- 验收断言：三条显式路线（dom/grounding/cv）均可直接调用并产出可渲染 DesignSpec；DOM 链 PageGraph 结构合理（容器/元素数量级与 bbox）、可见文本全量出现、无非法坐标。
- 任何改动必须全过该语料；单页补丁在此机制下自然暴露为过拟合。
- 删除 a11y 后清理并跑通现有离线单测基线，作为改动的回归门槛。

## 9. 明确不做（防止范围蔓延）

- a11y/CDP AX 路线：不做；若未来需要，重新设计评审后再引入。
- builder/critic 视觉比对回路：仅远期可选，不进本期架构与实施计划。
- 字体识别、hover/disabled 状态推断等通用精度项：保持 README 远期方向，不在本设计范围内实现。

## 10. 实施前的落地范围（供 writing-plans 引用）

1. 删除 a11y（代码/配置/路由/测试/文档/产物）。
2. dom.py 语义特判迁出核心：overlay 阈值与图标 aria 映射改为站点 Profile 数据/提示词按 URL/框架加载，核心默认路径不依赖；PageGraph schema 增加 ariaLabel/title。
3. 默认 DOM 路线改走 Interpreter；`--fast` 实验快路保留。
4. 修复 grounding bbox 尺寸缩放对齐并加单测。
5. 建 `samples/` 多页回归语料与断言入口。
6. 文档同步（README、docs/api.md 中 a11y 与三源并列表述全部修订）。
