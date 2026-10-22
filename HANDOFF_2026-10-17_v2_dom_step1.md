# HANDOFF — 2.0 方向 2 第一步：DOM → Figma 结构补强

**日期：** 2026-10-17  
**范围：** DOM 路线采集与 Figma 文本落点；不改截图路线，不合并 grounding/cv  
**版本：** `VERSION` 仍为 `1.1.0`，未提交 git

## 1. 本轮改动

### 1.1 单行文本对齐（页脚版权行）

- 文件：`figma_bridge/code.js`
- 根因：`createText()` 只在多行折行分支应用 `textAlign`；单行文本仍按
  `WIDTH_AND_HEIGHT` 从盒子左缘起排，`text-align:center` 的页脚版权行因此在
  Figma 里整体左偏。
- 修复：单行文本按盒子宽与实测文字宽反算落点，支持 `center` / `right` / `end`；
  保持自动宽高，不强制换行，避免 `nowrap` 文本被挤折。
- 验证：Node mock 调用 `create_text`，900/1170px 宽盒子下 center/right/left
  三种落点均与期望值一致。

### 1.2 Shadow DOM 采集

- 文件：`src/app/services/structure/capture.py`
- `DOM_JS` 从 `document.querySelectorAll('*')` 改为递归遍历 light DOM + open
  shadow root。
- 新增 `logicalParentOf` 逻辑父链：影子节点的 `parentElement` 为 null，
  现在仍能把宿主记为父级，`pIdx`、裁剪矩形和 Auto Layout 推断可跨组件边界。
- 只有 Shadow DOM 内的节点带 `shadow: true`；普通页面 DOM JSON 形状与顺序不变。
- `hasElementChildren` 同时识别 light/shadow 子节点，避免把只含影子内容的
  自定义元素误判成叶子。

### 1.3 DOM 结构诊断

- 新文件：`src/app/services/structure/diagnostics.py`
- 每次 URL 采集额外输出 `00_dom_diagnostics.json`（单页与 `capture_attempts/`
  都保留）。
- 字段区分两类缺口：
  - `capture_gaps.shadow`：页面有、快照没有的开放 Shadow DOM 节点；
  - `unsupported.grid / flex_wrap`：已进快照但 `layout_infer` 仍会 bail；
  - `unsupported.gradient / pseudo`：尚未进入 DesignSpec 的视觉能力。
- 探针只读页面，不改变 DOM、截图或渲染；诊断失败不影响采集主流程。
- `content:""` 的 clearfix 伪元素不计入装饰缺口。

### 1.4 文档

- `README.md` 增加 `00_dom_diagnostics.json` 输出说明与字段表。

## 2. 验证结果

合成页（open Shadow DOM + Grid + flex-wrap + gradient + 伪元素 + 居中页脚）：

```text
capture_gaps={"shadow": 0}
unsupported={"grid": 1, "flex_wrap": 2, "gradient": 1, "pseudo": 1}
```

- Shadow 文本/按钮进入 `00_dom.json`，`pIdx` 指向自定义元素宿主。
- 普通 dushu.com 页面回归：修复前后 `00_dom.json` 的 490 个节点
  `(tag,text,x,y,w,h)` 序列完全一致，采集顺序无变化。
- `py_compile`、`node --check figma_bridge/code.js`、`git diff --check` 通过。

## 3. 尚未做

- CSS Grid / flex-wrap 的语义布局推断（当前几何兜底保证像素，缺 Auto Layout 语义）。
- CSS 渐变、背景图容器、伪元素装饰进入 DesignSpec。
- Figma Auto Layout 的 true flow 模式（现在打开 layoutMode 后仍复位绝对坐标）。
- 独立“截图 → Figma”路线与两条路线融合。

## 4. 建议下一步

1. 先在真实站点上积累 `00_dom_diagnostics.json`，确认 gap 分布；
2. 按缺口优先级补渐变/背景图（视觉收益直接、可用像素指标验收）；
3. Grid/Wrap 改造必须用现有几何回归守住像素结果；
4. 等用户明确同意后再新起“截图 → Figma”路线。
