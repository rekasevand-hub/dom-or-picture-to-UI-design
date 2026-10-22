# P1 有限 frame barrier A/B

> 状态：`completed-for-current-scope`，2026-10-20。实验能力，默认关闭，不接生产采集、默认渲染或 Figma 写入。

## 1. 目标

验证 barrier 是否减少以下采样时序假差异：

- 两端 frame tree 采样顺序不同；
- 一端仍处于 frame 导航；
- 子文档内容在 DOM 快照前继续变化；
- 两端到达采样点时 document generation 不同。

不试图同步广告投放、opaque frame 内部内容、会话、实验分组或浏览器能力。

## 2. 实现

`src/app/services/structure/frame_barrier.py`：

- `frame_tree_key()` 只保留可渲染 frame；
- `compare_frame_trees()` 比较 path、URL、导航态、可访问性、opaque 原因和宿主几何；
- `FrameBarrierGate` 让两个 capture worker 在一次采样点会合，最多等待固定预算。

`scripts/p1_dual_browser_capture.py --frame-barrier`：

- 在最终 DOM 快照前记录一次可渲染 frame tree；
- 两端会合后比较；
- `synchronized=false` 或超时写入 `frame-barrier-mismatch`，执行态为 `state-unstable/inconclusive`；
- `synchronized=true` 但 tree 不同写入 `frame-barrier-divergence`，执行态仍 ready，比较结果为 `different`；
- 默认关闭，只有显式参数启用。

## 3. 固定预算 A/B

`scripts/p1_frame_barrier_experiment.py` 对 S01/S03 使用相同预算：

- 最多 3 次 attempts；
- 页面导航预算 15000ms；
- barrier 会合预算 3000ms；
- 首次 execution-ready 成对结果接受。

报告：`output/_p1_frame_barrier/experiment_round1.json`。

## 4. 结果

| 样本 | 无 barrier | 有 barrier | 结论 |
|---|---|---|---|
| S01 | `capture-failed/inconclusive` | `navigation-failed/inconclusive` | barrier 没有形成可靠共同参考，广告/frame tree 仍不同 |
| S03 | `ready/different` | `ready/different` | 结果仍为 different，但文本时序差明显减少 |

S03 细节：

| 指标 | 无 barrier | 有 barrier |
|---|---:|---:|
| Chromium/WebKit 文本数 | 477 / 505 | 477 / 477 |
| 文本节点覆盖 | 75.11% | 100% |
| Chromium/WebKit 节点数 | 716 / 917 | 716 / 685 |
| 比较结果 | different | different |
| 耗时 | 88.69s | 113.94s |

barrier 在第 2 个 attempt 的同一尝试内会合，确认 frame tree 仍不同。它消除了 S03 的文本采样差，但没有把 node/frame 结构差变成等价，也没有把样本变成 strict。

S03 额外耗时约 25.25s，约增加 28.5%。

`false_equivalence_detected=false`：没有出现 barrier 未匹配却判 equivalent 的情况。

## 5. 判断

barrier 对 S03 有明确的观测收益：文本差从 28 条降到 0，覆盖从 75.1% 升到 100%。这说明一部分差异确实来自采样时序。

但：

- 比较结果仍是 `different`；
- node 和 frame tree 仍有真实差异；
- S01 没有受益；
- 成本明显上升；
- 屏障不能同步 opaque frame 内部内容。

因此当前决定：

1. 保留 `--frame-barrier` 作为实验诊断能力。
2. 不接默认路径。
3. 不继续泛化增加 barrier timeout 或覆盖所有样本。
4. 后续只在需要估计“采样时序差占比”的样本上显式使用。

## 6. 测试

- 全量 unittest `106/106` 通过。
- 覆盖 tree 匹配、URL/几何/路径差异、未渲染 frame 排除、会合超时、同步但 divergent、首次 ready 重选和 A/B 漂移指标。

## 7. 不得宣称

- 不得把 barrier 写成广告同步或 opaque frame 内容同步。
- 不得把同步会合写成页面等价。
- 不得因为 S03 文本覆盖达到 100% 就声称 strict 通过。
- 不得把 `frame-barrier-divergence` 写成 `inconclusive`。
