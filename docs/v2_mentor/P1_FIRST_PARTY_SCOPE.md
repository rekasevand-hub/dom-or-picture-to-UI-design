# P1 第一方 frame scope 与 S07 feature-shim 轮次

> 状态：`completed-for-current-scope`，2026-10-20。两个能力都是显式实验，不接默认采集，不改变旧 strict 基线，也不构成新的生产验收。

## 1. 第一方 frame profile

Profile：`first-party-frame-strict/1.0`。

规则：

- 主文档正常加载；
- 同源可访问 iframe 继续递归采集；
- 跨源 frame 的 document 请求在浏览器路由层显式中断；
- frame 宿主、尺寸、sandbox、导航和 opaque 边界仍保留在 inventory；
- 被中断 URL 写入 `frame_request_policy`，便于审计；
- 只有显式参数 `--first-party-frame-profile` 启用。

这不是“广告加载失败后碰巧相同”，而是单独声明了排除对象和请求策略的 scope。

## 2. 固定预算 A/B

S01/S03/S05 使用相同预算：

- 最多 3 次 attempts；
- 页面导航预算 15000ms；
- 首次 execution-ready 成对结果接受；
- full-visible 和 first-party 分别运行。

报告：`output/_p1_first_party_scope/experiment_round1.json`。

| 样本 | full-visible | first-party | frame document blocked |
|---|---|---|---|
| S01 | `capture-failed/inconclusive` | `capture-failed/inconclusive` | 26 |
| S03 | `ready/different` | `ready/different` | 26 |
| S05 | `ready/different` | `ready/different` | 26 |

汇总：

- full-visible：different 2、inconclusive 1、equivalent 0；
- first-party：different 2、inconclusive 1、equivalent 0；
- false equivalence：0。

S01 没有形成 execution-ready 对，因此没有把它误标成 first-party profile 结果。

## 3. S03 的变化

| 指标 | full-visible | first-party |
|---|---:|---:|
| 节点数差 | 690 | 31 |
| 文本数差 | 477 | 1 |

跨源 frame document 是 S03 的主要噪声来源之一。显式中断后，帧和文本差显著缩小，但仍存在：

- 1 条动态 glyph 文本差；
- 剩余 node/structure/frame 差异；
- 最终比较仍为 `different`。

因此 first-party profile 当前只能作为诊断和独立 scope 候选，不能写成旧 strict 等价。

## 4. S05

S05：

- full-visible 节点差 33、文本差 0；
- first-party 节点差 33、文本差 0；
- 两者均为 `ready/different`。

说明该样本的剩余差异不是跨源 frame document 噪声主导。

## 5. S07 feature-shim 尝试

第二轮和第三轮增加以下受控条件：

- Chromium `password-credential-off`；
- WebKit `password-credential-on`；
- Chromium `conditional-mediation-off`。

同时保留 native UA 与交叉 UA 条件。

结果：

- round2：21 个会话，仅 1 个有效；
- round3：单 worker 重跑，21 个会话，仍仅 1 个有效；
- 其余均因 GitHub 导航预算内未提交非空文档而无效；
- 无效会话不参与“文案缺失”统计；
- 汇总只能是 `session-variation`，不能强化或推翻第一轮的 `engine-conditioned-candidate`。

文件：

- `output/_p1_engine_conditions/s07_condition_probe_round2.json`
- `output/_p1_engine_conditions/s07_condition_probe_round3.json`

第一轮 12/12 有效结果仍保留：

- 四项文案随 engine 稳定出现/缺失；
- UA swap 未改变结果；
- 当前仍是 engine-conditioned candidate，不是已确认根因。

2026-10-20 后续先跑串行 native 导航门：Chromium/WebKit 均 HTTP 200、`navigation=ok`、valid。导航恢复后做 round4 小批 1 repeat × 7 条件：

- 7/7 observation 有效；
- Chromium `password-credential-off`：四项文案仍存在；
- WebKit `password-credential-on`：四项文案仍缺失；
- Chromium `conditional-mediation-off`：四项文案仍存在；
- `feature_dependency_candidate=false`，继续只保留 `engine-conditioned-candidate`。

恢复门证据：`output/_p1_engine_conditions/s07_navigation_recovery_round1/`；round4：`output/_p1_engine_conditions/s07_condition_probe_round4.json`。

## 6. 测试与边界

- 全量 unittest `173/173` 通过。
- 覆盖跨源 document 显式中断、同源子文档保留、profile 不覆盖旧 scope、wrong-profile equivalent 拒绝、UA/feature/session 候选分离、无效会话隔离与独立 frame boundary scope。
- 默认采集仍加载跨源 frame document。
- 未实现生产 route policy、新 scope 发布、对象存储/TTL 或 Figma 写入。

## 7. 下一步

1. first-party 与 full-visible 的独立 frame-boundary comparison 已实现，authored holdout 已 9/9，见 `P1_RENDERED_FRAME_BOUNDARY.md`。
2. S07 round4 已在导航恢复后完成，feature shim 未改变结果；下次先重复 native gate，保持 candidate。
3. S06 navigation timeline 已单独完成；轻量 navigation-only probe 已补，2 attempts × 2 engines、4/4 observation 有效，不做 DOM 差异判断。
4. 新 scope 继续并列展示旧 full-visible 结果、排除 URL、不可观测项和独立分母。

## 8. 不得宣称

- 不得把 first-party profile 写成 full-visible strict。
- 不得把跨源 frame document 被阻断写成内部内容已比较。
- 不得把 S03 的节点/文本差缩小写成 equivalent。
- 不得用 S07 的无效会话证明 feature detection 或浏览器能力根因。
- 不得把 round4 的 feature shim 无变化写成 feature 或浏览器能力根因已确认。
