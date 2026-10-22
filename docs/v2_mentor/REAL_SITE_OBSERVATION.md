# 真实站点长期观测

> 任务 ID：`RS-LONG-01`  
> 状态：`independent-running`  
> 启动日期：2026-10-21  
> 关键规则：真实站点观测与 P3/P4 并行推进，但不进入生产准入分数，也不能抵消任何 canonical 硬门禁失败。

## 1. 目的

观测外部有效性：

- 页面是否可导航到稳定状态；
- DOM/可见文本/几何在冻结 comparison profile 下是否可比；
- 失败来自 navigation、state、capture、structure divergence 还是资源变化；
- 同一站点在不同时间是否保持可复现。

该任务不回答：

- P3/P4 是否可以生产发布；
- 所有真实站点是否等价；
- 登录态、广告、A/B 实验和 CDN 变异已被消除；
- Firefox 已覆盖。

## 2. 样本

| ID | 站点 | 主要用途 |
|---|---|---|
| `P1-S02-R1` | React | hydrated content / 动态页面 |
| `P1-S06-R1` | Dushu | 图片、目录和真实页面几何 |
| `P1-S02-R1`（Shoelace 独立轮次） | Shoelace | open shadow DOM |
| `P1-S01-R1` | W3Schools iframe | iframe、canvas、state instability |

Firefox 仍因 `BrowserType.launch: spawn UNKNOWN` 标记为 `environment-blocked`。

## 3. 冻结 Profile

观测必须记录并保持：

- URL 与最终 URL；
- Chromium/WebKit 版本；
- viewport、DPR、locale、timezone；
- navigation、network-idle 和字体等待策略；
- timeout、attempt 数和禁止挑选有利轮次的规则；
- state signature / comparison scope；
- 是否允许真实 session。

每次轮次必须保存 `run_summary.json`、`pair_summary.json`、capture attempts、DOM、page state、screenshot 和 sidecar。

## 4. 推荐运行

单样本 Chromium：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_sample_runner.py `
  --registry docs\v2_mentor\p1_sample_registry.json `
  --only P1-S02-R1 `
  --source-kind real `
  --browser-engine chromium `
  --allow-real-session `
  --sample-root output\_rs_long\P1-S02-R1\chromium\samples `
  --sidecar-root output\_rs_long\P1-S02-R1\chromium `
  --overwrite
```

WebKit 使用同一 registry、sample id 和冻结 profile，只替换：

```text
--browser-engine webkit
```

汇总既有 sidecar：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_real_pair_matrix.py `
  --sidecar-root output\_rs_long `
  --out output\_rs_long\pair_matrix.json
```

## 5. 节奏

- 每周至少一次：按冻结 profile 跑指定样本；
- 每次轮次使用新的时间戳目录与 run id，不覆盖旧证据；
- 站点结构变更或连续两次异常时增加一次人工复核；
- 季度审计：更新浏览器版本、选择器和 profile，并显式建立新版本，不静默改旧阈值；
- 只有冻结 profile 内的重复结果才可标记 `stable-for-profile`。

## 6. 结果分类

- `ready + equivalent`：只对当前 profile 有效；
- `ready + different`：保留结构/几何差异原因；
- `state-unstable`：不比较字段；
- `navigation-failure`：记录最终 URL、错误和尝试次数；
- `capture-failure`：记录浏览器/超时/资源原因；
- `environment-blocked`：不得用其他浏览器替代。

## 7. 门禁隔离

- 真实站点状态不写入 P3/P4 production admission score；
- 不因真实站点通过而覆盖 canonical visual/structure/edit/asset 失败；
- 不因真实站点失败而自动阻断 canonical holdout；
- 任何需要成为硬门禁的规则，必须先形成独立、冻结、可复现的合同。

## 8. 当前基线

- React：`equivalent`（当前 profile）；
- Dushu：`equivalent`（当前 profile，geometry max 13px，5/1936 over 2px）；
- Shoelace：`structure different`；
- W3Schools iframe：`state-unstable / inconclusive`；
- Firefox：`environment-blocked`。

历史证据：

- `output/_p2_real_observation_round1/`
- `output/_p2_real_observation_round2/`

### RS-LONG-01 Round 1

2026-10-21 独立重跑 `P1-S04-R1`（React）：

| 引擎 | page state | 状态 | unknown | content hash |
|---|---|---|---:|---|
| Chromium | content | ok | 3 | `7f69201bb62c7dc4d849b57c5bc6ff71163b5ef300aeab096ed2c637da590d02` |
| WebKit | content | ok | 3 | `f2f1bdaffecf5ca783f1a6068586b1ecbcf8d2d0c047fa9f35f44fb47a7a1c80` |

跨浏览器结果：

- comparison scope：`strict`；
- state comparable：`1/1`；
- text alignment：`322/322`，coverage `1.0`；
- geometry aligned：`true`；
- `default_path_changed=false`、`figma_write=false`。

证据：

- `output/_rs_long_round1/`
- `output/_rs_long_round1_webkit/`
- `output/_rs_long_round1/cross_browser_react.json`

该结果只说明本轮冻结 profile 下 React 可复现，不升级为生产准入门禁。
