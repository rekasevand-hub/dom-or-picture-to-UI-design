"""Axure RP 8 \u683c\u5f0f\u56de\u5f52\uff1a\u628a\u6837\u672c\u91cc\u7684\u6bcf\u4e2a c1 \u6d41\u4e0e\u6bcf\u4e2a\u5b58\u50a8\u91cd\u65b0\u5e8f\u5217\u5316\uff0c\u8981\u6c42\u9010\u5b57\u8282\u76f8\u540c\u3002

\u8fd9\u662f `归档文档 axure_rp8_format.md` \u00a78 \u8bc1\u660e A/B/E \u7684\u4ed3\u5e93\u7248\u672c\uff1a\u5b83\u4e0d\u4f9d\u8d56 \\%TEMP\\% \u91cc\u7684\u4e00\u6b21\u6027\u811a\u672c\uff0c
\u53ea\u7528 `scripts/axure_proto_gen.py` \u91cc\u7684\u8bfb\u5199\u5c42\u3002**\u9010\u5b57\u8282\u76f8\u540c**\u610f\u5473\u7740\u201c\u683c\u5f0f\u5df2\u5b8c\u5168\u89e3\u51fa\u201d\uff1a
\u53ea\u8981\u8fd9\u4e2a\u68c0\u67e5\u7eff\u7740\uff0c\u5c31\u80fd\u4fdd\u8bc1\u751f\u6210\u5668\u5199\u51fa\u7684\u5b57\u8282\u4e0e Axure \u81ea\u5df1\u5199\u7684\u540c\u6784\u3002

\u7528\u6cd5\uff1a

    & 'C:\\Users\\lzq\\.conda\\envs\\omni\\python.exe' scripts/axure_rp8_roundtrip.py
    & ... scripts/axure_rp8_roundtrip.py --samples 'path/to/*.rp'

\u9000\u51fa\u7801\uff1a0 = \u5168\u90e8\u9010\u5b57\u8282\u76f8\u540c\uff1b1 = \u6709\u4e0d\u4e00\u81f4\uff1b2 = \u6ca1\u627e\u5230\u6837\u672c\uff08\u4e0d\u7b97\u5931\u8d25\uff0c\u6253\u5370 SKIP\uff09\u3002
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import axure_proto_gen as G  # noqa: E402


def walk(data: bytes, acc: list[int]):
    """\u7edf\u8ba1\u5e76\u6821\u9a8c\u4e00\u68f5\u5b58\u50a8/\u6d41\u6811\u3002acc = [c1, c1_ok, stores, stores_ok, pages]\u3002"""
    if G.is_store(data):
        acc[2] += 1
        acc[4] += len(data) // G.BLOCK
        if G.rebuild(data, lambda _n, p: p) == data:
            acc[3] += 1
        for _name, _id, first_page, length in G.entries_of(data):
            walk(G.part_stream(data, first_page)[:length], acc)
    else:
        try:
            ver, names, guids, items = G.parse_stream(data)
        except Exception:
            return
        acc[0] += 1
        if G.serialize(ver, names, guids, items) == data:
            acc[1] += 1


def check_file(path: str) -> list[int]:
    acc = [0, 0, 0, 0, 0]
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            if member == G.VERSION_FILE:
                continue
            walk(z.read(member), acc)
    return acc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Axure RP 8 .rp \u9010\u5b57\u8282\u56de\u5f52")
    parser.add_argument("--samples", default=os.path.join("output", "_axure_samples", "*.rp"))
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(args.samples))
    if not paths:
        print(f"SKIP: \u6ca1\u627e\u5230\u6837\u672c ({args.samples})")
        return 2

    total = [0, 0, 0, 0, 0]
    bad = []
    for path in paths:
        acc = check_file(path)
        for i in range(5):
            total[i] += acc[i]
        mark = "ok" if (acc[0] == acc[1] and acc[2] == acc[3]) else "MISMATCH"
        if mark != "ok":
            bad.append(os.path.basename(path))
        print(f"{os.path.basename(path):22s} c1 {acc[1]}/{acc[0]}  stores {acc[3]}/{acc[2]}  "
              f"pages {acc[4]:5d}  [{mark}]")

    print()
    print(f"TOTAL  c1 {total[1]}/{total[0]}  stores {total[3]}/{total[2]}  pages {total[4]}")
    print("sha256(samples) =", hashlib.sha256("".join(paths).encode()).hexdigest()[:16])
    if bad:
        print("MISMATCH:", ", ".join(bad))
        return 1
    print("ALL BYTE-EXACT")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
