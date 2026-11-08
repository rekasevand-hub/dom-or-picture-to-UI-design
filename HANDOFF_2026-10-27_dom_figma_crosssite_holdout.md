# HANDOFF - DOM to Figma 稳定性修复与跨站 Holdout

**日期：** 2026-10-27  
**分支：** `feature/precise-agent-router`  
**工作树状态：** 存在大量未提交改动，包含此前生产准入工作和本轮 DOM/Figma 修复  
**当前结论：** 本轮实际问题已修复并完成定向验证；跨站泛化尚未验证  
**下一目标：** 冻结并执行全新的跨站 DOM -> Figma holdout

---

## 1. 本次交接的核心结论

本轮修复不是针对单个站点写死选择器或文案。源码中没有把
`new_topic`、`content-label`、`#1024`、`11赞`、`pointer-events-none`
等页面类名或具体内容写入生产逻辑。

当前可以声明的结论是：

- 修复对多个通用 DOM/文本/Frame 模式生效。
- LeetCode 题目页和掘金 `/pins/new` 已完成真实页面复核。
- 825 个 Python 测试通过，全部 Figma bridge JS 测试通过。
- 还不能声明“任意网页质量已经泛化通过”。

不能声明的内容：

- 不能把当前 825 个测试等同于跨站泛化证明。
- 不能把参与修复过程的 LeetCode、掘金、CSDN 页面算作新的 holdout。
- 不能忽略 Figma 插件超时、旧 Frame、新旧产物混放造成的误判。

---

## 2. 本轮修复的问题

### 2.1 行内特殊文本覆盖正文

问题：

- `<code>nums</code>`、嵌套的 `<em><code>target</code></em>` 等行内特殊文本
  被单独生成文字层，离线重排后压在正文上。

修法：

- 将 `code/kbd/samp/var/sub/sup` 及其嵌套 inline 文本收回父段落文本流。
- 特殊文本使用父段落普通字体，不再单独落覆盖层。
- 普通粗体等透明 inline 文本仍可作为 rich run 保留。

关键位置：

- `src/app/services/structure/capture.py:333`

### 2.2 图标覆盖文字与多图标行丢失层级

问题：

- 文字块与图标有 2 到 4px 的垂直差异时，旧逻辑不认作同一行。
- 两个 `img.tag` 加一个异常宽 wrapper 时，wrapper 外框与图标重叠，
  导致 Frame 无法建立。

修法：

- 几何行判定改为：
  - 横向区间不重叠；
  - 纵向条带相交。
- 水平布局使用文本真实 Range 的 `textEmBox`，不使用覆盖整行的 wrapper。
- 水平容器成员按视觉 x/y 排序后写入 `layoutChildren`。

关键位置：

- `src/app/services/rendering/layout_infer.py:578`
- `src/app/services/rendering/layout_plan.py:68`

### 2.3 父 Frame 因共享裁剪被拒绝

问题：

- 多图标行虽然推断成功，但文字成员继承了父行裁剪，图片成员只有自身
  `clipToBounds`，最终报 `clip-mismatch`，Frame 被放弃。

修法：

- 当所有有效成员共享同一裁剪，且裁剪等于父 Frame 边框时：
  - 将 `clipToBounds=True` 提升到父 Frame；
  - 移除成员上重复的同一裁剪。

关键位置：

- `src/app/services/rendering/layout_plan.py:108`

### 2.4 单行文字被错误折行

问题：

- 标签容器宽度和真实文本宽度不同，Figma 固定宽文本会把单行标签折成两行。
- `Plus 会员` 由多个 rich run 组成，浏览器 `textEmBox` 只覆盖部分片段。

修法：

- 浏览器实测单行时写入 `singleLine=True`。
- Figma 使用 `textAutoResize=WIDTH_AND_HEIGHT`，不再固定容器宽。
- 多 rich run 单行文本保留元素自身起点，不使用不完整的 Range 起点。
- 横向 Frame 高度只容得下一行时，自动给文本成员打单行标记。

关键位置：

- `src/app/services/rendering/adapter_base.py:97`
- `src/app/services/rendering/figma_adapter.py:709`
- `src/app/services/rendering/layout_plan.py:146`
- `figma_bridge/code.js`

### 2.5 长文本绕过 `maxLines`

问题分为两层：

1. 浏览器已经提供 11 行 `lines`，共享折行函数优先返回全部测量行，绕过
   `maxLines=2`。
2. 长文本同时带 `richRuns` 时，`_wrap_text_spec()` 直接原样返回，完全没有执行
   折行和截断。

修法：

- 测量行也必须服从显式 `maxLines`。
- 多行 rich text 如果需要换行或截断：
  - 放弃旧 rich run 偏移；
  - 退化为普通文本；
  - 使用预计算行，最后一行补省略号。
- 单行 rich text 仍保留格式。

关键位置：

- `src/app/services/rendering/text_wrap.py:287`
- `src/app/services/rendering/adapter_base.py:521`

产物级验证：

```text
#1024·AI时代程序员
的新饭碗#  这个…

jym，现在租房的小区物业对地下
临时停车位都加装了地锁，只保留…
```

### 2.6 DOM 源码缩进被当成真实换行

问题：

```text
11赞 ·
            1评论
```

浏览器实测 `textEmLines=1`，但采集字符串保留了源码缩进，Figma 将其解释成两行。

修法：

- 仅对实测单行、非 `pre/pre-wrap/pre-line/break-spaces` 文本折叠普通空白。
- 输出变为：

```text
11赞 · 1评论
```

关键位置：

- `src/app/services/som/direct_design.py:154`

### 2.7 空固定浮层被截图回填

问题：

- `ol.pointer-events-none` 是空的固定 toast/message 容器。
- 旧逻辑将整个 1440x32 区域裁成 Image Fill，覆盖真实导航文字。

修法：

- 只有 DOM 子树中存在文字、图片、图标、背景、边框或阴影时，才允许截图回填。
- 空 fixed overlay 不再生成像素底。

关键位置：

- `src/app/services/som/direct_design.py`

---

## 3. 当前证据

### 3.1 自动化验证

最后执行：

```text
825 passed in 68.22s
All bridge JS tests passed
Ruff passed
git diff --check passed
```

新增或重点覆盖测试：

- `tests/v2/test_dom_rich_text_runs.py`
- `tests/v2/test_dom_text_bounds.py`
- `tests/v2/test_layout_hierarchy_frames.py`
- `tests/v2/test_figma_adapter_edits.py`
- `tests/bridge/test_rich_text_runs.js`

### 3.2 真实页面与产物

LeetCode 最新完整 DesignSpec 产物：

```text
output/_dom_figma_example_20261027
```

掘金 `/pins/new` 最近一次完整离线验证产物：

```text
output/_juejin_pins_dom_fix_validation_20261027_r4
```

掘金多图标行产物级结果：

```text
Frame: p
layout.mode: HORIZONTAL
children: img.tag, img.tag, span.content-label
clipToBounds: true
Frame built: true
```

长文本产物级结果：

```text
lines: 2
最后一行以 … 结尾
richRuns: []
boundedText: true
```

`11赞 · 1评论` 产物级结果：

```text
text: 11赞 · 1评论
singleLine: true
lines: null
```

---

## 4. 已知限制与风险

### 4.1 泛化边界

- 修复是通用规则，但目前只有少量真实页面验证。
- Grid、多行 flex-wrap、复杂 absolute/sticky 和嵌套裁剪仍可能退回扁平结构。
- 多行 rich text 为避免溢出会牺牲局部字体、颜色、加粗等格式。
- 极窄单行容器仍可能依赖父级裁剪。
- 空 overlay 的可见子树判断是保守规则，极端 portal 结构仍需观察。

### 4.2 Figma 运行风险

- 修改 `figma_bridge/code.js` 后，必须关闭并重新运行 Figma 开发插件。
- 插件超时返回 `PLUGIN_TIMEOUT` 时，写入结果是 unknown，不能当成功。
- 插件超时可能留下部分 Frame，必须忽略或删除，不能参与验收。
- 同一个输出目录复用会覆盖上一页中间产物，测试多个页面时必须使用唯一目录。
- `scripts/figma_replay.py` 会按名称前缀清理旧画板；运行前确认前缀不会误删其他 Frame。
- 当前 bridge 端口默认是 `ws://localhost:8765`。

### 4.3 Git 工作树

当前工作树包含大量前序未提交改动，不属于本轮且不得回退：

- 生产准入文档与探针；
- Grounding reliability、fallback observability；
- bridge fencing、安全与 soak 相关文件；
- 本轮 DOM/Figma 修复与测试。

根目录还存在历史未跟踪项：

```text
2'
Figma'
```

不要无条件删除或覆盖。

---

## 5. 下一轮目标：冻结新的跨站 Holdout

### 5.1 为什么必须新建

以下页面已经参与本轮问题分析和修复，不能再作为新 holdout：

- LeetCode `https://leetcode.cn/problems/two-sum/`
- 掘金 `https://juejin.cn/pins/new`
- CSDN 文章诊断页
- 仓库已有 dushu 验收样本

新 holdout 必须在执行前冻结，运行后不得因结果不理想替换页面。

### 5.2 推荐样本规模

推荐 18 页，每类 3 页：

1. 文章/博客
2. 论坛/社区
3. 电商
4. 后台/数据面板
5. 表单/设置页
6. SPA/交互应用

固定环境：

```json
{
  "viewport": {"width": 1440, "height": 900},
  "device_scale_factor": 1,
  "route": "dom",
  "tool": "figma",
  "headedFallback": false
}
```

不得使用 image、grounding、CV 或 VLM 兜底。

### 5.3 Manifest 冻结字段

每个样本至少记录：

```json
{
  "sample_id": "HOLD-ARTICLE-01",
  "category": "article",
  "url": "https://example.com/page",
  "frozen_at": "2026-10-27T00:00:00+08:00",
  "viewport": [1440, 900],
  "device_scale_factor": 1,
  "route": "dom",
  "tool": "figma",
  "title": "captured title",
  "source_screenshot_sha256": "...",
  "dom_sha256": "...",
  "design_sha256": "..."
}
```

冻结后只允许记录 capture failure，不允许替换 URL。

### 5.4 指标定义

#### 层级保留率

对源 DOM 中父子关系明确、父元素为横向/纵向容器的可见元素：

```text
在 Figma readback 中仍位于正确祖先 Frame 内的节点数
/
可评估的源父子节点数
```

#### 文字越界率

不计算明确要求溢出的装饰元素：

```text
Figma TEXT 节点超出其直接父 FRAME 超过 1px 的数量
/
可评估 TEXT 节点数
```

#### 单行误折率

```text
源 textEmLines=1 且非 preformatted
但 Figma 回读 characters 含换行或高度超过一行容差的数量
/
源单行文本数
```

#### 可编辑文本率

```text
由 Figma TEXT 节点承载的源可见文本数
/
源可见文本数
```

这一轮先做 report-only，不临时设置通过阈值。阈值应在 holdout 结果产生后单独评审。

### 5.5 执行规模

建议采用混合方案：

1. 18 页全部执行 DOM -> DesignSpec 与离线结构指标。
2. 每类抽 2 页，共 12 页执行真实 Figma 写入、readback、PNG 导出。
3. 若 Figma 插件中途超时：
   - 该样本标记 `plugin-timeout`；
   - 保留中间证据；
   - 不把部分 Frame 计入指标。

如果用户要求更强结论，则 18 页全部进入 Figma。该选择尚未最终批准。

---

## 6. 建议实现结构

建议新增：

```text
tests/fixtures/dom-figma-crosssite-holdout-2026-10-27/manifest.json
src/app/services/evidence/dom_figma_crosssite_holdout.py
scripts/dom_figma_crosssite_holdout.py
tests/v2/test_dom_figma_crosssite_holdout.py
docs/v2_mentor/DOM_FIGMA_CROSSSITE_HOLDOUT_2026-10-27.md
```

职责：

- manifest loader 与 freeze validation；
- 唯一输出目录；
- DOM capture result validation；
- DesignSpec 与 DOM 对账；
- Figma readback 指标；
- 汇总 report 与逐样本 failure；
- 拒绝 `effective_route != dom`；
- 拒绝插件超时产物进入质量分母。

不要修改渲染规则来适配 holdout。

---

## 7. 执行顺序

1. 冻结 manifest，记录 URL、环境、分类和来源哈希。
2. 校验 manifest：无旧页面、无重复 URL、18 个唯一样本。
3. 每页使用唯一 `--output-dir` 运行显式 `--route dom --tool svg` 或离线渲染。
4. 检查 `manifest.json`：
   - `requested_route=dom`
   - `effective_route=dom`
   - `fallbacks=[]`
5. 计算离线层级、越界、单行误折、可编辑文本指标。
6. 重新运行 Figma 插件。
7. 对选定子集执行真实 Figma 写入、readback、PNG 导出。
8. 生成逐页报告与汇总。
9. 不根据失败样本替换 URL。
10. 在独立文档中记录结果，不修改本轮修复结论。

---

## 8. 复现命令

单页 DOM -> SVG：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m src.main `
  --url "https://example.com/article" `
  --route dom `
  --tool svg `
  --output-dir "output/_dom_figma_holdout/HOLD-ARTICLE-01"
```

单页 DOM -> Figma：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m src.main `
  --url "https://example.com/article" `
  --route dom `
  --tool figma `
  --output-dir "output/_dom_figma_holdout/HOLD-ARTICLE-01"
```

已有 DesignSpec 回放：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/figma_replay.py `
  --out "output/_dom_figma_holdout/HOLD-ARTICLE-01" `
  --design 12_design.json `
  --screen-name "HOLD-ARTICLE-01"
```

---

## 9. 完成标准

本交接后的下一轮只有在以下条件满足时，才能更新为“跨站泛化已验证”：

- holdout manifest 在执行前冻结并有哈希；
- 所有样本只使用 DOM 路线；
- 失败样本保留，不替换；
- 每个指标有明确分母和失败清单；
- 真实 Figma 子集无未处理 `PLUGIN_TIMEOUT`；
- 汇总报告能追溯到逐页产物；
- 结果不依赖参与修复过程的页面。

在此之前，建议继续使用：

```text
机制泛化已验证
任意网页质量泛化未验证
```

