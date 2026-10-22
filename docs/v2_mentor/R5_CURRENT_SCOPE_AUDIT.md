# R5 当前范围审计（2026-10-19）

> 目的：确认 `R5-EXP-01–06` 的产物、状态、哈希、检查与限制是否一致，并把它们与生产实现边界分开。
> 结论：6/6 实验为 `completed-for-current-scope`；合计 118/118 合同检查通过，123/123 结构化负向变异被拒绝；0 个实验为 `verified`。
> 边界：本审计只读取现有 JSON、文档和索引，复算 canonical hash，检查生产模块接口边界；不重跑实验、不连接 Figma、不修改生产实现。

## 1. 审计状态

| 项目 | 结果 |
|---|---|
| 实验数 | 6 |
| Current-scope | 6/6 |
| Verified | 0/6 |
| 合同检查 | 118/118 |
| 结构化负向变异 | 123/123 拒绝 |
| D39–D44 映射 | 6/6 |
| 生产切片 | 6 个；P0 已 `implemented-current-scope`，P1–P5 blocked |
| 审计结论哈希 | `ff36d2fc9fc51de25c9deae5d58eeac321c4f11e15594e5d2d21ed46adb54162` |

`R5-EXP-02` 的 result 没有 top-level structured mutation object；其确定性 51/51、真实 Figma 23/23 与 30 步重放仍保留在实验文档和 result 中。因此“123 个结构化变异”只统计有统一 `mutations` 结构的实验，不把 EXP-02 的重放次数冒充 mutation。

## 2. 实验审计

| ID | Decision | 范围 | 检查 | 结构化变异 | 哈希前缀 | 生产缺口 |
|---|---|---|---:|---:|---|---|
| `R5-EXP-01` | D39 | 冲突字段默认交付与报告 | 10/10 | 15/15 | `9ed7aba5d2607594` | 真实 Figma 报告、用户理解、业务权威 |
| `R5-EXP-02` | D40 | 写入失败、对账与补偿 | 27/27 | result 无统一对象 | `73a70b5af3445695` | 幂等、ownership、节点删除、权限/并发 |
| `R5-EXP-03` | D41 | DOM/截图字段权威矩阵 | 19/19 | 22/22 | `e954d75a4db5b5b2` | 生产采集接入、跨浏览器/站点、OCR 校准 |
| `R5-EXP-04` | D42 | PARTIAL 与 coverage map | 19/19 | 24/24 | `94f843feb23279dc` | 真实报告、覆盖率、导出 gate、用户理解 |
| `R5-EXP-05` | D43 | 四维验收硬门禁 | 22/22 | 30/30 | `b5cd12d499379712` | 真实检测器、阈值、运行门禁与监控 |
| `R5-EXP-06` | D44 | IR 持久化、TTL、迁移与重放 | 21/21 | 32/32 | `127fe5b3f9ee3c3c` | 生产存储、权限服务、TTL worker、迁移矩阵 |

所有实验：

- `status=completed-for-current-scope`；
- result 的 canonical hash 与文档前缀一致；
- 有 limitations，EXP-03–06 另有显式 boundary；EXP-01/02 的边界由实验文档、`limitations` 与 `not_claimed` 说明；
- 没有 `release_claims.verified=true`，也没有把实验状态写成生产通过。

## 3. 生产模块接口观察

现有主链：

```text
capture_page_with_fallback
  -> 00_screenshot.png / 00_dom.json / page_state
  -> build_direct_design
  -> 12_design.json
  -> RenderingController
  -> PrototypeAdapter
  -> FigmaBridgeAdapter / SVG / Axure / ...
```

关键事实：

- `PreciseAgent._design_and_render` 已负责设计生成、manifest 与渲染；
- `PrototypeAdapter.render_design` 已负责绘制序、clip 与 Auto Layout 容器；
- `FigmaBridgeAdapter` 当前只覆盖 create/frame/text/image/layout/export/readback 等实验动作；
- bridge 仍没有服务端幂等键、可靠 ownership marker、节点级删除、visibility 或 rename；
- 当前 result 没有统一的生产 IR/acceptance/coverage 数据层。

因此不能把 R5 的 JSON 合同直接塞入 `FigmaBridgeAdapter`。第一批实现应是纯合同库，再由证据适配器和交付层逐步接入主链。

## 4. 收口判断

| 结论 | 判断 |
|---|---|
| R5 实验是否完成当前范围 | 是 |
| 是否存在任何 `verified` | 否 |
| 是否可进入生产默认路径 | 否 |
| 纯合同实现切片 P0 | 已实现当前范围，未接默认路径 |
| 是否可开始 P1 evidence adapter | 否，等待真实样本与 retention 决策 |
| 是否应立即改真实 Figma 写入 | 否 |
| 是否应立即建设生产 TTL/存储 | 否 |
| 是否应先做跨浏览器检测器标定 | 否 |

## 5. 决策到生产的拆分

| Decision | 实验已证明 | 生产仍缺 |
|---|---|---|
| D39 | 未决字段不入正文、报告与 manifest 可分离 | 真实报告 Frame、业务权威、用户理解 |
| D40 | 逻辑提交、resume、对账、补偿合同 | 服务端幂等、ownership、节点能力、真实故障/并发 |
| D41 | 字段级权威与截图候选边界 | 生产采集/融合、跨浏览器、真实站点、检测校准 |
| D42 | PARTIAL、四种空缺、coverage map、固定分母 | 真实覆盖计算、报告 Frame、导出 gate |
| D43 | 四维状态、关键项闭包与三种发布 profile | 真实检测状态、阈值、监控与审批 |
| D44 | 文件级持久化、TTL、迁移、三种 replay | 生产数据库/对象存储、权限、迁移矩阵、保留政策 |

## 6. 审计检查

14/14 通过：

1. 六个 result 存在；
2. 六份实验文档存在；
3. 六个状态均为 current-scope；
4. 六个 canonical hash 可复算且匹配文档前缀；
5. 所有合同检查通过；
6. 结构化变异全部拒绝；
7. limitations / not-claimed 保留；
8. 没有 verified 提升；
9. 根与 mentor index 链接全部六个实验；
10. open-items 标记六个实验全部完成当前范围；
11. D39–D44 都有实验与生产切片映射；
12. P0 为 `implemented-current-scope`，模块与测试文件存在；
13. 所有未 ready slice 都有 blocker 与 dependency；
14. 审计保持离线且未修改生产源码。

审计脚本另有 8/8 元变异被拒绝，覆盖伪造 verified、删除 status、破坏 hash、错误提升第二个 slice、清空 blocker 等。

## 7. 复算

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\r5_closeout_audit.py
```

产物：

- `output/_r5_closeout/result.json`
- `output/_r5_closeout/production_slices.json`
- `output/_r5_closeout/r5_closeout_matrix.png`
- `output/_r5_closeout/r5_production_slices.png`

## 8. 不得宣称

- 不得把本审计写成实验重新验证或外部真值复核。
- 不得把 118/118、123/123 写成生产成功率。
- 不得因为 R5 六项全部 current-scope 就修改默认渲染路径。
- 不得把 `ready-to-implement` 写成已实现。
- 不得把 P0 的候选模块路径写成已批准架构决定。
