# Round 3 · 未决实验与标定清单

> 状态：R3 两轨回答已归档；`R3-EXP-01`–`R3-EXP-15` 均已达到 `completed-for-current-scope`（2026-10-18）。本文件保留实验清单、证据与剩余外部边界。  
> 依据：`ROUND_03_DOM_ANSWERS_FORMATTED.md`、`ROUND_03_ANSWERS_FORMATTED.md`、`V2_OPTIMIZATION_PLAN.md` 第 13 节。  
> 边界：本文件不代表任何项目已通过；未执行前保持 `pending / unknown`，不得写成 `verified`。`R3-EXP-13/14/15` 为 2026-10-18 补跑的边界实验，状态均为 `completed-for-current-scope`。

> 默认产品策略已于 2026-10-18 由用户确认，见 `V2_OPTIMIZATION_PLAN.md` 第 13.4 节；默认值不改变本文件的实验状态。

## 1. 总表

| ID | 实验 / 标定 | 阻塞对象 | 当前状态 | 产物 |
|---|---|---|---|---|
| R3-EXP-01 | 在线目录 21 个槽位完整核对 | layout_plan / 网格重建 | 已完成（限 `1:101`，21/21） | `output/_r3_experiments/online_grid.json`、`R3_EXP_01_ONLINE_GRID.md` |
| R3-EXP-02 | grid / wrap 能力与序列化回读 | adaptive 网格 | 已完成当前范围（27/27 + 32/32 + 13/13 步；保存重开一致）；嵌套 grid、HUG+FILL 宽度求解、自动+混合轨道未覆盖 | `grid_probe_run*.json`、`grid_span_fill_run.json`、`grid_hug_flex_probe.json`、`grid_*_pre/post_save.json`、`grid_span_readback_compare.json`、`R3_EXP_02_GRID_PROBE.md` |
| R3-EXP-03 | SVG、滤镜、mask、混合效果链矩阵 | 资产与重建策略 | 已完成当前范围（20 个 SVG + 12 个原生用例；直接导入与重建策略分列）；`R3-EXP-15` 补离线栅格回退 | `exp03_effect_matrix.json`、`exp03_*` PNG、`R3_EXP_03_EFFECT_MATRIX.md`、`r3_exp15_raster_fallback.json` |
| R3-EXP-04 | 无稳定 ID 的匹配成本与阈值标定 | 身份与跨重建映射 | 已完成当前范围（14 场景 / 37 配对；`0.20 / 0.06` 下 0 错误、0 漏配；弱标定） | `exp04_identity_matching.json`、`R3_EXP_04_IDENTITY_MATCHING.md` |
| R3-EXP-05 | full-page 拼接与 sticky/fixed 同态 | 参考状态契约 | 已完成当前范围（受控本地页；8 段拼接、文档捕获、扩展视口） | `exp05_fullpage_capture.json`、`exp05_*` PNG、`R3_EXP_05_FULLPAGE_CAPTURE.md` |
| R3-EXP-06 | `normal`、基线、字形阈值标定 | 文本验收 | 已完成当前范围（Chromium 单环境 12 用例；同环境噪声与 DPR 复核）；`R3-EXP-13` 补 Chromium + WebKit | `exp06_text_metrics.json`、`exp06_text_cases*.png`、`R3_EXP_06_TEXT_METRICS.md`、`r3_exp13_cross_renderer_text.json` |
| R3-EXP-07 | 截图分组与父关系人工一致性 | 截图结构 IR | 已完成当前范围（16 个 seed；5 `candidate` / 11 `ambiguous` / 0 错误候选；父编辑、环拒绝、split/merge、坏合并拒绝与 undo 均完成校验） | `exp07_grouping.json`、`exp07_*` PNG、`R3_EXP_07_GROUPING_LINEAGE.md` |
| R3-EXP-08 | OCR、低清、压缩与文本阈值 | 截图文本验收 | 已完成当前范围（13 用例 × 27 条件 × 2 引擎 = 702 条；普通 32px 核心 exact T 5/7、E 3/7；对抗 0/324 exact；证据字段仅 T 有效 32px 1/2）；`R3-EXP-14` 补已知字体/字号静态基线 | `exp08_text_acceptance.json`、`exp08_*` 条件图、`exp08_contact_sheet.png`、`R3_EXP_08_TEXT_ACCEPTANCE.md`、`r3_exp14_static_baseline.json` |
| R3-EXP-09 | 裁片来源、替换能力与共享图成本 | 截图资产 | 已完成当前范围（9 资产；观测类别 5/2/2 与 GT 数量一致；标签 9/9、原因 8/9；同源 6 TP / 0 FP / 0 FN；共享 vs 独立成本与矩形碰撞已测）；`missing` 未实例化 | `exp09_asset_contract.json`、`exp09_*` 图、`R3_EXP_09_ASSET_CONTRACT.md` |
| R3-EXP-10 | 截图 flow 扰动与 DOM 冲突隔离 | 截图布局 | 已完成当前范围（7 个输出合同场景：4 `pass`、1 `partial-fallback`、1 `partial-fixed-width`、1 `fallback-fixed`；0 失败检查；DOM 冲突记 `external-conflict`） | `exp10_flow_perturbation.json`、`exp10_flow_plugin/`、`EXP10_*_contact.png`、`R3_EXP_10_FLOW_PERTURBATION.md` |
| R3-EXP-11 | 四项验收样例集与评分校准 | 交付报告 | 已完成当前范围（24 样例 × 6 变体；标定/验证各 288/288；目标 60/60；跨维误报 0/180；baseline 0/12） | `exp11_acceptance_calibration.json`、`exp11_acceptance_site/`、`exp11_artifacts/`、`exp11_*.png`、`R3_EXP_11_ACCEPTANCE_CALIBRATION.md` |
| R3-EXP-12 | 多状态参考冲突与权威版本 | 截图输入契约 | 已完成当前范围（11 参考 / 6 状态 / 7 组；4 拼接：1 verified / 3 unknown；外部冲突 1；16/16 检查） | `exp12_reference_states.json`、`exp12_reference_state_site/`、`exp12_artifacts/`、`exp12_*.png`、`R3_EXP_12_REFERENCE_STATES.md` |
| R3-EXP-13 | 跨渲染器文本度量与基线 | 文本验收 | 已完成当前范围（Chromium + WebKit；8/8 检查；基线最大差 0.5px；Firefox 启动失败） | `r3_exp13_cross_renderer_text.json`、`r3_exp13_*`、`R3_EXP_13_CROSS_RENDERER_TEXT.md` |
| R3-EXP-14 | 静态截图基线估计 | 文本验收 | 已完成当前范围（28 次测量；最大误差 0.5px、平均 0.018px；6/6 检查） | `r3_exp14_static_baseline.json`、`r3_exp14_*`、`R3_EXP_14_STATIC_BASELINE.md` |
| R3-EXP-15 | 失败 SVG 的离线栅格回退 | 资产与重建策略 | 已完成当前范围（4/4 用例；PNG 无损；9/9 检查；非真实 Figma 端到端） | `r3_exp15_raster_fallback.json`、`r3_exp15_artifacts/`、`R3_EXP_15_RASTER_FALLBACK.md` |

## 2. DOM 轨

### R3-EXP-01 在线目录 21 个槽位完整核对

**状态：已完成（scope=`1:101`，21/21 槽位）**

结果与证据见 `R3_EXP_01_ONLINE_GRID.md` 和 `output/_r3_experiments/online_grid.json`。已确认 3 行×7 列、全部 152×237、列步长 162、列间隙 10、行步长 237、行间隙 0、padding `21/30/1/36`，且 5 种遍历顺序与 0.5/1/2 px 容差下分组稳定。该结论只覆盖这 21 个槽位的视觉几何；`dom_order` 仍为 `unknown`，编辑与序列化行为未验证。

**目的**

- 验证 7×3 网格是否等距、等高。
- 验证推导值 `162 / 152 / 237 / 21/30/1/36` 与每槽实际值是否一致。

**前置**

- 保留题内离线编号，不重绑定当前画布编号。
- 记录每个槽位的矩形、类型、内容角色和离群项。

**步骤**

1. 导出全部 21 个槽位矩形与类型。
2. 逐槽比较推导 152×237 与实际宽高。
3. 用垂直重叠、上沿、水平步长和内容角色做聚类。
4. 以不同起始遍历顺序重复聚类。
5. 记录人工锚点与旧序到新序映射。

**通过 / 输出**

- 每个槽位有矩形、行列号、聚类容差和离群标记。
- 展示顺序在不同遍历顺序下保持一致，或明确记录不稳定原因。
- 推导值与实测值的差异逐项列出。

**不得宣称**

- 未核对前，不得把 `152×237` 写成实测，也不得把 `dom_order=unknown` 改成已知。

### R3-EXP-02 grid / wrap 能力与序列化回读

**状态：`completed-for-current-scope`（不是全量 `verified`）**

已在 Figma `126.9.13` 的可编辑文件 `FigmaAgent复刻UI`、页面 `Page 1` 上，用独立实验插件完成三轮探测与一次隔离复测，共 72/72 步成功。已实测：5×10 固定轨道 grid、`MANUAL` 增删移动、`ROW_AUTO_FLOW` 压缩、5×2 grid 的 `ROWS` 自动轨道、固定轨道与 `HUG` 轨道、`appendChildAt`、行列重排、wrap 在 300/400/520 宽度下的分行，以及保存关闭重开后的逐字段回读。补充实验确认：跨列/跨行本身不拉伸，配合 `FILL` 后宽度为 `170`、高度为 `130`；`MIN/CENTER/MAX` 在固定单元格内分别产生 `20px` 偏移；`FLEX 1/2/1` 实测为 `60/120/60`；HUG 列与 HUG 父帧会把父帧宽度从 `276` 推到 `296`。同时发现：父帧设为 `HUG` 会把现有 `FLEX` 列改写为 `HUG`，恢复 `FIXED` 后轨道类型不会自动恢复。三个基础节点和三个补充节点的父/子结构、轨道、锚点、尺寸和 `id` 在重开后全部一致。证据见 `R3_EXP_02_GRID_PROBE.md` 与 `output/_r3_experiments/`。未覆盖嵌套 grid、直接创建 HUG 轨道并搭配 `FILL` 子项的宽度求解、自动轨道与混合轨道组合、全页面编辑和生产 bridge 集成；因此不得写 adaptive grid 已整体通过，也不得写生产 bridge 已支持 grid/wrap。

**目的**

- 确认当前环境的单个 grid 是否能作为等价实现。
- 区分“视觉几何等价”和“编辑行为等价”。

**步骤**

1. 建 5 列 10 卡样例。
2. 执行删除第 1、5、6 项，增加第 11 项，跨行移动。
3. 检查最后一行、空槽、顺序、身份与高度传播。
4. 保存重开、导出回读，检查轨道、顺序、尺寸、裁剪和身份映射。
5. 另测 wrap 的一维包行行为。

**通过 / 输出**

- 记录能力版本、`profile`、测试范围。
- 逐项记录几何、编辑、序列化结果。
- 明确 `regroup-on-rebuild` 与原生换行的差异。

**不得宣称**

- 像素相同不等于编辑等价；单样例通过不等于所有 grid 通过。

**延后补充项（2026-10-18 记录，不阻塞 R3 主线）**

- 嵌套 grid 与 grid 内 Auto Layout 子节点。
- 直接创建 `HUG` 轨道并将子项设为 `FILL` 时的宽度求解。
- 自动轨道 `ROWS/COLUMNS` 与 `FLEX/HUG` 的混合组合，以及内容变化后的重算稳定性。
- 长文本、变宽子项、图片与 grid 的尺寸冲突。
- 生产 bridge 的 grid/wrap 命令、回滚策略与集成。

边界：以上未闭合前，不得把 grid 加入生产白名单，不得宣称 adaptive grid 全量通过，也不得宣称生产 bridge 已支持 grid/wrap；这些项不阻塞 `R3-EXP-05/06` 的参考状态与文本测量实验。

### R3-EXP-03 SVG、滤镜、mask 与混合效果链矩阵

**状态：`completed-for-current-scope`（2026-10-18，不是全量 `verified`）**

已在 Figma `126.9.13` 上用独立实验插件完成 20 个 SVG 用例和 12 个原生用例，全部调用与 PNG 导出成功；这只是导入成功，不是语义等价。直接导入可用的有：线性/径向渐变、`clip-path`、alpha/luminance mask、渐变描边、data URI 图片、`feGaussianBlur`（`LAYER_BLUR`）；均值差均小于 1。直接导入丢失的有：`feDropShadow`（`effects=[]`）、filter 链（只剩一个 `LAYER_BLUR`）、`foreignObject`/`pattern`/远程图片（空白 frame）。`<use>` 只静态展开，`<animate>` 只保留首帧。原生能力侧：drop/inner shadow、layer/background blur、效果链、alpha/vector/luminance mask、`clipsContent`、16 种 blend mode 均为 `native-candidate`；mask 与阴影同帧时均值差 10.2087，改为 wrapper 后 1.2351。文本四个用例均值差 11.25–11.62，差异集中在抗锯齿边缘，不能用于字体判定；预加载用例与显式字体用例混杂，该命题 `not-evaluated`。`R3-EXP-15` 已补四个失败特性的 Chromium 渲染、PNG/JPEG 打包与本地 mock `create_image` 合同（PNG 无损、9/9），但没有执行真实“栅格化 → 导入 Figma → 再导出 → 像素复核”链路；因此 raster-fallback 当前是 `completed-for-current-scope` 的离线平铺资产合同，不能写成真实 Figma 端到端已验证。证据见 `R3_EXP_03_EFFECT_MATRIX.md`、`R3_EXP_15_RASTER_FALLBACK.md` 与 `output/_r3_experiments/exp03_*`、`output/_r3_supplements/r3_exp15_raster_fallback.json`。

**目的**

- 建立复杂效果的逐项准入证据。
- 防止“名字相同就等价”或“导入成功就准确”。

**步骤**

1. 每个算子先单测。
2. 再测透明背景、多层叠放、裁剪和组合效果。
3. 比较效果外扩、颜色、遮挡区域和裁剪边界。
4. 覆盖渐变、简单阴影/blur、混合模式、filter 链、alpha/vector mask、`clip-path`。
5. 覆盖 SVG 的渐变、clip/mask、文本、复用引用、复杂描边、filter、`foreignObject`、外部引用与动画。

**通过 / 输出**

- 每项标 `native-candidate`、`raster-fallback` 或 `unsupported`。
- 附依赖条件、版本、证据和验收结果。

**不得宣称**

- 单算子通过不证明效果链通过；未证等价不得进入白名单。

### R3-EXP-04 无稳定 ID 的匹配成本与阈值标定

**状态：`completed-for-current-scope`（2026-10-18，纯离线合成实验）**

已完成 5 个 calibration + 9 个 validation 场景、37 个预期配对。特征为 text 0.30、image 0.22、geometry 0.14、role 0.08、style 0.06、order 0.04、parent 0.06、neighbor 0.10；缺失特征按可用权重归一化并记录 `coverage`（`cal_missing_feature` 实测 0.72）；文本 `<0.35` 时成本强制 `>=0.70`；观测范围外直接 `not-seen`；Hungarian 一对一。推荐 `accept=0.20`、`gap=0.06` 时 calibration/validation 均为 0 错误记录、0 漏配；`accept=0.25` 开始误配“相似但不同”，`gap=0.10` 产生漏配。`0.15–0.20 × 0.03–0.06` 为平台区，属弱标定。基线 `naive_node_id` 有 10 条错误记录；仅内容特征 0 错误但漏 6 条（跨栏同标题/同父冲突）。不输出 `deleted`。证据见 `R3_EXP_04_IDENTITY_MATCHING.md` 与 `output/_r3_experiments/exp04_identity_matching.json`。

**目的**

- 验证一对一冲突检测匹配是否可复现。
- 避免“每项必须匹配到旧项”的强制目标。

**步骤**

1. 构造同名同封面双副本交换、插队、局部采集、虚拟节点复用样例。
2. 记录特征、特征缺失、匹配成本、候选差距和接受阈值。
3. 检查多对一、一对多、同分候选和跨栏目冲突。
4. 核对 `proposed-match / ambiguous / not-seen` 是否按预期输出。

**通过 / 输出**

- 权重与阈值由样例标定，不输出伪精确分数。
- 未采到项只记 `not-seen`，不误判 `deleted`。

**不得宣称**

- 位置接近不等于同一次出现；完全相同副本互换必须保留歧义。

### R3-EXP-05 full-page 拼接与 sticky/fixed 同态

**状态：`completed-for-current-scope`（受控本地页，2026-10-18）**

已在 Playwright 1.62.0 / Chromium 151.0.7922.34、1200×800、DPR 1、无外部资源与无动画的本地页完成三模式对比：8 段原视口滚动拼接（步长 640、重叠 160）、保持原视口的 `full_page=True` 文档捕获、扩展到 4904 高的视口捕获。8 段 M0/M1 全部稳定，覆盖 `[0,4904]` 无缺口，hero 与 6 个内容块的跨段文档坐标 spread 均为 0。屏蔽 sticky 顶栏、sticky 子头、fixed 条纹和 fixed 徽标后，拼接与文档捕获在 86.7961% 有效像素上平均差、P99、最大值均为 0；原始平均差 21.4613 集中在每段重复的 sticky/fixed 区域。扩展视口把 hero 从 800 改为 4904、`docHeight` 从 4904 改为 9008，截图只覆盖新文档的 54.44%，不能作为整页参考。懒加载把 `docHeight` 从 4504 推到 4904。未覆盖：真实站点、其他浏览器/版本、轮播/广告/遮挡、协作与动态状态、截图过程中发生的懒加载，以及真实站点上的跨接缝字体/资源变化。证据见 `R3_EXP_05_FULLPAGE_CAPTURE.md` 与 `output/_r3_experiments/exp05_*`。

**目的**

- 区分单视口、文档捕获和逐段合成参考。
- 验证接缝、固定头和懒加载边界。

**步骤**

1. 同页分别采用原视口滚动拼接和扩展视口捕获。
2. 加入 `100vh` 区域、fixed 背景、sticky 头、懒加载内容。
3. 每段记录 `capture_id`、`segment_id`、时间、视口、滚动、裁剪/拼接变换、重叠区与状态。
4. 每段做 M0／S／M1，比较跨段不变量与接缝。
5. 报告采样覆盖、有效区和无效区。

**通过 / 输出**

- 全局参考标 `composite`；固定头策略显式记录。
- 部分同态只支持局部几何结论。

**不得宣称**

- 不以同 URL、同页高或全局 hash 相同替代局部同态；`partial` 不支持整页 `verified`。

### R3-EXP-06 `normal`、基线与字形阈值

**状态：`completed-for-current-scope`（受控实验，2026-10-18）**

已在 Chromium 151.0.7922.34、1200×1600、DPR 1/2、24px/32px 的本地页完成 12 个用例：拉丁单/多行、中文单/多行、全角标点、混排、数字、省略号、粗体、斜体、缺字、emoji。关键实测：Arial 实际行进 32，YaHei/混排 33；零尺寸基线探针不改变容器与行盒，移除后布局完全一致；混排 YaHei 顶部 585 + 25 与 Arial 顶部 588 + 22 同基线 610；`document.fonts.check` 对缺字仍为 true，截图为两个 tofu。3 次重复 CSS 度量一致，DPR 1/2 CSS 度量一致。`R3-EXP-13` 已补 Chromium + WebKit 的 12 用例 × 2 DPR 标定：换行数差 0/12、基线 P50 0px / 最大 0.5px、8/8 检查；Firefox 本机启动失败（`spawn UNKNOWN`），未覆盖。其他 Chromium 版本、其他操作系统、可变字体与通用跨平台阈值仍为 `not-evaluated`。证据见 `R3_EXP_06_TEXT_METRICS.md`、`R3_EXP_13_CROSS_RENDERER_TEXT.md` 与 `output/_r3_experiments/exp06_*`、`output/_r3_supplements/r3_exp13_cross_renderer_text.json`。

**目的**

- 找到可复现的 used 行盒和基线证据。
- 标定跨浏览器、跨渲染器的字形阈值。

**步骤**

1. 同一字符串分别采用单行、多行、混合 run。
2. 交叉记录容器矩形、Range 矩形、相邻行进距离、字体 run 和字体度量。
3. 在受控副本使用零尺寸、基线对齐探针，验证不改变行高、换行和布局后恢复原内容。
4. 明确 alphabetic / ideographic 基线定义。
5. 固定字体二进制、版本、可变轴、字号、字重、DPR、浏览器与输出渲染版本。
6. 覆盖常见中文、全角标点、拉丁大小写、数字、中英混排、省略号、粗斜体、缺字；emoji 另测。
7. 先估同环境重复捕获噪声，再比较跨渲染器分布。

**通过 / 输出**

- 分角色报告边缘、行进、换行和粗细差异。
- 无可靠基线时标 `not-evaluated`，不填误差 0。

**不得宣称**

- Range 不等于行盒；Range 底部减常数、字形底边当基线、统一 1.4em 都不作实测。

## 3. 截图轨

### R3-EXP-07 截图分组与父关系人工一致性

**状态：已完成当前范围（单受控页，2026-10-18）**

结果与证据见 `R3_EXP_07_GROUPING_LINEAGE.md` 和 `output/_r3_experiments/exp07_grouping.json`。16 个有父对象的 seed 中，5 个为 `candidate`、11 个为 `ambiguous`、错误候选 0 个；`candidate_parent` 建议与 ground truth 16/16 一致，但只有 5 个达到候选强度。外层有边框的 `obj-band` 是主栏/侧栏的最小视觉容器，说明“边框包含”不能自动证明父关系；40px 纯白 gutter 的 `white_ratio=1.0`，naive gap merge 仍错误合并主栏与侧栏。父关系编辑、环拒绝、split、merge 和坏合并 undo 均保持对象身份与 lineage，最终 digest 恢复初始值。结论只覆盖该受控页；自动分割、OCR、真实站点和 Figma API 写入未验证。

**目的**

- 验证边界证据与语义证据是否足以稳定分组。
- 防止按最近距离合组或按视觉框数量评优。

**步骤**

1. 准备相同白底主栏/侧栏、无边框卡片、跨多个栏目的有边框背景。
2. 记录 `object_id`、`role`、`parent_relation`、`pixel_region`、`boundary_evidence`、`semantic_evidence`、`alternatives`、`evidence_status`、`review_status`。
3. 人工只改父关系，检查对象身份是否保持可追溯。
4. 检查拆分、合并是否保留 lineage。

**通过 / 输出**

- 分组结论可作为有证据假设，附替代解释和 review 状态。
- 共享白底不作为合组证据。

**不得宣称**

- 检测框不是 CSS 容器边界；“看起来居中”不证明 Hug／Fill。

### R3-EXP-08 OCR、低清、压缩与文本阈值

**状态：已完成当前范围（2026-10-18）**

结果与证据见 `R3_EXP_08_TEXT_ACCEPTANCE.md` 和 `output/_r3_experiments/exp08_text_acceptance.json`。受控页面 13 个用例、27 个条件标签、2 个 OCR 引擎共 702 条记录；`native_fs_32` 与 `scale_100` 为同一图像，实际 26 张不同图像。全量严格 `exact` 81/702，核心字符 exact 230/702，行数匹配 677/702。

关键结论：对抗字符 324 条记录 `exact` 为 0，核心字符仅 71/324；普通文本 32px 核心 exact 为 Tesseract 5/7、EasyOCR 3/7，16px 各 4/7，12px 为 1/7 与 2/7，8px 均为 0/7；证据字段只有 Tesseract 在有效 32px 的少数条件通过 1/2，EasyOCR 在清晰 32px 仍把 `¥` 识别为 `半`。JPEG 与模糊均非单调阈值；模糊边界约 σ 1.5–2.0px 但依赖内容。行数匹配、文本框 IoU 和 OCR 置信度都不能单独通过：447 条记录行数匹配但核心字符错误；exact 与错误记录的 IoU 中位数分别为 0.803 与 0.819；置信度 ≥0.8 的接受项中有 164 条错误。遮挡记录全部 `unknown`，用户补文保持 `user-supplied-unverified`。`R3-EXP-14` 已在已知字体/字号下从静态截图估计 alphabetic baseline（28 次测量、最大 0.5px、平均 0.018px、6/6 检查）；未知字体/字号仍为 `not-evaluated`。本实验只证明当前字体、Chromium、Tesseract 5.5.0 与 EasyOCR 1.7.2 的局部边界，不是通用阈值。

**目的**

- 分项验证内容、断行、框、字形和基线。
- 重新标定抗锯齿、压缩和缩放后的阈值。

**步骤**

1. 覆盖相似汉字、`0 / O / 〇`、`1 / l`、全角标点、三点与省略号、模糊截断、中英混排。
2. 分别测内容转写、可见断行、文本框、字形和基线。
3. 记录 OCR 原始分数口径、候选字符、来源框和复核状态。
4. 检查低清、压缩、遮挡与 `user-supplied` 补文是否被正确标记。

**通过 / 输出**

- 文本误差分项报告，可汇总问题数但保留子项。
- 基线未测为 `unknown`，字体替代不通过原字体验收。

**不得宣称**

- 单一 OCR 分数阈值不保证正确；统一 140% 行高不是行高证据。

### R3-EXP-09 裁片来源、替换能力与共享图成本

**状态：`completed-for-current-scope`（2026-10-18，不是 `verified`）**

已在单个 1200×900 受控页面上完成 9 个资产用例。观测类别为 `independent=5`、`reference-only=2`、`constrained=2`，与 ground truth 数量一致；标签一致 9/9，原因一致 8/9。`flat_badge` 的标签是巧合：观测因圆角边界不完整判 `constrained`，ground truth 因内部文字/渐变必须可编辑而判 `constrained`，像素并未观察到内部可编辑性。同源检测 36 个有序配对中 6 个预期对全部命中，0 FP / 0 FN；`cover_full_a` 与 `cover_full_b` 为精确像素重复。1x/2x 的共享整页、独立裁片、去重与混合模式字节成本已测，但不存在“共享必然更省”的单调结论。9 次替换中，独立资产窗口碰撞为 0–0.0005，合成/受限资产为 0.0264–0.6649；共享整页替换的窗口外变更均为 0。详见 `R3_EXP_09_ASSET_CONTRACT.md` 与 `output/_r3_experiments/exp09_asset_contract.json`。本实验并入 `R2-EXP-02`；`R2-EXP-01` 已完成 authored DOM 扰动，`R3-EXP-10` 也在输出合同层覆盖了扰动类型，但原站 DOM 与原站响应式仍未验收；`missing` 只定义并实现，未实例化样例。

**目的**

- 分离 `provenance` 与 `replaceability`。
- 验证 `derived` 是否真的可独立替换。

**步骤**

1. 准备同封面不同裁切、文字盖图、带阴影图标、低清 logo 样例。
2. 逐项记录来源、边界、分辨率、合并内容、替换范围与限制。
3. 只替换目标，检查邻近文字和背景是否被一并替换。
4. 比较共享全页图裁剪与独立裁片的导出、替换和编辑成本。
5. 标 `independent / constrained / reference-only / missing`。

**通过 / 输出**

- 来源可追溯、可导出、可独立替换、素材内部可编辑四项分别报告。

**不得宣称**

- 每个裁片都是原始素材；`derived` 必然可独立替换；近似外观可补造 logo 或封面。
- 9/9 标签一致等于通用分类器已验证；共享整页图必然更省字节；矩形替换不会误伤内容；`missing` 已被覆盖。

### R3-EXP-10 截图 flow 扰动与 DOM 冲突隔离

**状态：`completed-for-current-scope`（2026-10-18，不是 `verified`）**

已完成 7 个合成输出合同场景：页面纵向 stack、单行卡片集合、卡片信息、主栏/侧栏、页脚内容行、绝对定位底部分隔线与复杂叠放。4 个场景 `pass`：页面 stack 在 `+40`、插入/删除与宽度 `+10%` 下传播正确；卡片信息在标题 2→4 行、作者 1→2 行时卡片 `237→281→299`；页脚第 2 行 `44→84`、页脚 `222→262`、插行 `+44` 后删除回 262；绝对分隔线 `y 43→83`。卡片集合在宽度 `-10%` 时溢出 68.4，按规则回退整个区域为固定坐标；主栏/侧栏在宽度 `-10%` 时溢出 19，保留静态宽度并记 `partial-fixed-width`；复杂叠放保留 `layoutMode=NONE`。合成 DOM 夹具的 DOM 顺序 `A,B,C,D` 与视觉顺序 `D,C,B,A` 只记 `external-conflict`，在线目录 `dom_order` 仍为 `unknown`。首轮 4 个失败已披露：HUG 被后续 `resize()` 覆盖、页脚行 `AUTO` 与 `FIXED` 声明矛盾、卡片行 768/764 预期错误、顶对齐误用绝对零点与标题 128/134 行数假设。详见 `R3_EXP_10_FLOW_PERTURBATION.md` 与 `output/_r3_experiments/exp10_flow_perturbation.json`。`R2-EXP-01` 已完成 authored DOM 扰动，其扰动类型也在本实验的输出合同层覆盖；原站 DOM 与原站响应式仍未验收。

**目的**

- 验证所选输出规则是否满足获准的编辑合同。
- 保持截图轨与 DOM 轨来源隔离。

**步骤**

1. 在候选区域执行长标题、实际高度 +40、条目增删、宽度变化、主栏/侧栏高低交换。
2. 分别记录 L1 已设置、L2 布局参与、L3 行为正确。
3. 检查错序、丢项、非预期遮挡、传播不符、装饰脱锚，必要时回退该区域。
4. 与 DOM 结论冲突时只记 `external-conflict` 和对应 reference。

**通过 / 输出**

- 通过时写 `verified_for=output-contract`、`source_behavior=inferred`。
- 保留“父 flow＋子固定”时披露限制。

**不得宣称**

- 不证明原站响应式规则；不以 Auto Layout 数量或一次渲染成功评优；不用 DOM 覆盖截图证据。

### R3-EXP-11 四项验收样例集与评分校准

**状态：`completed-for-current-scope`（2026-10-18，不是 `verified`）**

已完成 24 个合成基础样例（标定集 12 + 验收集 12）× 6 个变体，共 144 张截图。样例覆盖中文、英文、混排、图标/logo、复杂背景与长页，每类含清晰与困难输入；变体为 `baseline / typo / occlusion / synthetic_asset / no_propagation / structure_role`。标定集与验收集均为 288/288 四维状态匹配、目标维度命中 60/60、跨维误报 0/180、baseline 假报警 0/12。`typo` 只在 visual 产生 `fail`；`occlusion` 只在 visual 产生 `partial`，被遮挡正文对象的内容/断行/字形为 `unknown`；`synthetic_asset` 只在 asset 产生 `fail`，视觉仍 `pass`；`no_propagation` 只在 edit 产生 `fail`；`structure_role` 只在 structure 产生 `fail`。冻结阈值为 `content_object_exact_min=0.98`、`content_character_exact_min=0.999`、`linebreak_match_min=1.0`、`glyph_local_mae_max=4.0`、`pixel_card_mae_max=0.1`、`geometry_min_iou_min=0.999`、`structure_role_accuracy_min=0.98`、`structure_parent_accuracy_min=0.999`、`structure_boundary_min_iou_min=0.999`、`edit_native_text_ratio_min=1.0`、`edit_propagation_error_px_max=16.0`、`asset_layer_isolation_min=0.5`、`asset_corner_unchanged_min=0.5`、`change_region_ratio_min=0.02`。其中 `linebreak / pixel / geometry / parent / boundary / native` 没有对应故障变体，只能写干净噪声上界或合同值，不能称为已标定判别阈值。详见 `R3_EXP_11_ACCEPTANCE_CALIBRATION.md` 与 `output/_r3_experiments/exp11_acceptance_calibration.json`。

**边界**

- 所有夹具是实验者编写的合成页面；候选是“基准 + 单缺陷”的差分，不是独立重建或真实站点。
- 内容 exact 使用 DOM 文本回读，不是 OCR；结构树来自夹具 DOM，不是截图自动推断；编辑探针是 DOM 文本与 CSS 传播，不是 Figma 写入。
- 资产替换用隐藏 DOM 图片层的探针测量；合成图是基准 tile 的烘焙截图，视觉相同由构造保证。
- 维度级 `unknown` 未触发；`partial` 只在 visual 出现（有效区域 89.99%–95.82%，未知区域 4.18%–10.01%）；长页只探测目标段，编辑只覆盖 12/20 段；每样例只测一个 tile 槽。
- 比例为 0.98 / 0.999 的阈值在更大页面规模下可能失去单字符敏感性；当前只覆盖 4–20 个文本对象、113–638 个字符。

**目的**

- 建立视觉、结构、编辑、资产的独立标定集与验收集。
- 验证报告能把错误定位到对应维度。

**步骤**

1. 覆盖中文、英文、混排、图标与 logo、复杂背景、长页；每类含清晰与困难输入。
2. 同一样例分别引入一个错字、一处遮挡、一张不可替换合成图、一个不传播高度的容器。
3. 检查报告是否在对应维度给出 `pass / partial / fail / unknown`。
4. 记录指标、单位、阈值来源、覆盖、未测项和评分分母。
5. 另建独立验收集，不用标定集自证。

**通过 / 输出**

- 四项分别有结论；`partial` 附有效/不可用区域、缺口、影响、不可做编辑和人工复核项。

**不得宣称**

- 单一像素分数不代替四项；`unknown` 不自动当作可接受误差；部分成功不掩盖核心目标失败。

### R3-EXP-12 多状态参考冲突与权威版本

**状态：`completed-for-current-scope`（2026-10-18，不是 `verified`）**

已完成 11 个参考、6 个状态签名、7 个 scope-state 组、4 个拼接场景与 8 个参考比较对。同态重复的像素 MAE 为 0、最小几何 IoU 为 1.0；轮播帧、滚动、缩放、遮挡和过渡均建立独立状态，异态不进入几何误差（0；避免 2 个 naive 假差异）。同态全重叠拼接为 `composite-verified`；缺口、混合帧和 v1/v2 混拼均为 `composite-unknown`。v2 显式 `supersedes` v1，v1/repeat 进入 historical，v3 保持未决；外部 A/B 为 `external-conflict`，winner 为 null。16/16 合同检查通过；`composite-conflict` 分支未实例化。详见 `R3_EXP_12_REFERENCE_STATES.md` 与 `output/_r3_experiments/exp12_reference_states.json`。

**边界**

- 单合成页面、单浏览器、DPR 1；轮播过渡是 authored CSS 状态，外部 A/B 是模拟导入，tile 来自两次同态重复捕获。
- 几何来自 authored DOM；没有真实站点、真实轮播时序、真实外部信任链、截图自动状态识别或 Figma 写入。
- 状态签名是精确匹配；近同态、设备旋转、分数 DPR、动画中间帧与时钟/广告变化未测。
- `composite-conflict`、同态重叠像素冲突与生产权限链未验证；`external-conflict` 只验证清单与解析器层面。

**目的**

- 验证轮播帧、不同缩放、不同滚动状态和拼接图的 reference/state 管理。
- 防止把多时刻素材拼成同一状态事实。

**步骤**

1. 为每个状态建立独立 `reference_id` 与 `state`。
2. 记录内容 hash、原像素尺寸、缩放/裁切/变换、滚动、时间、轮播帧和遮挡。
3. 检查同态多图能否验证重叠与覆盖，不同状态是否被误算作几何误差。
4. 新截图建立新 reference，明确权威版本与旧版本关系。
5. 检查 `composite-unknown` 与 `external-conflict` 是否按预期报告。

**通过 / 输出**

- 每个 reference 的范围、状态和不可宣称项明确。
- 冲突停在未决项，不被静默覆盖。

**不得宣称**

- 不拼出一个“原来就如此”的共同真值；不从图片宽度反推 CSS 视口或 DPR。

## 3.1 补充边界实验（2026-10-18）

### R3-EXP-13 跨渲染器文本度量与基线

**状态：`completed-for-current-scope`**

12 个用例在 Chromium 151.0.7922.34 与 WebKit 26.5、DPR 1/2 下共 72 次测量。同浏览器重复读取为 0 差异，DPR 1/2 的 CSS 度量一致，换行数差 0/12，基线 P50 为 0、最大 0.5px，8/8 合同检查。Firefox 已安装但本机启动失败（`spawn UNKNOWN`），因此不能宣称三渲染器覆盖；macOS/iOS/Android 字体栈、可变字体与嵌入 webfont 仍未覆盖。

证据：`R3_EXP_13_CROSS_RENDERER_TEXT.md`、`output/_r3_supplements/r3_exp13_cross_renderer_text.json`、`r3_exp13_captures/`、`r3_exp13_contact.png`。

### R3-EXP-14 静态截图基线估计

**状态：`completed-for-current-scope`**

在已知字体文件与字号时，从截图像素与字体度量估计 alphabetic baseline；7 用例 × 2 字号 × DPR 2/3 共 28 次测量，最大误差 0.5px、平均 0.018px，6/6 检查。含 descender 的拉丁文本与 CJK 必须使用字体 ascent/descent；未知字体、替换字体或未知字号仍为 `not-evaluated`。

证据：`R3_EXP_14_STATIC_BASELINE.md`、`output/_r3_supplements/r3_exp14_static_baseline.json`、`r3_exp14_captures/`、`r3_exp14_contact.png`。

### R3-EXP-15 失败 SVG 的离线栅格回退

**状态：`completed-for-current-scope`**

四个直接导入失败的 SVG 特性（drop-shadow、filter 链、`foreignObject`、`pattern`）经 Chromium 渲染并打包为 PNG/JPEG；4/4 生成平铺回退，PNG 与参考逐像素 MAE 为 0，JPEG q90 最大 MAE 1.121845，9/9 合同检查。executor 是本地 mock，没有真实 Figma 导入、插件运行时或设计文件回读；平铺栅格不能声称原始矢量或原生可编辑。

证据：`R3_EXP_15_RASTER_FALLBACK.md`、`output/_r3_supplements/r3_exp15_raster_fallback.json`、`r3_exp15_artifacts/`、`r3_exp15_contact.png`。

## 4. 执行顺序建议

1. `R3-EXP-01` 至 `R3-EXP-07` 均已完成当前范围；grid 的嵌套、HUG+FILL 与自动/混合轨道另列补充实验（见 R3-EXP-02「延后补充项」，不阻塞主线）。
2. `R3-EXP-13/14/15` 已补跨渲染器、静态基线与离线栅格回退的当前范围；仍欠：真实 Figma 导入/回读、显式 drop-shadow/filter 链重建、`R3-EXP-04` 的真实数据重标、`R3-EXP-05` 的真实站点/跨浏览器扩展、Firefox 与跨平台字体栈。
3. `R3-EXP-09` 已完成当前范围：资产来源、替换能力、同源关系、共享 vs 独立成本与矩形碰撞均已测；`R2-EXP-02` 已并入。`R3-EXP-10` 已完成当前范围：7 个输出合同场景的扰动、回退与 DOM 冲突隔离均已记录；`R2-EXP-01` 已完成 authored DOM 扰动，原站 DOM 与原站响应式仍未验收。`R3-EXP-11` 已完成四项验收样例集与评分校准当前范围：24 个合成样例 × 6 变体，标定/验证各 288/288，目标 60/60，跨维误报 0/180；维度级 `unknown`、真实站点/OCR、Figma 写入与更大页面规模仍未覆盖。`R3-EXP-12` 已完成多状态参考冲突与权威版本当前范围：11 参考、6 状态签名、4 拼接场景、16/16 检查；真实轮播时序、真实外部来源、同态重叠冲突、截图自动状态识别仍未覆盖。`R3-EXP-13–15` 已完成补充边界当前范围。R3 两条轨均已完成当前范围；R4 已完成 `R4-EXP-01–10` 当前范围。

## 5. 进入 R4 的门槛

- DOM 与截图两轨的 reference、资产、状态和结构清单仍保持来源隔离。
- `R3-EXP-01`、`R3-EXP-05`、`R3-EXP-10`、`R3-EXP-11`、`R3-EXP-12` 已完成当前范围并有可复核记录；真实站点、真实轮播/外部来源、同态重叠冲突与人工复核项仍未覆盖，才讨论融合。
- R4 必须由用户明确同意后另立问题与计划；本文件不自动开启 R4。
