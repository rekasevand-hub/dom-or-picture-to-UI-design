# -*- coding: utf-8 -*-
"""把一个**原生 Axure RP8 文件**的文档级成员抽成可复用模板。

背景：v1 时代用的 `assets/axure/rp8/base.rp` 是「借母本」的产物——它的文档级常量
（`DesignDocument` / `document.settings` / 生成器配置）带着 v1 改写痕迹（4 个 `PackageInfo`、
0 个 `Node`）；该模板已随 v1 遗产删除。这里从**用户自己的原生 `.rp`** 抽，作为唯一模板。

用法：

    & 'C:\\Users\\lzq\\.conda\\envs\\omni\\python.exe' scripts/axure_rp8_import_template.py `
        --src "<原生.rp>"

产物（默认）：`assets/axure/rp8/base_native.rp` + `thumbnail_native.bin` + `widgetinfo_native.bin`。
模板只保留文档级成员，**丢掉 `Page/*` 与 `Master/*`**（页面全部由 `writer.generate()` 生成）。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.services.rendering.axure import store, writer  # noqa: E402

ASSET_DIR = os.path.join("assets", "axure", "rp8")

# 文档级成员类别（缺一不可，否则模板不完整）
REQUIRED = (
    ".version",
    "document.settings",
    "DesignDocument/",
    "CsvAnnotationReportGeneratorConfiguration/",
    "HtmlPrototypeGeneratorConfiguration/",
    "Word2007SpecificationGeneratorConfiguration/",
    "PrintConfig/",
)


def required_of(name: str):
    for prefix in REQUIRED:
        if name == prefix or name.endswith(prefix) or name.startswith(prefix):
            return prefix
    return None


def _has(members, prefix: str) -> bool:
    return any(required_of(n) == prefix for n in members)


def page_constants(member: bytes):
    """页面成员里的 (thumbnail, widgetinfo)。真机页面 = 外层存储，主 part 是内层存储。"""
    thumb = info = None
    for _name, _id, first, length in store.entries_of(member):
        payload = store.part_stream(member, first)[:length]
        if not store.is_store(payload):
            continue
        sub = {n: store.part_stream(payload, f)[:l]
               for n, _i, f, l in store.entries_of(payload)}
        if "widgetinfo" in sub or "thumbnail" in sub:
            thumb = sub.get("thumbnail") or thumb
            info = sub.get("widgetinfo") or info
    return thumb, info


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="从原生 Axure RP8 文件抽文档级模板")
    parser.add_argument("--src", required=True, help="原生 .rp（必须是 Axure 自己写出来的）")
    parser.add_argument("--out", default=os.path.join(ASSET_DIR, "base_native.rp"))
    parser.add_argument("--thumbnail-bin",
                        default=os.path.join(ASSET_DIR, "thumbnail_native.bin"))
    parser.add_argument("--widgetinfo-bin",
                        default=os.path.join(ASSET_DIR, "widgetinfo_native.bin"))
    args = parser.parse_args(argv)

    with zipfile.ZipFile(args.src) as zf:
        raw = {name: zf.read(name) for name in zf.namelist()}

    missing = [p for p in REQUIRED if not _has(raw, p)]
    if missing:
        print("ERROR: 源文件缺文档级成员: %s" % ", ".join(missing))
        return 1

    members = {n: d for n, d in raw.items()
               if not n.startswith("Page/") and not n.startswith("Master/")}
    dropped = sorted(set(raw) - set(members))

    thumb = info = None
    for name in raw:
        if name.startswith("Page/"):
            thumb, info = page_constants(raw[name])
            break

    version_member = [n for n in members if n.endswith(".version")][0]
    print("源: %s" % args.src)
    print("版本成员: %s (%d B)" % (version_member, len(members[version_member])))
    print("丢掉 %d 个页面/母版成员: %s" % (len(dropped), dropped[:3]))
    print("页面常量: thumbnail=%s widgetinfo=%s"
          % ("—" if thumb is None else "%d B sha=%s" % (len(thumb), hashlib.sha256(thumb).hexdigest()[:16]),
             "—" if info is None else "%d B sha=%s" % (len(info), hashlib.sha256(info).hexdigest()[:16])))

    bytewise = writer.self_check(members)
    integrity = writer.integrity_check(members)
    print("自检: c1 %d/%d  stores %d/%d  ok=%s"
          % (bytewise["c1_ok"], bytewise["c1"], bytewise["stores_ok"], bytewise["stores"],
             bytewise["ok"]))
    print("完整性: pages %d registered %d ok=%s"
          % (integrity["pages"], integrity["registered"], integrity["ok"]))
    for err in integrity["errors"]:
        print("   - %s" % err)
    if not (bytewise["ok"] and integrity["ok"]):
        print("ERROR: 抽出来的模板没过自检，不写盘。")
        return 1

    path = writer.write_rp(members, args.out)
    if thumb is not None:
        with open(args.thumbnail_bin, "wb") as fh:
            fh.write(thumb)
        print("写出 %s (%d B)" % (args.thumbnail_bin, len(thumb)))
    if info is not None:
        with open(args.widgetinfo_bin, "wb") as fh:
            fh.write(info)
        print("写出 %s (%d B)" % (args.widgetinfo_bin, len(info)))
    print("写出 %s (%d B, %d 成员)" % (path, os.path.getsize(path), len(members)))
    for name in sorted(members, key=writer.member_order_key):
        print("  %-95s %8d B" % (name, len(members[name])))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())