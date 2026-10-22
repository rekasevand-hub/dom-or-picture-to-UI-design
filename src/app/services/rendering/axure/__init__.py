"""`DOM -> Axure RP 8` 写入层（v2：从零生成 `.rp`）。

方案：`归档文档 axure_rp8_plan.md`；格式权威：`归档文档 axure_rp8_format.md`。

* `c1.py`      对象流编解码（字节 <-> 树）
* `store.py`   `.rppkg` 分页存储 + 规范铺页
* `constants.py`  PName / 颜色 / 内置样式 id 等常量
* `model.py`   对象图构造器（`StreamBuilder` + 页面/控件发射配方）
* `writer.py`  模板 + 生成页 -> `.rp`
* `thumbnail.py` 页包里的 `thumbnail`：按页内容自己画预览（P4）
"""
