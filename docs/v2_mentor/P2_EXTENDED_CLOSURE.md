# P2 扩展收口：字体、移动矩阵与真实站点观测

> 状态：`p2-extended-current-scope`，2026-10-21。  
> 范围：italic、variable named instances、ambiguous platform fallback、320–430 移动矩阵、两个真实站点观测。  
> 结论：italic 与可表示字体实例通过；任意 variable axis 与 ambiguous glyph identity 仍 fail-closed；移动矩阵通过；真实站点只作外部有效性观测。

## 1. Italic / Oblique

实现：

- DOM capture 保留 `fontStyle`；
- DesignSpec 保留 `fontStyle`；
- SVG 输出 `font-style="italic"`；
- Figma bridge 优先选择 `Italic` / `Bold Italic`；
- Figma acceptance 独立检查 italic 请求与实际 face。

真实结果：

- Arial Italic；
- Times New Roman Bold Italic；
- structure/visual/edit 全部通过。

报告：

`output/_p2_figma_italic_font_acceptance_round2/figma_acceptance.json`

```text
status: pass
mean: 2.0478
over30_pct: 2.0422
content_hash: 4859b8bf2253d96dfc5b8a03fecf3c7cc1a5e8951b00335d4c61cdd8f519ce72
```

## 2. Variable font

本机 Figma 暴露 `Segoe UI Variable` 的命名实例，而不是任意 axis：

- `350 -> Semilight Text`；
- `650 -> Semibold Text`；
- `variationSettings` 未由 Figma readback 提供。

实现：

- 非标准 computed weight 写入 `fontWeightValue`；
- DOM/DesignSpec/SVG/Figma 保留数值字重；
- Figma face 选择支持光学/命名实例后缀：`Text / Small / Display`；
- `350` 可映射到 Semilight，`650` 只能落到 Semibold 600，不能证明任意 axis 精确。

诊断报告：

`output/_p2_figma_variable_font_diagnostic_round1/figma_acceptance.json`

```text
status: blocked-fail
mean: 4.9268
over30_pct: 4.3163
content_hash: e9e97c804e94250dce65e23a097021b9c1bcbb26c4383b15bdae32f925c56c22
```

边界：

- 命名实例可支持；
- arbitrary variable axis 不支持精确验证；
- 不把 650→600 写成 variable axis 已复现。

## 3. Ambiguous platform fallback

真实 Chromium 证据：

- Latin glyphs：`Arial / ArialMT`；
- CJK glyphs：`Noto Sans SC / Noto-Sans-SC`；
- DesignSpec 保持 `fontFamily=sans-serif`；
- `fontFamilyResolution=ambiguous-platform-font`；
- 同时保留两组 `platformFonts`。

Figma：

- generic stack 回退到 Inter；
- font dimension 以 `generic-family-resolved-to-concrete-font` fail-closed；
- 不选择一个 face 冒充完整 glyph identity。

诊断报告：

`output/_p2_figma_ambiguous_fallback_diagnostic_round1/figma_acceptance.json`

## 4. 移动宽度矩阵

canonical holder：

- 320×800；
- 375×812；
- 430×932；
- 412×915。

策略：

- 320/375/430 作为 mobile matrix calibration；
- 独立 412 holdout 用冻结的 `p2-figma-mobile-matrix-provisional/1.0` 验证；
- 所有配置保持同尺寸、结构、编辑和资产检查。

真实 Figma：

| 宽度 | 状态 | mean | over30 % |
|---:|---|---:|---:|
| 320 | pass | 2.1463 | 3.2320 |
| 375 | pass | 1.8034 | 2.7356 |
| 430 | pass | 3.0294 | 3.0110 |
| 412 holdout | pass | 1.4576 | 2.2025 |

重点修复：

- 文本节点在更高设计框中的内部垂直居中不再误判为 1px 错位；
- y 容差按盒内剩余垂直空间的一半扩展；
- x、宽度、containment、节点数量、顺序和可见性规则不变。

DPR2 资产：

- canonical 与 Figma 均使用 scale 2；
- 3/3 IMAGE fill；
- 3/3 payload SHA-256；
- replacement/restore probe 通过。

报告：

`output/_p2_figma_dpr2_assets_acceptance_round2/figma_acceptance.json`

## 5. 真实站点观测

本轮只做两个有界观测，不把动态站点当 canonical 硬门禁。

### React

- `https://react.dev/`
- execution：`ready`
- comparison：`equivalent`
- scope：`strict`
- geometry max：`2.0px`
- samples：`5660`

### W3Schools iframe

- `https://www.w3schools.com/html/html_iframe.asp`
- execution：`state-unstable`
- comparison：`inconclusive`
- attempts：2
- WebKit screenshot 超时，字体加载等待未能完成

证据：

- `output/_p2_real_observation_round1/sidecars/P1-S04-R1/pair_summary.json`
- `output/_p2_real_observation_round1/sidecars/P1-S01-R1/pair_summary.json`

### Shoelace shadow DOM

- `https://shoelace.style/`
- execution：`ready`
- comparison：`different`
- scope：`content`
- reason：`observed-structure-divergence`
- geometry：state gate failed，未比较

### Dushu assets

- `https://www.dushu.com/`
- execution：`ready`
- comparison：`equivalent`
- scope：`strict`
- geometry max：`13.0px`
- over 2px：`5/1936`

该 equivalent 只属于当前 comparison profile；较大几何偏差仍必须保留。

证据：

- `output/_p2_real_observation_round2/sidecars/P1-S02-R1/pair_summary.json`
- `output/_p2_real_observation_round2/sidecars/P1-S06-R1/pair_summary.json`

### Firefox

- Playwright Firefox launch：
  `BrowserType.launch: spawn UNKNOWN`
- 状态：`environment-blocked`
- 没有用 Chromium/WebKit 结果替代 Firefox。

## 6. 聚合

Independent Figma holdout：

`output/_p2_figma_holdout_round4/round1.json`

```text
sample_count: 11
pass_count: 10
partial_count: 1
blocked_count: 0
figma_evaluated_count: 11
content_hash: 34bbf5428fac46b9896e566251d92444eac978a305410829eb0bb5a4ddac8a9f
```

该聚合包含 italic 与 mobile 412 holdout；variable/ambiguous diagnostics 和 mobile matrix calibration 不计入 pass。

## 7. 验证

- 全量 unittest：`253/253 passed`；
- five 个 bridge 行为测试通过；
- `ruff check`（新增/改动测试与新增工具函数）、`ruff format --check`、`py_compile`、`node --check`、`git diff --check` 通过；
- 日志：`output/_p2_figma_holdout_round4/unittest-final.log`。

## 8. 仍未覆盖

- 任意 variable axis 的 Figma 精确复现；
- fallback run 的逐 glyph face split；
- Firefox 运行时环境仍为 `spawn UNKNOWN`；
- 登录态、广告、CDN、动态内容下的真实站点稳定复现；
- 跨 Figma 文档、跨机器字体版本。

## 9. 不得宣称

- 不得把命名实例支持写成任意 variable axis 支持。
- 不得把 ambiguous fallback 的 Inter 回退写成 glyph identity 通过。
- 不得把 React 单次 equivalent 写成所有真实站点等价。
- 不得把 Dushu 的 comparison-profile equivalent 写成几何 bbox 完全等价。
- 不得把 W3Schools 的 state-unstable 归因成页面 DOM 差异。
