# Round 1 · 导师回答后的思考

> 状态：R1、R2、R3 已回答并归档。本文保留 R1 基线，在第 6 节追加 R2 决策、第 10 节记录 R2 闭环、第 11 节记录 R3 闭环；不代表已实施。  
> 对应问题：`ROUND_01_QUESTIONS.md`  
> 对应回答：`ROUND_01_ANSWERS_FORMATTED.md`  
> 对应证据：`ROUND_01_FIG_INVENTORY.md`、`output/_fig_inspect/`  
> 对照代码：V1.1.0 工作区（含未提交改动，未改代码）

## 0. 一句话结论

导师样例的价值不在“Auto Layout 更多”，而在三件事：**结构表达更诚实、flow 准入更保守、资产与验收边界更明确**。2.0 的目标不应是“把所有容器都变成 Auto Layout”，而应是“每个 flow 都有证据，每个固定坐标都有理由，每个资产都能追溯”。

## 1. 结论摘要

1. **三块画板不是受控对照实验。** 输入不同、结构规范不统一，不能把结构差异反推成版本差异或算法差异。能确认的是三条路线的主要依据不同，不能确认的是历史实现版本和失败记录。
2. **DOM 版是 2.0 的几何与资产起点，不是最终布局模板。** 它的原图可独立替换、尺寸依据较明确；但内部几乎全是固定坐标，外层还有 5 个无语义 spacer，不能照搬。
3. **统一层级应采用“页面 → 页面区域 → 独立栏目 → 内容集合/布局行列 → 重复卡片 → 内容元素”。** 没有职责的层级省略；栏目标题和列表是栏目下的兄弟；左右并排的栏目是布局行下的兄弟；浏览器滚动条不属于网页内容 flow。
4. **flow 不是先验标签，而是双重验收后的结果。** 先过“语义顺序、单主轴、间隔/内边距可表达、无尺寸循环、能说明谁该移动”的静态条件，再过“原始外观 + 内容扰动”的行为验收。
5. **V1.1.0 的 Auto Layout 目前只到第 1 级。** `figma_bridge/code.js` 会设置 `layoutMode`、`itemSpacing`、padding 和对齐，但随后把所有子节点设为 `ABSOLUTE` 并写回快照坐标。它保存了结构信息，但没有让排版引擎真正接管布局。这是 DOM → Figma 2.0 最核心的缺口。
6. **固定坐标是合法的保底，不是失败。** 但必须限制在最小区域，使用父容器局部坐标，并记录容器矩形、子项矩形、裁剪、变换和保留原因；不能把主体文字偷偷改成绝对定位来掩盖布局错误。
7. **间隔优先 gap/padding，spacer 只在有明确占位职责时保留。** DOM 版的 20/20/20/20/50 可以用“内容容器 gap 20 + 与页脚 gap 50”等价表达，不需要 5 个空白节点。
8. **资产按优先级取用，并显式记录来源。** 同状态原资源 → 独立裁片 → 共享全页图裁剪并标记 → 原生形状/图标重建 → 明确缺失。共享 `imageHash` 不等于文件大 44 倍，但编辑、裁切、导出和替换成本确实不同。
9. **文本要分开记录“声明字体、实际字形、字体可用性、排版结果”。** 统一 140% 行高不能当作精确复刻；`lineHeight: normal` 也不应静默落到 1.4em 而不留标记。
10. **验收拆成四项：视觉还原、结构语义、编辑行为、资产可替换性。** 关键矩形 ≤1 CSS px、换行/数量/显示状态一致、纵向 +40 高度应让下游移动 40、标题变长和宽度 ±10% 是起始测试参数，不是原站响应式要求。
11. **路线降级方向与现有代码一致。** 无头被拦截但真实会话能看到内容时，V1 已会转到“自主截图 → 截图复刻”；目标页本身是登录页时，V1 会以 `hard_login` 停止并提示登录或手动上传。剩余缺口是参考状态锁定、登录页判定质量和截图路线本身的还原质量。
12. **不复制导师样例中的问题做法。** 不全局一键 Auto Layout、不用 spacer 掩盖错误、不统一 140% 行高、不隐式共享全页图、不按 Auto Layout 数量评优、不从最终结构反推不存在的历史。

## 2. 证据分层

| 结论 | 来源 | 置信度 | 对 2.0 的影响 |
|---|---|---|---|
| 三块画板不是受控对照，构建版本无法确认 | `[MENTOR]` + `[FIG]` | 高（“不是受控”）；版本异同未知 | 不能把结构差异归因于路线；DOM 版只作几何/资产基线 |
| DOM 版适合作为几何与资产起点 | `[MENTOR]` 建议 + `[FIG]` 24 张唯一原图 | 高 | DOM 路线保留原图与测量，重做层级与 flow |
| 统一六层语义层级 | `[MENTOR]` | 高 | 作为 StructureSpec 的骨架 |
| flow 需要静态外观 + 内容扰动双验收 | `[MENTOR]` | 高 | V2 必须从“设了 layoutMode”升级到“扰动通过” |
| V1 的 Auto Layout 只到“设置”级 | `[OUR-CODE]` `figma_bridge/code.js` | 高 | 主要缺口；不能宣称 true flow |
| 固定坐标应局部化、可追溯 | `[MENTOR]` | 高 | 保留最小固定区域与原因，不再全局拍平 |
| spacer 不是默认模式 | `[MENTOR]` + `[FIG]` 20/20/20/20/50 | 高 | 用 gap/padding 等价重建 |
| 资产按“原资源 → 独立裁片 → 共享裁剪”排序 | `[MENTOR]` + `[FIG]` 24 唯一图 vs 1 全页图 | 高 | 资产清单与共享裁剪标记 |
| 文本声明不等于实际字形；140% 不是精确复刻 | `[MENTOR]` + `[FIG]` 字体/行高分布 | 高 | 记录 `lineHeightSource`，分角色验收 |
| 验收应拆成视觉/结构/编辑/资产四维 | `[MENTOR]` | 高 | 四项分别报告，不互相替代 |
| 无头被拦截后的真实会话降级已实现 | `[OUR-CODE]` `capture.py`、`README.md` | 高（实现存在）；效果待实验 | 保留并补状态清单与回归测试 |
| 历史动机、失败记录、内部版本不可反推 | `[MENTOR]` | 高 | 未知项保留，不补造“曾经失败过” |

## 3. 对 2.0 的影响

### 3.1 路线与参考状态

**方向 1 的结论：现有代码方向正确，但验收还不完整。**

V1.1.0 已经在 `src/app/services/structure/capture.py` 中实现：

- `content / soft_block / hard_login` 三态判定；
- 无头被拦截后，依次尝试持久化用户目录、登录态 JSON、全新有头 Chromium；
- 真实会话拿到内容时，`screenshot_only=True`，调用方把截图当输入，DOM 只留作诊断；
- 目标页本身是登录页时，停止并提示登录或手动上传截图。

`src/app/agents/precise_agent.py` 也已把 `screenshot_only` 转成 `effective_route="screenshot"`，并把 `page_state`、尝试记录和降级来源写进 manifest。这与用户提出的“能 DOM 就 DOM，被拦截就自主截图，登录页才失败”一致。

导师回答补充的是**参考状态**：同一张截图只代表一个时刻的视口、轮播帧、懒加载状态、字体状态和滚动位置。2.0 需要把“我们截到了内容”升级为“我们截到了可复现的同一状态”：

- 固定视口宽高、DPR、缩放、滚动位置；
- 等字体加载完成，等目标图片解码完成；
- 冻结轮播/动画到指定帧；
- 记录 cookie/同意条/登录态；
- 记录每张目标图片的期望地址、实际地址、自然尺寸和占位状态；
- 对同一状态做至少两次稳定采样，但“稳定显示占位图”不等于资源成功。

**路线边界不变：** 本轮不融合 DOM 与截图路线。DOM → Figma 先独立变强；截图 → Figma 另起路线；融合等两条路线稳定后再谈。

### 3.2 结构与命名

六层规范落到读书网首页，大致是：

```text
页面
├─ 网站页头
│  ├─ 欢迎栏
│  ├─ 标志与搜索
│  └─ 主导航
├─ 焦点与分类
├─ 在线读书
├─ 新书与推荐（布局行）
│  ├─ 新书目录（栏目）
│  │  ├─ 栏目标题
│  │  └─ 图书行（内容集合）
│  │     └─ 图书（重复卡片）
│  │        ├─ 图书封面
│  │        ├─ 书名
│  │        └─ 作者
│  └─ 推荐排行（栏目）
├─ 国学与阅读排行
└─ 网站页脚
```

关键判断：

- `新书与推荐` 是**布局行**，不是语义栏目；语义上 `新书目录` 与 `推荐排行` 是并列栏目（DOM 结构上右栏多一层 `图书推荐` wrapper）。
- 注：上面的 `图书行` 层级来自 URL 版观察样本；DOM 版 `1:243 新书目录` 实际是 5×2 扁平网格，且右栏多一层 `1:212 图书推荐` 容器。R2-Q01 已建议重建行/列层与左栏 wrapper；仍不把本示例当作 DOM 事实，且结果只是 `candidate`。
- `图书行` 是**内容集合**，不是卡片；`图书` 才是重复卡片；封面、书名、作者是卡片的内容元素。
- 栏目标题和列表是栏目下的兄弟，不是父子。
- 页头、焦点区、主内容、页脚各自独立；不能像上传截图版那样把页头与焦点、页脚与排行合并。
- 浏览器滚动条放在独立的“截图外观层/浏览器界面”，排除在网页内容 flow 之外；若目标是网页设计稿，则不包含它。
- `Frame` 用于需要尺寸、背景、边框、裁剪、布局或约束的容器；`Group` 只用于一起选择/移动且没有独立职责的对象；wrapper 只有在控制列宽、行列排列、裁剪、对齐槽位或独立变换时才存在。

命名采用“可读语义名 + 可选稳定语义键”：

- `在线读书 / section.online-reading`
- `图书卡片 / book-card`
- `封面 / cover`
- `标题 / title`
- `作者 / author`

序号只用于重复项定位，不承担语义身份；节点 ID 只用于当前版本证据定位，不能作为跨重建的稳定身份。同名重复项要通过父级和内容标识辨认，不能只叫“内容”“图书位置”“Frame 123”。

### 3.3 Flow / Auto Layout

**候选条件（静态门）：**

1. 语义上有明确先后顺序；
2. 在流内容沿单一主轴排列，重叠只属于可单独识别的背景/装饰；
3. 父子关系、有效内容数量和视觉顺序一致；
4. 间隔、内边距、对齐和尺寸策略可明确表达；
5. 字体、文字宽度和素材尺寸已稳定；
6. 没有 Hug 依赖 Fill、Fill 又依赖 Hug 的未解尺寸循环；
7. 能明确说明内容增高后哪些兄弟应该移动。

网格或多列必须先建立“行/列/侧栏”层，再逐层验证；不能把所有后代一次塞进一个线性布局。像素级共享边框、负间距、叠放等无法表达或验证失败时，保留最小固定坐标区域并记录原因。

**三级验收：**

| 级别 | 含义 | V1.1.0 现状 |
|---|---|---|
| L1 设置 | Figma 里有 `layoutMode`、spacing、padding、align | 已有 |
| L2 引擎参与 | 子项不再全部 `ABSOLUTE`，由排版引擎按流摆放 | 未达到 |
| L3 行为正确 | 内容增高、长标题、宽度变化时，重排符合预期 | 未验证 |

V1 的 `setAutoLayout` 在 `figma_bridge/code.js` 中明确写了“子项一律钉死：全部子节点 ABSOLUTE + 复位到快照 x/y”。它的注释也说明，这是为了避免真机流式摆放导致整组右移。因此当前产物是“像素锁定的结构标注”，不是 true flow。`HANDOFF_2026-10-17_v2_dom_step1.md` 也把“Figma Auto Layout 的 true flow 模式”列为尚未做。

**转换协议（建议）：**

1. 先保留固定坐标基线，确保任何时候都能回到逐像素一致的版本；
2. 只挑满足静态门的容器，复制到测试副本；
3. 把候选容器的子项从 `ABSOLUTE` 改为在流，显式写 `FIXED / HUG / FILL`；
4. 先做静态对比：关键矩形 ≤1 CSS px，换行数、内容数量、显示状态一致；
5. 再做扰动：栏目高度 +40、标题变长、宽度 ±10%；
6. 通过则保留；失败则回退整个候选子树，不做“修补到看起来对”；
7. 只有父容器通过后，才考虑它的子容器，由外到内逐层升级。

**单子项容器：** 不能只用子项数量判断。单子项但仍承担居中、内边距、内容适应或对齐槽位职责的容器可以保留布局；只有一个绝对大图、只负责裁剪的容器（如 `读书网标志` 1:368、`京东图书活动` 1:402）应列为移除冗余 `layoutMode` 的候选。V1 的 `layout_plan.py` 目前用“成员 ≥ 2”作为门槛，可能漏掉有对齐价值的单子项容器；这一点需要 R2-Q02 的规则来收敛。

**Grid / flex-wrap：** V1 的 `layout_infer.py` 目前对 grid、flex-wrap、reverse、order 一律 bail，退回几何/绝对定位。这是保守且可接受的第一刀；2.0 应先补“行/列/侧栏”层，再决定是否支持，不要直接把 grid 压成一个线性 stack。

### 3.4 文本

导师明确提醒：声明字体不等于实际字形，统一 140% 行高不等于精确复刻。2.0 的文本记录至少要分开：

- 声明字体栈 `font-family`；
- 浏览器实际解析到的字体/字形回退；
- 字体在 Figma 环境是否可用；
- `font-size`、`font-weight`、`letter-spacing`；
- `line-height` 的原始值，以及它是 computed px、百分比、`normal` 还是推断值；
- `text-align`、`white-space`、`text-overflow`、最大行数；
- 文本盒、基线、换行数和可见字形。

V1 的 `text_wrap.py` 已经优先使用 computed `lineHeight`，缺失时才按 `1.4em` 估算。这个 fallback 可以保留，但必须标记为 `lineHeightSource=inferred`，不能和真实 computed 行高混在一起报告。`line-height: normal` 时应优先用浏览器实测行盒或字体度量，而不是静默套 1.4。

验收要分开：文本盒边界一致，不代表基线一致；基线一致，不代表字形一致；字形一致，也不代表换行策略一致。2.0 应分别报告。

### 3.5 资产

资产优先级：

1. 同状态的原始资源，图标优先准确矢量；
2. 匹配显示状态的其他合法可访问原资源；
3. 从权威截图按素材边界裁取独立图片；
4. 必要时共享全页图裁剪，并标记来源；
5. 简单 UI 用原生形状/准确图标重建；
6. 复杂封面和品牌图不随意重画或用相似图片替代；
7. 素材仍不可得时，保留参考中的真实占位状态或明确标为缺失。

每个资产至少记录：来源、原始尺寸、渲染矩形、`object-fit`/`object-position`、裁剪矩形、DPR/缩放、显示状态、失败/占位状态、是否可独立替换、是否共享。

DOM 路线应优先保留独立原图；截图路线保存的是截图中的像素，不等于拿到了原图。共享全页图裁剪可以用于“不需要编辑的视觉参考”，但必须显式标记为 `assetMode=shared-page-crop`，不能宣称“已提取独立素材”。

同一 `imageHash` 多次引用不等于按引用次数重复保存整张位图，不能说文件大 44 倍；但节点、裁剪和渲染开销会增加，单封面替换也要同时处理大图尺寸、偏移和裁剪。实际文件体积、导出耗时、替换成本要用实验测，不能用节点数估。

V1 的 `diagnostics.py` 已经统计 `grid / flex_wrap / shadow / gradient / pseudo` 缺口；其中渐变和伪元素装饰尚未进入 DesignSpec。2.0 需要决定它们走“原生形状/渐变”还是“截图裁片”，并记录选择理由。

### 3.6 验收与回退

验收四项分开报告：

1. **视觉还原**：关键容器和文字框边界误差 ≤1 CSS px；截图缩放比例为 `s` 时，画布阈值为 `s px`；图片保持纵横比；不以平均误差掩盖少量大偏移。
2. **结构语义**：层级、分组、命名能支持实际编辑任务；增加作者一行、替换单本书封面时，不需要搜索整页截图或改其他栏目。
3. **编辑行为**：栏目实际增高 40 px，下游应移动 40 px；标题变长、宽度 ±10% 时，重排符合预期；固定高度阻断传播要能被识别。
4. **资产可替换性**：单封面替换、源图缺失、占位图加载成功但原封面未加载等场景都能定位和处理。

回退原则：在副本中转换；转换前保存父子层级、顺序、尺寸、变换、约束、裁剪和文字排版参数；验收不通过时优先保留原子树、丢弃候选子树，而不是反复修补已漂移坐标。有旋转/嵌套缩放时要做变换矩阵换算，不能只做坐标相减。

## 4. 对照 V1.1.0 代码

| 模块 | 已有能力 | 与导师原则的关系 | 2.0 缺口 |
|---|---|---|---|
| `src/app/services/structure/capture.py` | `content/soft_block/hard_login`、真实会话降级、`screenshot_only`、尝试记录 | 与方向 1 一致；体现“先判定状态，再选路线” | 参考状态清单、登录页判定回归、截图稳定性测试 |
| `README.md:121-126` | 记录了三态与降级行为 | 与用户方向 1 一致 | 文档需要补“状态锁定”与“截图质量”边界 |
| `src/app/services/structure/diagnostics.py` | 统计 shadow/grid/flex-wrap/gradient/pseudo 缺口 | 与“记录未知项”一致 | 渐变/伪元素进入 DesignSpec 的策略未定 |
| `src/app/services/rendering/layout_infer.py` | CSS 优先 + 几何兜底；0.6px 重放；grid/wrap bail | 与“几何可重放才升级”一致 | grid/wrap 的层级建模；true flow 行为 |
| `src/app/services/rendering/layout_plan.py` | 成员 ≥2 才建 Frame；可合成透明 Frame | 与“无职责 wrapper 不加”部分一致 | 单子项但承担对齐/内边距的容器可能被漏掉 |
| `figma_bridge/code.js` `setAutoLayout` | 写 `layoutMode`、spacing、padding、align；子项全量快照复位 | 只达到 L1“设置”，未达到 L2/L3 | 需要白名单式 true flow 转换与扰动验收 |
| `HANDOFF_2026-10-17_v2_dom_step1.md` | 明确列出 true flow 尚未做 | 与导师“设置 ≠ 引擎参与 ≠ 行为正确”一致 | 作为 2.0 DOM 路线的直接起点 |
| `src/app/services/rendering/text_wrap.py` | computed lineHeight 优先；缺失时 1.4em | 与“不要统一 140%”部分一致 | `lineHeightSource` 标记；`normal` 的实测策略；基线/字形分项验收 |
| `src/app/agents/precise_agent.py` | `screenshot_only` 时把输入切为 image，effective_route=screenshot | 与方向 1 一致 | 截图路线的质量与状态锁定仍待补 |
| `src/app/services/structure/router.py` | 简单的 `dom → grounding → cv` 候选链 | 路线顺序正确 | page_state 的判定在 capture/precise_agent，不在 router；后续可考虑把状态纳入路由决策 |

**判断：** 2.0 不需要推翻 V1 的采集、诊断和几何推断；需要补的是“结构语义层 + true flow 转换 + 资产清单 + 分项验收”。这是一次有边界的升级，不是重写。

## 5. 未决问题 / Parking lot

| ID | 来源 | 问题 | 是否阻塞 |
|---|---|---|---|
| R2-Q01 | R1-Q02、Q03、Q07 | DOM 版哪些具体容器应转 true flow？请按节点给出轴、spacing、padding、sizing、在流/绝对子项和扰动验收 | 已回答；五个容器均为 `candidate`；`R2-EXP-01` 已完成 authored DOM 扰动（42/42），原站仍非 `verified` |
| R2-Q02 | R1-Q02 | 单子项容器的保留/移除规则；裁剪容器是否应移除 `layoutMode` | 已回答；规则见 `V2_OPTIMIZATION_PLAN.md` 12.4 |
| R2-Q03 | R1-Q05 | DOM 路线资产清单字段、同图多裁切复用规则、背景图/渐变/伪元素策略 | 已回答；复杂 SVG/滤镜仍待 `R3-D03` |
| R2-Q04 | R1-Q06 | 重复卡片/同名栏目的命名语法与稳定语义键 | 已回答；无稳定 ID 消歧待 `R3-D04` |
| R2-Q05 | R1-Q01、Q07 | DOM 采集前必须冻结哪些参考状态；如何判定 DOM 与截图属于同一状态 | 已回答；full-page/sticky 与阈值标定待 `R3-D05` |
| R2-Q06 | R1-Q03、Q07 | 中文文本的逐角色度量、`line-height: normal`、字体回退与分项验收 | 已回答；`normal`/基线测量待 `R3-D06` |
| R2-EXP-01 | R1-Q02、Q03 | 我们自己在测试副本做 +40 高度、长标题、宽度 ±10% 扰动 | 我们自己执行，不问导师 |
| R2-EXP-02 | R1-Q05 | 我们自己测共享全页图 vs 独立裁片的体积、导出耗时、替换成本 | 我们自己执行，不问导师 |

## 6. 可以进入实现方案的决策

只有满足“有明确规则、参数或验收标准”的结论才写到这里；其余留在未决问题。

| 决策 ID | 决策 | 依据 | 验收标准 | 状态 |
|---|---|---|---|---|
| D1 | DOM 版作为几何与资产基线，不作为最终结构模板 | `[MENTOR]` + `[FIG]` | 原图可独立替换；几何可追溯到 DOM 测量 | 采纳 |
| D2 | 采用六层语义层级，浏览器界面独立 | `[MENTOR]` | 能用栏目/卡片/内容角色定位单本书替换与作者行增删 | 采纳 |
| D3 | flow 候选必须过静态门 + 扰动门 | `[MENTOR]` | 每个候选有 before/after 几何与扰动记录 | 采纳；`R2-EXP-01` 已完成 authored DOM 的静态门与扰动门，原站仍待 |
| D4 | 三级验收：设置 / 引擎参与 / 行为正确 | `[MENTOR]` | 不能以 `layoutMode` 数量代替 L2/L3 | 采纳 |
| D5 | 固定坐标局部化并记录原因 | `[MENTOR]` | 每个固定区域有父容器局部矩形、裁剪、变换、原因 | 采纳 |
| D6 | 间隔优先 gap/padding，spacer 需有职责 | `[MENTOR]` + `[FIG]` | 20/20/20/20/50 能被等价表达且内容区起点不变 | 采纳 |
| D7 | 资产按优先级取用并建清单 | `[MENTOR]` + `[FIG]` | 每个资产有来源、尺寸、裁剪、状态、可替换性 | 采纳，字段边界已由 R2-Q03 给出 |
| D8 | 文本记录声明字体/实际字形/行高来源/排版结果 | `[MENTOR]` + `[OUR-CODE]` | 能区分 computed 与 inferred；基线/字形/换行分项报告 | 采纳，策略已由 R2-Q06 给出；测量方法待 `R3-D06` |
| D9 | 验收拆成视觉/结构/编辑/资产四维 | `[MENTOR]` | 四项分别有结论，不以一项代替全部 | 采纳 |
| D10 | 不复制全局 Auto Layout、spacer 掩盖、统一 140%、隐式共享裁剪、按数量评优 | `[MENTOR]` | 代码评审与产物审查能逐条排除 | 采纳 |
| D11 | 保留现有 URL 三态与真实会话降级 | `[OUR-CODE]` + 用户方向 1 | `soft_block` 后截图继续；`hard_login` 停止并提示 | 已有实现；`R1-EXP-02` 已完成受控三态回归（10/10） |
| D12 | `faithful` 与 `adaptive` 作为两套配置，禁止静默混用 | R2 回答元信息 | 每个候选与验收报告写明 `profile`；变量、阈值和失败判据可区分 | 采纳 |
| D13 | 五个 DOM 容器只进入 flow `candidate`，未做扰动不得标 `verified` | R2-Q01 | 每个容器有轴、spacing、padding、sizing、在流/绝对子项、扰动与回退记录 | 采纳；`R2-EXP-01` 已补 authored DOM 记录，原站 `verified` 仍不得声称 |
| D14 | 网格默认“横向行 + 纵向列表”，并分别记录 DOM、Figma 子项与视觉顺序 | R2-Q01 | 有旧序到新序映射；未知源 DOM 顺序标 `unknown`；不宣称原生响应式网格 | 采纳 |
| D15 | 单子项容器分开判断“保留 Frame”和“保留 `layoutMode`” | R2-Q02 | 保留需有对齐、padding、Hug、Fill 槽位或尺寸关系职责；纯裁剪默认为普通 Frame 候选 | 采纳 |
| D16 | 资产拆成 asset / use / capture state 三层，并记录替换契约 | R2-Q03 | 每个使用实例有 asset 引用、变换、裁剪、加载状态与 `independent/derived/reference-only/missing` | 采纳 |
| D17 | 身份拆成 entity / occurrence / slot，定位证据不等于永久身份 | R2-Q04 | 同名、同书、动态内容与跨版本映射有状态和冲突报告；不以标题/序号/DOM 路径/节点 ID 单独作主键 | 采纳 |
| D18 | DOM 采集使用 M0 → S → M1 同态验证和 `complete/partial/rejected` 结果 | R2-Q05 | 共同 `capture_id`；关键矩形起始阈值 ≤0.5 CSS px；不把单一信号或 DOM 失败伪装成成功 | 采纳，阈值待标定 |
| D19 | 文本源值与输出值分离，按 run 保存字体证据，四项独立验收 | R2-Q06 | 文本盒 ≤1 CSS px；有可靠基线时 ≤0.5 CSS px；换行一致；字形边缘 ≤1 CSS px 作起点 | 采纳，基线/字形阈值待实验 |
| D20 | 未测、推断、估算和未知必须显式标记，未知不默认通过 | R2-Q01–Q06 | IR/manifest 带 `observed/derived/estimated/unknown` 与验证状态；`candidate` 不得写成 `verified` | 采纳 |

## 7. 本轮明确不做

- 不改代码、不动 V1 产物、不新建分支。
- 不把全部容器一键转 Auto Layout。
- 不把 DOM 与截图路线融合。
- 不在没有扰动实验的情况下宣称 true flow 或“像素级 1:1”。
- 不把导师的“本次做法”直接当成“通用算法”。
- 不从三块样例反推导师的历史版本、失败记录或内部实现。

## 8. 下一步

1. R2 已归档；把 `ROUND_03_DOM_QUESTIONS.md` 的六项 DOM 遗留问题作为第三轮并行追问，不并入截图结论。
2. 把 `ROUND_03_QUESTIONS.md` 发给导师，单独收敛截图 → Figma 路线。
3. 我们自己在测试副本做 R2-EXP-01/02，标定 0.5/1 CSS px、权重、扰动与共享裁片成本。
4. 只有用户明确说“开始改代码”后，才动 `layout_plan.py` / `figma_bridge/code.js`；未实验的节点仍只能标 `candidate`。

## 9. 备注

导师的样例只能证明“这套做法在这三块画板上产生了当前结构”，不能证明它是可泛化的最优算法。2.0 应把这些结论当作**可测试假设**，用同源、同状态、同规范的样例验证，而不是当作跨站点定律。

## 10. R2 闭环记录（2026-10-18）

### 10.1 已收敛

- 回答仅到 2.0 建议规格；没有修改画布。该轮未执行扰动实验；后续 `R2-EXP-01` 已在 authored DOM 上补做，五个 DOM 容器仍为 `candidate`。
- `faithful` 与 `adaptive` 必须分开；`faithful` 保指定状态几何/换行，`adaptive` 才允许内容增删和重排。
- `1:211`：外部左右 padding 125、gap 20；左栏 790 纵向，右栏 380；左栏 18 + 38 + 2 + 496 = 554。
- `1:243`：5×2 行/列表候选；卡片 142 固定，横 gap 10、纵 gap 0，padding 21/19/1/21。
- `1:244`：封面 142²、gap 9.28、信息层左 8、标题 128×44、gap 7.68、作者 130×18、底 16.04；固定 44 不等于两行省略号。
- `1:213`：外层 padding 1，展开条目 378×144，7×378×44，更多区 378×42；44 已含分隔线，不额外加 1。
- `1:312`：2×2 行流，padding 21/7/0/16，横 gap 21、纵 gap 20；分隔线保持绝对装饰与锚点，不占流。
- 单子项：保留 Frame 与保留 `layoutMode` 分开；纯裁剪默认普通 Frame 候选；未知时不做破坏性优化。
- 资产：asset / use / capture state 分层；`independent / derived / reference-only / missing`；共享裁剪不冒充独立资产。
- 身份：entity / occurrence / slot 分离；标题、序号、DOM 路径、节点 ID 都不能单独充当永久键。
- 采集：M0 → S → M1，共同 `capture_id`；关键矩形起始 ≤0.5 CSS px；结果 `complete / partial / rejected`。
- 文本：源值与输出值分离，逐 run 字体；四项独立验收；`normal` 保留原值，1.4em 只是显式 low-fidelity 估算。

### 10.2 仍不能确认

| 未决项 | 处理 |
|---|---|
| 在线目录完整槽宽与源 DOM 顺序 | `R3-D01` |
| grid 等价实现 | `R3-D02` |
| 复杂伪元素、SVG、滤镜支持边界 | `R3-D03` |
| 无稳定 ID 的重复条目消歧 | `R3-D04` |
| full-page 与 sticky 同态验证 | `R3-D05` |
| `normal`、基线可靠测量与字形阈值 | `R3-D06` |

### 10.3 状态边界

- 本轮不把任何节点或规则写成“已实现”“已验证”或“像素级 1:1”。
- 只有扰动实验、阈值标定和人工复核完成后，才允许把对应候选从 `candidate` 升级为 `verified`。
- R3 截图结论不得覆盖 R2 的 DOM 证据；R4 融合前两条路线保持独立报告。

## 11. R3 闭环记录（2026-10-18）

### 11.1 DOM 并行轨

R3-D 六题已回答，结论仍是规格与建议，没有新增实测。

> 11.1 与 11.2 两表的“仍待实验”列记录 R3 回答当时的状态；截至 2026-10-18，`R3-EXP-01`–`R3-EXP-15` 均已完成当前范围，实际结果见 11.4–11.15 与 `R1_R4_CURRENT_SCOPE_AUDIT.md`。

| 议题 | 已收敛结论 | 仍待实验 |
|---|---|---|
| R3-D01 在线目录 | 条件推导列步长 162、槽宽 152、槽高 237、padding 21/30/1/36；`dom_order=unknown`，展示顺序用 `display_order` + `order_basis=visual-clustering` | 核对全部 21 槽 |
| R3-D02 grid | 白名单绑定能力版本、`profile` 与测试范围；视觉等价不等于编辑等价；两层 stack 只能 `regroup-on-rebuild` | grid/wrap 能力与回读 |
| R3-D03 复杂效果 | 逐项标 `native-candidate / raster-fallback / unsupported`；单算子通过不证明效果链通过 | SVG/滤镜/mask 矩阵（`R3-EXP-03` + `R3-EXP-15` 离线栅格回退） |
| R3-D04 身份匹配 | 有冲突检测的一对一匹配；记录特征、缺失、成本、候选差距与阈值；允许 `proposed-match / ambiguous / not-seen` | 权重与阈值标定 |
| R3-D05 full-page | 单视口 / 文档捕获 / 逐段合成分开；拼接标 `composite`；每段 M0/S/M1；`partial` 不支持整页 `verified` | 拼接与 sticky/fixed 实验 |
| R3-D06 文本 | `normal` 多方法交叉；Range 不等于行盒；基线定义必须明确；无证据标 `not-evaluated` | 基线与字形阈值（`R3-EXP-06` + `R3-EXP-13/14`） |

关键边界：

- `152×237` 与 `21/30/1/36` 是带前提的 `derived`，不是新增实测；前提是 7 列等距、列隙 10、行步长 237、行隙 0 且等高。
- 原 Figma 子项反向不能证明源 DOM 反向；`dom_order` 不能由视觉顺序替代。
- 无扰动、无回读、无冲突检测时，不得把 grid 或匹配结果写成已通过。

### 11.2 截图主线

R3-Q 七题已回答，截图路线形成从输入到失败处理的完整规格，但仍没有任何新增实验。

| 议题 | 已收敛结论 | 仍待实验 |
|---|---|---|
| R3-Q01 输入 | 原图 2544×4959；无可靠 DPR、CSS 视口、字体；以源图像素坐标重建，`canvas = s × source + offset`；拼接未知标 `composite-unknown` | reference/状态冲突 |
| R3-Q02 分组 | 不设单一视觉信号绝对优先级；共享白底不是合组证据；IR 记边界证据、语义证据、替代解释和 lineage | 人工一致性 |
| R3-Q03 文本 | OCR 分数保留原始口径；`faithful` 保留可见行序与断行；不按上下文补全；用户补文标 `user-supplied` | OCR/低清阈值 |
| R3-Q04 资产 | `provenance` 与 `replaceability` 分开；`derived` 不自动可替换；状态为 `independent / constrained / reference-only / missing` | 裁片替换能力 |
| R3-Q05 flow | 截图只能提出 `candidate`；无扰动不得标 `verified`；可记 `verified_for=output-contract`、`source_behavior=inferred` | 扰动与回退 |
| R3-Q06 验收 | 视觉、结构、编辑、资产分别给 `pass / partial / fail / unknown`；`s = 画布长度 / 源图像素长度` | 阈值与样例集 |
| R3-Q07 停止 | 只停止超出证据的承诺；局部可输出时给无效区域或遮挡掩码；人工接管只索取最小必要证据 | 拒收/接管实验 |

### 11.3 状态边界

- 两轨回答都只进入 2.0 规格，没有修改 `src/`、`figma_bridge/` 或其他实现。
- 截图布局最多到 `candidate`；没有扰动时 `source_behavior` 只能是 `inferred`。
- 所有未标定项进入 `ROUND_03_OPEN_ITEMS.md`，不在计划中写成已通过。
- 截图与 DOM 冲突时保持 `external-conflict` 与来源隔离；R4 融合需用户明确同意。

### 11.4 下一步

1. `R3-EXP-01`、`R3-EXP-02` 已完成当前范围；跨度+`FILL`、三档对齐、`FLEX` 比例与 HUG 列/父帧已补充实测，嵌套 grid、HUG+FILL 与自动/混合轨道另列补充实验。
2. `R3-EXP-05` 已完成受控本地页当前范围：8 段拼接、原视口文档捕获、扩展视口三模式对比；屏蔽 sticky/fixed 后有效像素差为 0，扩展视口只覆盖 54.44%。真实站点与跨浏览器扩展另列。
3. `R3-EXP-06` 已完成受控 Chromium 单环境当前范围：12 个文本用例、基线探针、混排 run 与同环境噪声。`R3-EXP-13` 已补 Chromium + WebKit 跨渲染器标定（基线最大差 0.5px，Firefox 启动失败未覆盖）；通用跨平台阈值仍为 `not-evaluated`。
4. `R3-EXP-03`、`R3-EXP-04` 已完成当前范围；未闭合项见下文 11.6。
5. `R3-EXP-07` 已完成受控分组与 lineage 验证，见下文 11.7；后续 `R3-EXP-08–12` 均已完成当前范围。
6. `R3-EXP-08` 已完成 OCR/低清/压缩的当前范围标定，见下文 11.8；文字验收仍未得到通用阈值。
7. `R3-EXP-09` 已完成资产来源、替换能力与共享图成本的当前范围标定，见下文 11.9；`R2-EXP-02` 已并入。`R3-EXP-10` 已完成输出合同层的 flow 扰动与 DOM 冲突隔离，见下文 11.10；`R2-EXP-01` 已完成 authored DOM 扰动，原站 DOM 与原站响应式仍欠。`R3-EXP-11` 已完成四项验收样例集与评分校准，见下文 11.11。`R3-EXP-12–15` 已完成当前范围；R3 两条轨均已完成当前范围，R4 已由用户同意并完成 `R4-EXP-01–10`。
8. 只有用户明确说“开始改代码”后，才动实现；未实验项仍只能标 `candidate / pending / unknown`。

### 11.5 用户确认的默认产品策略（2026-10-18）

用户在理解导师原则后确认采用以下默认值；它们是产品选择，不替代导师的证据规则。

| 项目 | 默认 | 例外 |
|---|---|---|
| 忠实还是重排 | 默认 `faithful` | 按区域显式开启 `adaptive`，记录规则、批准人和版本 |
| 缺字体 | 默认不替换，输出 `blocked-font / partial` | 用户授权后替换，标 `draft / fallback` 并复查断行 |
| 视觉降级 | 关键内容不允许明显差异 | 非关键装饰可轻微降级，但须报告缺口 |
| 部分结果 | 可交付，但必须标可用/不可用范围 | 核心缺失时降为草稿或参考 |
| 截图与 DOM | 截图轨默认不引入 DOM | 单独授权“DOM 辅助模式”，逐字段标来源 |

验收仍按视觉、结构、编辑、资产四项分别给 `pass / partial / fail / unknown`。交付级别由四项状态推导，不能用单一颜色或总分替代。

### 11.6 R3-EXP-03/04 实验结果（2026-10-18）

#### 效果矩阵

- 20 个 SVG 用例 + 12 个原生用例全部调用成功，但“导入成功”不等于语义等价。
- 可直接导入并接近参考：线性/径向渐变、`clip-path`、alpha/luminance mask、渐变描边、data URI 图片、`feGaussianBlur`；均值差均小于 1。
- 直接导入失败：`feDropShadow` 阴影整体消失（`effects=[]`）、filter 链只剩一个 `LAYER_BLUR`、`foreignObject`/`pattern`/远程图片为空白 frame。
- `<use>` 只静态展开，无可复用引用语义；`<animate>` 只保留首帧，动画不支持。
- 原生 drop/inner shadow、layer/background blur、效果链、alpha/vector/luminance mask、`clipsContent` 与 16 种 blend mode 均通过本矩阵。
- mask 与阴影同帧时均值差 10.2087；把阴影放到外层 wrapper 后降到 1.2351。生产结构必须显式规定包装层。
- 文本四个用例均值差 11.25–11.62，差异在抗锯齿边缘；Arial 与 YaHei 仅差约 0.37，像素均值不能用于字体判定。预加载用例与显式字体用例混杂，相关命题 `not-evaluated`。
- `R3-EXP-15` 已补四个失败 SVG 特性的离线栅格回退：PNG 逐像素无损、JPEG q90 最大 MAE `1.121845`、合同 9/9；真实 Figma 导入/回读端到端仍未执行。

#### 身份匹配

- 14 个合成场景、37 个预期配对；`accept=0.20`、`gap=0.06` 下 calibration 与 validation 均为 0 错误记录、0 漏配。
- `0.15–0.20 × 0.03–0.06` 是平台区，只能算弱标定；`0.25` 开始误配“相似但不同”，`gap=0.10` 产生漏配。
- 副本交换、一对多、跨栏同上下文均输出 `ambiguous`；局部采集输出 `not-seen`；不输出 `deleted`。
- 节点 ID 基线有 10 条错误记录；仅内容特征 0 错误但漏 6 条，说明 parent/neighbor/geometry 等上下文特征必要。
- 缺失特征按可用权重归一化；`cal_missing_feature` 的 `coverage=0.72`，仍正确匹配。

这两项都只算 `completed-for-current-scope`。`R3-EXP-15` 已把 raster-fallback 推进到离线平铺资产合同；未闭合项：真实 Figma 导入/回读端到端、显式 drop-shadow/filter 链重建、真实字体绑定、真实页面上的匹配阈值重标。

### 11.7 R3-EXP-07 截图分组与 lineage（2026-10-18）

- 单受控页、16 个有父对象的 seed：5 个 `candidate`、11 个 `ambiguous`、错误候选 0 个。`candidate_parent` 建议与 ground truth 16/16 一致，但只有 5 个达到候选强度，其余仍需 review。
- 外层有边框的 `obj-band` 同时包含主栏和侧栏，是两者最小视觉容器；但它是无标题装饰框，不能自动成为父节点。`obj-main`、`obj-sidebar` 保持 `ambiguous`，说明“边框包含”不等于父关系。
- `Section A` 与 `Promotions` 靠边框成为 `candidate`；`Section B` 靠重复缩略图 anchor 的节奏、`Filters` 靠等距 ink band 成为 `candidate`。无边框卡片、列表行和筛选行只有单行/少量证据，全部保持 `ambiguous`。
- 主栏与侧栏之间是 40px 纯白 gutter，`white_ratio=1.0`、非白像素 0；naive gap merge 仍把两栏合并，并额外产生 4 个错误合并组。距离近 + 白色中间区域只能作为弱证据。
- 父关系编辑记录 `from/to`，对象 id、rect 与边界证据保持稳定；把 `obj-page` 设到子对象的环被拒绝。split 后源对象 `superseded`、子行重挂；merge 后源对象都 `superseded`、子对象重挂到新对象；坏合并标 `review_status=rejected` 并保留 gutter 证据；所有 undo 都恢复初始 digest。
- 本实验只覆盖单个 1200×900 合成页，不覆盖自动分割、OCR、真实站点、响应式/DPR 变化或 Figma API 写入。状态仍为 `completed-for-current-scope`，不是全量 `verified`。

### 11.8 R3-EXP-08 OCR、低清、压缩与文字阈值（2026-10-18）

- 受控页面 13 个用例、27 个条件标签、2 个 OCR 引擎共 702 条记录；`native_fs_32` 与 `scale_100` 为同一图像，实际 26 张不同图像。全量严格 `exact` 81/702，核心字符 exact 230/702，行数匹配 677/702。
- 6 个对抗用例共 324 条记录 `exact` 为 0，核心字符仅 71/324；相似汉字、`0/O/〇`、`1/l/I`、全角标点与省略号都没有在任一条件下达到严格 exact。
- 普通文本 32px 核心 exact 为 Tesseract 5/7、EasyOCR 3/7；0.75 缩放为 4/7 与 4/7；0.5 缩放为 4/7 与 3/7；0.25 与 0.1875 缩放两引擎均为 0/7。原生 16px 各 4/7，12px 为 1/7 与 2/7，10px 为 1/7 与 0/7，8px 均为 0/7。不能写“统一 12px/16px 即可读”。
- 证据字段只有 Tesseract 在有效 32px 的少数条件通过 1/2；EasyOCR 全部 0/2，清晰 32px 仍把 `¥` 识别为 `半`。金额、日期、编号必须严格 exact 并人工复核。
- JPEG 非单调：Tesseract q90 与 q15 的 exact 都是 4/13，q50/q30 为 3/13；EasyOCR 基本 1/13。模糊边界约在 σ 1.5–2.0px，但 EasyOCR 在 σ2.0 降到 0/7，Tesseract 仍有 3/7。字号、压缩、模糊都不存在统一阈值。
- 行数匹配不能单独当断行通过：447 条记录行数匹配但核心字符错误；EasyOCR 在 0.25 缩放 13/13 行数匹配而核心 exact 0/13。文本框也不能证明内容：exact 记录的 IoU 中位数 0.803，错误记录 0.819。
- OCR 置信度不可自动接受：Tesseract mean_conf ≥0.8 接受 188 条、其中 128 条错误；EasyOCR 接受 50 条、其中 36 条错误。EasyOCR 置信度 0.983 仍把 `省略号……测试…` 输出为 `省略号测试`；Tesseract 置信度 0.957 把 `0O〇 O0〇 00OO` 输出为全 `0`。
- 字形可分性只在当前字体/渲染器内标定：32px 有 4/14 对不可分（`l/I`、`未/末`、`土/士`、`，/,`），16px 为 5/14，12px 为 12/14；16px JPEG q50 有 8 对不可分，blur σ1 有 7 对。不能外推为通用字形阈值。
- 遮挡会让 OCR 编造看似合理的文本（如 `FAIZ`、`iX RATS Peel`）；所有遮挡记录 `content_status=unknown`，用户补文保持 `user-supplied-unverified`。`R3-EXP-14` 已在已知字体/字号下从静态截图估计 alphabetic baseline（最大误差 0.5px、平均 0.018px）；未知字体或未知字号仍为 `not-evaluated`。
- 本实验只覆盖当前字体、Chromium、Tesseract 5.5.0 与 EasyOCR 1.7.2；真实站点、旋转/竖排、跨 DPI 与人工复核完成度未测。`R3-EXP-13` 已补 Chromium + WebKit 的文本度量与基线标定，Firefox 未覆盖。状态为 `completed-for-current-scope`，不是 `verified`。该记录完成时下一步为 `R3-EXP-09`，现已完成，见 11.9。

### 11.9 R3-EXP-09 裁片来源、替换能力与共享图成本（2026-10-18）

- 单个 1200×900 受控页面、9 个资产：4 个同封面用途（完整×2、左 60% 裁切、0.5x 缩略）、文字盖图、阴影图标、低清 logo、原生圆角徽章和干净照片。DPR 2 截图后 Lanczos 下采样到 1x；DOM 只用于评估窗口，逐项 `max_dom_rect_delta_css_px=0`。
- 观测类别为 `independent=5`、`reference-only=2`、`constrained=2`，与 ground truth 数量一致；标签 9/9，原因 8/9。`flat_badge` 是标签巧合：观测因圆角边界不完整（purity 0.972、boundary 0.911）判 `constrained`，ground truth 因内部文字/渐变必须可编辑而判 `constrained`；像素观察不到内部可编辑性。
- 独立资产 purity 为 0.999–1.000、boundary 为 1.000；`text_over_photo` 的 hole 0.096、edge 0.462、std 93.6，`icon_shadow` 的 purity 0.335；`logo_lowres` 的 acutance 0.0111；`flat_badge` 的 boundary 0.911。2x 复算同向。
- 首轮规则把 `logo_lowres` 与 `flat_badge` 判成 `reference-only`：只凭封闭孔洞会把白色 logo 图形、徽章白字和圆角背景误判为 baked overlay。最终规则要求 `hole_ratio >= 0.010` 且 `non_target_std >= 8.0`，低清改用内容归一化 `acutance`；绝对锐度 30 与中位数比值规则保留为报告指标但被否决。`acutance` sweep 在 0.02–0.20 内只隔离 logo，0 FP / 0 FN；这只是 9 个资产的局部结果。
- 36 个有序配对中 6 个预期同源对全部命中，0 FP / 0 FN；最低候选分 0.9983，最高非候选分 0.8739。`cover_full_a` 与 `cover_full_b` 为精确像素重复（裁片 SHA-256 相同），去重后 1x PNG 从 181942 B 降到 151777 B。
- 成本无单调优势：1x PNG 共享 161540 B、独立 181942 B（共享更小）；1x JPEG 共享 146746 B、独立 124397 B；2x PNG 249999 B vs 239119 B；2x JPEG 351640 B vs 275056 B（独立更小）。去重始终降低独立总量，混合模式最低（1x PNG 145036 B、1x JPEG 101837 B、2x PNG 183102 B、2x JPEG 228726 B）。
- 9 次替换：1x 共享 188.238 ms / 1,776,774 B，独立 26.987 ms / 333,626 B（约 6.98× / 5.33×）；2x 共享 558.679 ms / 3,422,891 B，独立 139.171 ms / 1,000,209 B（约 4.01× / 3.42×）。共享整页替换的窗口外变更均为 0，其他资产窗口未被波及。
- 矩形替换碰撞：独立资产为 0–0.0005；`flat_badge` 0.0264、`logo_lowres` 0.1005、`text_over_photo` 0.1462、`icon_shadow` 0.6649。碰撞只说明矩形替换会覆盖 baked 内容，不说明语义上必须整窗保留。
- 来源与四项能力分离：所有观测来源均为 `page-screenshot-crop`，`traceable=partial`；可导出均为 `yes`；内部可编辑均为 `not-observable-from-flat-crop`。精确重复只能支撑 `exact-duplicate-group`；同源候选不能恢复原文件，`derived` 不自动获得独立替换能力。
- 限制：`missing` 只定义并实现，没有实例化样例；mask 看不见与页面底色相同的内容（白色 logo 图形与徽章白字形成孔洞，不是外部叠层）；分类依赖 DOM 测量窗口，纯截图生产流需要单独检测器，因此观测结果只是窗口质量的上界。本实验并入 `R2-EXP-02`；`R2-EXP-01` 已完成 authored DOM 扰动，`R3-EXP-10` 也覆盖了输出合同层扰动，但原站 DOM 与原站响应式仍未验收。状态为 `completed-for-current-scope`，不是 `verified`。后续 `R3-EXP-10–15` 均已完成当前范围，R4 已完成 `R4-EXP-01–10` 当前范围。

### 11.10 R3-EXP-10 截图 flow 扰动与 DOM 冲突隔离（2026-10-18）

- 使用独立实验插件在 Figma `Page 1` 建立 7 个 `EXP10_` 场景，全部通过插件回读几何并导出 PNG；未调用生产 bridge 的 `setAutoLayout`，未修改 `src/` 与 `figma_bridge/`。统一容差 0.6 px。
- 页面纵向 stack：主栏 `220→260` 后 footer 下移 40、根高 `360→400`；插入 100px 通知条后顺序为 `header, main, notice, footer`，footer 再下移 100；删除后无空隙；宽度 `900→990` 时三个直接子项均为 990，main 内层子项为 950，右溢出 0。
- 单行卡片集合：5×140 + 4×12 + 2×8 = 764（不是 768）；插入第 6 张后父宽 +152、末卡 `x 616→768`；删除后回 764。宽度 `+10%` 到 840.4 无溢出；`-10%` 到 687.6 时固定卡片溢出 68.4，按规则回退整个区域为固定坐标并恢复相对位置，标 `partial-fallback`。
- 卡片信息：标题宽 134 时基线 2 行（44），长标题 4 行（88），作者下移 44，卡片 `237→281`；作者 1→2 行后卡片 `281→299`。这证明“文本高度→信息块 Hug→卡片 Hug”的传播链；行数由 `height / lineHeight` 估算，因为该 API 回读不提供 `lineCount`。
- 主栏/侧栏：行高 `496→536`；交换后侧栏 536、行高仍 536；宽度 `+10%` 到 1584 无溢出；`-10%` 到 1296 时溢出 19，没有获准的最小宽度/变列规则，保留静态宽度并标 `partial-fixed-width`。
- 页脚：5 行、44px 间距、根 padding 1，基线高 222；第 2 行 44→84、第 3 行下移 40、根高 222→262；插行 +44 后删除回 262；5 条分隔线均贴行底。绝对定位底部分隔线在行高 44→84 时 `y 43→83`，`vertical=MAX` 约束生效。
- 复杂叠放：320×240 区域内 base/overlay 有意重叠 10800 平方像素，保留 `layoutMode=NONE` 与 3 个子项，标 `fallback-fixed`；L1/L2/L3 不适用，而不是伪造通过。
- DOM 合成夹具：DOM 顺序 `A,B,C,D`、`row-reverse` 视觉顺序 `D,C,B,A`，Chrome 截图退出码 0，只记 `external-conflict`；在线目录 `R3-D01` 的 `dom_order` 仍为 `unknown`，不转成冲突或 DOM 证据。
- 首轮 4 个场景失败：子节点插入后先设 Hug、再用 `spec.height` 调用 `resize()` 把 `primaryAxisSizingMode` 改回 FIXED；页脚行同时声明 `AUTO` 与 `layoutSizingVertical=FIXED`；卡片行预期 768 而实际 Hug 为 764；主侧栏顶对齐误用绝对 `y==0`（场景在 `y=600`），标题宽 128 时实际 3 行。修复为“先 resize、再重设轴 sizing 与子项 sizing”，页脚行改 Hug，预期改 764/840.4/687.6，顶对齐改为比较父行 `absoluteY`，标题宽改 134。重跑后 4 `pass`、1 `partial-fallback`、1 `partial-fixed-width`、1 `fallback-fixed`，0 失败检查。
- 限制：所有场景都是合成输出合同夹具；不证明原站响应式、断点、真实字体/OCR 度量、两层 stack 跨行重组或生产 bridge。通过项只能写 `verified_for=output-contract`、`source_behavior=inferred`。`R2-EXP-01` 已完成 authored DOM 扰动，但原站 DOM 与原站响应式仍未验收。状态为 `completed-for-current-scope`，不是 `verified`。后续 `R3-EXP-11–15` 均已完成当前范围，R4 已完成 `R4-EXP-01–10` 当前范围。

### 11.11 R3-EXP-11 四项验收样例集与评分校准（2026-10-18）

- 建立标定集 12 + 验收集 12 个合成基础样例，覆盖中文、英文、混排、图标/logo、复杂背景与长页，每类含清晰与困难输入；每样例 6 个变体（baseline、typo、occlusion、synthetic_asset、no_propagation、structure_role），共 144 张截图。页面 1040 px 宽，长页 5 段，目标卡为第 3 段；其余单页目标卡为第 1 段。
- 标定集与验收集均为 288/288 四维状态匹配、故障目标命中 60/60、跨维误报 0/180、baseline 假报警 0/12。typo 只在 visual `fail`；occlusion 只在 visual `partial`，每例恰好一个正文对象的内容/断行/字形为 `unknown`；synthetic_asset 只在 asset `fail` 而视觉 `pass`；no_propagation 只在 edit `fail`；structure_role 只在 structure `fail`。
- 关键裕量：typo 对象 exact 1.0 vs 0.75–0.95、字符 exact 1.0 vs 0.99115–0.99843、字形 0–1.54 vs 9.13–43.02；遮挡面积比 0.25% 以下 vs 4.18%–10.01%；传播误差 0 vs 375–760 px；资产隔离度 0.966–0.979 vs 0.00418–0.00477、四角保留 1.0 vs 0.0；结构角色准确率 1.0 vs 0.875–0.964286。
- 冻结 14 个阈值：`content_object_exact_min=0.98`、`content_character_exact_min=0.999`、`linebreak_match_min=1.0`、`glyph_local_mae_max=4.0`、`pixel_card_mae_max=0.1`、`geometry_min_iou_min=0.999`、`structure_role_accuracy_min=0.98`、`structure_parent_accuracy_min=0.999`、`structure_boundary_min_iou_min=0.999`、`edit_native_text_ratio_min=1.0`、`edit_propagation_error_px_max=16.0`、`asset_layer_isolation_min=0.5`、`asset_corner_unchanged_min=0.5`、`change_region_ratio_min=0.02`。其中断行、像素、几何、父关系、边界、原生文本没有对应故障变体，只能写合同值或干净噪声边界；传播阈值 16 px 是候选网格上限，不是 375 px 的中点。
- 评分分母：每集 12 页、12 个目标区域、79 个文本对象、2693/2691 个字符、135 个结构对象、135 个边界配对、2,474,048 个目标卡像素、12 个编辑探针卡、12 个传播用例、36 个原生文本对象、12 个资产槽；全部页面共 20 段（10 个单段页 + 2 个 5 段长页），只探测 12 段，8 段未覆盖；资产槽在长页第 1 段，编辑目标在第 3 段。
- `partial` 只在 visual 遮挡出现：有效区域为目标卡内未被变化块覆盖的 89.99%–95.82%，未知区域 4.18%–10.01%；该正文对象不进入内容通过分子，不能改文、补全或重排，需原分辨率图或准确转写并另做验收。维度级 `unknown` 未触发。长页 hard 的 `s3-kicker` 缺失与第 4 段重复标题是源输入异常，保留而不自动修复。
- 限制：所有夹具为同一实验者的合成页面，候选是基准 + 单缺陷差分，不是独立重建；内容 exact 用 DOM 文本回读而非 OCR；结构树是 authored DOM，不是截图推断；编辑探针是 DOM/CSS，不是 Figma 写入；资产探针是隐藏 DOM 图片层；未注入字体替换、OCR、压缩、低清、断行/边界/几何专项、缺项或多状态缺陷；比例阈值只覆盖 4–20 个文本对象、113–638 个字符，更大页面可能失去单字符敏感性。状态为 `completed-for-current-scope`，不是 `verified`。后续 `R3-EXP-12–15` 均已完成当前范围，R4 已完成 `R4-EXP-01–10` 当前范围。

### 11.12 R3-EXP-12 多状态参考冲突与权威版本（2026-10-18）

- 建立 1 个合成页面、11 个参考记录、6 个状态签名与 7 个 scope-state 组。每条参考记录 scope、state、像素 hash、原始尺寸、裁切/变换、采集时间、轮播帧、遮挡矩形与 authority；viewport 与 DPR 始终显式记录，不从图片宽度反推。
- 8 个参考比较对中，3 个同态可比较、4 个异态、1 个瞬态。同态重复的完整图 SHA-256、像素 MAE `0.0`、exact ratio `1.0` 与最小几何 IoU `1.0` 一致；frame 0/1、scroll 600、zoom 1.25、toast 遮挡与过渡均保持独立状态。
- 异态比较不进入几何误差：frame 0 与 frame 1 的完整图 MAE 为 `50.950043`，scroll 600 为 `63.598985`，zoom 1.25 为 `52.636769`，但均由状态守卫挡住；守卫后几何错误 `0`，避免 2 个 naive 假差异。过渡状态最小几何 IoU `0.449275`，仍只记 `transient-not-comparable`。
- 4 个拼接场景：同态全重叠 `composite-verified`（覆盖 `1.0`、重叠 MAE `0.0`）；100 px 缺口 `composite-unknown / coverage-gap`（覆盖 `0.9`、缺口 `[500,600]`）；混合轮播帧 `composite-unknown / mixed-state`；v1+v2 混拼 `composite-unknown / content-version-mismatch`。缺口不补图，混合状态与历史/新版不靠多数投票合并。
- v2 以显式 `supersedes` 取代 v1，winner 为 `ref-frame0-v2-authorized`；v1 与 repeat 进入 historical，v3 保持 unresolved。外部 A/B 同状态但内容 hash 不同，结果为 `external-conflict`、winner `null`，两条参考均保留。合同值为 `overlap_mae_max=2.0`、`composite_coverage_min=0.999`、`geometry_requires_same_state=true`，不从图片宽度推断 viewport/DPR；16/16 检查通过，`composite-conflict` 分支未实例化。
- 限制：只有一个合成页面、一个浏览器、一个 DPR 和 authored CSS 状态；外部来源是模拟导入，tile 来自同态重复捕获，几何来自 authored DOM。真实轮播时序、真实外部来源、近同态、截图自动状态识别、Figma 写入与生产权限链仍未验证。状态为 `completed-for-current-scope`，不是 `verified`。
