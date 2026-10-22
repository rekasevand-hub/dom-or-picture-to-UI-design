# -*- coding: utf-8 -*-
"""按对象类型把 Axure RP8 页面里的对象（含它的 Axure:Style）dump 成可读树。

逆向用工具：`归档文档 axure_rp8_format.md` 里那些「键序 / PropList 槽」结论就是靠
这种东西逐条核出来的。只读，不改文件。

用法：

    & $PY scripts/axure_rp8_dump.py <file.rp> --kind ImageBox --index 0
    & $PY scripts/axure_rp8_dump.py <file.rp> --page 2 --kind VectorShape --style
    & $PY scripts/axure_rp8_dump.py <file.rp> --kinds          # 只列对象种类计数
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.services.rendering.axure import c1, store  # noqa: E402

BLOCK = store.BLOCK
PAYLOAD = store.PAYLOAD


def load_page(rp: str, index: int):
    """取第 index 个 Page/*.rppkg 的页面流（L1 -> L2 -> package part）。"""
    with zipfile.ZipFile(rp) as zf:
        pages = sorted(n for n in zf.namelist()
                       if n.startswith("Page/") and n.endswith(".rppkg"))
        if not pages:
            raise SystemExit("no Page/*.rppkg in %s" % rp)
        raw = zf.read(pages[index])
    outer = dict(store.parts_of(store.parts_of(raw)[0][1]))
    return c1.parse_stream(outer["package"])


class Dumper:
    def __init__(self, names, guids):
        self.names = names
        self.guids = guids

    def guid(self, idx):
        return self.guids[idx].hex()[:8] if idx else "NULL"

    def dump(self, it, ind=0):
        pad = "  " * ind
        t = it[0]
        if t == c1.T_OBJ:
            return "%sOBJ guid=%s type=%s\n%s" % (
                pad, self.guid(it[1]), self.names[it[2]], self.dump(it[3], ind + 1))
        if t == c1.T_DD:
            rows = []
            for k, v in it[1]:
                key = self.names[k[1]] if k[0] == c1.T_STR else "<key:%r>" % (k,)
                rows.append("%s  %s = %s" % (pad, key, self.dump(v, ind + 2).lstrip()))
            return pad + "dd{\n" + "\n".join(rows) + "\n" + pad + "}"
        if t == c1.T_LIST:
            if not it[1]:
                return pad + "list[]"
            return (pad + "list[\n"
                    + "\n".join(self.dump(c, ind + 1) for c in it[1])
                    + "\n" + pad + "]")
        if t == c1.T_STR:
            return "%r" % self.names[it[1]]
        if t == c1.T_GUID:
            return "guid(%s)" % self.guid(it[1])
        if t in (c1.T_REF, c1.T_REF20, c1.T_DJ, c1.T_PK):
            return "ref%d(%s)" % (t, self.guid(it[1]))
        if t == c1.T_INT:
            return "int(%d)" % it[1]
        if t == c1.T_I64:
            return "i64(%d)" % it[1]
        if t == c1.T_F64:
            return "f64(%r)" % it[1]
        if t == c1.T_F32:
            return "f32(%r)" % it[1]
        if t == c1.T_BOOL:
            return "bool(%d)" % it[1]
        if t == c1.T_BLOB:
            return "BLOB(%d bytes) head=%s" % (len(it[1]), it[1][:8].hex())
        if t == c1.T_AH:
            return "ah(name=%r, guid=%s)" % (self.names[it[1]], self.guid(it[2]))
        if t == c1.T_FX:
            return "fx(type=%r, guid=%s)" % (self.names[it[1]], self.guid(it[2]))
        if t == c1.T_PKGCTX:
            return "pkgctx(root=%s, pkg=%s)" % (self.guid(it[2]), self.guid(it[4]))
        return "<tag%d %r>" % (t, it[1:])


def pname_of(row, names):
    """PropList 一条 -> (PName 名, DOAName)。"""
    from src.app.services.rendering.axure.constants import pname_name
    from src.app.services.rendering.axure import c1 as _c1
    doa = _c1.dd_get(row, names, 'DOAName')[1]
    pname = doa & 0x7FFFFFFF if doa < 0 else doa
    pname = doa - (-1073741824) if pname >= 0x40000000 else pname
    return pname, pname_name(pname), doa


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Axure RP8 页面对象 dump")
    ap.add_argument("rp")
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--kind", default="", help="对象类型后缀，如 ImageBox / VectorShape")
    ap.add_argument("--index", type=int, default=0, help="第几个匹配对象")
    ap.add_argument("--all", action="store_true", help="dump 所有匹配对象")
    ap.add_argument("--style", action="store_true", help="同时 dump MyStyle 指向的 Axure:Style")
    ap.add_argument("--kinds", action="store_true", help="只列对象种类计数")
    args = ap.parse_args(argv)

    ver, names, guids, items = load_page(args.rp, args.page)
    d = Dumper(names, guids)
    objs = list(c1.iter_objects(items))

    if args.kinds:
        counts = {}
        for o in objs:
            counts[names[o[2]]] = counts.get(names[o[2]], 0) + 1
        print("c1 version:", ver)
        print("names=%d guids=%d objects=%d" % (len(names) - 1, len(guids) - 1, len(objs)))
        for k in sorted(counts):
            print("   %-52s %d" % (k, counts[k]))
        return 0

    matches = [o for o in objs if names[o[2]].endswith(":" + args.kind)]
    if not matches:
        print("no object of kind %r" % args.kind)
        return 1
    picks = matches if args.all else matches[args.index:args.index + 1]
    for n, obj in enumerate(picks):
        print("=" * 72)
        print("OBJ guid=%s type=%s" % (d.guid(obj[1]), names[obj[2]]))
        print(d.dump(obj[3]))
        if args.style:
            ref = c1.dd_get(obj[3], names, "MyStyle")
            if ref is not None:
                sg = guids[ref[1]]
                st = [o for o in objs if o[0] == c1.T_OBJ and guids[o[1]] == sg]
                if st:
                    print("-" * 72)
                    print("MyStyle -> Axure:Style guid=%s" % sg.hex()[:8])
                    print(d.dump(st[0][3]))
                    prop = c1.dd_get(st[0][3], names, "PropList")
                    if prop is not None:
                        print("-" * 72)
                        print("PropList 槽位表：")
                        for row in prop[1]:
                            pname, label, doa = pname_of(row, names)
                            value = row[1][1]
                            tv = value[0]
                            if tv == c1.T_DD:
                                keys = ",".join(names[k[1]] for k, _ in value[1])
                                summary = "dd{%s}" % keys
                            elif tv == c1.T_BLOB:
                                summary = "BLOB(%d)" % len(value[1])
                            elif tv == c1.T_STR:
                                summary = repr(names[value[1]])
                            elif tv == c1.T_BOOL:
                                summary = "bool(%d)" % value[1]
                            elif tv == c1.T_GUID:
                                summary = "guid(%s)" % d.guid(value[1])
                            else:
                                summary = "%r" % (value[1],)
                            print("   %-10s P%-5d doa=%-12d %s" % (label, pname, doa, summary))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())