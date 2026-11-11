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

修法（窄口径）：`_same_text_same_element` 用两条结构判据——覆盖 ≥0.5，或高度比 <1.5。表格里 `(选填)`×8、`石敏妤`×2（同字阶）继续抑制；同串不同字阶才算新元素。粗暴去掉文本判据那次让 light-table 多出 **23 个重复标签**，已记进 docstring。

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

---

## 7. 下一步应该从哪里继续

**优先级从高到低：**

1. **角标重影（§6.2）**——只差用户一个 A/B 选择，选完当天可落地。若选 B，实现"裁剪 → 合成圆角描边"（采样边框色、圆角半径、内部填充），并加单测锁住"不得把渐变/阴影裁掉一半"。
2. **重新登记 light-form / light-table 基线（§6.6）**——各跑一次全量 run（bridge 需重启、插件需重载），然后 `--register`。否则下次 rerun 的"逐位一致"判断会失真。
3. **反色问题（§6.3）**——`控制台` 只是最明显的一例。做法：控件层按源图采样 `fillColor` / `textColor` / `borderColor`，与现有 `style_resolver` 的默认调色板做"源图优先"仲裁。这块会同时改善 light-form 的深色按钮。
4. **logo 标缺失（§6.4）**——检测层补"小尺寸高饱和块"类，或用 `selection-plate` 的连通盒思路反向生成 asset 候选。注意：不能把文字碎片一起采进来（§2.7 的教训）。
5. **价格槽位（§6.5 / §6.8）**——先把 `conflict_adjudicator` 的账本跑全三族，看是否出现第三族的价格/标签冲突；有证据再写规则。
6. **Phase 5 结构发射**——可编辑性主菜，改动面大，建议单独立项（对标金稿 5–8 层）。
7. **native text gate**——独立立项。现状 1/30，需要 baseline 证据链（`baseline: unknown` 是所有 owner 的现状）。

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
