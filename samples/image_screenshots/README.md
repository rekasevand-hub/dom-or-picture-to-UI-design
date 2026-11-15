# 样本原图语料

七张基准截图（AtomGit / FluxWeaver / inventory / inventory2 / marketplace /
review / wecom-modal）的原图放在这里，文件名就是样本 tag。

**为什么存在这个目录。** 这些图当初是以剪贴板图片和微信临时文件的形式进来的，
`output/_v2_fit_<tag>/pipeline/image_reference.json` 只记了当时的绝对路径。
微信会自己清空 `RWTemp`，2026-11-15 上午五张曾一度全部消失，当天由用户重新提供、
按 sha256 逐一核对后入库。原图随仓库走，重放与度量就不再依赖任何临时目录。

**放进来之后要满足什么。** 尺寸必须和 `image_reference.json` 里的 `input.size`
完全一致（样本的所有坐标都是照这个画布量的），不一致会被 `sample_sources.bind`
直接拒绝。文件名里的 tag 与 `scripts/replay_pagegraph.py` 的 `SAMPLES` 一一对应。
`scripts/sample_sources.py` 先试记录路径，再试本目录。

**当前状态（七张齐）：**

| 文件 | 尺寸 | 与记录 sha256 |
|---|---|---|
| `AtomGit.jpg` | 1920x1008 | 一致 |
| `FluxWeaver.png` | 1920x826 | 一致 |
| `inventory.png` | 2560x1262 | 一致 |
| `inventory2.png` | 1920x826 | 一致 |
| `review.jpg` | 1920x1008 | 一致 |
| `wecom-modal.png` | 2560x1274 | 一致 |
| `marketplace.png` | 2544x1336 | **不同**：原文件已失，这是重新下载的一份，尺寸相同、PNG 字节不同；重测 95.99%，与失图前 96.00% 差 0.01 |

`marketplace` 这一行的 sha 差异只影响 `image_reference.json` 里那句
`screenshot_sha256` 的自述，不影响坐标与度量；如果日后拿到原文件，直接覆盖同名
文件即可，`bind()` 只校验尺寸。

**验证方式：**

```bash
python scripts/replay_pagegraph.py            # 七张全跑，产物 output/_replay_<tag>/
python scripts/visual_alignment.py            # within30/within15 + diff.png
python scripts/visual_alignment.py --json output/_align_roundN.json
```
