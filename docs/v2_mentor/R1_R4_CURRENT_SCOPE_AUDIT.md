# R1–R4 当前范围审计（2026-10-18）

> 目的：确认 R1–R4 的每个实验是否都达到 `completed-for-current-scope`，并明确哪些结论仍被外部环境边界阻塞。
> 结论：R1–R4 共 29 个实验记录全部达到 `completed-for-current-scope`；没有任何实验被提升为 `verified`。
> 边界：本审计只检查实验产物、状态、检查项、envelope 元数据与内容哈希；不重跑实验，不连接 Figma，不修改源页面或生产实现。

## 1. 状态定义

| 状态 | 含义 |
|---|---|
| `completed-for-current-scope` | 在文档写明的受控夹具、环境与检查项内已完成；结论可复现，但不能外推到未覆盖环境 |
| `verified` | 只在有足够外部真值、真实环境与独立复核时使用；本轮没有任何实验使用该状态 |
| `not-evaluated` / `unknown` | 没有测量或证据不足；不得填 0、不得默认通过 |
| 外部边界 | 真实站点、真实 Figma、真实登录会话、Firefox、生产 bridge 等未覆盖项；不阻塞当前范围，但不能被隐去 |

## 2. 总览

| 轮次 | 实验数 | `completed-for-current-scope` | 仍缺当前范围项 | 说明 |
|---|---:|---:|---:|---|
| R1 | 2 | 2 | 0 | 离线 true-flow 写计划 + URL 三态回归 |
| R2 | 1 | 1 | 0 | 五个 authored DOM 容器的 flow 扰动 |
| R3 | 15 | 15 | 0 | EXP-01–12 主实验 + EXP-13–15 补充边界 |
| R4 | 11 | 11 | 0 | EXP-01–10 + 元数据补齐 |

审计口径：每份主产物都必须有 `status=completed-for-current-scope`、`boundary`、`limitations` 与可按 canonical JSON 复算的 `content_hash`。R3 的 EXP-01–12 由 `r3_metadata_supplement.py` 补齐 envelope；R4 的 EXP-01–09 由 `r4_metadata_supplement.py` 补齐。

## 3. R1

| ID | 范围 | 检查 | `content_hash` 前缀 | 剩余外部边界 |
|---|---|---:|---|---|
| R1-EXP-01 | 离线 true-flow 写计划、容器职责与失败判据 | 47/47 | `4dbeaa2ecfc96123` | 原站 DOM、真实 Figma Auto Layout、生产写入 |
| R1-EXP-02 | `content / soft_block / hard_login` 三态分类、截图保留、soft-block 降级、hard-login 终止 | 10/10 | `05886a53523da35f` | 真实登录墙、CAPTCHA 供应商、反爬变体、真实凭据 |

## 4. R2

| ID | 范围 | 检查 | `content_hash` 前缀 | 剩余外部边界 |
|---|---|---:|---|---|
| R2-EXP-01 | 五个 authored DOM 容器、24 个内容/尺寸变体、faithful/adaptive 分歧 | 42/42 | `7368c7034ca7d2e4` | 原站 DOM、原站响应式、Figma Auto Layout 实际参与 |

R2 的五个容器仍是 `candidate`。authored DOM 的 flow 行为通过，不等于原站容器或 Figma 输出已 `verified`。

## 5. R3

| ID | 范围 | 关键检查 | `content_hash` 前缀 | 剩余外部边界 |
|---|---|---|---|---|
| R3-EXP-01 | 在线目录 `1:101` 的 21 个槽位 | 21/21 槽位、3×7、稳定聚类 | `687ffb46766a7484` | 其他目录、整页、`dom_order` |
| R3-EXP-02 | grid/wrap 能力、跨度+`FILL`、对齐、`FLEX`、HUG、保存重开、修复 | 15/15 + 12/12 + 32/32 + 13/13 + 9/9 | `7003ad369fa174e5` | 嵌套 grid、HUG+FILL、自动/混合轨道、生产 bridge |
| R3-EXP-03 | SVG/滤镜/mask/混合效果矩阵 | 20/20 SVG + 12/12 原生 | `704dbd288d74d663` | 真实 Figma 端到端、显式 drop-shadow/filter 链重建 |
| R3-EXP-04 | 无稳定 ID 的身份匹配与阈值 | 14 场景 / 37 配对 / 0 错误 | `2b0af6823e57bbf0` | 真实页面阈值、通用权重、`deleted` 语义 |
| R3-EXP-05 | full-page 拼接与 sticky/fixed 同态 | 8 段、3 模式对比 | `608a9e92cb517c17` | 真实站点、跨浏览器扩展、真实懒加载 |
| R3-EXP-06 | `normal`、行盒、基线与混排 | 12 用例、3 次重复、DPR 1/2 | `dc5da5320e471e40` | Firefox、其他版本/平台、可变字体 |
| R3-EXP-07 | 截图分组与 lineage | 16 seed，5 `candidate` / 11 `ambiguous` / 0 错误 | `647ac8bceb1d1505` | 自动分割、真实站点、Figma API 写入 |
| R3-EXP-08 | OCR、低清、压缩与文本验收 | 702 条记录、双引擎 | `f5073a10de5c9fad` | 真实站点、旋转/竖排、跨 DPI、通用阈值 |
| R3-EXP-09 | 裁片来源、替换能力与共享图成本 | 9 资产、6 同源 TP、0 FP/FN | `f486b5d8cf45665e` | 通用分类器、原文件恢复、真实站点 |
| R3-EXP-10 | 截图 flow 扰动与 DOM 冲突隔离 | 7 场景、0 失败检查 | `2cc07d045a0b9c10` | 原站响应式、真实 DOM 顺序、生产 bridge |
| R3-EXP-11 | 四项验收样例与评分校准 | 标定/验证各 288/288 | `fe14029b5f8d1702` | 真实站点/OCR、Figma 写入、更大页面 |
| R3-EXP-12 | 多状态参考冲突与权威版本 | 16/16 | `7389f5e7d92f6246` | 真实轮播、真实外部来源、自动状态识别 |
| R3-EXP-13 | Chromium + WebKit 文本度量与基线 | 8/8、基线最大差 0.5px | `ea4630fb6b92d58b` | Firefox、macOS/iOS/Android、跨平台字体栈 |
| R3-EXP-14 | 已知字体/字号下的静态基线估计 | 6/6、28 次测量 | `8974e1ab4bd213df` | 未知字体/字号、跨平台、通用阈值 |
| R3-EXP-15 | 失败 SVG 的离线栅格回退 | 9/9、PNG 无损 | `494926e54881ce5f` | 真实 Figma 导入/回读、插件运行时、其他 filter |

R3-EXP-13 的 Firefox 启动错误是 `spawn UNKNOWN`；因此不得写“三渲染器已验证”。R3-EXP-15 的 executor 是本地 mock，不得写“raster-fallback 已在 Figma 端到端验证”。

R3-EXP-01–12 的 envelope 由 `R3-METADATA-SUPPLEMENT` 补齐：8/8 检查、幂等复跑 `changed=0`、`content_hash=f0935e5f83c7351f...`。该补充只增加 `status / boundary / limitations / content_hash` 元数据，不升级任何结论。

## 6. R4

| ID | 范围 | 检查 | `content_hash` 前缀 | 剩余外部边界 |
|---|---|---:|---|---|
| R4-EXP-01 | 逐字段融合合同与来源审计 | 14/14 | `f139baf670c06caf` | 生产融合 API/IR、真实站点、Figma 写入 |
| R4-EXP-02 | 真实 OCR/CV 候选与 `screenshot-candidate` | 13/13 | `d8860d607c75c19e` | 端到端检测、真实站点/跨 DPR、生产 IR |
| R4-EXP-03 | 滚动/懒加载/动画相位的状态门 | 18/18 | `31eebbcebc2f5345` | 通用状态识别、轮播/视频、真实站点 |
| R4-EXP-04 | 只读、版本化的 provenance IR | 22/22 | `93b2047b74e2234c` | 生产 IR/持久化、外部真值、Figma 写入 |
| R4-EXP-05 | 跨 DPR/缩放/字体 bbox 容差 | 22/22 | `0f44b4251466b864` | 真实站点、跨浏览器、OCR/CV 检测框 |
| R4-EXP-06 | 无稳定身份的一对一配对 | 26/26 | `6b2f91fe3805ed78` | 真实站点、跨语言、无限滚动、生产匹配 API |
| R4-EXP-07 | 资产来源解析与降级链 | 39/39 | `711a5277e1ac672a` | 真实站点/CDN、鉴权/CSP、AVIF/HEIC |
| R4-EXP-08 | 多页面、多轮更新的权威链 | 35/35 | `5a776bbcf2bccd5c` | 真实 CMS、权限、并发与乱序更新 |
| R4-EXP-09 | 混合来源字段的 Figma 写入合同 | 38/38 | `f8b19768e1e53dc5` | 真实 Figma 连接与回读、事务、真实资产管线 |
| R4-EXP-10 | 九阶段离线集成与 envelope 审计 | 13/13、227/227 阶段检查 | `9e171aa32e29b421` | 运行时数据依赖、生产 envelope、并发 fuzz |
| R4-METADATA-SUPPLEMENT | R4 envelope 元数据幂等补齐 | 7/7、`changed=0` | `1e2e17549cf51ef3` | 无（元数据范围）；不升级任何结论 |

R4-EXP-10 当前 `bundle_hash=486a200d057dbb5d5f4acfaeb2931a6aa8463fa4fbf167f0452f906ab9a54dbb`；9/9 显式哈希、9/9 boundary、9/9 limitations、`envelope_gaps={}`。`sequence_semantics=ordered-audit-only`，不是运行时依赖。

### 6.1 真实 Figma 冒烟（2026-10-18 / 2026-10-19）

当前范围之外新增了四步真实环境冒烟，用来降低 `R4-EXP-09` 的最大外部边界：

- **Smoke A（写入 + 导出）**：34 元素夹具在真实 Figma 写入画板 `1:2` 并导出 PNG；全图差异 `22.323/255` 集中在参考图有、DesignSpec 没有的查询区渐变带，排除该带后均值 `0.923/255`。
- **Smoke B（写入 + 回读）**：frame/text/rectangle/image 四类节点真实写入，`get_node_tree` 回读 12/12，导出 PNG 4772 字节；`content_hash=322023b5af9ce673...`。
- **Smoke C（合同命令重放）**：把 `R4-EXP-09` 实际发出的 1 条画板命令 + 8 条写入命令重放到真实 Figma，回读 16/16：命令 ID、子节点顺序、延迟节点缺席、字体、资产哈希、文本/颜色/几何与 PNG 导出均通过；导出 13604 字节，`content_hash=186af6e44a5eecbc...`。
- **Smoke D（Auto Layout / 字体 / 遮挡）**：真实 Figma 中验证纵向 HUG 列与横向 `layoutGrow` 行的流式重排、严格字体探针与严格 `create_text` 缺族失败关闭（页面子节点数 4→4）、子节点顺序形成的部分遮挡，以及 `clipsContent=true/false` 的导出差异（240×160 对 280×160）；26/26 检查通过，`content_hash=fa904922230649a5...`。默认 `create_text` 缺族仍静默回退到 `Inter / Regular`，已记为高风险差异。

四者都不是生产写入路径。Smoke C 只重放已发出的 8 条命令，不重算 19 个字段决策；Smoke D 的 Auto Layout 走独立实验动作 `set_layout_flow`，不代表生产 `set_autolayout`。它们仍不覆盖 19 个字段决策、权威链、组件、效果、并发、事务或回滚。详见 `R4_SMOKE_B_READBACK.md`、`R4_SMOKE_C_WRITE_CONTRACT.md` 与 `R4_SMOKE_D_AUTOLAYOUT_FONT_OCCLUSION.md`。

## 7. 统一 envelope

| 轮次 | `status` | `boundary` | `limitations` | 显式 `content_hash` | 补齐方式 |
|---|---|---|---|---|---|
| R1 | 2/2 | 2/2 | 2/2 | 2/2 | 实验写盘自带 |
| R2 | 1/1 | 1/1 | 1/1 | 1/1 | 实验写盘自带 |
| R3 | 15/15 | 15/15 | 15/15 | 15/15 | EXP-01–12 由 `r3_metadata_supplement.py` 补齐；EXP-13–15 自带 |
| R4 | 11/11 | 11/11 | 11/11 | 11/11 | EXP-01–09 由 `r4_metadata_supplement.py` 补齐；EXP-10 自带 |

元数据补齐只增加 envelope 字段，不改实验证据、检查项或 summary。补齐后的哈希是当前 JSON 的内容证明，不是原始实验写盘时间的 attestation；R4-EXP-10 的集成审计也只按当前内容复算。

## 8. 仍未完成的外部边界

以下项目不属于当前范围，不能因为 R1–R4 全部 `completed-for-current-scope` 就写成已验证：

- 原站 DOM、原站响应式、真实站点状态识别与真实站点配对准确率。
- 真实 Figma 连接与基础写入/回读已由 Smoke A/B/C 覆盖到单文档、单次运行范围；Smoke D 另行覆盖了实验性 Auto Layout、严格字体失败和部分遮挡/裁剪。生产 `set_autolayout`、组件、effects、字体缺失后的交付策略、事务/回滚、并发与跨版本仍未覆盖。
- 真实登录会话、生产登录墙、CAPTCHA 供应商、反爬变体与权限链。
- Firefox、Safari、iOS、Android、Linux 字体栈与跨平台字形阈值。
- 真实轮播时序、视频、无限滚动、真实 CDN/CMS、AVIF/HEIC、真实 OCR 版本矩阵。
- 生产 `src/` 接入、持久化、并发事务、生产 fuzz 与生产 bridge。
- 未知字体/字号的静态基线、旋转/竖排文本、跨 DPI、人工复核完成度。

## 9. 复算方法

内容哈希口径：

```python
payload = {k: v for k, v in document.items() if k != "content_hash"}
canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

复跑元数据补齐：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r3_supplements/r3_metadata_supplement.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_metadata_supplement.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_end_to_end_integration.py
```

预期：R3 与 R4 元数据脚本第二次运行均为 `changed=0`；R4-EXP-10 为 227/227 阶段检查、13/13 集成检查、9/9 变异拦截。

## 10. 不得宣称

- 不得把 `completed-for-current-scope` 写成 `verified`。
- 不得把受控夹具结果外推为原站、真实 Figma、生产 bridge 或跨平台结论。
- 不得把 R3-EXP-13 写成 Firefox 或三渲染器覆盖。
- 不得把 R3-EXP-15 写成真实 Figma raster-fallback 端到端验证。
- 不得把 R4-EXP-10 的 227/227 写成生产链路成功率或真实 Figma 写入成功率。
- 不得把元数据补齐的哈希写成原始实验写盘时的 attestation。
