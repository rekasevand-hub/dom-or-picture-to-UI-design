# R3-EXP-03 · SVG、滤镜、mask 与混合效果矩阵（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18）。
> 范围：Figma 桌面版受控用例；只验证“直接 SVG 导入后 Figma 留下了什么”和“Figma 原生能力能否近似目标效果”。
> 证据：`output/_r3_experiments/exp03_effect_matrix.json`，以及 `exp03_figma/`、`exp03_reference/`、`exp03_diff/`。

## 1. 环境与判定口径

| 项 | 值 |
|---|---|
| Figma | 桌面版 `126.9.13` |
| 执行方式 | 独立实验插件 `effect_probe_plugin/`（`effect_probe.js`），经本机 `ws://localhost:8765` 发送实验命令；不经过生产写入路径 |
| 浏览器参考 | Playwright 1.62.0 / Chromium `151.0.7922.34` |
| 画布 | 每个用例独立 `200×140`（背景模糊 `240×160`，混合矩阵 `540×420`） |
| DPR | 1 |
| 导出 | Figma 节点 PNG 1× 导出；透明像素合成到白底后比较 |
| 像素指标 | 每通道绝对差：均值、P99、最大值、`>8` 的像素比例 |

判定词只表示“本受控用例的准入候选”，不是生产结论：

| 判定 | 含义 |
|---|---|
| `native-candidate` | Figma 直接导入或原生建模后存在对应模型，本用例视觉接近；仍需生产 bridge 实现与复核 |
| `conditional-native` | 依赖字体、显式重建或包装层等条件，条件不满足时会降级 |
| `unsupported-direct` | 直接 SVG 导入丢失语义；必须重建或走回退，不等于整个特性永远不支持 |
| `raster-fallback` | 离线平铺资产合同已由 `R3-EXP-15` 完成；真实“栅格化 → 导入 Figma → 回读”仍未执行 |
| `not-evaluated` | 未测 |

`ok=true` 只表示插件调用返回、节点创建和 PNG 导出成功，**不表示语义等价**。

## 2. SVG 直接导入结果（20/20 调用成功）

| 特性 | 均值差 | P99 | 最大差 | `>8` 比例 | 导入后结构 | 判定 |
|---|---:|---:|---:|---:|---|---|
| 线性渐变 | 0.3261 | 1 | 45 | 0.001429 | `VECTOR` + `GRADIENT_LINEAR` | `native-candidate` |
| 径向渐变 | 0.3474 | 2 | 32 | 0.001714 | `VECTOR` + `GRADIENT_RADIAL` | `native-candidate` |
| `clip-path` | 0.0945 | 1 | 59 | 0.007464 | `GROUP` + `VECTOR` | `native-candidate` |
| alpha mask | 0.2283 | 3 | 47 | 0.006393 | `GROUP` + `VECTOR` | `native-candidate` |
| luminance mask | 0.1494 | 1 | 2 | 0 | `GROUP` + `VECTOR` | `native-candidate` |
| 文本（Arial） | 11.6203 | 238 | 238 | 0.088893 | `TEXT`，CJK 仍记 `Arial` | `conditional-native` |
| 文本（显式 YaHei） | 11.2531 | 238 | 238 | 0.089107 | `TEXT`，`Microsoft YaHei` | `conditional-native` |
| 文本（字体列表） | 11.6203 | 238 | 238 | 0.088893 | 取列表首项 `Arial` | `conditional-native` |
| 文本（YaHei + 预加载） | 11.2531 | 238 | 238 | 0.089107 | 与显式 YaHei 完全相同 | `conditional-native`；预加载命题 `not-evaluated`（见 3.1） |
| `<use>` | 0.0421 | 1 | 2 | 0 | 静态展开为 `VECTOR` | `native-candidate`（无可复用引用语义） |
| 复杂描边 | 1.3497 | 38 | 163 | 0.025607 | `VECTOR` + `SOLID` stroke | `native-candidate`（边缘有模糊差异） |
| 渐变描边 | 0.1254 | 2 | 44 | 0.004607 | `VECTOR` + `GRADIENT_LINEAR` stroke | `native-candidate` |
| `feGaussianBlur` | 0.7246 | 6 | 9 | 0.000214 | `LAYER_BLUR` | `native-candidate` |
| `feDropShadow` | 7.5478 | 125 | 137 | 0.1155 | `effects=[]`，阴影消失 | `unsupported-direct`；显式映射 `DROP_SHADOW` 属 `derived` |
| filter 链（阴影 + blur） | 10.2756 | 109 | 122 | 0.231286 | 仅剩 `LAYER_BLUR(10)` | `unsupported-direct`（链式语义丢失） |
| `foreignObject` | 59.7875 | 181 | 181 | 0.566464 | 空白 `FRAME`，非白像素 0 | `unsupported-direct`；`raster-fallback` 离线合同已完成（`R3-EXP-15`） |
| data URI 图片 | 0.8201 | 31 | 109 | 0.030857 | `IMAGE` fill | `native-candidate` |
| 远程 URL 图片 | 18.3508 | 169 | 199 | 0.278 | 空白 `FRAME`，非白像素 0 | `unsupported-direct`；需预抓取 |
| `<animate>` | 0.4909 | 3 | 12 | 0.000071 | 保留静态首帧 | 静态 `native-candidate`；动画 `unsupported` |
| `<pattern>` | 29.3818 | 163 | 163 | 0.771429 | 空白 `FRAME`，非白像素 0 | `unsupported-direct`；`raster-fallback` 离线合同已完成（`R3-EXP-15`） |

### 2.1 结论

1. 渐变、`clip-path`、alpha/luminance mask、渐变描边、data URI 图片和 `feGaussianBlur` 在本矩阵中可以直接导入为原生节点，均值差均小于 1。
2. `feDropShadow` 直接导入后 `effects=[]`，参考图非白比例 `0.377107`，导入图只剩 `0.270143`；不是“阴影略有偏差”，而是阴影整体缺失。
3. filter 链只剩 `LAYER_BLUR(10)`，阴影与链式顺序均未保留；不能把单测 blur 的结果外推到链式 filter。
4. `foreignObject`、`pattern`、远程 URL 图片都导入为空白 frame（非白像素 0）。其中远程图片的失败原因是外部资源未被解析；`foreignObject` 和 `pattern` 应视为直接导入不支持。
5. `<use>` 只做静态展开，视觉接近（0.0421），但没有保留可复用的 symbol/instance 引用语义。
6. `<animate>` 只保留静态首帧；本实验没有验证任何动画时间轴。

## 3. 文本用例的额外限制

四个文本用例都在 28px、200×140 下比较。差异图显示差异集中在字形边缘的彩色抗锯齿条纹，而不是断行或整体位移：

| 用例 | 文本节点实际 `fontName` | 文本宽度（Hello / CJK） | 均值差 |
|---|---|---:|---:|
| Arial | `Arial Regular` | 64 / 127 | 11.6203 |
| 显式 YaHei | `Microsoft YaHei Regular` | 71 / 131 | 11.2531 |
| 字体列表 `Arial, Microsoft YaHei, sans-serif` | `Arial Regular` | 64 / 127 | 11.6203 |
| YaHei + 预加载 | `Microsoft YaHei Regular` | 71 / 131 | 11.2531 |

由此只能得到：

- 同一渲染链下，文本像素均值的约 11.2 是抗锯齿差异的底噪；Arial 与 YaHei 之间仅相差约 0.37，**像素均值不能用来判定字体是否一致**。
- 字体列表会取首项 Arial；CJK 字形由系统回退提供，但节点 `fontName` 仍显示 Arial，因此“节点字体名”不等于“实际字形来源”。
- `Microsoft YaHei` 在 Figma 字体列表中确实存在（可用字体 9381 个，含 `Regular/Bold/Light`）。

### 3.1 预加载用例的混杂

“YaHei + 预加载”的 SVG 与“显式 YaHei”完全相同，仅多一次字体预加载；两者结果逐像素相同（均值差都为 11.2531）。因此本次**没有**测到“预加载会改变字体列表解析”这一命题，该点保持 `not-evaluated`，不能写成“预加载无效”。

文本验收仍应按 `R3-EXP-06` 的行盒、基线、断行和字形分项处理，不能用本矩阵的像素均值代替。

## 4. 原生 Figma 能力（12/12 调用成功）

原生化用例由插件直接创建，参考图是按同一意图手写的 HTML/CSS 近似，不是“源代码真值”。因此这里比较的是“Figma 原生模型与 CSS 近似是否接近”，不是 Figma 与 CSS 的规范等价。

| 原生能力 | 参数 | 均值差 | P99 | 最大差 | 判定 |
|---|---|---:|---:|---:|---|
| `DROP_SHADOW` | offset 8/8，blur 12，alpha 0.55 | 0.7408 | 7 | 11 | `native-candidate` |
| `INNER_SHADOW` | offset 8/8，blur 12，alpha 0.55 | 0.2071 | 4 | 7 | `native-candidate` |
| `LAYER_BLUR` | radius 8 | 3.4048 | 36 | 63 | `native-candidate`（高斯核实现不同） |
| `BACKGROUND_BLUR` | radius 12 | 5.2023 | 49 | 53 | `native-candidate`（模糊核与取样不同） |
| 效果链 | shadow 8/8/12 + blur 4 | 2.6188 | 33 | 65 | `native-candidate`（顺序需固定并复核） |
| alpha mask | `maskType=ALPHA` | 0.1566 | 1 | 2 | `native-candidate` |
| vector mask | `maskType=VECTOR` | 0.2333 | 3 | 52 | `native-candidate` |
| luminance mask | `maskType=LUMINANCE` | 1.4208 | 11 | 41 | `native-candidate` |
| `clipsContent` | 子项超出父 frame | 0.0048 | 0 | 1 | `native-candidate` |
| 16 种 blend mode | normal…luminosity | 0.1481 | 2 | 19 | `native-candidate` |
| mask + shadow 同帧 | 同一 frame 内 mask 与阴影 | 10.2087 | 96.01 | 106 | 不可直接采用 |
| mask + shadow 包装层 | 阴影放在外层 wrapper | 1.2351 | 7 | 9 | `native-candidate` |

16 种混合模式在 540×420 矩阵上逐格一致，均值差 0.1481；这只覆盖本组颜色与叠放顺序，不外推到所有颜色空间组合。

### 4.1 mask 与 effect 的顺序

同帧组合用例中，阴影被 mask 语义一起裁剪或改写，均值差 10.2087；把被 mask 的内容放进独立 wrapper、把阴影放到 wrapper 上后降到 1.2351。结论是：**mask 与阴影共存时必须显式规定包装层和 effect 所在节点**，不能依赖导入器或调用顺序。

## 5. 建议的重建策略

| 输入 | 直接导入 | 建议策略 | 状态 |
|---|---|---|---|
| 渐变、`clip-path`、alpha/luminance mask | 原生节点 | 直接采用，保留导入结构 | `native-candidate` |
| 渐变描边、简单实线描边 | 原生 stroke | 直接采用；复杂 join/cap/dash 逐例复核 | `native-candidate` |
| `feGaussianBlur` | `LAYER_BLUR` | 直接映射，记录 radius 换算 | `native-candidate` |
| `feDropShadow` | 阴影丢失 | 解析参数，显式创建 Figma `DROP_SHADOW` | `derived`；端到端未测 |
| filter 链 | 仅剩一个 blur | 按顺序显式重建 effect 链；无法表达时栅格回退 | `derived`；端到端未测 |
| `foreignObject` | 空白 | 优先栅格化该子树，再作为图片放入 | `raster-fallback`；离线合同已完成（`R3-EXP-15`），真实导入未验证 |
| `pattern` | 空白 | 展开为重复矢量或栅格化 | `raster-fallback`；离线合同已完成（`R3-EXP-15`），真实导入未验证 |
| 远程图片 | 空白 | 先抓取字节，再以 data URI/`IMAGE` fill 写入 | `derived`；未做端到端 |
| data URI 图片 | `IMAGE` fill | 直接采用 | `native-candidate` |
| `<use>` | 静态 vector | 采用视觉结果；如需复用语义，显式建组件/实例 | `native-candidate`（视觉） |
| `<animate>` | 静态首帧 | 只交付静态状态；动画另立契约 | 动画 `unsupported` |
| 文本 | 原生 `TEXT` | 绑定字体、字号、行高与可用性；按 EXP-06 验收 | `conditional-native` |

**raster-fallback 的边界**：本实验只确认了“直接导入会得到空白或丢失效果”。`R3-EXP-15` 已补四个失败特性的 Chromium 渲染、PNG/JPEG 打包与本地 mock `create_image` 合同（4/4、PNG 无损、9/9 检查）；但它没有执行真实“栅格化 → 导入 Figma → 再导出 → 像素复核”的完整链路。因此 raster-fallback 当前是 `completed-for-current-scope` 的离线平铺资产合同，不能写成真实 Figma 端到端已验证。

## 6. 对生产的影响

1. 资产准入不能按“SVG 导入成功”放行，必须按本矩阵逐项记录直接导入结果和重建策略。
2. 文本不能进入像素均值白名单；必须使用独立文本验收。
3. mask 与 effect 共存时，生产模板应固定为“内容层被 mask，效果层在外层 wrapper”，并把该结构写入序列化契约。
4. `foreignObject`、`pattern`、远程图片需要在采集阶段就决定预抓取或栅格化，不能等到导入后补救。
5. 所有这些仍是候选；生产 `src/`、`figma_bridge/` 未修改。

## 7. 不得宣称

- 不得写“SVG 导入 20/20 成功，所以 20 个特性都支持”。
- 不得写“`feDropShadow` 可直接导入”；直接导入的 `effects=[]` 已经证伪。
- 不得写“filter 链已支持”；链式语义在当前导入中被截断。
- 不得写“raster-fallback 已在真实 Figma 端到端验证”；`R3-EXP-15` 只完成离线平铺资产合同。
- 不得写“文本像素差 11 说明字体错误”或“说明字体正确”；该指标被抗锯齿主导。
- 不得写“预加载无效”；预加载用例与显式字体用例混杂，命题未被检验。
- 不得把本受控用例的均值差外推到其他尺寸、颜色、层叠顺序或 Figma 版本。

## 8. 证据文件

| 文件 | 内容 |
|---|---|
| `output/_r3_experiments/exp03_effect_matrix.py` | 可复现实验脚本 |
| `output/_r3_experiments/exp03_effect_matrix.json` | 20 个 SVG 用例 + 12 个原生用例的结构、像素与错误数据 |
| `output/_r3_experiments/effect_probe_plugin/` | 独立实验插件（`manifest.json`、`effect_probe.js`、`ui.html`） |
| `output/_r3_experiments/exp03_figma/*.png` | Figma 导出图 |
| `output/_r3_experiments/exp03_reference/*.png` | 浏览器参考图 |
| `output/_r3_experiments/exp03_diff/*.png` | 4× 放大差异图 |
| `output/_r3_experiments/exp03_contact_sheet.png` | 总览对照 |

重跑说明：`grid_probe_plugin/manifest.json` 已恢复为 `main: code.js`；效果矩阵需在 Figma 中导入 `effect_probe_plugin/manifest.json`（独立插件 id `ui-reconstruct-effect-probe-r3`）后再执行。
