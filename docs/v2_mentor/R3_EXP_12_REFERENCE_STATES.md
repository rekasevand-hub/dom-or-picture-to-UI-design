# R3-EXP-12 · 多状态参考冲突与权威版本（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：1 个合成页面、11 个参考记录、6 个状态签名、7 个 scope-state 组、4 个拼接场景、8 个参考比较对、16 项合同检查。  
> 证据：`output/_r3_experiments/exp12_reference_states.json`、`output/_r3_experiments/exp12_reference_state_site/`、`output/_r3_experiments/exp12_artifacts/`、`exp12_state_matrix.png`、`exp12_composite_strip.png`、`exp12_conflict_map.png`、`exp12_overlap_zoom.png`。  
> 边界：只验证“状态元数据能否阻止多时刻素材被拼成同一状态事实”，以及“冲突是否停在未决项”。不验证真实轮播引擎、真实外部来源、截图自动状态识别、Figma 写入或生产权限系统。

## 1. 目的与边界

本实验回答五个问题：

1. 轮播帧、滚动、缩放、遮挡和过渡状态，能否各自建立独立的 `reference_id` 与 `state`，而不是共享一个“同一页面”标签。
2. 每条参考能否记录内容 hash、原始像素尺寸、裁切/变换、滚动、采集时间、轮播帧和遮挡区域。
3. 同态多图能否用重叠与覆盖验证拼接；不同状态是否会被误算成几何误差。
4. 新截图能否建立新 reference，并通过显式权威关系取代旧版本，而不是静默覆盖。
5. `composite-unknown` 与 `external-conflict` 是否按预期停在未决项。

所有页面、状态和外部来源都是实验者编写的合成夹具。外部来源是“模拟导入”，不是第三方站点或真实上传。几何来自 authored DOM，状态来自显式元数据，不是从截图像素反推。未调用 Figma 写路径，未修改 `src/`、`figma_bridge/`。

本实验**不做阈值标定**，也没有标定集/验收集。16 项检查是确定性合同检查：状态匹配才允许比较、拼接必须有覆盖与重叠证据、冲突必须有权威链才能消解。合同值不是从缺陷样本拟合出的通用阈值。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Chromium | 151.0.7922.34（Playwright headless） |
| 视口 / DPR | 1200×1000 CSS px / 1 |
| 页面宽度 | 1200 px |
| 字体 | Segoe UI / Microsoft YaHei（系统字体） |
| 捕获 | viewport PNG，动画与过渡关闭，光标隐藏 |
| 合成页面 | `output/_r3_experiments/exp12_reference_state_site/index.html` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r3_experiments/exp12_reference_states.py
```

脚本会重建站点、11 张参考截图、JSON 与四张联系/冲突图；本次完整重跑约 6 秒。

## 3. 方法

### 3.1 参考记录

每条参考显式记录：

- `reference_id`、`scope_id`、`provenance`、`revision`；
- `state`：`zoom`、`scroll_y`、`frame`、`transition`、`occlusion`、`occlusion_rect`、`transform`、`viewport_css`、`device_scale_factor`、`captured_at`；
- `capture`：`mode=viewport`、原始像素尺寸、裁切矩形；
- `pixel`：完整 PNG 的 SHA-256、宽高；
- `regions`：carousel、article、toast 三个区域的裁切矩形与 SHA-256；
- `authority`：`claim`、`granted_by`、`supersedes`；
- `claims` / `cannot_claim`：本参考可宣称与不可宣称的范围。

状态签名包含 scope 之外的 `zoom / scroll_y / frame / transition / occlusion / occlusion_rect / transform / viewport_css / device_scale_factor`。采集时间被记录，但不进入状态签名；它用于审计，不作为同态判据。

所有参考的基础宣称是“捕获时视口内的像素与 DOM 框”和“该图片的内容 hash”；基础不可宣称包括“其他帧/滚动/时间”“视口外整页”“从图片宽度反推 CSS 视口或 DPR”“没有 supersedes 关系时对另一参考拥有权威”。遮挡参考额外记录未知矩形。

### 3.2 状态矩阵

| 参考 | scope | 状态摘要 | revision | 角色 |
|---|---|---|---|---|
| `ref-frame0-v1` | product | frame 0 · scroll 0 · zoom 1 · 无遮挡 | `2026-10-18` | 初始权威；后被 v2 取代 |
| `ref-frame0-v1-repeat` | product | 同 v1 | `2026-10-18` | 同态重复捕获；content-equal |
| `ref-frame1` | product | frame 1 · scroll 0 · zoom 1 · 无遮挡 | `2026-10-18` | 独立轮播帧 |
| `ref-scroll600` | product | frame 0 · scroll 600 · zoom 1 | `2026-10-18` | 独立滚动状态 |
| `ref-zoom125` | product | frame 0 · scroll 0 · zoom 1.25 | `2026-10-18` | 独立缩放状态 |
| `ref-occlusion-toast` | product | frame 0 · scroll 0 · zoom 1 · toast 遮挡 | `2026-10-18` | 独立遮挡状态 |
| `ref-transition-0-to-1` | product | frame `0->1` · transition | `2026-10-18` | 瞬态；不可比较 |
| `ref-frame0-v2-authorized` | product | 同 v1 状态 | `2026-10-19` | 新权威；显式 supersedes v1 |
| `ref-frame0-v3-unattested` | product | 同 v1 状态 | `2026-10-20` | 未授权候选；不得自动提升 |
| `ref-external-a` | external | 同 S0 状态 | `external-A` | 外部未认证版本 A |
| `ref-external-b` | external | 同 S0 状态 | `external-B` | 外部未认证版本 B |

11 条参考共享 6 个不同状态签名；由于 product 与 external 使用不同 scope，形成 7 个 scope-state 组。所有截图均为 1200×1000、DPR 1；缩放状态通过 authored CSS zoom 改变内容，而不是从图片宽度推断视口。

### 3.3 比较与拼接规则

1. 先比较 `scope_id`；不同 scope 不合并。
2. 再比较状态签名；不同签名标记 `not-compared / different-state`，不进入几何误差。
3. 瞬态状态标记 `not-compared / transient-state`。
4. 只有 scope 与状态签名都匹配，才计算像素 MAE、几何 IoU 与内容 hash 是否相等。
5. 拼接要求同 scope、同状态、无缺口、覆盖率达到合同值，且相邻 tile 重叠 MAE 不超过合同值。
6. 缺口、混合状态、不同内容版本均返回 `composite-unknown`；不允许插值、补图或多数投票。

### 3.4 权威与冲突规则

- 只有显式 `authoritative` 且没有被 supersedes 的参考可以成为 effective authority。
- `supersedes` 只按记录中的显式边生效；内容相同但未显式取代的重复参考，跟随其内容版本进入 historical。
- 没有 authority 的冲突返回 `external-conflict`，`winner=null`，所有参考保留。
- 有 effective authority、但仍有未授权冲突时返回 `authority-required`；winner 保留，冲突候选单列。

## 4. 结果总表

| 指标 | 结果 |
|---|---:|
| 参考记录 / 唯一 ID | 11 / 11 |
| 状态签名 | 6 |
| scope-state 组 | 7 |
| 比较对 | 8 |
| 同态可比较对 | 3 |
| 异态对 | 4 |
| 瞬态对 | 1 |
| 守卫后几何错误 | 0 |
| 避免的 naive 几何假差异 | 2 |
| 拼接场景 | 4 |
| `composite-verified` | 1 |
| `composite-unknown` | 3 |
| `composite-conflict` | 0 |
| `external-conflict` 组 | 1 |
| `authority-required` 组 | 1 |
| 未决参考 | 3（v3、external-A、external-B） |
| 合同检查 | 16/16 |

## 5. 同态与异态

### 5.1 同态重复

`ref-frame0-v1` 与 `ref-frame0-v1-repeat` 的完整 PNG SHA-256 相同，像素 MAE `0.0`、exact ratio `1.0`，最小几何 IoU `1.0`。这说明在本静态夹具中，同态重复捕获可以被识别为可比较，并且可以作为拼接的独立来源。

这只证明两次重复捕获一致；不证明任意时间跨度的同态截图都一致。时间被记录，但本实验没有注入时钟、广告或异步内容变化。

### 5.2 轮播帧

frame 0 与 frame 1 的完整图 MAE 为 `50.950043`，但几何最小 IoU 仍为 `1.0`；carousel 区域 hash 从 `a56aa13f8575…` 变为 `2fad5a6454b9…`，article 区域 hash 保持 `5e1776333c48…`。因此：

- 状态差异是内容差异，不是布局几何错误；
- 仅靠几何 IoU 会把两帧误判为同态；
- 必须同时使用显式 frame 状态与内容 hash。

比较结果为 `not-compared / different-state`，未进入几何误差。

### 5.3 滚动与缩放

| 对 | 状态差 | 完整图 MAE | 最小几何 IoU | 判定 |
|---|---|---:|---:|---|
| frame 0 → scroll 600 | `scroll_y 0→600` | 63.598985 | 0.0 | `not-compared / different-state` |
| frame 0 → zoom 1.25 | `zoom 1→1.25` | 52.636769 | 0.0 | `not-compared / different-state` |

如果直接比较 DOM 框，这两个状态会产生 2 个“几何错误”；状态守卫把它们全部挡住，因此守卫后的几何错误为 0。所有参考仍记录 `viewport_css=1200×1000`、`device_scale_factor=1`，没有从图片宽度反推视口或 DPR。

### 5.4 遮挡与瞬态

- 遮挡参考记录 toast 矩形 `(80, 300, 360×160)`；完整图 MAE `3.888951`，几何 IoU 仍为 `1.0`。参考把该矩形标为未知区域，比较结果为 `different-state`。
- 过渡参考同时显示两帧的中间状态，完整图 MAE `27.189678`，几何最小 IoU `0.449275`；状态带 `transition=true`，结果为 `not-compared / transient-state`，不并入 frame 0 或 frame 1。

遮挡与轮播说明：几何相同并不等于同态；状态元数据和未知区域必须独立保留。过渡说明：即使几何明显不同，也不能把它当作布局缺陷。

## 6. 拼接覆盖

| 场景 | 来源 | 状态数 | 内容 hash 数 | 覆盖 | 缺口 | 重叠 MAE | 结果 |
|---|---|---:|---:|---:|---|---:|---|
| `composite-valid-same-state` | v1 + v1 repeat | 1 | 1 | 1.0 | 无 | 0.0 | `composite-verified` |
| `composite-gap-same-state` | v1 + v1 repeat | 1 | 1 | 0.9 | `[500,600]`，100 px | 不比较 | `composite-unknown / coverage-gap` |
| `composite-mixed-state` | frame 0 + frame 1 | 2 | 2 | 1.0 | 无 | 不比较 | `composite-unknown / mixed-state` |
| `composite-historical-new-mixed` | v1 + v2 | 1 | 2 | 1.0 | 无 | 0.0 | `composite-unknown / content-version-mismatch` |

要点：

- 同态全重叠拼接的 overlap MAE 为 `0.0`、exact ratio `1.0`、覆盖 `1.0`，因此可以标 `composite-verified`。它的宣称仍只覆盖目标区间 `[0,1000]`，不是整页真值。
- 有 100 px 缺口时，覆盖为 `0.9`，缺口 `[500,600]` 原样保留；没有补图或插值。
- 两个轮播帧即使覆盖达到 `1.0`，仍因 2 个状态签名而 `composite-unknown`；没有把混合帧拼成一个“共同真值”。
- v1 与 v2 的重叠 MAE 也为 `0.0`，覆盖为 `1.0`，但仍因 2 个内容 hash 而 `composite-unknown`。这说明**重叠一致不足以证明可以混用历史与新版参考**。

本实验没有实例化“同状态、同内容版本但重叠像素冲突”的 `composite-conflict`，因此该分支只实现未触发，不能写成已验证。

## 7. 权威与外部冲突

### 7.1 显式取代

`ref-frame0-v2-authorized` 使用 `authority=authoritative`、`granted_by=operator-confirmed`，并显式 `supersedes=[ref-frame0-v1]`。product 组结果：

- winner：`ref-frame0-v2-authorized`；
- historical：`ref-frame0-v1`、`ref-frame0-v1-repeat`；
- unresolved：`ref-frame0-v3-unattested`；
- 状态：`authority-required`。

v1 与 v2 的完整图 MAE 仅 `0.005643`，exact ratio `0.999918`，几何 IoU `1.0`；差异只是 revision 标记。这正说明小像素差异不能自动决定权威，必须有显式 supersedes 关系。

`ref-frame0-v3-unattested` 没有 authority 或 supersedes；它保留为候选，不能替换 v2，也没有被静默丢弃。

### 7.2 外部冲突

external scope 中 `ref-external-a` 与 `ref-external-b` 共享同一状态签名，但内容 hash 不同；完整图 MAE `0.069642`，exact ratio `0.999319`，几何 IoU `1.0`。两者都是 `external-unattested`，没有 authority，结果：

- 状态：`external-conflict`；
- winner：`null`；
- unresolved：两条参考都保留；
- 不按 hash 顺序、像素相似度、图片宽度或多数投票选边。

本实验的外部来源是模拟导入，只验证清单与解析器层面的冲突处理，不验证真实第三方抓取、签名或信任链。

## 8. 检查清单

| 检查 | 观测 | 结果 |
|---|---|---|
| manifest-complete | 11/11 条参考包含 scope/state/hash/像素尺寸/non-claims | 通过 |
| state-identities | 6 个状态签名 | 通过 |
| carousel-separation | `not-compared / different-state` | 通过 |
| scroll-zoom-occlusion-transient-separation | 4/4 `not-compared` | 通过 |
| occlusion-region-recorded | toast 矩形已记录 | 通过 |
| same-state-repeat | MAE 0.0；最小 IoU 1.0 | 通过 |
| geometry-guard | 0 错误；避免 2 个 naive 假差异 | 通过 |
| composite-valid | 覆盖 1.0；重叠 MAE 0.0 | 通过 |
| composite-gap | 缺口 `[500,600]`；覆盖 0.9 | 通过 |
| composite-mixed-state | 2 个状态；`mixed-state` | 通过 |
| composite-version-mix | 1 个状态、2 个 hash；`content-version-mismatch` | 通过 |
| authority-chain | winner v2；v1/repeat historical；v3 unresolved | 通过 |
| external-conflict | winner null；2 条 unresolved | 通过 |
| transient-not-merged | `transient-not-comparable` | 通过 |
| no-viewport-dpr-inference | 2/2 显式记录；0 次推断 | 通过 |
| claims-and-non-claims | 参考与拼接均填写 | 通过 |

## 9. 合同值

| 合同 | 值 | 性质 | 实测 |
|---|---:|---|---|
| `overlap_mae_max` | 2.0 | 合同值，不是缺陷阈值 | 同态重叠 `0.0`；混合状态不比较 |
| `composite_coverage_min` | 0.999 | 合同值 | 有效拼接 `1.0`；缺口拼接 `0.9` |
| `geometry_requires_same_state` | true | 策略 | 异态比较 0 次进入几何误差 |
| `viewport_inference_from_image_width` | false | 策略 | 11/11 记录显式视口 |
| `dpr_inference_from_image_width` | false | 策略 | 11/11 记录 DPR 1 |

这些值只说明本实验的合同解释，不是跨站点、跨浏览器或跨 DPR 的通用阈值。没有注入“同态重叠冲突”或“近同态但略有差异”的缺陷，因此不能写成判别阈值已标定。

## 10. 限制与未测

1. 只有一个合成页面、一个浏览器、一个 DPR 和一个字体栈；没有真实站点、真实轮播引擎或真实外部来源。
2. 轮播过渡是 authored CSS 状态，不是按时间采样到的生产轮播帧；动画时序、自动播放和停顿未测。
3. 外部 A/B 是模拟导入；没有真实上传、签名、凭证或信任链。
4. 拼接 tile 来自两次同态重复捕获；没有覆盖任意第三方拼接图、不同工具导出或压缩链。
5. 遮挡是 authored toast 与测量矩形；生产遮挡物发现、半透明遮挡和部分可读区域未测。
6. 几何使用 authored DOM 框；没有从截图自动识别状态、帧或结构。
7. 没有 Figma 写入、OCR、页面规模扩展、人工复核或标注者一致性。
8. 状态签名是精确匹配；近同态、设备旋转、分数 DPR、动画中间帧和时钟/广告等内容变化未测。
9. `composite-conflict`（同状态同版本的重叠像素冲突）没有实例化；只测了 `composite-unknown` 与 `external-conflict`。
10. 权威链是夹具级策略检查，不是生产权限、同意或审计模型。
11. 没有从图片宽度推断视口或 DPR 的代码路径；因此只能证明本解析器未这样做，不能验证外部系统的推断行为。

## 11. 不得宣称

- 不得宣称“多状态参考解析器已通用验证”或“生产就绪”。
- 不得宣称可以从截图像素自动识别轮播帧、滚动位置或缩放状态。
- 不得把不同帧、滚动、缩放、遮挡或过渡拼成一个“原来就如此”的共同真值。
- 不得从图片宽度反推 CSS 视口或 DPR。
- 不得在没有显式 authority 与 supersedes 关系时覆盖、提升或删除旧 reference。
- 不得把 `composite-unknown`、`external-conflict` 或瞬态状态写成 `pass`、`partial pass` 或几何误差。
- 不得把本实验的合成权威链当成真实权限、同意或审计控制。
- 不得把 11 条参考、4 个拼接场景或 16/16 检查外推到真实站点或任意页面规模。

## 12. 证据文件

- `output/_r3_experiments/exp12_reference_states.py`
- `output/_r3_experiments/exp12_reference_states.json`
- `output/_r3_experiments/exp12_reference_state_site/index.html`
- `output/_r3_experiments/exp12_artifacts/`（11 张参考截图）
- `output/_r3_experiments/exp12_state_matrix.png`
- `output/_r3_experiments/exp12_composite_strip.png`
- `output/_r3_experiments/exp12_conflict_map.png`
- `output/_r3_experiments/exp12_overlap_zoom.png`

## 13. 状态与后续

- 本实验状态：`completed-for-current-scope`，不是 `verified`。
- 当前范围：受控状态矩阵、同态重叠/覆盖、混合状态拒绝、显式权威取代与外部冲突。
- 未覆盖：真实站点/轮播时序、真实外部导入、同态重叠冲突、近同态、截图自动状态识别、Figma 写入与人工复核。
- R3 截图轨的 12 项实验与 `R3-EXP-13–15` 补充边界均已完成当前范围；R4 已由用户明确同意并完成 `R4-EXP-01–10` 当前范围。
