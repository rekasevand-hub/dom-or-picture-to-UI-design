# R3-EXP-15 · 失败 SVG 的离线栅格回退

> 状态：`completed-for-current-scope`（2026-10-18），不是真实 Figma 端到端 `verified`。  
> 范围：四个直接导入失败的 SVG 特性，经 Chromium 渲染、PNG/JPEG 打包，再由本地 mock executor 检查 `create_image` 合同。  
> 证据：`output/_r3_supplements/r3_exp15_raster_fallback.json`、`r3_exp15_artifacts/`、`r3_exp15_contact.png`。

## 1. 用例

- `FILTER_DROP_SHADOW`
- `FILTER_CHAIN`
- `FOREIGN_OBJECT`
- `PATTERN`

四个用例直接导入时均丢失效果或变成空白；参考图来自 Chromium DPR 2 元素截图。

## 2. 结果

- 4/4 用例生成平铺栅格回退。
- PNG 与参考截图逐像素 MAE 为 0，4/4 无损。
- JPEG q90 4:4:4 最大 MAE 为 `1.121845`，作为体积/质量对照，不替代 PNG 默认。
- 每个 `create_image` 命令都声明 `claim=flat-raster-crop`。
- `cannot_claim` 明确包含 `original-asset / native-editability / dom-identity`。
- 合同检查：9/9。

## 3. 结论

对于直接导入会丢失语义的 SVG 子树，**平铺栅格回退可以作为确定的视觉保底**；但它在资产合同上只能算截图裁片，不能声称原始矢量、原生可编辑或 DOM 身份。

## 4. 限制

- 没有真实 Figma 导入、插件运行时或设计文件复核；executor 是本地 mock。
- 只覆盖四个已知失败特性；其他 filter、外部引用与动画内容未评估。
- 平铺栅格不可原生编辑，不能作为原始资产。
- JPEG 只用于包装比较；默认仍推荐无损 PNG。

## 5. 不得宣称

- 不得写“raster-fallback 已在 Figma 端到端验证”。
- 不得写“平铺栅格是原始资产或可编辑资产”。
- 不得写“所有 SVG 失败都能靠栅格解决”。

