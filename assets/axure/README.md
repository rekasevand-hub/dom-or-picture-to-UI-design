# Axure 资产

> **2026-10-13**：v1「骨架 + 按值改写几何」路线及其全部资产（`skeleton*`、
> `color_slots.json`、`source/grown_*.rp`、`backup/`、`axure_rp.py` 与其脚本 / 测试）
> 已删除。`--tool axure` 现在走 **v2 从零生成**：直接写 `Page/<guid>.rppkg` +
> 改写 `DesignDocument` 注册表。

当前目录只剩 v2 需要的**文档级模板**：

    assets/axure/rp8/base_native.rp        # 文档级常量（原生 Axure 文件抽出）
    assets/axure/rp8/widgetinfo_native.bin # Page 包常量（199 B）
    assets/axure/rp8/thumbnail_native.bin  # 页面缩略图字节（暂借用原生，见 §3.5）

模板由 `scripts/axure_rp8_import_template.py` 从**用户自己的原生 `.rp`** 抽出；换模板时才重跑。

* 现行实现：`src/app/services/rendering/axure/`（`c1` / `store` / `constants` / `model` / `doc` / `writer`）
* 历史格式/方案：`axure_rp8_format.md`、`axure_rp8_plan.md`（已随 1.0.1 归档）
* 现行交接：`../../HANDOFF_2026-10-17_release.md`
* 真机发布：`scripts/axure_publish_html.ps1`（会 kill `AxureRP8`，先存盘退出）
