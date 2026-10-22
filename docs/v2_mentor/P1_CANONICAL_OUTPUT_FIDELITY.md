# P1 Canonical 输出保真与 Chromium 参考环境

> 状态：`frame-holdout-closed / figma-canonical-frame-assets-and-layout-pass`，2026-10-21。产品主目标转为固定 Chromium 参考下的实际 SVG/Figma 输出保真；跨浏览器 full-visible DOM 等价降为诊断与受控回归，不再作为当前产品主优化指标。

## 1. 决策

- 默认 canonical engine：项目当前可重复运行的 Chromium 固定构建。
- canonical 不是抽象“Chromium 页面”，而是锁定 browser build、OS、字体、viewport/DPR、locale/timezone、页面状态和截图/DOM 合同的参考环境。
- SVG 与 Figma 分开验收。
- 视觉通过不补偿内容、结构、编辑或资产失败。
- 不使用单一 composite score。
- `first-party-frame-strict/1.0` 只保留为诊断切片，不替代 full-visible 声明。
- 跨浏览器辅助 scope 优先 `rendered-frame-boundary-strict/1.0`，并明确只覆盖 frame 边界层。

## 2. 旧 strict 的新角色

旧定义、版本和证据保留：

- round3 full-visible strict `3/7`、content `5/7` 继续作为历史基线；
- 历史失败样本和归因不删除；
- 受控、可重复的旧 strict case 应作为硬回归门禁；
- 七个动态真实站点作为持续观测与外部有效性检查。

动态站点的 strict 数量会随广告、站点版本和状态变化，因此实时 `3/7` 不再作为产品回归门禁，也不能单独代表输出失败。

实时矩阵新增 `gate_contract` 顶层字段：

- canonical engine=`chromium`；
- product primary goal=`canonical-output-fidelity`；
- legacy live strict hard gate=false；
- controlled legacy strict hard gate=true，status=`planned`；
- first-party role=`diagnostic-slice`。

报告：`output/_p1_dual_sidecars/real_pair_matrix_outcome_round2.json`。其中实时 `strict_count` 是 outcome scope 的观测汇总，不是产品验收分数。

## 3. Canonical 环境

首轮实际指纹：

- engine：`chromium`
- browser：`151.0.7922.34`
- OS：`Windows-11-10.0.26300-SP0`
- viewport：`900×700`
- DPR：`1`
- locale：`zh-CN`
- timezone：`Asia/Shanghai`
- headless：`true`
- capture contract：`capture_page_with_fallback+dom-direct-svg`

字体文件同时记录 size 与 SHA-256，包括 Segoe UI、Microsoft YaHei、Arial 和 SimHei。完整环境、executable path 与字体哈希在报告中。

实现：`scripts/p1_canonical_output_fidelity.py`。

## 4. 首轮 canonical 样例

Manifest：`tests/fixtures/p1/canonical/manifest.json`。

| 样例 | 覆盖 |
|---|---|
| `text-flow` | 中英混排、多行文本、固定高度 flow 区块、容器 padding |
| `assets` | img、CSS background image、inline SVG |
| `iframe` | 可访问 frame、sandbox opaque frame、边界与子文档文本 |
| `font-fallback` | 缺失声明字体、系统 fallback、native text |
| `transparent-crop` | 半透明 overlay、object-fit 裁剪、叠加文字 |
| `partial-asset` | 有效图片、缺失图片、部分交付 |

每个样例使用独立 truth：

- expected/absent text；
- critical text box 与 1px 起始容差；
- asset count；
- native text 要求。

## 5. 首轮结果

渲染范围：

- DOM -> `12_design.json` -> `prototype.svg` -> `render.png`；
- 6 样例中 SVG `5 pass + 1 partial + 0 fail`；
- `partial-asset` 保持 partial，声明 `missing-asset-bytes`，不计 pass；
- 视觉指标已测量但阈值 `not-calibrated`，没有视觉 pass；
- Figma `not-evaluated`，因为未执行真实写入、回读、导出和渲染；
- composite score：未使用。

首轮视觉基线：

| 样例 | mean | ink_mean | over30% | diff px | bad px |
|---|---:|---:|---:|---:|---:|
| assets | 0.5520 | 6.7772 | 0.3792 | 2607 | 2389 |
| iframe | 2.6854 | 66.6029 | 1.5249 | 10918 | 9607 |
| text-flow | 3.1386 | 73.9762 | 2.6321 | 18358 | 16582 |

报告：`output/_p1_canonical_output_fidelity/round1.json`。

## 6. 实际修复

### 6.1 Frame 宿主偏移

问题：

- `collect_frame_dom()` 用 child index 直接对齐 iframe host index；
- 页面存在前置隐藏 tracking frame 时，隐藏 frame 吃掉可见 iframe 的 host；
- 可访问子文档文本丢失宿主偏移，被搬到父页顶部。

修复：

- iframe host 按 rendered frame 顺序消费；
- 子文档坐标使用实际 iframe host；
- 新增有前置内容、隐藏 frame 的回归测试。

结果：

- iframe 可访问文本回到 frame 内部；
- `mean 2.6854 -> 2.6372`；
- `ink_mean 66.6029 -> 64.4276`；
- diff px `10918 -> 10856`；
- bad px `9607 -> 9540`。

### 6.2 Flow 文本盒与 paint ownership

问题：

- 带背景和 padding 的 flow 文本节点使用容器元素盒排版；
- 文本忽略 padding，从容器左上角开始；
- 修正文本几何后，背景/边框又被文本元素重复绘制。

修复：

- flow 文本使用真实 `textBox`；
- 背景/边框只由容器拥有，文本元素变为纯文字样式；
- 新增 textBox/container paint ownership 测试。

结果：

- text-flow padding 与文本位置正确；
- `mean 3.1386 -> 2.8559`；
- `ink_mean 73.9762 -> 69.2888`；
- over30 `2.6321% -> 2.4662%`；
- diff px `18358 -> 17170`；
- bad px `16582 -> 15537`；
- assets 指标保持不变。

### 6.3 浏览器实测分行

问题：

- 输出端仍用离线字体估宽决定折行，text-flow 与 Chromium 的断点不同；
- DOM 探针已有真实行数，但没有逐行文本；
- 新增 `textLines` 后，SoM annotate 重建元素白名单时仍会丢掉该字段。

修复：

- DOM 探针逐字符使用 Range，按 top 分组记录浏览器真实分行文本和行盒；
- `textLines` 穿过 PageGraph、SoM、DesignSpec；
- `wrap_for_spec()` 优先复用浏览器实测行，不再用 0.55em/1em 估算。

结果：

- text-flow 换行与 Chromium 参考一致；
- `mean 2.8559 -> 0.7348`；
- `ink_mean 69.2888 -> 15.2487`；
- over30 `2.4662% -> 0.7600%`；
- diff px `17170 -> 5039`；
- bad px `15537 -> 4788`；
- assets 与 iframe 指标保持不变。

### 6.4 六样例扩展

新增样例结果：

| 样例 | 范围 | 指标 |
|---|---|---|
| font-fallback | declared family + native text + geometry | `mean=0`、`ink_mean=0`，视觉逐像素一致 |
| transparent-crop | 透明 overlay + 图片裁剪 + native text | `mean=0.2381`、`ink_mean=4.2070`、bad px `1579` |
| partial-asset | 有效/缺失资产混合 | `partial`，`missing-asset-bytes`，不冒充 pass |

资产 region 验收：

- 每个声明资产检查显示盒与 1px 起始容差；
- 要求 local bytes 的资产必须存在本地图像/色块证据；
- scope 明确区分显示盒/local bytes、源资产 identity 与 source crop；
- data URI 资产同时校验 content SHA-256、natural size、object-fit 与 source rect；
- canonical 实验可通过受控 loopback server 下载远程资产原字节；生产下载策略仍拒绝 loopback/私网。

最终报告：`output/_p1_canonical_output_fidelity_round16/round1.json`。

### 6.5 独立视觉 holdout

Policy 先冻结，再运行 holdout：

- policy：`p1-canonical-visual-policy/1.0`；
- 分类阈值：`text / assets / overlay / frame`；
- 每类所有指标必须分别通过，不使用 composite score；
- calibration 6 例与 holdout 5 例分母独立；
- 看到 holdout 结果后未修改阈值或 fixture truth。

Holdout 结果：

| 样例 | policy | mean | ink_mean | over30% | bad px | 状态 |
|---|---|---:|---:|---:|---:|---|
| holdout-text | `text-v1` | 0 | 0 | 0 | 0 | pass |
| holdout-assets | `assets-v1` | 0.5088 | 6.8223 | 0.3608 | 2273 | pass |
| holdout-overlay | `overlay-v1` | 0.0470 | 0.9999 | 0.0656 | 413 | pass |
| holdout-frame | `frame-v1` | 0.0011 | 0.0693 | 0.0020 | 12 | pass |
| holdout-remote-asset | `assets-v1` | 0.5221 | 7.9906 | 0.3746 | 2360 | pass |

汇总：SVG `5 pass / 0 partial / 0 fail`，visual gate `5 pass / 0 fail`。

报告：`output/_p1_canonical_visual_holdout_round14/round1.json`。

frame 修复：

- opaque frame 内部区域已从视觉分母排除；
- 单行 browser-measured text 使用 `textEmBox` 行高，避免把正常段落按 1.4em 行高下移；
- iframe 默认 `border: 2px inset` 采集为 `borderStyle=inset`，输出为四段内侧 bevel；
- 子文档坐标加入 iframe border 的 content-box 偏移；
- `srcdoc` 默认字体按 Chromium 实际渲染归一为 sans-serif，避免把子文档文字画窄；
- 失败样例保留，阈值未回调。

### 6.6 源资产 identity 与裁剪映射

新增采集字段：

- `naturalWidth / naturalHeight / objectFit / objectPosition`；
- data URI MIME、byte length、natural size、content SHA-256；
- `sourceCrop.source_rect / scale / display_box`；
- 远程资产记录 source-ref；canonical 实验另用受控 loopback 下载 content SHA-256，生产策略不变。

验证：

- calibration 的 img、background-image data URI、transparent crop 均通过 identity + source rect；
- holdout 的 assets/overlay 资产同样通过；
- remote asset holdout 的 MIME、size、content SHA-256、显示盒全部通过；
- 同 policy 下视觉 holdout 为 5 pass / 0 frame fail；
- 最新 holdout 报告：`output/_p1_canonical_visual_holdout_round14/round1.json`。

### 6.7 Canonical frame 的真实 Figma 回放

桥接服务：`ws://localhost:8765`。当前 Figma 插件已连接并完成真实写入。

最小烟测：

- `scripts/figma_readback_smoke.py --out output/_p1_figma_smoke_round2`；
- frame、text、rectangle、image 四类节点真实写入；
- node-tree 回读正常，PNG 导出正常；
- 12/12 checks 通过。

canonical frame 回放：

- 输入：`output/_p1_canonical_visual_holdout_round14/samples/holdout-frame/12_design.json`；
- 输出：`output/_p1_figma_canonical_frame_round1/figma_render.png`；
- readback：`output/_p1_figma_canonical_frame_round1/readback_tree.json`；
- 画板实际为 `900×700`，包含 2 个 iframe host、8 条 border band 和 5 个文本节点；
- 独立 Figma 回放指标为 `mean=2.088`、`ink_mean=88.560`、`over30=1.97%`；
- 当时尚未接入 canonical evaluator 的 Figma 四维验收，该轮保持 `figma_evaluated_count=0`；6.8 已用后续独立验收器收口。

当时全量 unittest `180/180` 通过。

### 6.8 Figma 独立验收链

新增独立验收器：

- `src/app/services/rendering/figma_acceptance.py`；
- `scripts/p1_figma_acceptance.py`；
- `scripts/figma_edit_probe.py`；
- `scripts/figma_asset_probe.py`。

内容、几何、字体、原生文本编辑、图片替换和视觉分别记录。缺少编辑或资产证据时保持 `not-evaluated`，不允许其他维度补偿。

canonical frame 当前结果：

- structure `pass`；
- visual provisional `pass`；
- native text probe `pass`；
- font strict `pass`，`sans-serif` 通过 Chromium 平台字体证据解析为 Microsoft YaHei；
- asset `not-required`；
- overall `pass`；
- `figma_evaluated_count=1`。

报告：`output/_p1_figma_acceptance_frame_round14/figma_acceptance.json`。

Canonical asset sample：

- `output/_p1_figma_assets_acceptance_round3/figma_acceptance.json`；
- structure / visual / edit / asset 全部 `pass`；
- 3/3 图片节点几何与 IMAGE fill 通过；
- 3/3 Figma fill bytes 与本地 payload SHA-256 一致；
- 独立图片替换/恢复探针通过。

Auto Layout 编辑传播：

- `output/_p1_figma_autolayout_edit_probe_round1/figma_autolayout_edit_probe.json`；
- native text 增长后 sibling y `64 → 100`，parent height `120 → 156`；
- 恢复后回到初始布局；
- probe `status=pass`。

Figma visual holdout：

- 历史报告：`output/_p1_figma_holdout_round1/round1.json`，当时为 `4 pass / 1 blocked`；
- 当前报告：`output/_p1_figma_holdout_round2/round1.json`，现为 `5 pass / 0 blocked`；
- 单行文本此前未把 CSS 显式 `line-height` 写入 Figma，改用默认行盒后字形整体偏上；
- 修复后 `holdout-remote-asset` 的 `bad_pixel_count` 从 `14520` 降到 `12769`，在原 `14000` 冻结阈值下通过；
- 五样例 structure/visual/edit/asset 所需维度均通过，`figma_evaluated_count=5`，未使用 composite score；
- 阈值和 fixture truth 均未在结果后修改。

真实 native text 编辑和图片替换探针均已通过当前单文档 scope：

- `output/_p1_figma_edit_probe_round5/figma_edit_probe.json`；
- `output/_p1_figma_text_edit_probe_round3/figma_edit_probe.json`；
- `output/_p1_figma_overlay_edit_probe_round2/figma_edit_probe.json`；
- `output/_p1_figma_remote_asset_edit_probe_round2/figma_edit_probe.json`；
- `output/_p1_figma_asset_probe_round4/figma_asset_probe.json`。

`holdout-text` 首次热重载后曾出现 `212 -> 242` 的宽度瞬态并导致一次 restore probe 失败；失败报告保留，后续两次独立重放稳定为 `242×40` 且 probe 通过。该瞬态不作为 verified 清空。

详见：`docs/v2_mentor/P1_FIGMA_ACCEPTANCE.md`。

### 6.9 Chromium platform-font provenance

新的 generic family 解析不依赖固定映射表：

- `DOM_JS` 只为 generic font stack 文本写临时 probe marker；
- Chromium 通过 `CSS.getPlatformFontsForNode` 读取实际平台字体；
- 单一字体时才写入 `fontFamily`，并保留 `fontFamilyRequested`、`fontFamilyResolution` 和 `platformFonts`；
- 多字体 run 标记为 `ambiguous-platform-font`，不强行压成一个 face；
- 临时 DOM marker 在探针结束后移除。

canonical frame 的 `sans-serif` 实际解析为 Microsoft YaHei。复跑结果：

- SVG holdout：`5/5`，frame 仍为 `12` bad pixels；
- calibration：`5 pass + 1 partial`，`partial-asset` 未升级；
- Figma font strict：pass；
- Figma 最终 acceptance：pass。

实现：`src/app/services/structure/font_provenance.py`。

当前全量 unittest：`226/226 passed`。

## 7. 仍未完成

- 视觉 policy 当前为 5 pass / 0 frame fail；阈值仍保持 provisional，不能外推到所有真实页面；
- 资产 region 已覆盖 data URI/受控远程 content identity、natural size、object-fit source rect 与 local display bytes；canonical asset sample 的 Figma 四维验收、本地 payload SHA-256 和替换/恢复均已通过；原始 SVG source bytes 的 Figma identity 仍未证明；
- text-flow 主要断点已与参考浏览器一致，frame holdout 已达到约 0.0011 mean；仍有 12 个非遮蔽差异像素，不能声称逐像素完全等价；
- Auto Layout probe 已覆盖当前垂直固定宽度流式布局；Grid、wrap、component 和复杂嵌套传播仍未验证；
- Figma 已完成真实写入、回读、PNG 导出、独立四维报告、canonical frame/assets 通过、native text 本地编辑传播、Auto Layout 父级传播和图片替换；
- 首轮 suite 已覆盖图片裁剪、透明叠放、字体缺失、资产失败和 partial delivery；
- 真实站点 canonical 输出尚未进入持续观测；
- 受控旧 strict 硬回归套件仍待正式拆分和固定版本化。

## 8. 不得宣称

- 不得把 5/5 canonical SVG 范围写成 Figma 完成、整页视觉通过或生产可用。
- 不得把视觉 `measured-not-gated` 写成 pass。
- 不得用视觉指标抵消内容、结构、编辑或资产失败。
- 不得把受控 canonical 结果外推到所有真实站点。
- 不得把动态真实站点的 strict 数量变化写成产品硬回归。
- 不得把 first-party 诊断视图写成 old full-visible strict 改善。
