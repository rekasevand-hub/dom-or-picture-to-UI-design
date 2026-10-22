"""Axure `.rppkg` 的分页存储（MultiStore）读写与规范铺页。

格式依据 `归档文档 axure_rp8_format.md` §3。页 = 4096 B：

    [0 .. 4)      页头 i32  == 所属 part 的目录 id（目录页为 0）
    [4 .. 4088)   净荷（逻辑流的一段）
    [4088 .. 4096) epilogue: 非末页 (1, 下一页号) / 末页 (2, 已用字节数)

**规范布局**（§3.5）：第 0 页是目录页；part 按目录顺序从第 1 页起连续铺；`id = 1..n`；
`first-page = 1 + 前面各 part 的页数`；页数 `= max(1, ceil(Length / 4084))`；
每页页头 = 所属 part 的 id；`Length` 是逻辑长度 `(页数-1)*4084 + used`。

`lay_store(parts)` 是唯一的写入口；`rebuild(physical)` 用「读 -> 铺」做逐字节自检。
"""
from __future__ import annotations

import math
import struct

from .c1 import DIR_VERSION, T_DD, T_END, T_INT, T_LIST, T_STR, i32, parse_stream, serialize

BLOCK = 4096
PAYLOAD = 4084


def is_store(buf):
    return len(buf) >= BLOCK and len(buf) % BLOCK == 0 and i32(buf, 4088) in (1, 2)


def part_stream(physical, first_page):
    """沿页链把一个 part 的净荷拼回逻辑流。"""
    out = bytearray()
    page = first_page
    while True:
        block = physical[page * BLOCK:(page + 1) * BLOCK]
        kind = i32(block, 4088)
        value = i32(block, 4092)
        if kind == 1:
            out += block[4:4088]
            page = value
        elif kind == 2:
            out += block[4:4 + value]
            break
        else:
            raise ValueError("bad epilogue %d @page %d" % (kind, page))
    return bytes(out)


def entries_of(physical):
    """读目录页，返回 [(name, id, first-page, Length)]（目录顺序）。

    旧版本（如 Axure 8.0.0.3251 的 `WelcomeTo8.rp`）目录行里**没有 `Length` 键**，
    此时按 `-1`（整条链）处理；`first-page` / `id` 一直都有。
    """
    _, names, _, items = parse_stream(part_stream(physical, 0))
    out = []
    for entry in items[0][1][0][1][1]:
        row = {names[key[1]]: value for key, value in entry[1]}
        length = row["Length"][1] if "Length" in row else -1
        out.append((names[row["name"][1]], row["id"][1],
                    row["first-page"][1], length))
    return out


def parts_of(physical):
    """返回 [(name, payload)]。

    `Length` 是逻辑长度（净荷按它截断）；**`Length < 0` 表示「整条页链」**——
    实测 Axure 8.0.0.3251 的自带样本 `WelcomeTo8.rp` 的 `DesignDocument` 就是这么写的
    （目录里 `Length = -1`，真长度比页链少 1 字节，直接用链长才对）。
    """
    out = []
    for name, _id, first, length in entries_of(physical):
        payload = part_stream(physical, first)
        out.append((name, payload if length < 0 else payload[:length]))
    return out


def directory_stream(entries):
    """目录流 = c1 信封 + dd{"item-infos": list[...]} + tag 28。

    名字池按**首次使用顺序**建（与 Axure 写出的字节一致）：
    `item-infos` -> 每行依次 `name`、`<part 名>`、`id`、`first-page`、`Length`。
    """
    pool = [None]

    def pidx(text):
        if text not in pool:
            pool.append(text)
        return pool.index(text)

    item_infos = pidx("item-infos")
    rows = []
    for name, idx, first_page, length in entries:
        rows.append([T_DD, [
            [[T_STR, pidx("name"), T_STR], [T_STR, pidx(name), T_STR]],
            [[T_STR, pidx("id"), T_STR], [T_INT, idx, T_INT]],
            [[T_STR, pidx("first-page"), T_STR], [T_INT, first_page, T_INT]],
            [[T_STR, pidx("Length"), T_STR], [T_INT, length, T_INT]],
        ], T_DD])
    body = [T_DD, [[[T_STR, item_infos, T_STR], [T_LIST, rows, T_LIST]]], T_DD]
    return serialize(DIR_VERSION, pool, [None], [body, [T_END, T_END]])


def lay_store(parts):
    """用规范布局把 [(name, payload)] 铺成一个物理存储。"""
    entries = []
    first = 1
    for idx, (name, payload) in enumerate(parts, start=1):
        entries.append((name, idx, first, len(payload)))
        first += max(1, math.ceil(len(payload) / PAYLOAD))
    dirc = directory_stream(entries)
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


def rebuild(physical, mutate=None):
    """读 -> 铺。`mutate(name, payload) -> payload` 可对每个 part 改写净荷。"""
    parts = []
    for name, payload in parts_of(physical):
        if mutate is not None:
            payload = mutate(name, payload)
        parts.append((name, payload))
    return lay_store(parts)


def walk_streams(physical):
    """递归产出所有**非存储**净荷 [(名字路径, payload)]。"""
    for name, payload in parts_of(physical):
        if is_store(payload):
            yield from walk_streams(payload)
        else:
            yield name, payload
