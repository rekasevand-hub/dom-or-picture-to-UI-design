# HANDOFF - P2 DPR、移动、字体、frame 与资产边界

**日期：** 2026-10-21  
**工作目录：** `D:\LLM-Data\Figma_auto_agent`  
**分支：** `feature/precise-agent-router`  
**状态：** P2 扩展当前范围完成；11 个独立 Figma holdout 为 `10 pass + 1 partial + 0 blocked`  
**仓库状态：** 未 commit、未新建分支；工作树有大量本轮之前就存在的 modified/deleted/untracked 文件

## 1. 新会话必读

1. `docs/v2_mentor/P2_EXPANSION.md`
2. `docs/v2_mentor/P1_FIGMA_ACCEPTANCE.md`
3. `docs/v2_mentor/P2_EXTENDED_CLOSURE.md`
4. `output/_p2_figma_holdout_round4/round1.json`
5. `output/_p2_figma_holdout_round4/unittest-final.log`

## 2. 当前结论

- DPR2 text/assets：SVG 与 Figma 均通过；
- DesignSpec 逻辑画布保持 CSS 尺寸，SVG/Figma 按 DPR 导出物理尺寸；
- mobile calibration 与独立 mobile holdout 分离；
- missing-font holdout 的内容、几何、字体解析与原生编辑均通过；
- mixed-font family/weight run、边界空白、nested srcdoc frame、transparent crop 均通过；
- partial asset 保持 `partial`，计入 evaluated，不升级为 pass；
- italic 与 bold italic 通过；
- variable named instances 可解析，任意 axis 保持 unsupported；
- ambiguous fallback 保留双平台字体并 fail-closed；
- 320/375/430/412 移动宽度矩阵均通过；
- React/Dushu 当前 comparison profile equivalent，Shoelace different，W3Schools inconclusive；
- Firefox 启动失败为 `spawn UNKNOWN`，保持 environment-blocked；
- Figma 聚合：`10 pass + 1 partial + 0 blocked`，未使用 composite score。

## 3. 关键策略

- canonical P2：`tests/fixtures/p1/canonical/p2/visual_policy_dpr_aware.json`
- Figma DPR/fallback：`tests/fixtures/p1/canonical/p2/figma_visual_policy.json`
- Figma mobile：`tests/fixtures/p1/canonical/p2/figma_mobile_visual_policy.json`
- Figma mixed-font：`tests/fixtures/p1/canonical/p2/figma_mixed_font_visual_policy.json`
- Figma mobile matrix：`tests/fixtures/p1/canonical/p2/figma_mobile_matrix_visual_policy.json`

绝对 `bad_pixel_count` 在 P2 中只记录，不跨视口门禁；比例、均值和尺寸仍为硬门禁。

## 4. 复现

DPR2 canonical：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_canonical_output_fidelity.py `
  --manifest tests\fixtures\p1\canonical\p2\dpr2_manifest.json `
  --out-root output\_p2_dpr2_probe_rerun
```

Mobile canonical：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_canonical_output_fidelity.py `
  --manifest tests\fixtures\p1\canonical\p2\mobile_holdout_manifest.json `
  --out-root output\_p2_mobile_holdout_probe_rerun
```

DPR2 Figma replay must use:

```text
--scale 2
```

Mobile Figma replay uses:

```text
--scale 1
```

P2 其余 manifest：

- `mixed_font_holdout_manifest.json`
- `mixed_font_holdout2_manifest.json`
- `nested_iframe_manifest.json`
- `transparent_crop_manifest.json`
- `partial_asset_manifest.json`

## 5. 已知风险

- mixed-script text 在字体激活前可能报告临时宽度；稳定验收要先激活字体再回读/导出；
- mobile policy 只有一个 calibration 和一个 holdout，仍为 provisional；
- missing-font 只证明 fallback family/style/size 和编辑能力，不证明 glyph identity；
- variable font 只支持可用的命名实例，不支持任意 axis 精确复现；
- ambiguous platform-font 仍无逐 glyph face split；
- file:// iframe 是 opaque origin；nested 证据仅覆盖 srcdoc；
- mixed-font visual policy 仍为 provisional；
- 真实站点只有四次有界观测，不能作为持续稳定性结论；
- Dushu equivalent 仍包含 geometry max `13px` 和 `5/1936` 个 over-2px 样本；
- bridge 仍是单客户端实验服务。

## 6. 下一步

- 扩展 DPR2 资产 identity；
- 增加 Firefox 与跨机器字体版本矩阵；
- 为 ambiguous fallback 设计显式 run split；
- 将真实站点观测扩展为冻结 profile 下的定期外部有效性检查。
