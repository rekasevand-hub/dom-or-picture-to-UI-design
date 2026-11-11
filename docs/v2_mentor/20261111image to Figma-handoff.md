# Image → Figma · 交接文档（2026-11-11）

**日期：** 2026-11-11（承接 11-10 快进合并 `02f2ffc` 之后的工作）
**性质：** 当日工作交接（目标 / 完成 / 文件 / 修改明细 / 测试 / 遗留 / 下一步 / 禁改项）
**前置文档：**
- `20261110image to Figma-handoff.md`（Phase 1 字重 / 字号口径 / light-table 换代）
- `IMPLEMENTATION_ROADMAP_2026-11-08.md`（路线图）
- `20261110_font_weight_evidence.md`（字重/字号的否定性证据）

**当日提交（8 笔，工作区干净）：**

| 提交 | 内容 |
|---|---|
| `f6018a5` | chore(repo): 忽略 `.workbuddy/` 工作区状态 |
| `d013761` | fix(perception): OCR 合并保留"同串不同字阶"（`模型广场` 召回） |
| `77f4179` | feat(calibration): 五条结构规则（导航字重 / 重复 owner / 表格字号 / 同槽冲突 / 冻结仲裁） |
| `18f1fb8` | feat(scripts): 三个审计工具（重叠 / VLM 观感 / 冲突仲裁） |
| `04b7ad0` | test(fixtures): dark 参考图换 Kimi K3 版 + truth 更正 + 基线重登记 |
| `42af2d2` | test(fixtures): 金稿重新导出，对齐 `11 月 11 日更新` |
| `432841b` | feat(calibration): 文本碎片图丢弃 + 选中态底色合成 |
| `afcb736` | test(fixtures): dark 基线按新规则重登记 |

**运行环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`
**Bridge：** `python -m src.app.services.bridge_server`（ws://localhost:8765）。**交付时已关闭**（`OnwuSn` 已 kill，8765 无监听，TCP 探活超时）。下次写 Figma 前需重新启动并**在 Figma 里重载插件**。

---

## 0. 本轮速览（要只读一段就读这里）

本轮的转折点是：**像素指标全绿，但肉眼可见的缺陷一堆**。所以这一天的产出分两半——一半是把"指标看不见的东西"变成可测量（三个审计工具 + VLM 观感报告），另一半是修其中确定性的那部分。

| # | 事情 | 结果 |
|---|---|---|
| 1 | 导航字重（结构规则） | dark `style_mm` **21 → 15/39**（6 条导航全中；剩 2 条是副价格，拒绝 2 样本拟合） |
| 2 | `模型广场` 召回 | 根因是 OCR 合并"同串即重复"，已修；新全量 run 里恢复 |
| 3 | 三条结构清理 | 重复 owner / 表格字号 48.5→21（16 处）/ 同槽冲突（丢 1 记 6） |
| 4 | 冻结仲裁落地 | 4 条唯一标签**按金稿归位**（不删），light-table 门禁仍 PASS |
| 5 | 观感验收 | 三族 VLM 报告；用户复核 5 个 reject，VLM 全中（5/5），多报 1 minor |
| 6 | 参考图换代 | dark 换 Kimi K3 版（同 2544×1336），truth sha/日期更正；金稿重新导出对齐 |
| 7 | 图压字 + banner | 丢 8 张文字碎片图；合成选中态胶囊；**banner 坏像素 6.52% → 3.34%**（阈值 5%），chrome gate `fail → pass` |

三族终态（`--rerun --policy 2.1`，全 PASS）：

| 族 | within30 | ink_ratio | style_mm | dy_med | critical | nodes / bitmap |
|---|---|---|---|---|---|---|
| dark-card-grid | 94.84% | 0.931 (n=40) | 20/41 | 4.5 | **27/27** | 68 / 5 |
| light-form | 92.19%（rerun 92.16） | 1.000 (n=74) | 16/75 | 1.0 | 24/24 | 149（rerun 145）/ 32（rerun 28） |
| light-table | 95.00%（rerun 95.17） | 1.000 (n=100/101) | 14/105 | 5.9（rerun 5.8） | **30/30** | 166（rerun 165）/ 12 |

> 括号里是 rerun 的实测值，与基线有差是因为 light-form / light-table 的基线还没按新规则重登记，见 §6.6。

> **方法层还留了一道口子（本轮最后才发现）**：`d013761` 那条 OCR 合并判据是**代码级的同一性判定**，VLM 裁定覆盖不到它（它发生在候选生成之前），而它的记录又只留了 `{"text", "reason"}`、不带证据 → 不可复核。也就是说"代码当尺子"这一侧还没有接受和 VLM 决策同等的证据要求。见 §6.12 / §7.2 / §8.15–17。**本次只记录，未改代码。**

---

## 1. 本次任务的目标

用户指令依次为：「合并」→「`.workbuddy/` 加忽略 + 启动 bridge」→「改 dark 剩余 8 条 Medium 导航项」→「模型广场为什么没提」→「同串不同位/不同阶判不完，能不能全交给 VLM」→「不要像素 1:1，近似 + 不突兀就行」→「先修类 1、2、3」→「继续类 4 和 banner」→「提交、关 bridge、写交接」。

拆成五件事：

1. **Phase 1 字重收尾**：dark 剩余 8 条 Medium 失配，用结构信号（不是点名）压到 ≤13。
2. **召回缺口**：用户指出 `模型广场` 三处文档/指标都没提——查清是被丢了还是没采到。
3. **验收口径换轨**：从"像素 1:1"改成"近似 + 不突兀"，需要一套能判"突兀"的尺子。
4. **修确定性缺陷**：遮挡、槽位错配、占位符字号、图压字、banner 装饰缺失。
5. **基线与参考图治理**：参考图换代（Kimi K3）、金稿对齐、全量 run、基线重登记。

**贯穿的纪律：** 每个规则先取证再实现，实现后跑三族 `--rerun`，另两族必须"逐位不变"；改结构层（感知/发射）必须走全量 run，`--rerun` 看不到。

---

## 2. 已经完成的内容

### 2.1 导航字重：`nav-row-weight` ✅（部分达成）

用户给的判据是"同行 ≥3 个等距同字号短文本"。**取证发现"等距"不可测**：真实导航行的感知框间距是 `12 / 24 / 54 / 58 / 112 / 230 px` 混杂，因为 padding 主导且**选中项不作为标签发射**（`模型广场` 当时还没召回）。等距检验永远不会触发。

改落四条可测不变量：同一垂直带（中心 y 差 ≤ max(4px, 0.3×中位高)）、≥3 个成员且都是 ≤12 字短标签、共享字号（容差 25%，`Agent 优惠` 是 32.25 vs 众数 27.5）、落在画布顶部 10% 带内。

一个必须记住的细节：`community` 那类标签是 `role=control` 的按钮，如果按角色排除就会漏掉 `社区`。放行条件是 **`controlType == "navigation"`**，这是结构字段不是文本特判。

结果：dark `style_mm` **21 → 15/39**，6 条导航全部修正。剩下的 2 条是副价格 `¥2.00` / `¥8.00`，见 §6.8。

### 2.2 `模型广场` 召回：OCR 合并的同串判据 ✅

链路取证（用户点名后才查的）：

| 阶段 | 实例 | 结局 |
|---|---|---|
| 金稿 | 导航项 120×36 / hero 375×128 | 两个都在答案键里 |
| EasyOCR | 导航 `[561,35,130,42]` conf 0.963；hero `[90,251,395,120]` conf 0.878 | **两个都采到了** |
| `merge_ocr_candidates` | 导航项被标 `already-covered` 丢弃 | 只剩 hero |

根因在 `image_contract.py`：`normalized == current["normalized"]` **没有几何条件**，文本相同就跳过，不管隔了 200px、字阶差 2.9 倍。

为什么两个指标都没报警：`critical` 只问"这段文本出现过吗"，hero 已经满足；`style_mm` 按"文本 + 最近位置"配对，金稿导航 `模型广场`(Bold) 被配到流水线 hero（display 规则已提成 Bold）→ **假 match**。

修法（窄口径）：`_same_text_same_element` 三个结构判据依次为——中心距 ≤0.75×小框宽、覆盖 ≥0.5、高度比 <1.5（命中任一即判"同一元素"）。表格里 `(选填)`×8、`石敏妤`×2（同字阶）继续抑制；同串不同字阶才算新元素。粗暴去掉文本判据那次让 light-table 多出 **23 个重复标签**，已记进 docstring。

**边界（重要，容易被误读成"VLM 裁定"）：** 这条判的是**同一性**——两条 OCR 观测是不是同一处；不是**留用/舍弃**——这块该不该留。它发生在候选生成之前：`模型广场` 的导航项在函数返回 True 时**已经不存在**，`conflict_adjudicator` 没有对象可裁。所以它不在"VLM 取代代码卡控"的范围内，属于分工里"代码当尺子"的那一侧。

**但它现在的记录不合格**：丢弃时只写 `{"text": text, "reason": "already-covered"}`，没有两个 bbox、没有触发的是哪一支、没有中心距/覆盖/字阶比 → **不可复核、不可回放**。这与它最初静默吞掉 `模型广场` 是同一种毛病，也与"VLM 决策必须引用证据"的准入标准双标。见 §6.12 与 §7.2。

### 2.3 三条结构清理 ✅

- **`duplicate-owner`**：框装不下自己一半的字 + 同串（模糊 ≥0.85）在别处有装得下的 owner → 判为错位副本。第一版直接硬丢，**门禁立刻 26/27**：那条 critical 的干净文本恰好在幽灵框上。改成"丢框、把干净文本写给幸存者"（按 OCR 噪声字符数择优）后 27/27。
- **`table-cell-scale`**：表格自己声明字号。light-table 16 个单元格是 48.5pt，旁边中位数 21——是输入框高度灌进字号，**不是框太窄**（这一点我一开始判错了，扩框无效）。夹紧后 16 处全部归位。
- **`same-slot-conflict`**：一个框里两个不同字符串，只自动处理可证的一种（短串 + ≤2 个非 CJK 字符，如 `Q搜索` = 放大镜图标被读成 `Q` + `搜索`）。其余 6 对**记账不猜**：`confidence` 全是 0.85 默认值，多数框两边都装得下，没有几何证据。

### 2.4 冻结仲裁：`conflict_adjudicator` + `adjudicated-conflict` ✅

读未决账本 → 参考/渲染同框裁片 → VLM 判"该留谁" → 与几何投票交叉 → **只有证据一致且动作是 drop 才自动应用**。

实测 6 对：**0 条自动 drop**。这不是失败——它证明这 6 对确实是"几何判不了"的，而且 VLM 自己出现过一次自相矛盾（keep=both 又说 drop），正好说明双证据闸门是必要的。

按用户决定改成 **move**：唯一标签绝不删（删了 critical 从 30 掉到 26，内容也没了），改为按金稿坐标归位。light-table 实跑 4 条：

| 标签 | 原位 → 归位 |
|---|---|
| 工时管理 | (35,134) → (77.6,290) |
| 个人信息 | (495,350) → (113,368) |
| 展开查询 | (2171,423) → (2351,204) |
| 我的工时看板 | (494,605) → (113,599) |

决策冻结在 `output/_conflict_decisions/<family>.json`（**不能放 run 目录内**，门禁重建 run 时会清掉，踩过一次）。

### 2.5 观感验收三件套 ✅（advisory，不改退出码）

- **`overlap_audit.py`**：零 token 几何扫描，读**回读快照**而不是校准前的 design（这点踩过一次，读错源会一直报旧数据）。三族现状：dark 10（text/text 5、image/text 5）、light-form 1、light-table 6。
- **`vlm_aesthetic_report.py`**：同区域参考/渲染裁片 → 按硬线/软线 rubric 判 accept/minor/reject；决策按 `(模型, prompt 哈希, 两裁片哈希)` 缓存，**重跑免费、可回放**。区域取"设计 ∪ 金稿"——只按设计切，**没画出来的东西永远进不了审计视野**（`Kimi K3` 就是因此漏掉的）；宽行按 1000px 切窗。
- **`conflict_adjudicator.py`**：见 §2.4。

**一致率标定（关键数据）**：用户复核 dark 的 7 个区域，先判"全 accept"后修正为 band00/01/03/04/06 reject。按"minor 也算不合格"口径，**用户 5 个 reject，VLM 全中（5/5），只多报 1 个 minor** → 精确 5/6 ≈ 83%，仍低于 85% 进环门槛。结论：**检测力够，severity 语义偏严**；报告已加 `non_accept` 口径。

顺带修正一个旧数据：handoff 里写"VLM 真实请求 90 秒"，小裁片实测 **1.4–11 秒/次**。

### 2.6 参考图换代 + 金稿对齐 + 基线重登记 ✅

- 用户提供 Kimi K3 版截图（同 2544×1336）替换 dark 参考图；旧图备份 `output/_fixtures_backup/reference_url_variant_20261110.png`；`truth.image_sha256` 更新并写 `corrections[]`。
- 换图后 acceptance **critical 26/27**：新图写 `11 月 11 日更新`，truth 还是 8 日 → 修 truth + `corrections[]`，`--reuse-prepared` 重算后 27/27。
- 用户手动改的是 **Figma 里的金稿框**，本地 `gold_tree.json` 仍是 8 日（mtime 未变）。用 `export_gold_tree.py --node 35:2909` 重新导出：**全量差异只有那条日期串 + 该文本节点及两级父框 width +18px**（多一个字），其余 0 变化。
- 换入前跑 `audit_gold_tree.py --gold`：51/51 落墨迹、文本一致度 85.1%（4 处已知改写）、verdict `usable`。
- 重登记后：配对 39→40、dy 6.0→4.5、ink 0.938→0.944。

### 2.7 图压字 + banner ✅（角标一类除外，见 §6.2）

**`fragment-image`**：根因不是"图压在字上"，是**图片本身就是文字碎片**——裁剪框把邻近字形一起裁进来，文字又单独发射，叠成重影。判据：图比该文字窄、右缘落在文字跨度内、重叠 ≥30% 较小框、同行（高比 0.5–1.6）。角标/按钮底色比标签**宽**，不触发。

dark 丢 4 张（`Qwen3.8 Flash` / `Kimii` / `DeepSeek` / `Seedance`），light-form 丢 4 张（`执行成功` 从"勾行成功"变干净），light-table 0 张。代价：这些裁剪里同时含 logo 图标，**图标没了、文字干净了**（同一裁剪内无法把"图标"和"三个字母"分开）。

**`selection-plate`**：选中态底色不是 asset（9 个里没有）。从源图采样合成：窗口内去掉页面底色 → 单一颜色占 ≥45% 且出现在标签左右两侧 → 取该色连通盒。dark 精确命中 `[544,23,712,87] / #CC291F`，另两族 0 命中。

| 指标 | 修前 | 修后 |
|---|---|---|
| banner 坏像素 | 6.52% ❌ | **3.34% ✅** |
| page 坏像素 | 1.71% | 1.50% |
| chrome gate | fail | **pass** |
| within30 | 94.60 | **94.84** |

---

## 3. 已修改的文件

**修改（M，10 个）：**
- `.gitignore`
- `src/app/services/structure/fidelity/calibration_strategies.py`
- `src/app/services/structure/fidelity/text_calibration.py`
- `src/app/services/structure/image_contract.py`
- `tests/fixtures/benchmark_families/dark-card-grid/family.json`
- `tests/fixtures/benchmark_families/dark-card-grid/gold_tree.json`
- `tests/fixtures/benchmark_families/dark-card-grid/reference.png`
- `tests/fixtures/benchmark_families/dark-card-grid/truth.json`
- `tests/v2/test_grounding_text_calibration.py`
- `tests/v2/test_image_contract.py`

**新增（A，9 个）：**
- `scripts/conflict_adjudicator.py`
- `scripts/overlap_audit.py`
- `scripts/vlm_aesthetic_report.py`
- `tests/v2/test_duplicate_owner.py`
- `tests/v2/test_fragment_image.py`
- `tests/v2/test_nav_row_weight.py`
- `tests/v2/test_same_slot_conflict.py`
- `tests/v2/test_selection_plate.py`
- `tests/v2/test_table_cell_scale.py`
- （本文档 `docs/v2_mentor/20261111image to Figma-handoff.md` 随后单独提交）

**不入库（按设计）：** `.env`（含 `VISION_API_KEY`，本次从 `656141e2` 复制）、`output/`（run 产物）、`.workbuddy/`（工作区记忆）。

---

## 4. 每个文件修改了什么

### 核心代码

| 文件 | 修改内容 |
|---|---|
| `text_calibration.py` | ① 新增 `apply_nav_row_weight`：顶部 10% 带内、≥3 个 ≤12 字短标签、共享字号（容差 25%）→ Medium(500)；只提升 400；排除 table-cell/table-header/control，**但放行 `controlType == "navigation"`**（否则漏 `社区`）。② 新增 `drop_implausible_duplicate_owners`：框宽 < 文本估算 1/2 且同串（≥0.85）在别处有装得下的 owner → 丢框，**并把更干净的文本写给幸存者**（噪声字符计数判优）。③ 新增 `clamp_table_cell_font_outliers`：`table-cell` 字号中位数 1.6× 以外夹紧到中位数。④ 新增 `resolve_same_slot_conflicts`：只自动丢"短串 + ≤2 非 CJK 字符"的 OCR 粘连，其余写 `unresolved` 账本。⑤ 新增 `apply_adjudicated_conflicts`：读冻结决策，`apply` 删、`move` 按 `move_to` 改 x/y（唯一标签只 move 不删）。⑥ 新增 `drop_text_fragment_images`：图比标签窄 + 右缘在标签跨度内 + 重叠 ≥30% + 同高比 0.5–1.6 → 丢图。⑦ 新增 `synthesize_selection_plate`：header band 内从源图采底色 → 合成 `rectangle`（`paintDepth = 0`，插在标签之前）。⑧ 新增 `_box_of` 辅助。⑨ `calibrate_low_contrast_placeholder_from_render` **显式排除 table-cell / table-header**（其 `15.25/700` 兜底会把 16 个占位符刷成 Bold）。 |
| `calibration_strategies.py` | `font-initial` 组依次插入 `fragment-image` → `selection-plate` → `duplicate-owner` → `adjudicated-conflict` → `same-slot-conflict` → `table-cell-scale` →（原有 display-weight / nav-row-weight / control-fonts …）。全部 `always=True`，不增加渲染次数；决策文件按 `<repo>/output/_conflict_decisions/<family>.json` 查找（run 目录会被门禁重建清空）。 |
| `image_contract.py` | 新增 `_same_text_same_element`：覆盖 ≥0.5 或高度比 <1.5 才算"同一元素"；`merge_ocr_candidates` 的原"文本相同即已覆盖"改用它。修 `模型广场` 导航项被 hero 标题"顺带覆盖"的丢失。 |
| `dark-card-grid/reference.png` | 换成 Kimi K3 版（同 2544×1336，303586 → 227724 bytes）。旧图备份 `output/_fixtures_backup/reference_url_variant_20261110.png`。 |
| `dark-card-grid/truth.json` | `image_sha256` → `38175f80…`；`critical_texts` 的 `11 月 8 日更新` → `11 月 11 日更新`；`corrections[]` 补两条（换图理由 + 日期）。 |
| `dark-card-grid/gold_tree.json` | 从 Figma 节点 `35:2909` 重新导出（133 节点 / 51 TEXT / 深度 8）。差异只有日期串 + 该文本节点与两级父框 width +18px。 |
| `dark-card-grid/family.json` | `pipeline_run` → `_image_figma_acctoken_20261111_plate`；`baselines` 全部重登记（94.84 / 0.931(40) / 4.5 / 27-27 / 68 nodes / 5 bitmap）；`history[]` 记两条（换参考图、加碎片图与胶囊规则）。 |
| `.gitignore` | 新增 `.workbuddy/`（本地记忆与会话状态，永不提交）。 |

### 新增工具

| 文件 | 作用 |
|---|---|
| `overlap_audit.py` | 零 token 几何审计，读**回读快照**：文本↔文本重叠、小图压字、文本宽于自身框。输出 high 项用于排序修复优先级。 |
| `vlm_aesthetic_report.py` | 参考/渲染同区域裁片 → 硬线/软线 rubric → accept/minor/reject；决策缓存可回放；区域取"设计 ∪ 金稿"（否则漏"没画出来的东西"），宽行 1000px 切窗。 |
| `conflict_adjudicator.py` | 未决同槽冲突 → 裁片 → VLM 判归属 → 几何投票交叉；唯一标签只给 `move_to`（金稿坐标），拒绝删除；分歧一律 `needs-human`。 |

### 新增测试（共 37 例）

| 文件 | 例数 | 覆盖 |
|---|---|---|
| `test_nav_row_weight.py` | 8 | 几何全部取自真实 dark 设计；导航行识别、control/navigation 放行、搜索占位符排除、幂等 |
| `test_duplicate_owner.py` | 6 | 幽灵框丢弃 + 文本合并到幸存者、合法重复（框够宽）不动、输入不被改写 |
| `test_table_cell_scale.py` | 6 | 中位数计算、1.6× 边界、非 table-cell 不动 |
| `test_same_slot_conflict.py` | 5 | 只丢 OCR 粘连（`Q搜索`）、真冲突记账不丢 |
| `test_fragment_image.py` | 7 | 四种真实几何 + 全幅图/价格不误伤 + 输入不变 |
| `test_selection_plate.py` | 5 | 合成胶囊、纯背景不触发、band 外不触发、已有形状覆盖时跳过、缺图不致命 |
| `test_image_contract.py`（改） | +3 | 同串不同字阶保留、同字阶仍抑制、同位置抖动仍抑制 |
| `test_grounding_text_calibration.py`（改） | +1 | 低对比策略不再作用于 table-cell |

---

## 5. 已运行的测试及结果

**单元测试**（omni python + `-p no:cacheprovider --basetemp=output/_pytest_tmp/...`）：

| 范围 | 结果 |
|---|---|
| 全量 `tests/v2`（提交前，两次） | **1431 passed / 8 failed**，两次失败集合相同 |
| 校准链相关 13 个文件（含 6 个新测试） | **149 passed** |
| `test_fragment_image` + `test_selection_plate` | 12 passed |
| `ruff check`（全部改动文件） | All checks passed |

**8 个失败全部是既有问题**（与本轮无交集）：4 个 `test_axure_holdout_*_manifest`（缺冻结输入 `DQ-R01:dom_path`）、4 个 `test_p5_*_probe`（环境态不符）。已用另一个 worktree 的同一基础提交 `02f2ffc` 复跑，同样失败。

> 踩坑记录：直接跑 pytest 退出码可能是 1，但测试全过——原因是 pytest 退出时清理历史临时目录触发环境的批量删除护栏（`SAFE_DELETE_BULK_GUARD_ERROR`）。加 `--basetemp=output/_pytest_tmp/<name>` 可得干净退出码。

**端到端 / 门禁：**

| 实验 | 结果 |
|---|---|
| 三族 `--rerun`（nav-row-weight） | PASS；dark style 21→15，另两族不变 |
| 三族 `--rerun`（duplicate-owner 硬丢版） | dark **26/27**（掉 critical）→ 改合并文本 → 27/27 |
| 三族 `--rerun`（table-cell-scale） | light-table style 14→30/105（被低对比策略刷 Bold）→ 排除后回到 14/105 |
| 三族 `--rerun`（same-slot-conflict） | PASS；light-table nodes 166→165、overlaps 10→9 |
| light-table `--rerun`（4 条归位决策） | PASS；within30 95.27→95.17、critical 30/30 |
| dark 全量 run（Kimi K3 新图） | within30 94.82、critical 27/27（修 truth 日期后） |
| 三族 `--rerun`（fragment-image） | PASS；dark overlaps 19→14→10、light-form 5→1 |
| dark `--rerun`（selection-plate） | PASS；banner 6.52→3.34、chrome gate pass、within30 94.60→94.84 |
| dark 全量 run `_image_figma_acctoken_20261111_plate` | within30 94.84、ink 0.931(40)、style 20/41、critical **27/27**、68 nodes / 5 bitmap、`acceptance.status = blocked-fail`（仅 native text gate） |
| `--register`（dark） | 基线写入：94.8406 / 0.931(n=40) / 4.5 / 27-27 / 68 / 5 |

**审计与勘察（只读）：**

| 工具 | 结论 |
|---|---|
| `overlap_audit`（三族） | dark 10（t/t 5、i/t 5）、light-form 1、light-table 6；修前分别是 19 / 5 / 10 |
| `vlm_aesthetic_report`（三族，各 12–16 区域） | light-form 8 accept / 1 minor / 0 reject；dark 1/4/2；light-table 7/1/4；每区域 1.4–11s，命中缓存 1.5–2s |
| 用户复核（dark 7 区域） | 5 个 reject，VLM 全中（5/5），多报 1 个 minor → 精确率 83% |
| `audit_gold_tree --gold`（新 dark 金稿） | 51/51 落墨迹 = 100%，文本一致度 85.1%，verdict `usable` |
| `check_benchmark_families --rerun` 复跑一致性 | light-table / light-form 复跑与上一次逐位一致（同一份 pipeline 确定性） |

---

## 6. 当前仍存在的问题

1. **native text gate 三族都未达标**（政策要求 100%）：dark 新 run 是 30 个 owner 过 1 个，`acceptance.status = blocked-fail` 的唯一阻塞项。这是老墙，`within30` / `critical` / 结构 / 保真 / chrome 全部 pass。
2. **角标类重影未修**：`6.6折` / `8.5折` 的裁剪图**自带角标文字**，再叠渲染文字 → 2px 级错位重影。裁剪比标签宽，`fragment-image` 不触发。两条路待选：**A** 丢裁剪保留文字（丢红框，与 logo 处理一致）；**B** 把裁剪换成合成圆角描边（保边框，丢渐变/内阴影）。
3. **`控制台` 不是被图压，是反色**：button `fillColor=#eff5e8 / textColor=#1a1917`（浅底深字），参考图是深底白字。属跨族默认调色板问题，需要在控件层按源图采样配色（新能力，未做）。
4. **ACCTOKEN 红色方形 logo 标缺失**：9 个 asset 里没有它，**asset 检测从未采到**，属检测层缺口（不是校准层能补的）。
5. **卡片内价格压标题**：`¥4.64` / `¥8.00` 落在 `DeepSeek V4.1 Flash` 文本框内（text-over-text），属 `conflict_adjudicator` 的未决清单，需要"价格应该在哪个槽位"的语义裁决。
6. **light-form / light-table 基线未按新规则重登记**：基线仍是旧全量 run（149 nodes / 32 bitmap、166 / 12），而 rerun 现在是 145 / 28、165 / 12。差值来自 `fragment-image`（-4 图）与 `same-slot-conflict`（-1 节点）。门禁仍 PASS（within30 未退化），但基线与实际行为已不一致，**需要各跑一次全量 run 再 `--register`**。
7. **dark `style_mm` 20/41**（昨天 15/39）：换成新参考图 + 新金稿后分母变大（+2），且 `ACCTOKEN` 字标被 `nav-row-weight` 提成 Medium 而金稿是 Bold（无结构信号可区分品牌字标与菜单标签）。属"指标变诚实"，不是回归。
8. **副价格 `¥2.00` / `¥8.00` 缺规则**：同卡片内尺寸 ≤0.6× 主价格 → Medium。设计里这两个元素**没有任何语义字段**，只能靠"¥ 开头"或相对字号，样本只有 2 条。仓库纪律反对 2 样本拟合（`≥2×body→Black` 就是这么被否的），**等第三个族的证据再做**。
9. **VLM 裁判仍是 advisory**：一致率 83% < 85% 门槛；rubric 偏严（minor ≈ 用户的 reject）。要进环先做 rubric 收紧 + 再标定。
10. **输出仍是扁平 1 层**（金稿 5–8 层）：Phase 5 结构发射完全未做。
11. **`--rerun` 对结构层仍是盲区**：`fragment-image` / OCR 合并 / 金稿换代都必须走全量 run 才能验证。
12. **OCR 合并决策不可复核（新暴露，未修）**：`merge_ocr_candidates` 丢弃重复观测时只记 `{"text", "reason": "already-covered"}`（`image_contract.py:529`），**没有两个 bbox、没有触发分支、没有中心距/覆盖/字阶比**。后果有三：
    - 无法判断某次合并是"同一处抖动"还是"同串两处被误吞"——`模型广场` 当初就是这样消失的，而报告里看不出任何异常；
    - 无法回答"这条规则准不准"，只能靠出事再回查；
    - 与 VLM 侧的标准双标：那边要求每条决策引用证据 id + 裁片 hash，这边只留一个字符串。
    注意这条**不能靠删除规则解决**：实测放开文本判据会让 light-table 多出 23 个重复标签。要的是"补证据 + 可复核"，不是"去规则"。

---

## 7. 下一步应该从哪里继续

**优先级从高到低：**

1. **角标重影（§6.2）**——只差用户一个 A/B 选择，选完当天可落地。若选 B，实现"裁剪 → 合成圆角描边"（采样边框色、圆角半径、内部填充），并加单测锁住"不得把渐变/阴影裁掉一半"。
2. **OCR 合并的证据化 + 复核队列（§6.12）**——改动面小，不动判定逻辑：
   - `image_contract.py` 的 `skipped` 每条补 `dropped_bbox` / `covered_by: {element_id, bbox}` / `center_distance` / `coverage` / `height_ratio` / `branch: center|coverage|scale`，落进 `ocr_supplement.json`；
   - `conflict_adjudicator.py` 增加 `merge-review` 分支：把每条合并决策连同两侧裁片送 VLM，问"这是一处还是两处"，**只允许否决（unmerge），不允许新增**；
   - 先在三族上量 veto 率：≈0 → 规则被验证；>0 → 看是哪一支（多半是 `scale`）误合并，再定向收紧。
   - 不做的事：不让 VLM 直接决定"要不要合并"。那会让每轮结果漂移，也绕开了唯一性的确定性底线。
3. **重新登记 light-form / light-table 基线（§6.6）**——各跑一次全量 run（bridge 需重启、插件需重载），然后 `--register`。否则下次 rerun 的"逐位一致"判断会失真。
4. **反色问题（§6.3）**——`控制台` 只是最明显的一例。做法：控件层按源图采样 `fillColor` / `textColor` / `borderColor`，与现有 `style_resolver` 的默认调色板做"源图优先"仲裁。这块会同时改善 light-form 的深色按钮。
5. **logo 标缺失（§6.4）**——检测层补"小尺寸高饱和块"类，或用 `selection-plate` 的连通盒思路反向生成 asset 候选。注意：不能把文字碎片一起采进来（§2.7 的教训）。
6. **价格槽位（§6.5 / §6.8）**——先把 `conflict_adjudicator` 的账本跑全三族，看是否出现第三族的价格/标签冲突；有证据再写规则。
7. **Phase 5 结构发射**——可编辑性主菜，改动面大，建议单独立项（对标金稿 5–8 层）。
8. **native text gate**——独立立项。现状 1/30，需要 baseline 证据链（`baseline: unknown` 是所有 owner 的现状）。

**开工前必读：**
- 改字重/字号 → `20261110_font_weight_evidence.md`
- 改感知层（OCR / 资产）→ 只能全量 run 验证，`--rerun` 看不到
- 换金稿 → 先跑 `scripts/audit_gold_tree.py`（验收线 80% / 80%）
- 跑门禁 → `check_benchmark_families.py --rerun --policy 2.1`，跑前把 `output/_benchmark_families/rerun/<family>` 挪走（否则自清理触发批量删除护栏）
- 写 Figma → 先启动 bridge（**当前已关闭**），并在 Figma 里重载插件（长会话后回调表会失效，重启 bridge 无效）
- 看"突兀"问题 → `scripts/overlap_audit.py` + `scripts/vlm_aesthetic_report.py`，两者都不阻塞流水线

---

## 8. 哪些内容禁止再次修改

**延续 11-09 / 11-10 的全部禁改项**（truth/黄金稿语义、Policy 2.0、已回退的 style_resolver 与 `calibrate_text_weight_from_render` 路线、baseline 语义、fail-closed 纪律、`visible_full_screenshot_underlay: blocked`、门禁度量口径、dark truth 勘误既成事实、`_anchor_table_columns` 方差守卫、split 节点双写、审计的包含剩余检查先于 `suppression_allowed`、`family.json` 的 history 链、ink-convergence 的死区 `[0.85,1.175]` 与钳位 `[0.7,1.5]`、`font_ratio` 只作诊断），另加本轮新增：

1. **不要**用"等距"判导航条。实测间距 `12/24/54/58/112/230 px`，padding 主导且选中项不作为标签发射，等距检验永不触发。判据是"同带 + 数量 + 短标签 + 共享字号 + 顶部 band"。
2. **不要**把 `controlType == "navigation"` 的控件排除出导航行。`社区` 是 `role=control` 的按钮，排除就会漏一个菜单项。
3. **不要**把 `duplicate-owner` 改回"硬丢"。硬丢会让 dark critical 27→26，因为干净文本恰好在被丢的框上。必须"丢框 + 把干净文本写给幸存者"。
4. **不要**让低对比占位符策略（`15.25 / 700` 兜底）作用于 `table-cell` / `table-header`。一次就把 16 个占位符刷成 Bold，light-table style 14→30/105。
5. **不要**用"扩框"解决表格里的大字号。`请输入0~` 的框本身够宽（0 溢出），真因是 `fontSize=48.5` 从输入框高度灌进来。
6. **不要**放宽 `fragment-image` 的判据（尤其"图比标签窄"和"右缘在标签跨度内"两条）。放宽会把角标/按钮底色（比标签宽）一起丢掉。
7. **不要**把 `selection-plate` 从 header band 扩到整页。它靠"单一颜色占窗口 45% 且出现在标签两侧"识别，扩到整页会把卡片背景误判成胶囊。
8. **不要**在没有第三个族证据时写"副价格 → Medium"规则。样本只有 2 条，且元素没有任何语义字段；`≥2×body→Black` 的 2 样本拟合就是这么被否的。
9. **不要**让仲裁器删除唯一标签。删了内容消失且 critical 掉 3 条；唯一标签只允许 `move_to` 金稿坐标。
10. **不要**把仲裁决策文件放进 run 目录。门禁重建 run 时会清空，必须放 `output/_conflict_decisions/<family>.json`。
11. **不要**把 `vlm_aesthetic_report` 直接接成门禁。一致率 83% < 85%，且它对 severity 偏严（把用户接受的近似判成 reject）。先收紧 rubric 再谈。
12. **不要**只按设计切审计区域。没画出来的元素在设计中不存在，只按设计切就永远审不到（`Kimi K3` 漏检的原因）；区域必须是"设计 ∪ 金稿"，宽行要切窗。
13. **不要**再让 `overlap_audit` 读 `pipeline/12_design.json`。那是校准前的设计，修完还在报旧数据；必须读回读快照 `figma_ink_converged/readback.json`。
14. **不要**用"看起来像误报"否定 VLM 的观察。`社区被遮挡`、`Qwen→Qween` 两条我判成误报，几何一查全是真的（输入框 58px 装 243px 文字；logo 图与标题重叠 40%）。先查几何，再判真假。
15. **不要**删掉 `_same_text_same_element`（或把它的文本判据整个放开）。实测 light-table 会多出 23 个重复标签。它是**同一性判据**，不是内容留舍判定；"VLM 取代代码卡控"指的是"两个候选谁占这个槽位"，不包括"这两条观测是不是同一处"。
16. **不要**让 VLM 直接决定"要不要合并 OCR 观测"。它可以否决（unmerge），不能新增；合并的**默认结果必须由确定性判据给出**，否则同一份截图每轮会产出不同的元素集合，`--rerun` 与基线全部失效。
17. **不要**只给合并决策留 `{"text", "reason"}` 这种记录。凡是没有两个 bbox、没有触发分支、没有度量值的决策，都等于不可复核——这正是 `模型广场` 消失时报告看不出异常的原因。补记录不改变行为，优先级高于任何新规则。

---

## 9. 角标重影（§6.2）：方案 B 已落地（2026-11-11 下午）

用户选 **B**：裁剪换合成圆角描边（保边框，丢渐变/内阴影）。

### 9.1 根因比 §6.2 的写法更具体

裁剪框 `153x43`，真正的描边 `105x44`——**横向 overshoot 48px、纵向 undershoot 1px**（角标正好贴在截图底边，被裁掉）。两个方向同时错，所以两边规则都不认它：

- `fragment-image` 要求"图比标签窄"，这里图比标签宽 → 不触发；
- 裁剪把**字形烤进图里**，标签又原生发射一次 → 2px 级错位的双层字形。

### 9.2 判据：两条像素证据必须同时成立

不是几何，是像素：

1. 一个强调色画出**细闭合描边**——标签左侧有竖条、右侧有竖条、上方有横条，三者同色；
2. **同一强调色出现在标签框内部**（字形被烤进去了）。

实测 `label_ink_share` = 0.285 / 0.287（阈值 0.03），描边厚 3px，闭合。四条边界情况因此各归其位：

| 样本 | 结局 | 原因记录 |
|---|---|---|
| `8.5折` / `6.6折` | ✅ 替换 | — |
| `控制台`（dark，浅底深字按钮） | 跳过 | `crop is not wider than the label`（55 vs 55） |
| `hamburger`（light-table，图标） | 跳过 | `no bar left of the label` |
| light-form 的 1744x448 容器 | 静默略过 | 面积比 > 3，属粗筛不算判断（否则一条 20 行噪声） |

**每个拒绝都带原因**，写在 `font_calibration.json` 的 `badge-outline` 报告里，不需要重跑就能回答"这块为什么没动"。

### 9.3 几何恢复的两个反直觉点

- **上边界不能量在左竖条那一列。** 那列在圆角里，起点比真实上边低一个半径：实测 1298 vs 真值 1292，44px 高的角标少 6px。改量中间列（直边区）。
- **下边界不能用"标签框下方扫描"。** 截图把角标裁在页面底边，中间列最低的一次命中是字形不是边框（1331 vs 页面底 1336）。改成取两列最远延伸：截断的角标和完整的角标都对。
- 圆角量的是"直边区起点"，AA 让它偏 1–2px（测得 9，真值约 7）。不影响观感，但别把它的绝对值当答案。

### 9.4 交付形态

两个 image **原地替换**为 `rectangle`——保留 `id`、绘制顺序、`paintDepth = 0`，元素数不变（61 → 61）：

```
x=1103 y=1292 w=105 h=44
fillColor #1A1917  borderColor #F05943  borderWidth 3  borderRadius 9
```

Figma 侧 `strokeAlign = INSIDE`（bridge 已设），所以外框 105x44 与源图逐边对齐。

### 9.5 门禁（`--rerun --policy 2.1`，三族 PASS）

| 族 | within30 | ink_ratio | style_mm | dy | critical | nodes / bitmap |
|---|---|---|---|---|---|---|
| dark | 94.84 → **94.79** | 0.931 → **0.900**(n=40) | 20/41 | 4.5 | 27/27 | 68 / **5→3** |
| light-form | 92.16 → 92.16 | 1.000 (74) | 16/75 | 1.0 | 24/24 | 145 / 28 |
| light-table | 95.17 → 95.17 | 1.000 (101) | 14/105 | 5.8 | 30/30 | 165 / 12 |

另两族**逐位不变**，证明策略在它们上面是 no-op。`bitmap 5→3` 是两处角标从 image 变成 rectangle，门禁只向上卡这个数，故不构成回归。

### 9.6 三个必须知道的副作用

1. **`ink_ratio` 下降是"指标变诚实"，不是字号回退。** 逐对核过：`8.5折` / `6.6折` 两个金稿框的比值从 **1.000** 变成 **0.889**（渲染墨高 18→16 vs 源图 18）。之前的 1.000 是**裁片里的字形在冒充"渲染墨迹"**——去掉裁片后，原生文字比参考细 11% 这件事才第一次被测出来。`within10` 因此从 0.55 掉到 0.50，正好是这两对出带。
2. **基线没有重注册，是故意的。** 现状 0.900 落在旧基线允许带 `0.881–1.119` 内；若按 0.900 重注册，允许带会变成 `0.850–1.150`，**方向是假通过**（详见 `20261110_font_weight_evidence.md` §5.4 同一机制），把未来真实退化放过去。
3. **`8.5折` / `6.6折` 现在是"细字 + 干净描边"，参考图是"粗字 + 干净描边"。** 这份字重/字号失配是既有的（`style_mm 20/41` 里有它们），裁片一直盖着它。同一位置的字号是 `23.75`（= 0.86× body 27.5），结构上不够展示级，`display-weight` 的 1.8× 阈值合理不触发；要修得走"字标/角标"的独立证据，不是调阈值。
4. **底边框会多画一条。** 角标被截图裁在页面底边，发出去的矩形仍会在最后 3 行画出真图没有的描边（每处 105x3px）。矩形不能只有三条边，这是方案 B 的固有代价，也是 within30 -0.05pp 的主要来源。

### 9.7 本轮新增禁改项

1. **不要**把 `badge-outline` 的"图比标签宽"放开。那是它与 `fragment-image` 的分界线：窄图由 `fragment-image` 整块丢弃，宽图由这条规则换成描边。两条同时放宽会让一块角标被处理两次。
2. **不要**给 `badge-outline` 加"实心药丸"分支。没有证据（三族 0 例），而 2 样本拟合在本仓库已被否过两次。它现在会以 `interior is filled with the accent colour` 或 `accent area too thick to be an outline` 记录后跳过。
3. **不要**把 `ring_fill_ratio` 改回阈值判据。它把"描边有多细"和"里面装了多字"混在一个数里（合成样本 0.353，真样本 0.21），分不开描边和实心；分离实心的是"内部填充是否等于强调色"这一条精确判据。
4. **不要**用左竖条那一列量上边界，也不要用"标签框下方"找下边框——实测分别少 6px、找不到。
5. **不要**把 `badge-outline` 的成功判据写成只留 `{"text", "reason"}`。它现在记 `bbox / crop_bbox / stroke / radius / 两个颜色 / ring_fill_ratio / label_ink_share`，这是 §8.17 那条纪律的第一次正面执行。

---

## 10. 旋转取证：链路里完全没有这个字段（2026-11-11 下午）

**背景**：`5.8折` / `8.8折` 是 tilt 过的大号折扣，参考图里明显倾斜，而设计元素是横排的（`fontSize 86.5`）。查证结果比"漏了个角度"严重：**设计层、Figma 桥（`code.js`）、SVG 适配器都没有任何 rotation 字段**。倾斜角标之所以还看得过去，全靠位图把倾斜带进来。

只读取证脚本：`scripts/p1_text_rotation_evidence.py` → `output/_p1_text_rotation_evidence/evidence.json`
度量函数：`measure_element_rotation`（`text_calibration.py`）

### 10.1 真值从哪来（金稿没有 rotation 字段）

`export_gold_tree.py` 不导出 `rotation`，三族 TEXT 节点里 0 条。但 Figma 同时给了两样东西——节点**自身尺寸**和**轴对齐外接框**——对倾斜 `t` 有：

```
box_w = w·cos t + h·sin t
box_h = w·sin t + h·cos t
```

所以这对观测本身就是一个角度预言机。三族扫完：**只有 dark 的 4 个节点不一致，全部 6.00°（残差 0.00）**：

| 节点 | 自身尺寸 | 外接框 | 反解角度 |
|---|---|---|---|
| `5.8` | 95×70 | 101.8×79.5 | 6.00° |
| `折` | 30×34 | 33.4×36.9 | 6.00° |
| `8.8` | 95×70 | 101.8×79.5 | 6.00° |
| `折` | 30×34 | 33.4×36.9 | 6.00° |

light-form / light-table 各 0 个。**注意这个预言机只能给 `|t|`**（cos 是偶函数），方向必须从像素来——这正是下面估计器要解决的。

### 10.2 估计器：投影方差去斜，`minAreaRect` 不行

**先否证两条捷径**（都实测过）：

- `cv2.minAreaRect` 对 `5.8折` 给 **0.0°**（真值 6.0°）。原因：该元素跨**两条**倾斜文本行，两条平行斜线的并集接近方形，最小外接矩形锁到了轴对齐外壳上。
- 二阶矩同病：这个长宽比下，行间离散度压过行内离散度。

**可行做法**：把墨迹掩膜按候选角度旋转，取行投影方差最大的角度（文字基线一旦水平，行投影最尖）。返回的是"纠正角"，取反得到倾斜角。

**合成数据精度**（−8°…+8° 三根横条）：**误差 0.00°**，死区外一次不落。

**三族 218 条实测**：

| 族 | 可测文本 | 检出（≥2.5°） | 直立文本 raw 最大 |
|---|---|---|---|
| dark-card-grid | 48 | `5.8折` +6.75°、`8.8折` +6.00° | 2.0° |
| light-form | 61 | 0 | 0.0° |
| light-table | 109 | 0 | 1.25° |

**零误报**，且两个真值误差 +0.75° / 0.00°。死区 2.5° 就是噪声底（直立文本靠抗锯齿也能到 1–2°），不是调出来的数。

**符号约定**：正角 = **逆时针**，与 Figma `rotation` 同向，接线时不用再翻符号（合成数据用例 `test_sign_convention_is_counter_clockwise` 锁住）。

### 10.3 关键结论：`5.8折` 不是"只差旋转"

金稿是**两个**节点（`5.8` 95×70 与 `折` 30×34，都 6°），设计里被 VLM 合成**一个** `5.8折`（109×105，`fontSize 86.5` —— 从倾斜外接框 105px 高反推出来的）。所以：

- 只接旋转 → 把"一个横排大字"转成"一个倾斜大字"，仍是错的（参考是两行），双发也还在；
- 要真正修好这一族，**行切分（2 行）+ 旋转 + 字号**三样必须一起做。

这也解释了为什么它现在是页面上最丑的地方：位图带着倾斜的 `5.8`/`折`，上面再压一个横排 86.5px 的 `5.8折`，框内墨量是参考的 **2.2 倍**。

### 10.4 接线计划（尚未做）

| 层 | 改动 | 注 |
|---|---|---|
| 设计 | 元素新增 `rotation`（度，逆时针正） | 附加字段，缺省不出现 |
| SVG 渲染 | `transform="rotate(deg cx cy)"` | 闭环要看得到倾斜结果 |
| Figma 桥 | `node.rotation = +deg`（不再取反） | 与 10.2 的符号约定一致 |
| 校准 | `text-rotation` 策略：`measure_element_rotation` ≥ 2.5° 才写 | 报告带 raw / gain / ink |

### 10.5 新增禁改项

1. **不要**用 `minAreaRect` 或二阶矩量文本倾斜。实测 `5.8折` 给 0.0°（真值 6.0°），因为跨行并集接近方形。
2. **不要**把 2.5° 死区调小。直立文本的 raw 角度靠抗锯齿就能到 2.0°（dark）/ 1.25°（light-table），调小就开始转直角文本。
3. **不要**用 `absolute` 外接框反解**方向**。cos 是偶函数，这对观测只能给 `|t|`；方向必须来自像素。
4. **不要**只接旋转就宣称修好 `5.8折`。它同时是"两行被合成一行"，见 §10.3。

---

## 11. 旋转接线（①a 完成）与一个埋了很久的坑

### 11.1 插件路径陷阱（本轮最重要的一条）

Figma 里那个 dev plugin **不是从任何 worktree 导入的**，而是
`D:/LLM-Data/Figma_auto_agent/figma_bridge/manifest.json` —— 同一分支的**另一份独立 checkout**，停在 `fe89f46`，它的 `code.js` 是 **11-08** 的版本。

后果：**在 worktree 里改 `code.js` 从来没有生效过**。前两次"已重载插件"只是让 11-08 的代码又跑了一遍，所有插件侧的改动都静默无效。

**怎么发现**：给回读摘要加了 `rotation`（`"rotation" in node` 对 TEXT/RECTANGLE 恒真），重跑后 148 个节点里 **0 个**带这个字段 → 跑的不是新代码。对比 6 个 worktree 的 `code.js`，全是 2891 行旧版。

**处置**：把本 worktree 的 `code.js` 复制到 D 盘那份（`git -C D:/LLM-Data/Figma_auto_agent status` 显示 ` M figma_bridge/code.js`，要还原直接 `git checkout --`）。复制后同一轮验证：**68/68 节点带 `rotation`**，两个角标分别是 6.75 / 6.0。

**禁改项**：以后改 `figma_bridge/` 下任何文件，**必须同步到 D 盘那份**再 Run 插件，否则等于没改。

### 11.2 接线本身

| 层 | 实现 |
|---|---|
| 设计 | 元素可选 `rotation`（度，**逆时针正**，与 Figma `rotation` 同向，不取反） |
| 校准 | `text-rotation` 策略（`apply_text_rotation`）→ `measure_element_rotation` ≥2.5° 才写，直立则清除旧值 |
| SVG | `_append` 套 `<g transform="rotate(deg cx cy)">`，中心 = **元素盒子中心**；裁边 `<g clip-path>` 包在旋转**外层** |
| Figma | `applyRotation()` → `node.rotation`，绕节点自身中心；`applyStyle` / `createText` / `createImage` 三处调用 |
| 回读 | 摘要新增 `rotation` 字段（诊断用；顺带让金稿预言机不必再靠尺寸反解） |

三族实测写入：dark 2 个（`5.8折` 6.75°、`8.8折` 6.00°），light-form 0，light-table 0。直立方一经测量即清除，二次执行 no-op。

### 11.3 门禁

| 族 | within30 | ink_ratio | style_mm | critical | nodes/bitmap |
|---|---|---|---|---|---|
| dark | 94.79（不变） | 0.900 (40) | 20/41 | 27/27 | 68 / 3 |
| light-form | 92.16（不变） | 1.000 (74) | 16/75 | 24/24 | 145 / 28 |
| light-table | 95.17（不变） | 1.000 (101) | 14/105 | 30/30 | 165 / 12 |

三族 PASS 且**逐位不变**；回读证明旋转真的落地。角标区像素失配 23.0% → 22.9%，等于没变——原因见 11.4。

### 11.4 ①b 为什么这轮没做（三个实测卡点）

1. **拆节点会掉 critical。** `_critical_matches` 是按**单个 TEXT 节点**做字符串包含；`5.8折` 拆成 `5.8` + `折` 后，27 条里直接掉 2 条。实测 `5.8\n折`（一个节点带换行）**仍然匹配** —— 所以可行路线是"一个节点 + 换行"，不是"两个节点"。
2. **倾斜让行切分失效。** `5.8折` 框内行剖面只有 **1 个连通带**：两条倾斜行的墨迹在 y 上重叠，找不到行间空隙。必须先用测得的角度去斜，才能分带。
3. **字号才是主误差，不是角度。** 声明 `fontSize 86.5`，而金稿是 `5.8`(95×70) + `折`(30×34) 两个节点、目测字高约 34。图上 `5.8` 整个溢出描边框——只把大字转 6.75°，等于把"横排大字"变成"斜排大字"。

所以 ①b 的真实工作量是：**去斜 → 分带 → 字符分配 → 盒子回映射 → 字号重定**，是一个独立小项目，本轮没有硬凑一个只对小角标有效、却可能把多行段落拆坏的规则。

---

## 12. ①b 第一步：块内分行可测（去斜之后）

**已完成**：`measure_text_block_lines`（`text_calibration.py`）+ `tests/v2/test_text_block_lines.py`（5 例）+ 取证脚本输出并入行信息。

### 12.1 为什么必须先去斜

倾斜块的**行间空隙在轴对齐坐标里不存在**：`5.8折` 的元素框内行剖面只有 **1 个连通带**（墨高 155 = 整个窗口），两条倾斜行的墨迹在 y 上互相盖住。任何"按行空隙切分"的规则在这个形状上都不会触发。

按测得角度去斜后（零填充扩画布，避免四角被裁），**2 条带**立刻出现：

| 样本 | 去斜后 | 金稿 |
|---|---|---|
| `5.8折` | 89×47 + 30×29（块 89×86） | `5.8` 62pt / 95×70，`折` 30pt / 30×34 |
| `8.8折` | 88×48 + 30×29（块 88×87） | 同上 |

直立文本不受影响：`8.5折`/`6.6折`/`模型广场` 全部 1 行。三族跑下来没有误切。

### 12.2 卡点：两行字号不同，而渲染端只有一种字号

金稿这两行**不是同一个字号**（62 与 30），所以"切行 + 一个 fontSize"复现不了：

- **Figma 端**支持：`createText` 的 `richRuns` 分支会 `setRangeFontSize`；
- **SVG 端不支持**：`_lines_text_element` 是"一个 `<text>` + 每行一个 `<tspan>`"，`font-size` 写在 `<text>` 上，整块共用。

这条不能凑：本地渲染（ink-convergence 的闭环量尺）用的是 SVG 端。如果只给 Figma 按行字号、SVG 仍按一个字号，闭环会拿一份**错的渲染**去拟合源图，越调越偏。

**退而求其次的方案也试算过**：只切行、字号取"两行等大且装得下框"（约 46pt）。框是装进去了，但两行一样大——参考里 `折` 只有 `5.8` 的一半高，观感明显不对。所以没走。

### 12.3 下一步（本项的剩余全部工作）

1. SVG `_lines_text_element`：允许每行带自己的 `font-size`，并按行字号重算各行基线（不同字号的 em 基线不同，不能共用 `dy`）；
2. Figma 侧同时写 `richRuns`（端点已存在，只差生成）；
3. 两端一致后再接 `lines` + 块框 + 每行字号，然后跑三族门禁。

在此之前，`measure_text_block_lines` 是**只读能力**：能回答"这块有几行、每行多大"，但还没有任何策略调用它。

---

## 13. 按行字号（①b 第二步）：两端都通了

**已完成**：`lineSizes`（与 `lines` 平行的一行一个字号）在 SVG 与 Figma 两端都生效，5 个单测（`tests/v2/test_line_font_sizes.py`）。

### 13.1 为什么不能共用一个字号

金稿这两行是 **62pt / 30pt**（`5.8` 与 `折`），比例 2.07。用一个字号时：
- 取大 → `折` 变成和 `5.8` 一样大，观感错；
- 取中（46pt）→ SVG 按 1.4em 排行距，两行 46pt = 128px，超过块高 86px，第二行直接掉出框（已渲图验证）。
- 且不同字号的 em 基线不在同一条线上，**不能共用 `dy`**。

### 13.2 两端实现

| 端 | 做法 |
|---|---|
| SVG | `_lines_text_element` 新增分支：`lineSizes` 存在时每个 `<tspan>` 带自己的 `font-size`，并按**自己的行框**（`size × 行框比`）累加游标算基线；行框比取自 `lineHeight / fontSize`，所以显式 `lineHeight` 仍然生效 |
| Figma | `figma_adapter.create_text` 由 `lines + lineSizes` 生成 `richRuns`（字符区间 = 该行在 `lines.join("\n")` 里的位置） |
| 桥 | `applyRichRuns` 抽成独立函数，并在**折行分支写入 `characters` 之后重放一次**——区间是对着字符算的，先设字符再设区间，否则区间落在旧串上 |

**字节兼容**：没有 `lineSizes` 时走原分支，`<tspan>` 不带 `font-size`，`<text>` 上仍是单一字号（`test_svg_without_line_sizes_keeps_the_old_shape` 锁住）。

### 13.3 本地验证（未接线）

把 `5.8折` 改成 `lines=["5.8","折"]`、`lineSizes=[62,30]`、`lineHeight=70`、块框 95×104，本地渲图对比：`5.8` 大、`折` 小、两行、基本装进描边框——与参考的字号关系一致。

**仍然乱的原因**：位图里那份 `5.8`/`折` 还在（描边框本身就是那张位图）。这是 ①b 的第 2 件事，见 §14 的计划。

### 13.4 尚未做

1. 把 `measure_text_block_lines` 的结果接成策略（写 `lines` / `lineSizes` / 块框）；
2. 消掉位图重复：`badge-outline` 现在要求标签完全落在裁剪框内，而这块的标签溢出 27px；放开判据并让它发出的矩形带上 `rotation`。

两件都做完才谈得上"对上参考"。在此之前新能力是**惰性**的：没有任何策略写 `lineSizes`。

---

## 14. 文本块重建已接线（①b 收口，门禁改善）

**门禁**（`--rerun --policy 2.1`，三族 PASS）：

| 族 | within30 | ink_ratio | style_mm | critical |
|---|---|---|---|---|
| dark | 94.79 → **95.06（+0.27）** | 0.900 (40) | 20/41 | 27/27 |
| light-form | 92.16（不变） | 1.000 (74) | 16/75 | 24/24 |
| light-table | 95.17（不变） | 1.000 (101) | 14/105 | 30/30 |

新增策略 `text-block-lines`（`restructure_tilted_text_block`），排在 `text-rotation` 之后：

- **只处理倾斜块**（|rotation| ≥ 2.5°）——段落是直立的，按墨带重写段落行结构属于猜；
- 去斜分带（§12）→ **切串** → 按带宽估字号 → 写 `lines` / `lineSizes` / `fontSize` / `lineHeight` / 块框；
- dark 结果：`5.8折` → `["5.8","折"]`、字号 **64 / 30**（金稿 62 / 30，误差 4%），切分误差 0.04。

### 14.1 切串判据：宽度占比是错的

第一版按"字符宽度占比 vs 带宽度占比"打分，best 误差 0.336，**两个块都被自己的闸门拒掉**。原因是两行字号不同，"占比较"本身不成立。

改成**两个独立观测必须自洽**：带的宽度 / 字宽模型 = 字号，该字号 × 该文字体的墨高比 = 预测墨高，和实测墨高比。
- 切在 `5.8` 后：预测 46.4 / 27.6 vs 实测 47 / 29 → 误差 4%；
- 切在 `5.` 后：预测 77 vs 47 → 差 20 倍，直接排除。

闸门：平均相对误差 > 0.15 就不切（宁可不动，也不改写可见字符串）。

### 14.2 位图那一半：试了，但撤回

同轮还试着让 `badge-outline` 接受"标签溢出裁剪框"（`5.8折` 溢出 27px），并给发出的矩形加旋转。结果**不成立**，已撤回：

- 倾斜角标的环量出来是**轴对齐外接框**（132×152，而真实约 109×105），反解自身尺寸后仍偏大；
- 更要命的是圆角：在倾斜形状的 AABB 上量"直边区起点"会读到 **61**（真实约 12），矩形被画成椭圆（已渲图确认）。

结论：**环的几何测量只对直立形状成立**。要在倾斜角标上也成立，得先把窗口按角度去斜再量（`measure_text_block_lines` 已经做了去斜，但环测量还没接这条路径）。在此之前 `badge-outline` 维持"标签必须完整落在裁剪框内"，大的两块继续保留位图。

**现状**：位图里的 `5.8`/`折` 还在，原生文字已按 62/30 两行叠上去——双层没消，但 2.2 倍的溢出墨量已经没了，这也是 within30 +0.27 的来源。
