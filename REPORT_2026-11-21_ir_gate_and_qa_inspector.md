# design-ir/2.0 生产闸门 + 只读 QA 巡检（2026-11-21）

> 两条工程底座：**所有生产出口统一过 `design-ir/2.0`**，以及**独立的只读找茬工具**。
> 纯 CV 视觉基线不动：七页 `94.34 / 91.37 / 7.571`，冻结红线 `13/6/10/14/9/3/6`，
> 单测 **1719 passed / 8 skipped / 0 failed**。

---

## 一、`design-ir/2.0` 生产闸门

### 1.1 一个出口，两个产物

新增 `src/app/services/contracts/production_gate.py`：`gate_design_for_output()`。

* 输入：`12_design.json`（或其等价 DesignSpec）+ 目标后端；
* 产出：`13_design_ir.json`（output-neutral 投影）与 `13_degradations.json`
  （目标端带不动的特性，带节点 id）；
* 默认**记账不阻断**；`--strict-ir` 时契约违规 → 非零退出（脚本侧 exit 3），
  且**先落盘再抛**，失败也有证据。

`13_degradations.json` 同时给两样东西：`degradations`（本稿真的要降级的）与
`target_gaps`（目标端一共缺哪些能力）。后者让"空账本"不再等于"没检查"。

### 1.2 接入点（消灭绕过）

| 入口 | 覆盖面 | 落盘位置 |
|---|---|---|
| `scripts/image_figma_mvp.py` | `--route physical`，`--tool figma` / `--tool axure` | `<out>/13_*.json` |
| `src/app/agents/precise_agent.py` | `--route dom`（单页 `run()` 与多页 `run_many()`） | `<out>/13_*.json`（多页还有各页子目录） |
| `scripts/axure_dom_output.py` | 另一个 axure 入口（`image_axure_mvp.py` 也走它） | 同名同形的两份账本 |

`--strict-ir` 已从 `src/main.py` 与 `scripts/image_figma_mvp.py` 暴露。

### 1.3 `--tool axure` 不再是"渲染完就完事"

`_emit_axure()` 的链路：闸门 IR → `plan_axure_route(ir=…)`（节点/资源哈希校验）
→ 生成 `.rp` → `evidence.inspect_rp` + `compare_rp_to_design` →
`--generate-twice` 逐字节比对 → `artifact_report.json`。任何一项不过即非零。

`precise_agent` 侧同样补了 `_verify_axure_output()`：dom 路线用 axure 输出时，
渲染完立刻只读回读，写 `axure_evidence.json`。

### 1.4 实测（`--route physical --tool axure --generate-twice`）

| 页 | 页/控件/资源 | self_check | integrity | comparison | 两次逐字节 | sha256 |
|---|---|---|---|---|---|---|
| FluxWeaver | 1 / 119 / 13 | ✅ | ✅ | ✅ | ✅ | `461aad1ad6c4cd13…` |
| marketplace | 1 / 68 / 2 | ✅ | ✅ | ✅ | ✅ | `9182833d2bb8f7b9…` |

`13_degradations.json` 摘要：

| 页 | 帧/节点 | 降级特性 | 影响节点 | can_claim_complete |
|---|---|---|---|---|
| FluxWeaver | 1 / 118 | `auto-layout → fixed-coordinate` | 7 个容器 | false |
| marketplace | 1 / 67 | `auto-layout → fixed-coordinate` | 6 个容器 | false |

顺带修了一个"账本永远为空"的老问题：`_node` 过去只在 `layout.status == verified`
时才声明 `auto-layout`，而物理链路的帧只有 `mode/source`，于是 7 个帧在 Axure 里被
排成固定坐标这件事从来没被记过账。现在"带着布局规格 + 有成员"就声明，
账本才第一次说出了真话。

**Figma 端**：同一份闸门接进主链后，FluxWeaver `95.30 / 5.331`、AtomGit
`91.43 / 10.334`、marketplace `95.12 / 6.653`，与接入前逐字节相同；
七页红线 `13/6/10/14/9/3/6` 未动。

---

## 二、只读 QA 巡检 `scripts/vlm_qa_inspect.py`

### 2.1 只做三件事：点名、证实、归桶

```
VLM 全图并排巡检（一次调用，最多 3 处）
   ↓
像素证实（still_missing + 墨点密度）→ missing / present / unjudgeable
   ↓
四桶归因
```

* `perception-miss`：原图有墨、渲染无墨，且设计里**没有节点**覆盖该框；
* `emitter-drift`：设计有节点，渲染无墨；回读能进一步区分
  `absent-in-target` / `displaced(dx,dy)` / `present（裁切遮挡）`；
* `planned-degradation`：该节点在 `13_degradations.json` 里被点过名，写明特性与 fallback；
* `style-mismatch`：两边都有墨——**不是缺字，是字号/字重/颜色/间距**。

第三态 `unjudgeable` 很关键：一块 320×30 的框里只有 38 个墨点（0.4%），那不是一行字，
是邻字的尾巴扫进来了。这种框既不判"缺"，也不判"在"，报告里单列——不硬凑证据。

**只读保证**：脚本只读 `--ref/--rendered/--design/--ir/--degradations/--readback`，
只写 `--out` 下的三个文件，不碰设计稿、不进闭环、不回滚。单测里直接断言
设计文件字节未变。

### 2.2 产物

`qa_report.json`（机器可读，含每条的证据：墨量、ink_share、ink_state、回读状态）、
`qa_report.md`（分桶表 + 逐条表）、`qa_overlay.png`（按桶着色、编号、左上角带底框的图例）。

overlay 修了两处画图 bug：①画布全程 RGB、落盘改走 PIL（原先交给 `cv2.imwrite`，二进制被当 BGR 读，整页与标注的 R/B 通道一起对调——FluxWeaver 蓝按钮变红、marketplace 红价签变蓝）；②图例先铺白底+灰描边再写字（原先四行字直接压在页面 Logo 上）。桶色同时按 RGB 重写，屏幕上看到的就是原来的红/橙/紫/蓝。

### 2.3 三页实测（最新 Figma 导出）

| 页 | 点名 | perception-miss | emitter-drift | planned-degradation | style-mismatch | dismissed | unjudgeable |
|---|---|---|---|---|---|---|---|
| FluxWeaver | 3 | 0 | 0 | 0 | 3 | 1 | 2 |
| AtomGit | 3 | 0 | 0 | 0 | 3 | 3 | 0 |
| marketplace | 3 | 0 | 0 | 0 | 3 | 3 | 0 |

结论和上一轮的实证一致：**三页没有一处"设计有、导出没有"**，被点名的全是样式偏差
（典型是 11.5px 的表格正文与 17px 的标题）。上一轮巡检报的 6 处"缺字"，现在被
`still_missing` + 密度门槛逐一证伪，直接归到 `style-mismatch`——不再产生"去补一个
本来就在的节点"的坏工单。

---

## 三、验收

* 全量单测 **1719 passed / 8 skipped / 0 failed**（本轮新增 15 条：
  闸门 6、axure 生产分支 2、QA 7）；
* 七页冻结基准 **13/6/10/14/9/3/6** 零变化；
* 三页 Figma 分数与上一轮逐字节相同（95.30 / 91.43 / 95.12）；
* `--route physical --tool axure --generate-twice` 两页全绿、逐字节一致。

---

## 四、已知限制 / 下一步

1. **多页 + axure 的闸门**：`run_many` 已过闸门，但每页子目录的 `13_*` 与合并稿的
   `13_*` 是两份；多页设计当前只做一次投影，页级降级汇总还没按页拆开。
2. **`13_degradations` 只覆盖能力降级**，不含"资源未渲染"（`asset_render_summary`
   在 `route.json` 里）——是否并进同一账本，取决于下一轮要不要单一账本。
3. **QA 巡检的召回取决于一次 VLM 调用**：`--max-defects` 默认 3，超过 3 处的页面
   需要多次调用；脚本目前只跑一轮。
4. **`emitter-drift` 在真实三页里是 0**：不是没实现，是确实没有节点丢失。
   单测里用合成样本覆盖了这条路径（含 `displaced` 与 `absent-in-target`）。
