# R3-EXP-13 · 跨渲染器文本度量与基线

> 状态：`completed-for-current-scope`（2026-10-18），不是通用阈值 `verified`。  
> 范围：同一组 12 个文本用例，在 Chromium 151.0.7922.34 与 WebKit 26.5、DPR 1/2 下逐项测量。  
> 证据：`output/_r3_supplements/r3_exp13_cross_renderer_text.json`、`r3_exp13_captures/`、`r3_exp13_contact.png`。

## 1. 方法

12 个用例覆盖拉丁单/多行、中文单/多行、全角标点、混排、数字、省略号、粗体、斜体、缺字与 emoji。每个用例在同一浏览器内重复读取两次，并在 DPR 1/2 下记录 CSS 行盒、行数、零尺寸基线探针和截图。

## 2. 结果

- 可用浏览器 2 个；12 用例 × 2 浏览器 × 2 DPR × 2 次读取，共 72 次测量。
- 同浏览器重复读取稳定，CSS 度量差异为 0。
- DPR 1/2 的 CSS 度量一致；像素尺寸随 DPR 缩放。
- Chromium 与 WebKit 的换行数差异 0/12。
- 基线差 P50 为 `0.0px`，最大 `0.5px`。
- 行盒高度差 0；首行行高差 0。
- 合同检查：8/8。

WebKit 的差异只出现在 `latin_single` 与 `latin_multi` 的基线上，均为 `0.5px`；其余用例基线差为 0。该结果是当前 Windows 字体文件与浏览器构建的标定，不是跨平台常量。

## 3. Firefox 边界

Firefox 已安装但本机启动失败，错误为：

```text
Error: BrowserType.launch: spawn UNKNOWN
```

因此本实验只覆盖 Chromium + WebKit，不能宣称 Firefox 或三渲染器矩阵已完成。

## 4. 限制

- 仅 Windows 上的浏览器构建；macOS Safari、iOS、Android 与 Linux 字体栈未覆盖。
- 只使用 Arial 与 Microsoft YaHei；可变字体、嵌入 webfont 与复杂 fallback 链未覆盖。
- 基线探针是 authored inline-block，不是 OCR 或生产截图基线提取器。
- 跨渲染器差值只是标定数据，不能直接当通用通过阈值。

## 5. 不得宣称

- 不得写“Firefox 已覆盖”或“三渲染器全部通过”。
- 不得把 0.5px 写成所有字体、平台和 DPR 的通用阈值。
- 不得把 CSS 行盒稳定写成字形栅格完全一致。

