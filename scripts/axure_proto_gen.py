"""Axure RP 8 \u300c\u4ece\u96f6\u751f\u6210\u300dPoC\uff08M0 \u8bc1\u636e\u811a\u672c\uff09\u3002

\u80cc\u666f\uff1a`归档文档 axure_rp8_format.md` \u5df2\u628a `.rp` \u683c\u5f0f\u5b8c\u5168\u89e3\u51fa\uff08c1 \u6d41\u9010\u5b57\u8282\u91cd\u653e 100/100\uff1b
\u5206\u9875\u5b58\u50a8\u91cd\u94fa 50/50\uff09\u3002\u672c\u811a\u672c\u628a\u5b83\u7528\u6210\u4e00\u4e2a\u771f\u7684\u751f\u6210\u5668\uff0c\u8bc1\u660e\uff1a
**\u4e0d\u9700\u8981\u300c\u501f\u9aa8\u67b6\u300d\uff0c\u4e5f\u4e0d\u9700\u8981\u7b49\u957f\u6539\u5199\u2014\u2014\u9875\u9762\u5305\u53ef\u4ee5\u7531\u6a21\u578b\u91cd\u65b0\u751f\u6210\uff0c\u5305\u62ec\u540d\u5b57\u6c60\u6269\u5bb9**
\uff08\u65e7\u8def\u7ebf\u65ad\u8a00\u201c\u6269\u5bb9\u4e0d\u53ef\u884c\u201d\uff09\u3002

\u505a\u4e0b\u5217\u4e8b\uff1a

1. \u628a\u6e90 `.rp` \u6bcf\u4e2a\u6210\u5458\u89e3\u6790\u6210\u6a21\u578b\uff1b
2. \u7528**\u89c4\u8303\u5e03\u5c40**\uff08\u76ee\u5f55\u9875\u5728 0\u3001part \u8fde\u7eed\u94fa\u3001\u9875\u5934 = part id\uff09\u91cd\u65b0\u751f\u6210\u6bcf\u4e2a
   `.rppkg`\uff0c\u5e76\u628a\u76ee\u6807\u63a7\u4ef6\u7684\u51e0\u4f55\uff08\u5728 `Style.PropList` \u91cc\uff09\u4e0e\u6587\u672c\uff08\u5728
   `RichTextPanel.rtf-block...Inlines[].Text`\uff09\u6362\u6210\u65b0\u503c\uff1b\u6587\u672c\u4f1a**\u6269\u5145\u540d\u5b57\u6c60**\uff1b
3. \u5199\u51fa\u4e00\u4e2a\u65b0 `.rp`\uff1b
4. \u81ea\u68c0\uff1a\u6bcf\u4e2a c1 \u6d41\u9010\u5b57\u8282\u91cd\u653e\u3001\u6bcf\u4e2a\u5b58\u50a8\u9010\u5b57\u8282\u91cd\u94fa\u3001\u6539\u540e\u7684\u503c\u80fd\u8bfb\u56de\u3002

\u7528\u6cd5\uff1a

    & 'C:\\Users\\lzq\\.conda\\envs\\omni\\python.exe' scripts/axure_proto_gen.py `
        --src output/_axure_samples/rect_a.rp --out output/_axure_proto/rect_a_gen.rp `
        --geometry 300,250,260,140

\u9650\u5236\uff1a\u8fd9\u662f PoC\uff0c\u4e0d\u662f\u4ea7\u54c1\u4ee3\u7801\u3002\u5b83\u4e0d\u65b0\u589e\u63a7\u4ef6\u3001\u4e0d\u6539 GUID \u8868\u3002
\u201cAxure \u80fd\u4e0d\u80fd\u6253\u5f00\u201d\u7528\u7684\u662f\u771f\u673a oracle\uff0c\u4e0d\u5728\u672c\u811a\u672c\u91cc\u3002
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import zipfile
from pathlib import Path

BLOCK = 4096
PAYLOAD = 4084
VERSION_FILE = "8.0.0.3400.version"

# PName\uff08Core.dll\uff09\u2014\u2014\u51e0\u4f55\u843d\u5728 Style.PropList\uff0cDOAName = 0xC0000000 | PName
PNAME_LOCATION = 101
PNAME_SIZE = 105
# DOAName 存的是 **有符号** int32：0xC0000000 读出来是 -1073741824（c1 的 i32 是 signed）。
DOA_BASE = -1073741824   # == 0xC0000000


# --------------------------------------------------------------------------- \u4f4e\u5c42\uff1ac1 \u6d41 -------------------------------------------

def i32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<i", buf, off)[0]


def part_stream(raw: bytes, first_page: int) -> bytes:
    """\u6cbf\u9875\u94fe\u628a\u4e00\u4e2a part \u7684\u51c0\u8377\u62fc\u56de\u903b\u8f91\u6d41\u3002"""
    out = bytearray()
    page = first_page
    while True:
        block = raw[page * BLOCK:(page + 1) * BLOCK]
        kind = i32(block, 4088)
        value = i32(block, 4092)
        if kind == 1:
            out += block[4:4088]
            page = value
        elif kind == 2:
            out += block[4:4 + value]
            break
        else:
            raise ValueError(f"bad epilogue {kind} @page {page}")
    return bytes(out)


def read_header(buf: bytes):
    if i32(buf, 0) != 27:
        raise ValueError("not a c1 stream")
    ver = struct.unpack_from("<5i", buf, 4)
    if i32(buf, 24) != 31:
        raise ValueError("bad name-pool marker")
    count = i32(buf, 28)
    pos = 32
    names = [None]
    for _ in range(count):
        size = i32(buf, pos)
        pos += 4
        names.append(buf[pos:pos + size].decode("utf-8"))
        pos += size
    if i32(buf, pos) != 30:
        raise ValueError("bad guid-pool marker")
    guid_count = i32(buf, pos + 4)
    pos += 8
    guids = [None] + [bytes(buf[pos + 16 * k:pos + 16 * k + 16]) for k in range(guid_count)]
    pos += 16 * guid_count
    return ver, names, guids, pos


def parse_item(buf: bytes, pos: int):
    raw = i32(buf, pos)
    pos += 4
    tag = raw & 31            # \u8bfb\u4fa7\u906e\u7f69\uff08c1.cs:1296\uff09\uff1b\u5199\u4fa7\u5199\u5e73\u7684 1..31
    if tag == 1:
        count = i32(buf, pos)
        pos += 4
        pairs = []
        for _ in range(count):
            key, pos = parse_item(buf, pos)
            value, pos = parse_item(buf, pos)
            pairs.append([key, value])
        return [1, pairs, raw], pos
    if tag == 2:
        count = i32(buf, pos)
        pos += 4
        items = []
        for _ in range(count):
            item, pos = parse_item(buf, pos)
            items.append(item)
        return [2, items, raw], pos
    if tag in (8, 3, 17, 20, 21, 22, 5):
        return [tag, i32(buf, pos), raw], pos + 4
    if tag == 7:
        return [7, struct.unpack_from("<f", buf, pos)[0], raw], pos + 4
    if tag == 6:
        return [6, struct.unpack_from("<d", buf, pos)[0], raw], pos + 8
    if tag == 29:
        return [29, struct.unpack_from("<q", buf, pos)[0], raw], pos + 8
    if tag == 25:
        return [25, buf[pos], raw], pos + 1
    if tag == 4:
        size = i32(buf, pos)
        return [4, bytes(buf[pos + 4:pos + 4 + size]), raw], pos + 4 + size
    if tag == 9:
        guid_idx = i32(buf, pos)
        type_idx = i32(buf, pos + 4)
        body, pos = parse_item(buf, pos + 8)
        return [9, guid_idx, type_idx, body, raw], pos
    if tag in (16, 19):
        return [tag, i32(buf, pos), i32(buf, pos + 4), raw], pos + 8
    if tag == 26:
        return [26, *struct.unpack_from("<4i", buf, pos), raw], pos + 16
    if tag in (27, 28, 30, 31):      # 无 payload
        return [tag, raw], pos
    raise ValueError(f"unknown tag raw={raw} tag={tag} at {pos - 4}")


def emit(item) -> bytes:
    tag = item[0]
    out = bytearray(struct.pack("<i", item[-1]))
    if tag == 1:
        out += struct.pack("<i", len(item[1]))
        for key, value in item[1]:
            out += emit(key) + emit(value)
    elif tag == 2:
        out += struct.pack("<i", len(item[1]))
        for child in item[1]:
            out += emit(child)
    elif tag in (8, 3, 17, 20, 21, 22, 5):
        out += struct.pack("<i", item[1])
    elif tag == 7:
        out += struct.pack("<f", item[1])
    elif tag == 6:
        out += struct.pack("<d", item[1])
    elif tag == 29:
        out += struct.pack("<q", item[1])
    elif tag == 25:
        out += struct.pack("<B", item[1])
    elif tag == 4:
        out += struct.pack("<i", len(item[1])) + item[1]
    elif tag == 9:
        out += struct.pack("<ii", item[1], item[2]) + emit(item[3])
    elif tag in (16, 19):
        out += struct.pack("<ii", item[1], item[2])
    elif tag == 26:
        out += struct.pack("<4i", item[1], item[2], item[3], item[4])
    elif tag in (27, 28, 30, 31):
        pass
    else:
        raise ValueError(f"unhandled tag {tag}")
    return bytes(out)


def serialize(ver, names, guids, items) -> bytes:
    out = bytearray(struct.pack("<i", 27) + struct.pack("<5i", *ver))
    out += struct.pack("<i", 31) + struct.pack("<i", len(names) - 1)
    for name in names[1:]:
        blob = name.encode("utf-8")
        out += struct.pack("<i", len(blob)) + blob
    out += struct.pack("<i", 30) + struct.pack("<i", len(guids) - 1)
    for guid in guids[1:]:
        out += guid
    for item in items:
        out += emit(item)
    return bytes(out)


def parse_stream(buf: bytes):
    ver, names, guids, pos = read_header(buf)
    items = []
    while pos < len(buf):
        item, pos = parse_item(buf, pos)
        items.append(item)
    return ver, names, guids, items


# --------------------------------------------------------------------------- \u4f4e\u5c42\uff1a\u5b58\u50a8 -------------------------------------------

def is_store(buf: bytes) -> bool:
    return len(buf) >= BLOCK and len(buf) % BLOCK == 0 and i32(buf, 4088) in (1, 2)


def entries_of(physical: bytes):
    """\u8fd4\u56de [(name, id, first_page, length)]\uff08\u8bfb\u76ee\u5f55\u9875\uff09\u3002"""
    _, names, _, items = parse_stream(part_stream(physical, 0))
    out = []
    for entry in items[0][1][0][1][1]:
        row = {names[key[1]]: value for key, value in entry[1]}
        out.append((names[row["name"][1]], row["id"][1], row["first-page"][1], row["Length"][1]))
    return out


def lay_store(parts):
    """\u7528\u89c4\u8303\u5e03\u5c40\u628a [(name, payload)] \u94fa\u6210\u4e00\u4e2a\u7269\u7406\u5b58\u50a8\u3002"""
    import math
    entries = []
    first = 1
    for idx, (name, payload) in enumerate(parts, start=1):
        entries.append((name, idx, first, len(payload)))
        first += max(1, math.ceil(len(payload) / PAYLOAD))
    dirc = _directory_stream(entries)
    out = bytearray()
    out += struct.pack("<i", 0) + dirc + bytes(PAYLOAD - len(dirc))
    out += struct.pack("<ii", 2, len(dirc))
    for (_, payload), (_, idx, _, _) in zip(parts, entries):
        offset = 0
        while True:
            chunk = payload[offset:offset + PAYLOAD]
            used = len(chunk)
            out += struct.pack("<i", idx) + chunk + bytes(PAYLOAD - used)
            if offset + PAYLOAD >= len(payload):
                out += struct.pack("<ii", 2, used)
                break
            out += struct.pack("<ii", 1, (len(out) // BLOCK) + 1)
            offset += PAYLOAD
    return bytes(out)


def _directory_stream(entries) -> bytes:
    """目录流 = c1 信封 + dd{"item-infos": list[...]} + tag 28。

    名字池按 **首次使用顺序** 建，与 Axure 写出的字节一致：
    item-infos → 每行依次 name, <part名>, id, first-page, Length。
    残影（rect_a.rp 的 L2）：
    [item-infos, name, thumbnail, id, first-page, Length, widgetinfo, package]
    """
    pool = [None]

    def pidx(text):
        if text not in pool:
            pool.append(text)
        return pool.index(text)

    item_infos = pidx("item-infos")
    rows = []
    for name, idx, first_page, length in entries:
        rows.append([1, [
            [[8, pidx("name"), 8], [8, pidx(name), 8]],
            [[8, pidx("id"), 8], [5, idx, 5]],
            [[8, pidx("first-page"), 8], [5, first_page, 5]],
            [[8, pidx("Length"), 8], [5, length, 5]],
        ], 1])
    body = [1, [[[8, item_infos, 8], [2, rows, 2]]], 1]
    # 目录流的版本元组与对象流不同：实测 7 个样本里每个 DIR 都是
    # (0,0,3,0,50001)，每个 OBJ 都是 (8,0,5,0,50001)。
    return serialize((0, 0, 3, 0, 50001), pool, [None], [body, [28, 28]])


# --------------------------------------------------------------------------- \u6a21\u578b\u5c42\uff1a\u67e5\u627e\u4e0e\u4fee\u6539 --------------------------------

def dd_get(item, names, key):
    if item[0] != 1:
        return None
    for k, v in item[1]:
        if k[0] == 8 and names[k[1]] == key:
            return v
    return None


def all_records(items):
    """\u6240\u6709 tag 9 \u8bb0\u5f55\uff08\u6df1\u5ea6\u4f18\u5148\uff09\u3002"""
    for item in items:
        if item[0] == 9:
            yield item
            yield from all_records([item[3]])
        elif item[0] == 2:
            yield from all_records(item[1])
        elif item[0] == 1:
            for _, v in item[1]:
                yield from all_records([v])


def set_double(item, value):
    assert item[0] == 6, item
    item[1] = float(value)
    return item


def set_string(item, pool_index, names):
    assert item[0] == 8, item
    item[1] = pool_index
    item[2] = 8
    return item


def pool_add(names, text):
    if text in names:
        return names.index(text)
    names.append(text)
    return len(names) - 1


def patch_geometry(records, names, x, y, width, height):
    """\u51e0\u4f55\u5728 `Axure:Style.PropList`\uff1aDOA = 0xC0000000|PName\u3002"""
    hits = {"x": 0, "y": 0, "w": 0, "h": 0}
    for record in records:
        if names[record[2]] != "Axure:Style":
            continue
        proplist = dd_get(record[3], names, "PropList")
        if proplist is None:
            continue
        for entry in proplist[1]:
            doa = dd_get(entry, names, "DOAName")
            value = dd_get(entry, names, "Value")
            if doa is None or value is None or value[0] != 1:
                continue
            if doa[1] == DOA_BASE | PNAME_SIZE:
                if dd_get(value, names, "Width") is not None:
                    set_double(dd_get(value, names, "Width"), width)
                    hits["w"] += 1
                if dd_get(value, names, "Height") is not None:
                    set_double(dd_get(value, names, "Height"), height)
                    hits["h"] += 1
            elif doa[1] == DOA_BASE | PNAME_LOCATION:
                if dd_get(value, names, "X") is not None:
                    set_double(dd_get(value, names, "X"), x)
                    hits["x"] += 1
                if dd_get(value, names, "Y") is not None:
                    set_double(dd_get(value, names, "Y"), y)
                    hits["y"] += 1
    return hits


def patch_text(records, names, text):
    """\u6587\u672c\u5728 `RichTextPanel.rtf-block.attributed-string.Paragraphs[].Inlines[].Text`\u3002"""
    index = pool_add(names, text)
    hits = 0
    for record in records:
        if names[record[2]] != "Axure:DiagramObject:RichTextPanel":
            continue
        rtf = dd_get(record[3], names, "rtf-block")
        if rtf is None:
            continue
        strings = dd_get(rtf, names, "attributed-string")
        paragraphs = dd_get(strings, names, "Paragraphs")
        for paragraph in paragraphs[1]:
            inlines = dd_get(paragraph, names, "Inlines")
            for inline in inlines[1]:
                node = dd_get(inline, names, "Text")
                if node is not None:
                    set_string(node, index, names)
                    hits += 1
    return hits, index


def has_page(stream: bytes) -> bool:
    try:
        _, names, _, items = parse_stream(stream)
    except Exception:
        return False
    return any(names[r[2]] == "Axure:Page" for r in all_records(items))


# --------------------------------------------------------------------------- \u91cd\u5efa -----------------------------------------------

def rebuild(physical: bytes, mutate):
    """\u9012\u5f52\u91cd\u5efa\u4e00\u68f5\u5b58\u50a8\u6811\uff1bmutate(stream) -> stream \u53ea\u5bf9\u9875\u9762\u5305\u751f\u6548\u3002"""
    parts = []
    for name, _, first_page, length in entries_of(physical):
        payload = part_stream(physical, first_page)[:length]
        if is_store(payload):
            payload = rebuild(payload, mutate)
        else:
            payload = mutate(name, payload)
        parts.append((name, payload))
    return lay_store(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Axure RP 8 \u4ece\u96f6\u751f\u6210 PoC")
    parser.add_argument("--src", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--geometry", default=None, help="x,y,w,h")
    parser.add_argument("--text", default=None)
    args = parser.parse_args(argv)

    geometry = None
    if args.geometry:
        geometry = [float(v) for v in args.geometry.split(",")]
        assert len(geometry) == 4, "--geometry \u9700\u8981 x,y,w,h"

    src = zipfile.ZipFile(args.src)
    names_in_zip = src.namelist()
    page_member = next(n for n in names_in_zip if n.startswith("Page/"))
    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {"geometry_hits": None, "text_hits": 0, "pool_before": 0, "pool_after": 0}

    def mutate(member_name, payload):
        if member_name != "package" or not has_page(payload):
            return payload
        ver, names, guids, items = parse_stream(payload)
        report["pool_before"] = len(names) - 1
        records = list(all_records(items))
        if geometry:
            report["geometry_hits"] = patch_geometry(records, names, *geometry)
        if args.text:
            report["text_hits"], index = patch_text(records, names, args.text)
            report["text_index"] = index
        report["pool_after"] = len(names) - 1
        return serialize(ver, names, guids, items)

    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == page_member:
                data = rebuild(data, mutate)
            dst.writestr(info, data)

    check(args.out, args.src, geometry, args.text, report)
    return 0


def _walk_streams(physical: bytes):
    for name, _, first_page, length in entries_of(physical):
        payload = part_stream(physical, first_page)[:length]
        yield name, payload
        if is_store(payload):
            yield from _walk_streams(payload)


def check(out_path, src_path, geometry, text, report):
    out = zipfile.ZipFile(out_path)
    src = zipfile.ZipFile(src_path)
    streams_ok = streams = 0
    stores_ok = stores = 0
    for member in out.namelist():
        data = out.read(member)
        if member == VERSION_FILE:
            continue
        if not member.endswith(".rppkg") and member != "document.settings":
            continue
        for name, payload in _walk_streams(data) if is_store(data) else [("stream", data)]:
            if is_store(payload):
                continue
            try:
                ver, names, guids, items = parse_stream(payload)
            except Exception:
                continue
            streams += 1
            if serialize(ver, names, guids, items) == payload:
                streams_ok += 1
            else:
                print(f"  !! c1 \u91cd\u653e\u4e0d\u4e00\u81f4: {member}::{name}")
        if is_store(data):
            stores += 1
            if rebuild(data, lambda n, p: p) == data:
                stores_ok += 1
            else:
                print(f"  !! \u5b58\u50a8\u91cd\u94fa\u4e0d\u4e00\u81f4: {member}")

    # \u6539\u540e\u7684\u503c\u80fd\u4e0d\u80fd\u8bfb\u56de
    page_member = next(n for n in out.namelist() if n.startswith("Page/"))
    got = None
    for name, payload in _walk_streams(out.read(page_member)):
        if name == "package" and has_page(payload):
            _, names, _, items = parse_stream(payload)
            got = (names, items)
    assert got is not None, "\u8bfb\u4e0d\u5230\u9875\u9762\u5305"
    names, items = got
    records = list(all_records(items))
    if geometry:
        found = {}
        for record in records:
            if names[record[2]] != "Axure:Style":
                continue
            proplist = dd_get(record[3], names, "PropList")
            if proplist is None:
                continue
            for entry in proplist[1]:
                doa = dd_get(entry, names, "DOAName")
                value = dd_get(entry, names, "Value")
                if doa is None or value is None or value[0] != 1:
                    continue
                for key, tag in (("X", 101), ("Y", 101), ("Width", 105), ("Height", 105)):
                    node = dd_get(value, names, key)
                    if node is not None and doa[1] == DOA_BASE | tag:
                        found[key] = node[1]
        expect = {"X": geometry[0], "Y": geometry[1], "Width": geometry[2], "Height": geometry[3]}
        assert all(found.get(k) == v for k, v in expect.items()), f"\u51e0\u4f55\u8bfb\u56de\u4e0d\u5bf9: {found} != {expect}"
        print(f"  [ok] \u51e0\u4f55\u8bfb\u56de {found}")
    if text:
        found = []
        for record in records:
            if names[record[2]] != "Axure:DiagramObject:RichTextPanel":
                continue
            rtf = dd_get(record[3], names, "rtf-block")
            for paragraph in dd_get(dd_get(rtf, names, "attributed-string"), names, "Paragraphs")[1]:
                for inline in dd_get(paragraph, names, "Inlines")[1]:
                    node = dd_get(inline, names, "Text")
                    if node is not None:
                        found.append(names[node[1]])
        assert found == [text], f"\u6587\u672c\u8bfb\u56de\u4e0d\u5bf9: {found}"
        print(f"  [ok] \u6587\u672c\u8bfb\u56de {found}")

    print(f"  [ok] c1 \u6d41\u91cd\u653e {streams_ok}/{streams}\uff1b\u5b58\u50a8\u91cd\u94fa {stores_ok}/{stores}")
    print(f"  [ok] \u540d\u5b57\u6c60 {report['pool_before']} -> {report['pool_after']}\uff08\u6269\u5bb9\uff09\uff1b"
          f"\u51e0\u4f55\u547d\u4e2d {report['geometry_hits']}\uff1b\u6587\u672c\u547d\u4e2d {report['text_hits']}")
    diff = []
    for member in src.namelist():
        if member not in out.namelist():
            diff.append(member)
            continue
        a, b = src.read(member), out.read(member)
        if a != b:
            diff.append(f"{member} ({len(a)}->{len(b)} B)")
    print(f"  [ok] \u4e0e\u6e90\u6587\u4ef6\u76f8\u6bd4\u53d8\u5316\u7684\u6210\u5458: {diff or '\u65e0'}")
    print(f"  [ok] \u5199\u51fa {out_path}")


if __name__ == "__main__":
    sys.exit(main())
