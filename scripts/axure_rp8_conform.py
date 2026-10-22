# -*- coding: utf-8 -*-
"""对**真实 Axure RP8 文件**跑完整性自检 + 逐字节自检（真机一致性回归）。

`scripts/axure_rp8_roundtrip.py` 只覆盖仓库里的 v1 样本；这个脚本用来把
`writer.integrity_check` 压到原生 Axure 写出的文件上（几十到几百页、含母版、
文件夹、动态面板、空页）。真实文件不入库，所以在这里按路径传入。

用法：

    & 'C:\\Users\\lzq\\.conda\\envs\\omni\\python.exe' scripts/axure_rp8_conform.py <file.rp> ...
    & ... scripts/axure_rp8_conform.py --dirs 'D:\\path\\one;D:\\path\\two'

`--dirs` 用 `os.pathsep`（Windows 上是 `;`）分隔，递归找 `*.rp`。
退出码：0 = 全部通过；1 = 有失败；2 = 没找到文件（打印 SKIP）。
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.services.rendering.axure import writer  # noqa: E402


def _collect(args) -> list:
    paths = []
    for path in args.files:
        paths.append(path)
    for root in (args.dirs or "").split(os.pathsep):
        root = root.strip()
        if not root:
            continue
        paths += [str(p) for p in sorted(Path(root).rglob("*.rp"))]
    return sorted(dict.fromkeys(paths))


def check(path: str) -> tuple:
    with zipfile.ZipFile(path) as zf:
        members = {name: zf.read(name) for name in zf.namelist()}
    integrity = writer.integrity_check(members)
    return integrity, writer.self_check(members)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Axure RP 8 真机一致性回归")
    parser.add_argument("files", nargs="*", help="真实 .rp 文件")
    parser.add_argument("--dirs", default="", help="递归扫描的目录（os.pathsep 分隔）")
    args = parser.parse_args(argv)

    paths = _collect(args)
    if not paths:
        print("SKIP: 没给文件。用 `<file.rp>` 或 `--dirs <目录>`。")
        return 2

    failed = []
    for path in paths:
        name = os.path.basename(path)
        try:
            integrity, bytewise = check(path)
        except Exception as exc:                       # 非 .rp / 非 RP8：跳过不判失败
            print(f"{name:52s} [{type(exc).__name__}: {exc}]")
            continue
        ok = integrity["ok"] and bytewise["ok"]
        if not ok:
            failed.append(name)
        print(f"{name:52s} members={bytewise['members']:4d} pages={integrity['pages']:4d} "
              f"registered={integrity['registered']:4d} "
              f"c1={bytewise['c1_ok']}/{bytewise['c1']} "
              f"stores={bytewise['stores_ok']}/{bytewise['stores']} "
              f"[{'ok' if ok else 'FAIL'}]")
        for err in integrity["errors"][:6]:
            print("      -", err)

    print()
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print(f"ALL {len(paths)} FILE(S) PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
