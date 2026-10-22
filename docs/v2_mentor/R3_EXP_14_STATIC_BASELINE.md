# R3-EXP-14 · 静态截图基线估计

> 状态：`completed-for-current-scope`（2026-10-18）。  
> 范围：已知字体文件与字号时，从静态截图像素估计 alphabetic baseline。  
> 证据：`output/_r3_supplements/r3_exp14_static_baseline.json`、`r3_exp14_captures/`、`r3_exp14_contact.png`。

## 1. 估计公式

```text
baseline = ink_bottom_css - (font_bbox_bottom - font_ascent)
```

输入只有截图像素、已知字体文件与字号；**不使用** DOM baseline、DOM 几何或 OCR。

## 2. 结果

- 7 个用例 × 2 个字号 × DPR 2/3，共 28 次测量。
- 最大基线误差 `0.500px`，平均误差 `0.018px`。
- DPR 2/3 结果稳定。
- 零尺寸探针没有改变布局。
- 合同检查：6/6。

## 3. 关键条件

- Arial 拉丁大写/数字可直接用墨迹底边与字体度量估计。
- 含 descender 的拉丁文本必须使用字体度量；只取墨迹底边会把 descender 误当基线。
- CJK 文本不能仅靠墨迹底边推基线；必须知道字体 ascent/descent。
- 未知字体、替换字体或未知字号仍为 `not-evaluated`，不能填 0 误差。

## 4. 限制

- 估计器要求精确字体文件与字号。
- 只覆盖 Windows Chromium；跨渲染器栅格差异由 R3-EXP-13 单独标定。
- 这是受控本地标定，不是通用截图基线阈值。
- CJK 与 descender 用例明确拒绝 `ink-bottom-only`。

## 5. 不得宣称

- 不得写“任何截图都能自动得到基线”。
- 不得写“字形底边就是基线”。
- 不得把 0.5px 写成跨字体、跨平台通用阈值。

