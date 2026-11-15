# 样本原图语料

七张基准截图（AtomGit / FluxWeaver / inventory / inventory2 / marketplace /
review / wecom-modal）的原图放在这里，文件名就是样本 tag。

**为什么存在这个目录。** 这些图当初是以剪贴板图片和微信临时文件的形式进来的，
`output/_v2_fit_<tag>/pipeline/image_reference.json` 只记了当时的绝对路径。
微信会自己清空 `RWTemp`，2026-11-15 复核时只剩 AtomGit 和 review 两张还能打开，
其余五张的绝对路径已经指向不存在的文件。`scripts/sample_sources.py` 现在先试
记录的路径，再试 `samples/image_screenshots/<tag>.{png,jpg,jpeg}`，两处都没有就
抛 `MissingScreenshot`——重放和回归测试会明确说"这张图没了"，而不是在
`cv2.imread` 里报一个看不懂的空指针。

**放回来之后要满足什么。** 尺寸必须和 `image_reference.json` 里的
`input.size` 完全一致（样本的所有坐标都是照这个画布量的），不一致会被
`sample_sources.bind` 直接拒绝。文件名里的 tag 与 `scripts/replay_pagegraph.py`
的 `SAMPLES` 一一对应。

**当前缺口。** FluxWeaver / inventory / inventory2 / marketplace / wecom-modal
五张原图已随微信临时目录丢失，暂时无法重放或重新度量。仓库里能查到的它们最后
一次量化结果在 `output/_align_round3.json`（不入库），数值抄在
`HANDOFF_2026-11-15_visual_fidelity_pass.md`。拿到原图后按上面的规则命名放进来，
`python scripts/replay_pagegraph.py` 与 `python scripts/visual_alignment.py`
即可恢复对这五张的度量。
