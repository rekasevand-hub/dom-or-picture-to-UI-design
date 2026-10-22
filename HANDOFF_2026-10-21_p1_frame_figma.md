# HANDOFF - P1 frame holdout 收口与 Figma bridge 真实回放

**日期：** 2026-10-21  
**工作目录：** `D:\LLM-Data\Figma_auto_agent`  
**分支：** `feature/precise-agent-router`  
**状态：** frame holdout 已在当前 canonical scope 收口；Figma canonical frame 与 canonical assets 已通过独立四维验收；Auto Layout 父级传播 probe 已通过；其他 Figma 样例仍待验证  
**仓库状态：** 未 commit、未建分支；工作树有大量本轮之前就存在的 modified/deleted/untracked 文件

---

## 1. 一句话状态

在当前固定 Chromium canonical 环境中，5 个独立视觉 holdout 已全部通过，frame 从 `mean=4.3294 / bad pixels=16697` 降到 `mean=0.0011 / bad pixels=12`。真实 Figma canonical frame 四维通过；canonical assets 也全部通过，3/3 Figma fill payload SHA-256 与 DesignSpec 本地图片一致；Auto Layout 编辑后 sibling 与 parent 均真实重排并恢复。Chromium `sans-serif` 已通过平台字体证据解析为 Microsoft YaHei。

---

## 2. 新会话必读顺序

1. `HANDOFF_2026-10-21_p1_frame_figma.md`：本文件，当前状态与下一步。
2. `docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md`：产品目标、canonical 环境、全部修复与边界。
3. `docs/v2_mentor/P1_EVIDENCE_ADAPTER.md`：P1 样本、证据 adapter、历史 strict 与 boundary 背景。
4. `docs/v2_mentor/P1_FIGMA_ACCEPTANCE.md`：Figma 四维验收、字体 provenance、编辑与资产探针。
5. `output/_p1_canonical_visual_holdout_round16/round1.json`：最终 5 例视觉 holdout。
6. `output/_p1_canonical_output_fidelity_round17/round1.json`：最终 6 例 calibration。
7. `output/_p1_figma_acceptance_frame_round14/figma_acceptance.json`：canonical frame 当前 Figma 四维报告。
8. `output/_p1_figma_assets_acceptance_round3/figma_acceptance.json`：canonical assets 当前 Figma 四维报告。
9. `output/_p1_figma_autolayout_edit_probe_round1/figma_autolayout_edit_probe.json`：Auto Layout 父级传播 probe。
10. `output/_p1_figma_holdout_round1/round1.json`：5 个 Figma holdout 的独立聚合报告。

导师已确认的产品方向：

- 主目标是固定 Chromium canonical 参考下的实际 SVG/Figma 输出正确性。
- SVG 和 Figma 分开验收。
- 跨浏览器 full-visible strict 保留历史定义和诊断价值，但实时 `3/7` 不再是产品硬门禁。
- 视觉通过不能补偿内容、结构、编辑或资产失败。
- 不使用单一 composite score。

---

## 3. Canonical 运行基线

| 项目 | 当前值 |
|---|---|
| Engine | Chromium |
| Browser build | `151.0.7922.34` |
| OS | Windows 11 `10.0.26300` |
| Viewport | `900 x 700` |
| DPR | `1` |
| Locale | `zh-CN` |
| Timezone | `Asia/Shanghai` |
| Headless | `true` |
| Python | `C:\Users\lzq\.conda\envs\omni\python.exe`，Python `3.12.0` |
| Capture contract | `capture_page_with_fallback+dom-direct-svg` |

字体文件及 SHA-256 记录在 calibration 报告的 `environment.font_files` 中，包括 Segoe UI、Microsoft YaHei、Arial 和 SimHei。

当前结论只适用于这套环境和这些 authored/controlled 样例，不能外推到所有真实站点。

---

## 4. 本轮完成的实际修复

### 4.1 单行 browser-measured text 基线

问题：

- 浏览器实测单行文本被送入多行 `tspan` 路径后，没有 computed `lineHeight` 时按 `1.4em` 估算。
- 16px Times New Roman 段落因此整体下移约 3px。

修复：

- 保留浏览器实测断行，避免二次估宽。
- 单行 measured line 在 `lines_spec_fields()` 中使用 `textEmBox` 的真实行框高度。
- 标量文本在没有 computed `lineHeight` 时，也可使用 measured first-line height 和对应的基线修正。

相关文件：

- `src/app/services/rendering/text_wrap.py`
- `src/app/services/rendering/svg_adapter.py`
- `src/app/services/som/direct_design.py`

### 4.2 iframe 默认 inset border

问题：

- Chromium iframe 默认样式是 `border: 2px inset rgb(0,0,0)`。
- 旧输出只保留 `borderWidth/borderColor`，最终画成黑色实线；reference 实际是内侧深灰/浅灰 bevel。

修复：

- DOM 采集新增 uniform non-solid `borderStyle`。
- Style 合同只透传当前能正确表达的 `inset / outset / groove / ridge`。
- SVG 输出四段内侧 edge band。
- Figma 输出一个透明 FRAME 加四个边带矩形，避免单色 stroke 抹平 bevel。
- Chromium 黑色 2px inset 的 canonical 边色归一为 `#9a9a9a` 和 `#eeeeee`。

相关文件：

- `src/app/services/structure/capture.py`
- `src/app/utils/style_utils.py`
- `src/app/services/structure/providers/dom.py`
- `src/app/services/som/direct_design.py`
- `src/app/services/rendering/svg_adapter.py`
- `figma_bridge/code.js`

注意：

- `double` 当前没有正确渲染支持，因此没有写入 `borderStyle` 合同。
- 非均匀边框仍走已有的 `edges` 路径；bevel 的逐边 style 还没有完整建模。

### 4.3 iframe 子文档 content-box 偏移

问题：

- iframe 子文档坐标以 content box 为原点。
- 旧合并只加 host border box 的 `x/y`，漏掉了 host border。

修复：

- DOM 记录 host 的 `borderTopWidth/borderLeftWidth`。
- 合并可访问子文档时把 host border 计入 offset。
- 新增带默认 2px iframe border 的回归用例。

相关文件：

- `src/app/services/structure/capture.py`
- `src/app/services/structure/frames.py`
- `tests/v2/test_p1_frame_capture.py`

### 4.4 srcdoc 默认字体

问题：

- canonical fixture 中 `srcdoc` 子文档的 computed `fontFamily` 报告 `"Times New Roman"`。
- Chromium 实际文字宽度匹配 generic sans-serif。
- 直接信任 computed family 会让子文档文字窄约 28px。

修复：

- 对 `about:srcdoc` 且没有显式 inline `font-family` 的默认 Times New Roman 文本，采集时归一为实际生效的 `sans-serif`。
- SVG 子文档文本因此与 reference 的 bbox 对齐。
- Figma 中 `sans-serif` 仍由插件字体探测回退到本机可用字体；最新运行选择 `Inter Regular`。

相关文件：

- `src/app/services/structure/capture.py`
- `figma_bridge/code.js`

边界：

- 这个规则只处理当前确认的 srcdoc 默认字体行为，不是通用字体识别器。
- 显式 stylesheet 字体来源仍未逐条追踪。

### 4.5 Figma replay 回读证据

`scripts/figma_replay.py` 现在除导出 PNG 外，还会保存：

- `readback_tree.json`
- `font_report.json`
- `figma_render.png`
- `figma_compare.png`
- `figma_diff.png`

相关文件：

- `scripts/figma_replay.py`
- `src/app/services/rendering/figma_adapter.py`

---

## 5. 结果与证据

### 5.1 Frame holdout progression

| 阶段 | mean | bad pixels | 说明 |
|---|---:|---:|---|
| round5 | 4.3294 | 16697 | 单行基线回归，iframe 黑色实线 |
| round9 | 0.91 | 3748 | 四段 inset bevel |
| round11 | 0.87 | 3685 | exact bevel colors |
| round12 | 0.54 | 2187 | srcdoc 默认 sans-serif |
| round14 | 0.0011 | 12 | measured h1 基线与最终收口 |

最终报告：

`output/_p1_canonical_visual_holdout_round14/round1.json`

最终 frame：

```text
policy_id: frame-v1
status: pass
mean: 0.0011359026369168357
ink_mean: 0.06931407942238267
over30_pct: 0.002028397565922921
bad_pixel_count: 12
excluded_region_pixel_count: 38400
```

仍然不能写“逐像素完全等价”：还有 12 个非遮蔽差异像素。

### 5.2 完整 holdout

最终汇总：

```text
SVG: 5 pass / 0 partial / 0 fail
visual: 5 pass / 0 fail
composite_score_used: false
figma_evaluated_count: 0
```

最终报告：

`output/_p1_canonical_visual_holdout_round14/round1.json`

### 5.3 Calibration

最终 calibration：

```text
6 samples
SVG: 5 pass + 1 partial
failed: 0
Figma evaluated: 0
```

关键指标：

| 样例 | mean | ink_mean | over30% | bad pixels |
|---|---:|---:|---:|---:|
| assets | 0.00 | 0.00 | 0.00 | 0 |
| iframe | 0.27 | 14.97 | 0.16 | 1017 |
| text-flow | 0.73 | 15.25 | 0.76 | 4788 |
| font-fallback | 0.00 | 0.00 | 0.00 | 0 |
| transparent-crop | 0.04 | 1.36 | 0.05 | 326 |
| partial-asset | 0.64 | 18.75 | 0.48 | 3032 |

`partial-asset` 继续是 partial，不能因为其他指标通过而升级。

最终报告：

`output/_p1_canonical_output_fidelity_round16/round1.json`

---

## 6. Figma 当前状态

### 6.1 Bridge

当前服务：

```text
ws://localhost:8765
```

最后一次检查：

- `127.0.0.1:8765` 与 `[::1]:8765` 在监听。
- 插件连接为 Established。
- 当前后台 bridge PID 为 `3652`。

启动命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m src.app.services.bridge_server
```

如果需要后台启动：

```powershell
$out = 'output\_p1_figma_bridge'
New-Item -ItemType Directory -Force -Path $out | Out-Null
Start-Process `
  -FilePath 'C:\Users\lzq\.conda\envs\omni\python.exe' `
  -ArgumentList @('-m','src.app.services.bridge_server') `
  -WorkingDirectory 'D:\LLM-Data\Figma_auto_agent' `
  -WindowStyle Hidden `
  -RedirectStandardOutput "$out\bridge.stdout.log" `
  -RedirectStandardError "$out\bridge.stderr.log"
```

如果日志显示服务已监听但 plugin 未连接，在 Figma Development 里重新 Run/Reload 本仓库插件。

### 6.2 最小真实烟测

命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_readback_smoke.py `
  --out output\_p1_figma_smoke_round2
```

结果：

- frame/text/rectangle/image 四类节点真实写入。
- `get_node_tree` 回读正常。
- PNG 导出正常。
- `12/12` checks 通过。
- `status=completed-for-current-scope`
- `content_hash=c239f4e8f59795ad8b7e90e9e9faeb0415d60de2541abeab771a0fab8afed74d`

报告：

`output/_p1_figma_smoke_round2/figma_readback_smoke.json`

### 6.3 Canonical frame 真实回放

命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_replay.py `
  --out output\_p1_figma_canonical_frame_round1 `
  --design 12_design.json `
  --scale 1
```

当前结果：

```text
mean: 2.088 / 255
ink_mean: 88.560
over30: 1.97%
canvas: 900 x 700
text nodes: 5
iframe host FRAME: 2
bevel border rectangles: 8
```

证据：

- `output/_p1_figma_canonical_frame_round1/figma_render.png`
- `output/_p1_figma_canonical_frame_round1/figma_compare.png`
- `output/_p1_figma_canonical_frame_round1/figma_diff.png`
- `output/_p1_figma_canonical_frame_round1/readback_tree.json`
- `output/_p1_figma_canonical_frame_round1/font_report.json`

当前 Figma 字体解析：

- Times New Roman / Regular
- Times New Roman / Bold
- Arial / Bold
- `sans-serif` 未在本机直接命中，回退 Inter / Regular

当前 Figma 页面残留：

- `SmokeB Root`
- `Screen 900×700 · 6/11 (100%)`
- 最后一次 canonical replay 的画板 id 为 `23:85`
- 最后一次 smoke 的根 frame id 为 `23:81`

这些是真实测试节点，不要在没有确认用途时批量删除。

### 6.4 Figma 不能宣称什么

当前只证明了：

- 真实 bridge 连通。
- 文本、矩形、图片和 frame 可以写入。
- 节点树可以回读。
- 画板可以导出 PNG。
- canonical frame 的边框、文本和画板可以被真实写入。

当前没有证明：

- Figma 四维验收通过。
- Figma 字体严格通过。
- 原生文本编辑传播通过。
- 资产替换能力通过。
- 视觉通过可以补偿编辑或资产失败。
- bridge 具备生产级并发、事务、幂等和恢复能力。

canonical evaluator 仍保持：

```text
figma_evaluated_count = 0
```

---

## 7. 测试状态

最终全量 unittest：

```text
180/180 passed
```

命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m unittest discover -s tests -p "test*.py" -v
```

本轮新增或更新的重点测试：

- `tests/v2/test_p1_border_style.py`
- `tests/v2/test_p1_dom_text_geometry.py`
- `tests/v2/test_p1_frame_capture.py`
- `tests/v2/test_p1_canonical_output_fidelity.py`

全量测试之后又收窄了 `borderStyle` 支持集合，移除未实现的 `double` 映射；随后执行了：

- border/frame 定向测试 `20/20`
- `node --check figma_bridge\code.js`

两项均通过。

---

## 8. 主要改动文件

采集与样式：

- `src/app/services/structure/capture.py`
- `src/app/services/structure/frames.py`
- `src/app/services/structure/providers/dom.py`
- `src/app/utils/style_utils.py`

DesignSpec 与渲染：

- `src/app/services/som/direct_design.py`
- `src/app/services/rendering/text_wrap.py`
- `src/app/services/rendering/svg_adapter.py`

Figma：

- `figma_bridge/code.js`
- `scripts/figma_replay.py`

测试：

- `tests/v2/test_p1_border_style.py`
- `tests/v2/test_p1_dom_text_geometry.py`
- `tests/v2/test_p1_frame_capture.py`

文档：

- `docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md`
- `docs/v2_mentor/P1_EVIDENCE_ADAPTER.md`
- `docs/v2_mentor/README.md`
- `docs/v2_mentor/R5_PRODUCTION_BACKLOG.md`
- `docs/v2_mentor/V2_OPTIMIZATION_PLAN.md`

---

## 9. 已知风险与边界

### 9.1 Frame

- 仍有 12 个非遮蔽差异像素。
- 当前只覆盖 `900 x 700`、DPR1、Chromium Windows 环境。
- 显式 `border: none`、`solid`、`double`、非均匀 bevel 还没有独立 holdout。
- 嵌套 iframe + padding + border + transform 的组合覆盖有限。
- srcdoc 默认字体规则仍是范围化规则，不是通用字体解析器。

### 9.2 Figma

- `mean=2.088`，与 SVG holdout 的 `0.0011` 不是一个完成度。
- Figma 文本仍有局部 1px 级落点/抗锯齿差异。
- `sans-serif` 回退到 Inter，不能声称字体身份一致。
- Auto Layout 当前主要保留结构信息，子节点几何仍固定；编辑传播未验证。
- Figma replay 是诊断/烟测，不是 canonical 四维验收器。

### 9.3 Bridge

- 服务端当前是单 `_plugin_ws` 和单 `_plugin_inbox`。
- 并发 command 之间没有 request id 关联。
- 30 秒响应超时后没有完整的命令级恢复语义。
- 父节点不存在时插件侧仍可能回退到 `currentPage`，不是严格 fail-closed。
- 当前 bridge 适合本地单客户端实验，不是生产服务。

### 9.4 仓库

- 工作树有大量既存未提交改动。
- 不要执行 `git reset --hard`、`git checkout --`、`git clean` 或批量删除。
- 不要删除 `output/`、Figma 登录态、已有画板或用户产物。
- 不要自动 commit 或创建新分支，除非用户明确要求。

---

## 10. 下一步建议

### 优先级 1：把 Figma 真实回放接入独立验收器

- 输入必须是 fixed canonical capture。
- 回读必须是真实 Figma node tree。
- 导出必须来自真实 Figma PNG。
- Figma 内容、几何、字体、原生文本和资产分别验收。
- 保持 `figma_evaluated_count` 在真正通过前为 0。

### 优先级 2：继续缩小 Figma 输出差异

- 对 h1、普通段落、子文档文本分别统计 bbox 和基线差。
- 区分 Figma 自身字体度量、Inter fallback、文本节点 y 与抗锯齿。
- 不要用移动所有文本的全局 nudge 掩盖不同文本类型的问题。

### 优先级 3：扩 frame holdout

- `border:none`
- `border:2px solid`
- `border:2px double`
- 非均匀 border
- nested iframe
- srcdoc 显式 font-family
- srcdoc 无 doctype/quirk 页面
- DPR2 与移动视口

### 优先级 4：bridge 生产化

- request id
- command 与 response 一对一关联
- 多客户端隔离
- plugin 断连与重连状态
- parent 不存在 fail-closed
- 节点 ownership marker 与清理语义
- 幂等、事务、回滚和 partial-write 报告

### 优先级 5：受控旧 strict 回归

- 冻结旧定义和版本。
- authored controlled cases 作为硬门禁。
- 7 个动态真实站点只作持续观测。
- 不要求实时 `3/7` 每次完全相同。

---

## 11. 可直接复现的命令

### 11.1 完整 holdout

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_canonical_output_fidelity.py `
  --manifest tests\fixtures\p1\canonical\holdout\manifest.json `
  --out-root output\_p1_canonical_visual_holdout_round15
```

### 11.2 完整 calibration

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_canonical_output_fidelity.py `
  --manifest tests\fixtures\p1\canonical\manifest.json `
  --out-root output\_p1_canonical_output_fidelity_round17
```

### 11.3 全量测试

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m unittest discover -s tests -p "test*.py" -v
```

### 11.4 Figma 烟测

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_readback_smoke.py `
  --out output\_p1_figma_smoke_round3
```

### 11.5 Figma canonical replay

先确保目标目录内已有：

- `00_screenshot.png`
- `12_design.json`

然后运行：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_replay.py `
  --out output\_p1_figma_canonical_frame_round1 `
  --design 12_design.json `
  --scale 1
```

---

## 12. 新会话启动检查

1. 读第 2 节入口文档。
2. 运行 `git status --short --branch`，不要清理工作树。
3. 检查 `127.0.0.1:8765` 是否监听。
4. 检查 Figma plugin 是否已连接；未连接时重新 Run/Reload development plugin。
5. 先跑 Figma 最小烟测，再跑 canonical frame replay。
6. 任何 Figma 结果都单独报告，不写入 SVG 的通过结论。
7. 任何新阈值或 holdout 调整都要先冻结，再运行；不要看到失败后回调阈值。

---

## 13. 当前最终结论

- SVG canonical holdout：在当前 controlled scope 内 `5/5` 视觉通过。
- Frame holdout：实际差异已定位并修复，剩余 12 个非遮蔽差异像素。
- Figma：真实 bridge、写入、回读、PNG 导出已建立；真实输出仍为诊断结果。
- Legacy live strict：继续作为诊断和外部有效性观测，不是产品主优化指标。
- 下一轮真正值得追求的是 Figma 实际产物和编辑能力的独立四维验收，而不是让两个浏览器偶然得到相同 DOM。

## 14. 2026-10-21 后续进展

Figma 独立验收链已实现：

- `src/app/services/rendering/figma_acceptance.py`
- `scripts/p1_figma_acceptance.py`
- `scripts/figma_edit_probe.py`
- `scripts/figma_asset_probe.py`

当前 canonical frame 验收：

```text
structure: pass
visual: pass (provisional)
native_text: pass
font: pass (sans-serif -> Microsoft YaHei)
asset: not-required
acceptance_status: pass
figma_attempted_count: 1
figma_evaluated_count: 1
```

报告：

- `output/_p1_figma_acceptance_frame_round14/figma_acceptance.json`
- `output/_p1_figma_edit_probe_round4/figma_edit_probe.json`
- `output/_p1_figma_asset_probe_round4/figma_asset_probe.json`

真实 native text 探针把文本从 `306px` 拉到 `561px` 并成功恢复；真实图片填充替换了 hash，保持 `FILL`，并成功恢复。platform-font provenance 把 canonical `sans-serif` 解析为 Microsoft YaHei，Figma 不再回退 Inter。Auto Layout 父级重排仍未验证。

策略已冻结：

- `tests/fixtures/p1/canonical/figma_structure_policy.json`
- `tests/fixtures/p1/canonical/figma_visual_policy.json`

详细说明：`docs/v2_mentor/P1_FIGMA_ACCEPTANCE.md`。

平台字体实现：`src/app/services/structure/font_provenance.py`。canonical holdout 复跑仍为 SVG `5/5`、frame `12` bad pixels；calibration 仍为 `5 pass + 1 partial`。

Canonical assets 验收：`output/_p1_figma_assets_acceptance_round3/figma_acceptance.json`。structure / visual / edit / asset 全部 pass，3/3 fill payload SHA-256 与 DesignSpec 本地图片一致，`figma_evaluated_count=1`。

Auto Layout 编辑传播：`output/_p1_figma_autolayout_edit_probe_round1/figma_autolayout_edit_probe.json`。文本 height `36→72`，sibling y `64→100`，parent height `120→156`，恢复通过。

Figma holdout 汇总：`output/_p1_figma_holdout_round1/round1.json`。当前 `4 pass / 1 blocked`；`holdout-remote-asset` 仅因 `bad_pixel_count=14520 > 14000` 失败，其他维度通过。阈值未回调。

最终验证：全量 unittest `225/225`、`ruff check`、`py_compile` 与 `node --check` 均通过。Figma canonical frame 与 assets 当前均为 `pass`，Auto Layout 父级传播 probe 为 `pass`；Figma holdout 汇总为 `4 pass / 1 visual blocked`。
