# R4-EXP-07 · 资产来源解析与降级链

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：1 个受控页面、2 个 loopback HTTP 服务、20 个资产用例、DPR 1/2 两个真实 Chromium 会话；验证原始资产下载、来源选择、失败降级与成本。  
> 证据：`output/_r4_experiments/r4_asset_resolution.json`、`output/_r4_experiments/r4_asset_artifacts/`，以及 `r4_asset_flow.png`、`r4_asset_outcomes.png`、`r4_asset_cost.png`、`r4_asset_contact_sheet.png`。  
> 边界：页面与资产由作者构造，但 HTTP 请求、DOM 观测、浏览器渲染、元素截图与图片解码均来自真实 Chromium/Pillow；未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。

## 1. 目的与边界

本实验回答 `R4-O06`：当页面同时存在可直接下载的原图、内联 SVG、CSS 渐变、data/blob URL、canvas、跨域图片、懒加载图片和失败资源时，解析器能否稳定区分“原始资产”与“视觉替代品”，并在下载失败时给出可解释的降级原因。

本实验验证的是**来源解析规则、验证门与降级链**，不验证：

- 真实站点、CDN、鉴权、Cookie、CSP、Service Worker 或缓存重验证；
- 感知哈希、视觉嵌入、OCR/CV 对资产的语义识别；
- 全站资产去重、共享整页成本或生产资产缓存；
- Figma 资产替换、图片填充写入或可编辑性；
- 任意图片格式、任意超时策略或跨浏览器行为。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Playwright / Chromium | 1.62.0 / 151.0.7922.34（headless） |
| Pillow / NumPy / Matplotlib | 12.2.0 / 1.26.4 / 3.11.0 |
| 页面服务 | 一个页面源 + 一个独立跨域源，均为 loopback HTTP |
| DPR | 1.0 与 2.0 |
| 用例 | 20 |
| 检查 | 39/39 通过 |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_asset_resolution.py
```

脚本会重建两个 HTTP 服务、页面、截图、下载文件、联系表与三张分析图。`content_hash` 覆盖包含端口与耗时在内的完整结果，因此每次重跑的哈希会变化；写盘后可排除 `content_hash` 字段重新计算并核对。

## 3. 方法

### 3.1 来源优先级

解析器按以下顺序选择：

1. `inline-svg` / `native-css`：保留原生标记或 CSS，不下载替代位图。
2. 通过验证的 HTTP 原图：`original-asset` / `http-download`。
3. `data:` / `blob:`：本地解码，分别输出 `embedded-data-uri` / `blob-url`。
4. 无法取得原图时：元素截图裁片或 canvas 导出，统一标为 `flat-raster-crop`。
5. 只有既无原图又无可用光栅替代时才输出 `unresolved`。

### 3.2 HTTP 下载验证门

下载使用独立的 Playwright `APIRequestContext`，最多跟随 5 次重定向，默认超时 2000 ms；超时用例使用 300 ms。正文必须依次通过：

- HTTP 状态为 200；
- body 非空；
- 按 magic number/内容嗅探 MIME；
- `Content-Type` 与正文嗅探结果一致；
- Pillow 能完整解码；
- 解码尺寸等于预期 `160×120`。

任一失败都记录具体原因并进入截图降级，不把“浏览器能显示”当作“原图可安全采用”。`mime-body-mismatch` 表示 header 与 body 类型不一致；`decode-failed` 表示截断或损坏；`http-404` 与 `timeout` 分别保留网络失败语义。

### 3.3 DPR 选择

同一页面分别在 DPR 1 与 DPR 2 下加载，记录 `currentSrc`、`image-set` 计算值与服务端请求计数。`srcset` 使用 `1x/2x` 描述符；`picture` 只提供 WebP；CSS `image-set` 使用 `1dppx/2dppx`。测试同时验证“选中候选”和“实际发出的请求路径”，避免只相信 DOM 字符串。

### 3.4 降级与成本

截图降级使用元素边界上的真实 Chromium 元素截图；canvas 使用页面内 `toDataURL("image/png")`。本实验为比较成本，对 20 个用例都生成了裁片；生产中应只在原图不可用时才截图，否则裁片的固定成本会被无谓放大。

成本记录为 `download_ms + crop_ms + decode_ms`；字节数是编码后的长度，不是磁盘分配或传输压缩后的线上成本。

## 4. 场景与结果

| 用例 | 声明来源 | 状态 | 选中来源 | 原因 | 尺寸 | 字节 |
|---|---|---|---|---|---:|---:|
| `img_png` | `<img>` | `original-asset` | `http-download` | `validated-original` | 160×120 | 1138 |
| `img_jpeg` | `<img>` | `original-asset` | `http-download` | `validated-original` | 160×120 | 6349 |
| `img_webp` | `<img>` | `original-asset` | `http-download` | `validated-original` | 160×120 | 1334 |
| `img_redirect` | `<img>` | `original-asset` | `http-download` | `validated-original` | 160×120 | 1138 |
| `img_404` | `<img>` | `flat-raster-crop` | `screenshot-crop` | `http-404` | 160×120 | 1744 |
| `img_timeout` | `<img>` | `flat-raster-crop` | `screenshot-crop` | `timeout` | 160×120 | 1126 |
| `img_mime_lie` | `<img>` | `flat-raster-crop` | `screenshot-crop` | `mime-body-mismatch` | 160×120 | 6291 |
| `img_truncated` | `<img>` | `flat-raster-crop` | `screenshot-crop` | `decode-failed` | 160×120 | 361 |
| `img_srcset` | `srcset` | `original-asset` | `http-download` | `validated-original` | 160×120 | 1138 |
| `picture_webp` | `<picture>` | `original-asset` | `http-download` | `validated-original` | 160×120 | 1440 |
| `css_background` | CSS background | `original-asset` | `http-download` | `validated-original` | 160×120 | 1635 |
| `css_image_set` | CSS `image-set` | `original-asset` | `http-download` | `validated-original` | 160×120 | 1472 |
| `inline_svg` | 内联 SVG | `inline-svg` | `inline-markup` | `inline-vector` | 160×120 | 346 |
| `css_gradient` | CSS gradient | `native-css` | `native-css` | `native-css` | 160×120 | 0 |
| `data_uri` | data URL | `embedded-data-uri` | `data-uri` | `data-uri-decoded` | 160×120 | 1138 |
| `blob_url` | blob URL | `blob-url` | `blob-url` | `blob-url-decoded` | 160×120 | 1138 |
| `canvas` | `<canvas>` | `flat-raster-crop` | `canvas-export` | `no-source-asset` | 160×120 | 2969 |
| `cross_origin` | 跨域 `<img>` | `original-asset` | `http-download` | `validated-original` | 160×120 | 1335 |
| `lazy_img` | `loading="lazy"` | `original-asset` | `http-download` | `validated-original` | 160×120 | 993 |
| `broken_no_src` | 无 `src` 的 `<img>` | `flat-raster-crop` | `screenshot-crop` | `missing-source` | 160×120 | 1814 |

汇总：10 个 HTTP 原图、6 个光栅降级（5 个截图裁片 + 1 个 canvas 导出）、4 个原生/本地来源（内联 SVG、CSS 渐变、data、blob）。所有 20 个用例状态、来源与原因均与预期一致。

## 5. 关键行为

### 5.1 下载失败可区分

- 404 保留 `http-404`，不误报为 `timeout` 或 `missing-source`。
- 300 ms 客户端超时对 1.2 s 端点得到 `timeout`。
- JPEG 正文冒充 `image/png` 得到 `mime-body-mismatch`。
- 60 字节截断 PNG 得到 `decode-failed`。

四类失败都回退到真实元素截图，并保留失败下载文件供复核。浏览器在超时用例中最终仍渲染出图片，但解析器仍按自己的 300 ms 超时判失败；这说明“页面视觉可用”与“原图通过采用门”是两件事。

### 5.2 跨域与懒加载

跨域图片在页面中正常渲染；页面上下文 `fetch` 被 CORS 阻断（`TypeError: Failed to fetch`），而独立请求上下文可以下载并通过验证。因此跨域资产不能只靠页面内 `fetch` 判断可用性。

懒加载图片在滚动前请求计数为 0，`currentSrc` 为空；滚动到懒加载区后请求计数为 1，并解析为 `original-asset`。滚动前的“未请求”不等于“资源缺失”。

### 5.3 原生与本地来源

内联 SVG 直接从 DOM 标记生成 `inline-svg`，不下载位图；CSS 渐变保持 `native-css`，不产生资产字节。data URL 与 blob URL 均由本地字节解码并通过尺寸检查；canvas 没有可下载的源资产，使用 `toDataURL` 导出 PNG 并标为 `flat-raster-crop`。

### 5.4 DPR

| 选择点 | DPR 1 | DPR 2 |
|---|---|---|
| `srcset` | `/srcset-1x` | `/srcset-2x` |
| CSS `image-set` | `/image-set-1x` | `/image-set-2x` |
| `picture` | `/picture-webp` | `/picture-webp` |

DPR 2 的服务端计数中没有 `1x` 候选请求；说明选择不仅在 DOM 字符串上成立，也反映到真实请求。

## 6. 成本

| 指标 | 值 |
|---|---:|
| 接受的原图字节 | 17972 |
| 降级裁片字节 | 14305 |
| 最终选中字节 | 34899 |
| 全部裁片字节（20 个） | 48570 |
| 下载 P50 / P95 / 最大 | 2.6664 / 113.9350 / 312.0163 ms |
| 截取 P50 / P95 / 最大 | 64.0540 / 65.9203 / 66.1874 ms |
| 总解析时间 | 1639.8741 ms |

裁片是主要固定成本：20 次元素截图约 1.28 s，远高于本地 HTTP 下载。实验为完整对比而对所有用例截图；生产路径应只对下载失败、canvas 或无源图片执行截图，否则“降级”会变成默认成本。

## 7. 检查

39/39 检查通过，覆盖：

- 20 个用例唯一、状态/来源/原因全部匹配；
- 原图字节、SHA-256、解码、尺寸与 MIME 一致；
- 降级裁片可解码且绝不冒充原图；
- 404、timeout、MIME 欺骗、截断、重定向原因；
- `srcset`/`image-set` 的 DPR 1/2 选择与真实请求；
- 跨域 CORS 阻断与请求上下文下载；
- 懒加载滚动前后；
- 内联 SVG、CSS 渐变、data/blob、canvas、缺失源；
- 成本字段完整、无 `unresolved`、无 `deleted`、边界只读。

## 8. 对生产资产解析器的建议

1. 先识别原生/本地来源，再尝试原图下载；不要把内联 SVG 或 CSS 渐变转换成位图。
2. 原图采用必须同时过状态、MIME、解码和尺寸门；仅“浏览器显示成功”不足以证明原图可用。
3. 失败原因必须细分到 `http-404 / timeout / mime-body-mismatch / decode-failed / missing-source`，便于重试与人工复核。
4. 跨域资产使用独立请求上下文或服务端代理下载，不能只依赖页面内 `fetch`。
5. 懒加载资产必须先滚动/触发再判断；未请求状态输出 `not-loaded`，不要输出 `missing`。
6. 截图只作降级，并统一标 `flat-raster-crop`；不得写成原始资产或可编辑资产。
7. 裁片应按需生成；固定元素截图成本明显高于本地 HTTP 下载。
8. `srcset`/`image-set` 必须记录实际 DPR 与最终请求，而不是只记录声明字符串。
9. 缓存键至少包含最终 URL、字节哈希、MIME、尺寸和 DPR 候选，避免不同候选互相覆盖。

## 9. 限制与未覆盖

- 页面与资产为作者构造的受控 loopback HTTP 内容，不是真实站点或 CDN 分布。
- 只覆盖 Chromium 与 DPR 1/2；未覆盖 Firefox/WebKit、移动模拟或浏览器 UI 缩放。
- 未覆盖 TLS、Cookie、鉴权、CSP、Service Worker、缓存重验证、Range 请求、流式响应或网络抖动。
- 未覆盖 AVIF/HEIC、外链 SVG、视频 poster、CSS cross-fade、伪元素背景与 `srcset` 宽度描述符。
- 超时是 300 ms 对 1.2 s 端点的实验设置，不是通用超时策略。
- 计时的下载使用独立请求上下文，截图使用元素截图；不是完整页面加载瀑布或生产网络剖面。
- 未实现资产去重、共享整页、生产缓存、持久化、Figma 图片替换或 Figma 写入。

## 10. 不得宣称

- 不得写“资产解析器已在真实站点验证”；本实验是受控 loopback 页面。
- 不得把 20/20 或 39/39 写成真实站点资产接受率、下载成功率或生产覆盖率。
- 不得写“截图裁片等于原始资产”或“裁片可编辑”。
- 不得写“跨域图片一定可下载”；本实验只证明 CORS 与请求上下文在此场景下的差异。
- 不得把 300 ms、2000 ms 或 5 次重定向写成通用网络策略。
- 不得把元素截图成本写成生产固定成本；应按需生成并单独测量。
- 不得把本实验写成已接入 `src/`、`figma_bridge/` 或已驱动 Figma 写入。

## 11. 证据文件

| 文件 | 内容 |
|---|---|
| `output/_r4_experiments/r4_asset_resolution.py` | 可复现实验脚本（HTTP 服务、页面、下载验证、降级、DPR、成本、绘图） |
| `output/_r4_experiments/r4_asset_resolution.json` | 20 个用例的期望、DOM、下载、验证、裁片、选择、成本与 39 项检查 |
| `output/_r4_experiments/r4_asset_artifacts/site/index.html` | 真实渲染页面 |
| `output/_r4_experiments/r4_asset_artifacts/manifest.json` | 用例、URL、期望与边界清单 |
| `output/_r4_experiments/r4_asset_artifacts/downloads/` | 成功与失败下载的原始字节 |
| `output/_r4_experiments/r4_asset_artifacts/crops/` | 20 张真实元素截图 |
| `output/_r4_experiments/r4_asset_artifacts/page_top.png` | DPR 1 页面顶部截图 |
| `output/_r4_experiments/r4_asset_artifacts/page_lazy.png` | 滚动到懒加载区后的截图 |
| `output/_r4_experiments/r4_asset_artifacts/page_dpr2.png` | DPR 2 页面截图 |
| `output/_r4_experiments/r4_asset_flow.png` | 来源优先级与降级链 |
| `output/_r4_experiments/r4_asset_outcomes.png` | 状态/来源/原因分布 |
| `output/_r4_experiments/r4_asset_cost.png` | 下载、裁片与总解析成本 |
| `output/_r4_experiments/r4_asset_contact_sheet.png` | 20 个用例联系表 |
