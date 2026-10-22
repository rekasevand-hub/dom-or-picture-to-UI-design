# R4 未决实验与准入清单

> 更新：2026-10-18  
> 当前范围：`R4-EXP-01` 已完成逐字段融合合同，`R4-EXP-02` 已完成真实 OCR/CV 候选接入，`R4-EXP-03` 已完成真实滚动/懒加载/动画相位的状态门，`R4-EXP-04` 已完成只读、版本化的字段级 provenance IR 回放，`R4-EXP-05` 已完成跨 DPR/缩放/字体的 bbox 容差标定，`R4-EXP-06` 已完成无稳定身份的一对一配对与歧义标定，`R4-EXP-07` 已完成资产来源解析与降级链，`R4-EXP-08` 已完成多页面/多轮更新的权威链，`R4-EXP-09` 已完成混合来源字段的离线 Figma 写入合同，`R4-EXP-10` 已完成九阶段产物级离线集成与 envelope 审计；以下项目的真实环境与生产实现部分**尚未验证**，不得写成生产结论。

## 已完成的合同结论

`R4-EXP-01` 只证明以下政策在 24 个合成用例上自洽：

1. 融合前先过 scope/state 门；异态、瞬态与遮挡不进入字段比较。
2. DOM 负责 `text / font / color / role / editability / asset_source`；截图负责 `visible_state / occlusion / z_order / rendered_effect`；`content_hash / pairing` 只做交叉核对。
3. bbox 只用绝对容差 `2.0 px`；超差返回 `external-conflict`，禁止平均。
4. 未决态保留双侧观测且 `winner=null`；决策审计 24/24。
5. 裁片只标 `flat-raster-crop`，不得宣称原始资产或原生可编辑。

`R4-EXP-02` 只证明以下候选门在 1 个合成页面、13 个识别用例上自洽：

1. 遮挡、单引擎、双引擎分歧、重复文本和几何未对齐都不得自动升级文本内容。
2. 只有双引擎 exact、最小置信度 ≥ 0.85 且跨引擎 bbox IoU ≥ 0.50 时，才允许提升 `text-content`。
3. `editability / role / asset_source` 永不随 OCR 或 CV 候选升级；CV 框只作 `visual-box-candidate`。
4. 2 个升级均为真值正确，升级精度 2/2；朴素最高置信度基线升级 8 例、误升级 2 例（O08、O10）。
5. 13/13 检查通过，重复过门哈希一致；`unknown` 分支未被真实触发。

`R4-EXP-03` 只证明以下状态门在 1 个合成页面、11 次捕获、55 个捕获对上自洽：

1. 状态门必须先于字段与像素比较；11 次捕获得到 7 个状态签名，55 对中只有 4 对同态重复可比较。
2. 4 对同态重复的状态哈希一致，字段差异 0，缩略图像素差 0；异态/瞬态对全部被阻断，假可比与假阻断均为 0。
3. 状态签名覆盖滚动位置、懒加载代次、文档高度、动画相位、pending 与滚动进行中标记；`S00 vs S03` 仅因 `animation-phase` 被阻断。
4. 懒加载真实提交三代内容，探针数 23 → 26 → 29 → 32，文档高度 3112 → 3032；这些变化属于状态迁移，不是内容缺陷。
5. pending 懒加载（`S04`，`pending=3`）与滚动中捕获（`S06`，滚动进行中、`stable=false`）相关 19 个唯一捕获对全部保持 transient（各 10 对，其中一对重叠）。
6. 若跳过状态门，51 个被阻断对会产生 2172 个朴素字段假差异；18/18 检查通过，门投影哈希一致。

`R4-EXP-04` 只证明以下只读回放合同在三个前序实验上自洽：

1. 24 个融合字段、13 个 OCR 用例、11 次捕获与 55 个状态对可回放为 34 个节点、77 个字段、181 条证据的版本化 IR；103 条来源决策全部一致。
2. 每个字段固定记录权威、状态、选中值（或显式 `null`）、选择来源、理由、provenance 与保留观测；冲突保留双侧观测且 winner 为 `null`，`unknown` 只保留 absent observation。
3. OCR 只提升 `text-content`；`editability / role / asset_source` 永不从截图候选升级；O06/O11 的晋升各由两条不同引擎的选中 provenance 支撑。
4. 只有 4 个同态重复状态对可比较且字段/像素差为 0；32 个异态对与 19 个瞬态对全部不携带 `field_result`。
5. 22/22 合同检查通过，11/11 非法变异被拒绝（删除 provenance、伪晋升、原生 editability、瞬态强制比较、冲突 winner、unknown 发明值、权威交换、悬空 state_ref、删除双侧观测、阻断对 field_result、非法版本）。
6. IR 为只读设计产物：`read_only=true`、`source_mutation=false`、`figma_write=false`；未接入 `src/` 或 `figma_bridge/`。

`R4-EXP-05` 只证明以下 bbox 量化误差在 1 个受控页面、4 个 DPR、5 个缩放和 4 组字体上成立：

1. 20 次真实 Chromium 截图产生 200 个 bbox 样本；`max(|Δleft|, |Δtop|, |Δright|, |Δbottom|) <= 2.0 CSS px` 为 200/200。
2. 160 个常规字体样本与 40 个小尺寸压力样本全部通过；P50 为 0.5000 px，P95 为 0.8333 px，P99 为 1.0375 px，最大为 1.1000 px。
3. 最大误差出现在 DPR 1.25 / zoom 1.0，而非 DPR 或 zoom 的边界；误差不随 DPR/缩放单调增长。
4. 8 px 微型徽标与 1.25 px 细线在本矩阵内也通过，最大分别为 0.8500 px 与 1.0375 px；该结果不能推广到任意极小字形或真实 CV 检测。
5. 对截图框做正向平移诊断：+2.5 px 及以上全部被拒绝；`2.0 px` 仍是有测量噪声的门限，不表示完整的 2 px 安全余量。
6. 22/22 完整性检查通过；截图 PNG 哈希、JSON round-trip 与写盘后 `content_hash` 均可复核。未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。

`R4-EXP-06` 只证明以下配对合同在 12 个受控场景、24 次捕获、109 个真实 DOM 观测上自洽：

1. 46 个预期配对全部以 `proposed-match` 输出；4 个旧项与 4 个新项保持 `ambiguous`，6 个采集范围外旧项为 `not-seen`，3 个新副本为 `unmatched-new`；错误配对、漏配与非预期歧义均为 0，26/26 检查通过。
2. 一对一分配，且完全相同副本的 `primary-content-tie` 先于位置、顺序、节点 ID 与 Hungarian 分配；节点 ID 不进入特征，随机替换节点 ID 后结果不变。
3. 局部采集只产生 `not-seen`，不产生 `deleted`；输出状态限定为 `proposed-match / ambiguous / not-seen` 与 `matched / ambiguous / unmatched-new`。
4. 节点 ID 基线产生 3 个错误配对、8 条错误记录；纯文本+图像基线 0 误配但漏配 5 个，说明上下文特征用于消除跨栏歧义，而不是替代内容判断。
5. `accept=0.20 / gap=0.04 / coverage>=0.30` 在 calibration 与 validation 两个分支均为 0 错误；零错误交集为 `accept 0.20–0.25 × gap 0.02–0.06`，仍只是本次数据上的弱标定。
6. 72 次输入顺序置换与随机节点 ID 替换均无结果变化；写盘后 `content_hash` 可复算。未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。

`R4-EXP-07` 只证明以下资产来源与降级链在 20 个受控用例上自洽：

1. 10 个 HTTP 原图全部通过状态、非空、MIME 嗅探、header/body 一致、解码与尺寸门；6 个光栅降级与 4 个原生/本地来源（内联 SVG、CSS 渐变、data、blob）均按预期分流，39/39 检查通过。
2. 404、超时、MIME 欺骗与截断分别保留 `http-404 / timeout / mime-body-mismatch / decode-failed`，并回退到真实元素截图；失败原因没有合并成单一下载失败。
3. `srcset` 与 CSS `image-set` 在 DPR 1 请求 `1x`、DPR 2 请求 `2x`，服务端计数与 `currentSrc` 一致；`picture` 使用提供的 WebP。
4. 跨域图片在页面中渲染，页面上下文 `fetch` 被 CORS 阻断，而独立请求上下文可下载并通过验证；懒加载图片滚动前请求数为 0、`currentSrc` 为空，滚动后请求数为 1 并解析为原图。
5. 20 次元素截图共 48570 字节，裁片 P50 约 64.05 ms，是主要固定成本；本实验为完整对比对所有用例截图，生产应只在降级时按需生成。
6. 未修改 `src/`、`figma_bridge/`，未执行 Figma 写入；写盘后 `content_hash` 可复算。

`R4-EXP-08` 只证明以下多页面、多轮权威链在 15 个受控页面修订上自洽：

1. 6 条同页面、轮次严格递增的显式 `supersedes` 边全部生效；detail/spec/inventory/promo 的旧修订被淘汰，legacy mirror 作为内容等价历史副本不进入候选。
2. 5 个有效权威页参与解析；`rogue-detail@r4` 的自声明 `title` 权威被标记为 `authority_mismatch`，但不被静默删除，并与 `detail@r4` 形成 `external-conflict`，`winner=null`。
3. `price` 由 `inventory@r2` 保持 `1399`；`detail@r4` 与其他页面的 `1349/1299/1199` 只作为候选，输出 `authority-required`，不按最新页面覆盖。
4. `description` 在 `detail@r3/r4` 显式删除；`archive-snippet@r3` 的旧文本被保留为 `ignored candidate`，不能复活删除。
5. `stock / battery / weight` 在 r3/r4 未再出现，输出 `carried-forward-not-seen`；缺 tombstone 变异只产生 `not-seen`，不产生 `deleted`。
6. 24 次输入置换产生同一 `resolution_hash`；四轮重放稳定；隐式 recency、supersedes 环、非权威 supersedes、缺 tombstone 四种变异均按预期失败；35/35 检查通过。
7. 未修改 `src/`、`figma_bridge/`，未执行 Figma 写入；写盘后 `content_hash` 可复算。

`R4-EXP-09` 只证明以下混合来源写入合同在 19 个受控字段用例上自洽：

1. 19 个用例得到 8 个 `written`、7 个 `deferred`、4 个 `skipped`；仅生成 8 条写入命令（5 条 `create_text`、1 条 `create_rectangle`、2 条 `create_image`），另 1 条 `create_frame`。
2. DOM 文本写入并使用 DOM 颜色；单引擎 OCR 候选、文本外部冲突、重复歧义和未观测文本均不写入。
3. 双引擎 OCR exact、最小置信度 `0.92 >= 0.85` 且 IoU `0.71 >= 0.50` 时允许写入；门槛仍沿用 R4-EXP-02 的实验值。
4. DOM 颜色 `#dc2626` 覆盖截图候选 `#ef4444`；截图-only 颜色不生成 fill；缺失颜色不发明值。
5. 已验证原图与显式 `flat-raster-crop` 均可写为 `create_image`，但后者必须携带降级 claim 与 `cannot_claim=[original-asset, native-editability, dom-identity]`；未验证资产和 native CSS 零命令。
6. 完全遮挡节点零命令；遮挡未知节点 defer；被遮挡卡片的文本与资产合计 0 条命令。
7. 写入命令按截图 z-order 升序（`10, 12, 30, 32, 40, 45, 60, 101`），不按 DOM 顺序；modal 标题最后写入。bridge 没有 `visible` action，本实验不伪造 `visible=false`。
8. 8/8 非法变异保持安全，38/38 检查通过；`real_figma_connected=false`、`figma_write=false`、`source_mutation=false`，未修改 `src/` 或 `figma_bridge/`。

`R4-EXP-10` 只证明以下九阶段产物级组合合同：

1. 9 个实验产物均能归一化为最小 stage envelope，9/9 状态为 `completed-for-current-scope`，227/227 阶段检查通过。
2. 9 个阶段均声明显式 `content_hash`，9/9 复算一致；同时保留 9/9 派生 canonical digest。
3. 9/9 阶段声明 boundary，9/9 阶段声明 limitations；`envelope_gaps={}`，不补造、不升格为已验证。
4. 120 次阶段输入顺序置换得到同一 `bundle_hash`；13/13 集成检查通过，9/9 非法变异被预期问题拦截。
5. `sequence_semantics=ordered-audit-only`；实验顺序不是运行时数据依赖，本实验未重跑 OCR/CV、浏览器采集、配对、权威解析或写入。

历史 envelope 缺口已由 `output/_r4_experiments/r4_metadata_supplement.py` 幂等补齐：EXP-01–06 的 boundary、EXP-08 的 limitations、EXP-01–04 的显式 `content_hash`；补跑审计确认 `changed=0`、7/7 检查通过。

## 未决项

| ID | 问题 | 阻塞对象 | 当前状态 | 建议验证 |
|---|---|---|---|---|
| R4-O01 | 真实 OCR/CV 候选如何进入 `screenshot-candidate` 通道 | 截图感知、文本交付 | 已完成当前范围；门限与 13 用例见 R4-EXP-02；仍非端到端检测与通用阈值 | 扩展到真实站点、检测框缺失/偏移、多引擎与跨 DPR 矩阵 |
| R4-O02 | 真实滚动、懒加载、动画帧的状态签名是否足够 | 状态门、拼接 | 已完成当前范围；11 次捕获 / 7 签名 / 55 对 / 18 项检查见 R4-EXP-03；仍限单个合成页面，动画为暂停相位 | 扩展到真实站点、轮播/视频/无限滚动、网络失败与实时动画采样 |
| R4-O03 | bbox 容差在不同 DPR、缩放和字体下是否仍为 `2.0 px` | 几何融合 | 已完成当前范围；20 次捕获 / 200 样本 / 4 DPR / 5 缩放 / 4 字体，200/200 通过，最大 1.1000 px，见 R4-EXP-05；仍非真实站点、跨浏览器或 CV 检测基准 | 扩展到真实检测器、真实站点、跨浏览器与变换/裁剪/遮挡矩阵 |
| R4-O04 | 重复元素的自动配对算法 | 配对歧义 | 已完成当前范围；12 场景 / 24 捕获 / 109 观测 / 46 配对 / 26 项检查见 R4-EXP-06；仍限受控合成页面、DPR 1 与 8×8 图像签名 | 扩展到真实站点、跨语言/价格规格变体、无限滚动与生产匹配 API |
| R4-O05 | 生产 IR 的字段级 provenance schema | 实现落地 | 已完成当前范围；34 节点 / 77 字段 / 181 证据 / 22 项检查见 R4-EXP-04；仍非生产 IR，未接入 `src/` | 接入生产模型、持久化与外部真值验证；扩展到真实站点与多页面 |
| R4-O06 | 资产来源解析与降级链 | 资产编辑 | 已完成当前范围；20 用例 / 10 原图 / 6 降级 / 4 原生本地来源 / 39 项检查见 R4-EXP-07；仍限受控 loopback 页面、Chromium、DPR 1/2 与构造资产 | 扩展到真实站点/CDN、鉴权/CSP、AVIF/HEIC、生产缓存与 Figma 资产替换 |
| R4-O07 | 多页面/多轮更新的权威链 | 增量融合 | 已完成当前范围；15 页面修订 / 4 轮 / 2 scope / 10 字段 / 35 项检查见 R4-EXP-08；仍限受控 loopback 页面与显式关系，未自动发现页面关系 | 扩展到真实站点/CMS、权限、并发与乱序更新、生产 IR 与持久化 |
| R4-O08 | 混合来源字段进入 Figma 写入时的行为 | 生产写入 | 已完成当前范围；19 用例 / 8 写入 / 7 延迟 / 4 跳过 / 38 项检查见 R4-EXP-09；仅离线 mock executor，未连接 Figma | 接入真实 Figma bridge 与回读、部分遮挡/半透明、字体加载、事务与真实资产管线 |
| R4-O09 | 九个 R4 实验产物能否构成统一离线合同 | 实现落地、跨阶段审计 | 已完成当前范围；9 阶段 / 227 阶段检查 / 13 集成检查 / 9 变异见 R4-EXP-10；9/9 显式哈希、9/9 boundary、9/9 limitations、`envelope_gaps={}` | 统一生产 envelope、接入 `src/`、真实 Figma 回读与运行时数据依赖验证 |

## 明确不能宣称

- 不能把 R4-EXP-01 写成 OCR/CV 准确率或真实站点融合准确率。
- 不能把 R4-EXP-02 的 2/2 升级精度写成通用 OCR 精度或生产接受率。
- 不能把 `0.85 / 0.50 / 0.30` 写成跨站点、跨字体、跨 DPR 的通用阈值；OCR 仍只在给定框内运行。
- 不能把 `2.0 px` 写成通用 bbox 阈值。
- 不能把 `screenshot-only` 或 `screenshot-candidate` 写成已验证的原生事实。
- 不能把裁片写成原始资产、可编辑文本或 DOM 身份。
- 不能声称已有生产融合 API、IR schema 或 Figma 写入能力。
- 不能把 R4-EXP-03 的 7 个状态签名写成通用状态识别器；签名、探针和懒加载位置均为实验者编写。
- 不能把 R4-EXP-03 的 `1.0 px / 16 ms / 0.05 / 0.02 / 0.00005` 写成通用几何、动画或视觉回归阈值。
- 不能把暂停到显式相位的动画写成实时动画采样；轮播、视频、无限滚动、网络失败和跨浏览器状态仍未覆盖。
- 不能把 R4-EXP-04 的 22/22 检查写成生产 schema 或外部真值验证；它只证明三个来源实验之间的合同自洽和非法变异拒绝。
- 不能把 R4-EXP-04 的 IR 写成已接入 `src/`、已持久化或已驱动 Figma 写入；它仍是只读设计产物。
- 不能把 R4-EXP-05 的 200/200 写成通用 bbox 阈值；它只覆盖 Chromium、纯色背景连通域、CSS zoom 和 4 组字体。
- 不能把 R4-EXP-05 的截图框写成 OCR/CV 检测结果；它不包含检测框偏移、漏检、误检和真实背景干扰。
- 不能把 R4-EXP-05 的 CSS `zoom` 写成浏览器 UI 缩放、pinch zoom、旋转、变换或裁剪的等价验证。
- 不能把 R4-EXP-06 的 46/46 写成真实商品配对准确率或生产接受率；它只覆盖 12 个受控合成场景。
- 不能把 `0.20 / 0.04 / coverage 0.30` 写成通用配对阈值；零错误交集只是本次数据上的弱标定。
- 不能把节点 ID 写成稳定身份，也不能把 `not-seen` 写成 `deleted`。
- 不能把 8×8 RGB 图像签名写成感知哈希、OCR/CV 检测或原始资产。
- 不能把 R4-EXP-06 的配对器写成已接入 `src/`、`figma_bridge/` 或已驱动 Figma 写入。
- 不能把 R4-EXP-07 的 20/20 或 39/39 写成真实站点资产接受率、下载成功率或生产覆盖率。
- 不能把截图裁片写成原始资产、可编辑资产或生产缓存对象。
- 不能把跨域场景的请求上下文下载写成“跨域图片一定可下载”。
- 不能把 300 ms / 2000 ms / 5 次重定向写成通用网络策略。
- 不能把 R4-EXP-08 的 35/35 写成真实站点多页面解析准确率、覆盖率或生产接受率。
- 不能把轮次或页面更新时间写成权威；隐式 recency 在本实验中是明确拒绝项。
- 不能把 `carried-forward-not-seen` / `not-seen` 写成 `deleted`，也不能把 `authority-required` 写成已解决。
- 不能把 `external-conflict` 的平均值、最高分或最新值写成 winner。
- 不能把 R4-EXP-08 写成已自动发现 `supersedes`、已接入 `src/` 或已执行 Figma 写入。
- 不能把 R4-EXP-09 的 38/38 写成生产写入成功率、Figma 插件兼容率或真实设计稿还原度。
- 不能把 R4-EXP-09 的 mock executor 写成 Figma bridge runtime；本实验未打开 Figma、未建立 socket、未创建真实节点。
- 不能把 `flat-raster-crop` 写成原始资产或可编辑资产，也不能把截图-only 颜色写成原生颜色。
- 不能把 `deferred` / `skipped` 写成成功写入；隐藏内容被省略不等于 Figma 遮挡已实现。
- 不能声称当前 bridge 已支持 `visible`、mask、部分遮挡或真实 z-index 回读。
- 不能把 R4-EXP-10 写成生产端到端管线；它只验证九个产物能否被统一封装和审计。
- 不能把 227/227 写成真实运行时成功率，也不能把 `ordered-audit-only` 写成阶段间的数据流依赖。
- 不能把派生 digest 写成实验写盘时的原始哈希 attestation；当前 9/9 显式哈希已补齐，但其他实验产物仍不能假定具备同等 envelope。

## 复现

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_fusion_contract.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_ocr_candidates.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_state_gate.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_provenance_ir.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_bbox_calibration.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_pairing_calibration.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_asset_resolution.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_authority_chain.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_figma_write_contract.py
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_end_to_end_integration.py
```

产物：

- `output/_r4_experiments/r4_fusion_contract.json`
- `output/_r4_experiments/r4_fusion_artifacts/dom_route.json`
- `output/_r4_experiments/r4_fusion_artifacts/screenshot_route.json`
- `output/_r4_experiments/r4_fusion_artifacts/fusion_output.json`
- `output/_r4_experiments/r4_fusion_matrix.png`
- `output/_r4_experiments/r4_fusion_flow.png`
- `output/_r4_experiments/r4_fusion_status.png`
- `output/_r4_experiments/r4_ocr_candidates.json`
- `output/_r4_experiments/r4_ocr_artifacts/ocr_candidates.json`
- `output/_r4_experiments/r4_ocr_artifacts/cv_candidates.json`
- `output/_r4_experiments/r4_ocr_artifacts/gate_results.json`
- `output/_r4_experiments/r4_ocr_matrix.png`
- `output/_r4_experiments/r4_gate_flow.png`
- `output/_r4_experiments/r4_ocr_confidence.png`
- `output/_r4_experiments/r4_cv_boxes.png`
- `output/_r4_experiments/r4_state_gate.json`
- `output/_r4_experiments/r4_state_artifacts/captures.json`
- `output/_r4_experiments/r4_state_artifacts/state_pairs.json`
- `output/_r4_experiments/r4_state_artifacts/gate_results.json`
- `output/_r4_experiments/r4_state_artifacts/captures/`（11 张）
- `output/_r4_experiments/r4_state_artifacts/site/index.html`
- `output/_r4_experiments/r4_state_matrix.png`
- `output/_r4_experiments/r4_state_pair_matrix.png`
- `output/_r4_experiments/r4_naive_vs_gate.png`
- `output/_r4_experiments/r4_state_gallery.png`
- `output/_r4_experiments/r4_provenance_ir.json`
- `output/_r4_experiments/r4_provenance_artifacts/design_ir.json`
- `output/_r4_experiments/r4_provenance_artifacts/schema.json`
- `output/_r4_experiments/r4_provenance_artifacts/replay_manifest.json`
- `output/_r4_experiments/r4_ir_flow.png`
- `output/_r4_experiments/r4_ir_coverage.png`
- `output/_r4_experiments/r4_ir_replay.png`
- `output/_r4_experiments/r4_bbox_calibration.json`
- `output/_r4_experiments/r4_bbox_artifacts/measurements.json`
- `output/_r4_experiments/r4_bbox_artifacts/site/index.html`
- `output/_r4_experiments/r4_bbox_artifacts/captures/`（20 张）
- `output/_r4_experiments/r4_bbox_heatmap.png`
- `output/_r4_experiments/r4_bbox_distribution.png`
- `output/_r4_experiments/r4_bbox_overlay.png`
- `output/_r4_experiments/r4_pairing_calibration.json`
- `output/_r4_experiments/r4_pairing_artifacts/site/index.html`
- `output/_r4_experiments/r4_pairing_artifacts/captures/`（24 张）
- `output/_r4_experiments/r4_pairing_artifacts/observations.json`
- `output/_r4_experiments/r4_pairing_matrix.png`
- `output/_r4_experiments/r4_pairing_thresholds.png`
- `output/_r4_experiments/r4_pairing_cases.png`
- `output/_r4_experiments/r4_asset_resolution.json`
- `output/_r4_experiments/r4_asset_artifacts/site/index.html`
- `output/_r4_experiments/r4_asset_artifacts/manifest.json`
- `output/_r4_experiments/r4_asset_artifacts/downloads/`
- `output/_r4_experiments/r4_asset_artifacts/crops/`（20 张）
- `output/_r4_experiments/r4_asset_flow.png`
- `output/_r4_experiments/r4_asset_outcomes.png`
- `output/_r4_experiments/r4_asset_cost.png`
- `output/_r4_experiments/r4_asset_contact_sheet.png`
- `output/_r4_experiments/r4_authority_chain.json`
- `output/_r4_experiments/r4_authority_artifacts/site/pages/`（15 个页面修订）
- `output/_r4_experiments/r4_authority_artifacts/dom_observations.json`
- `output/_r4_experiments/r4_authority_artifacts/round_snapshots.json`
- `output/_r4_experiments/r4_authority_artifacts/mutations.json`
- `output/_r4_experiments/r4_authority_artifacts/index.png`
- `output/_r4_experiments/r4_authority_chain.png`
- `output/_r4_experiments/r4_authority_matrix.png`
- `output/_r4_experiments/r4_authority_conflicts.png`
- `output/_r4_experiments/r4_figma_write_contract.json`
- `output/_r4_experiments/r4_figma_write_artifacts/write_plan.json`
- `output/_r4_experiments/r4_figma_write_artifacts/commands.json`
- `output/_r4_experiments/r4_figma_write_artifacts/decisions.json`
- `output/_r4_experiments/r4_figma_write_artifacts/assets/`（3 张）
- `output/_r4_experiments/r4_figma_write_flow.png`
- `output/_r4_experiments/r4_figma_write_matrix.png`
- `output/_r4_experiments/r4_figma_write_occlusion.png`
- `output/_r4_experiments/r4_figma_write_assets.png`
- `output/_r4_experiments/r4_end_to_end_integration.json`
- `output/_r4_experiments/r4_end_to_end_artifacts/stage_bundle.json`
- `output/_r4_experiments/r4_end_to_end_artifacts/stage_envelopes.json`
- `output/_r4_experiments/r4_end_to_end_artifacts/mutations.json`
- `output/_r4_experiments/r4_end_to_end_stages.png`
- `output/_r4_experiments/r4_end_to_end_evidence.png`
- `output/_r4_experiments/r4_end_to_end_mutations.png`
