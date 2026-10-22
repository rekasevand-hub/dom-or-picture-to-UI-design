"""Axure RP 8 `.rp` 内层 c1 对象流的编解码（唯一实现）。

格式依据 `归档文档 axure_rp8_format.md` §4。条目（item）是一个列表，**末位保留原始 raw tag**：

    [tag, payload..., raw]

* 读侧 `tag = raw & 31`（`c1.cs:1296` 的掩码；实测无高位污染，见格式文档证明 D）。
* 写侧写平整的 `tag`（1..31）。

本模块只做「字节 <-> 树」的对称读写：对任何合法流都有 `serialize(parse_stream(b)) == b`
（证明 A/E）。构造对象图请用 `model.StreamBuilder`。
"""
from __future__ import annotations

import struct

# --- 条目 tag（`c1.b` 枚举，格式文档 §4.2）--------------------------------
T_DD = 1        # a  : dd 键值表（**有序**，键是 str 条目）
T_LIST = 2      # b  : a1 列表
T_REF = 3       # c  : 引用（guid 池下标）
T_BLOB = 4      # d  : og（i32 长度 + 裸字节）
T_INT = 5       # e  : i32
T_F64 = 6       # f  : f64
T_F32 = 7       # g  : f32
T_STR = 8       # h  : 名字池下标
T_OBJ = 9       # i  : 对象记录 = guidIdx + typeNameIdx + dd
T_AH = 16       # p  : (nameIdx, guidIdx)
T_GUID = 17     # q  : guid 池下标
T_FX = 19       # s  : (typeNameIdx, guidIdx)
T_REF20 = 20    # t  : 同 T_REF 的另一种写法
T_DJ = 21       # u  : guid 池下标
T_PK = 22       # v  : guid 池下标
T_BOOL = 25     # y  : 1 字节
T_PKGCTX = 26   # z  : (15, rootGuidIdx, 18, pkgGuidIdx)
T_27 = 27
T_END = 28      # ab : 流结尾
T_I64 = 29      # ac
T_30 = 30
T_31 = 31

# 池下标 1-based：索引 0 是 null 哨兵（格式文档 §4.1）。
_INT32_TAGS = (T_REF, T_STR, T_GUID, T_INT, T_REF20, T_DJ, T_PK)
_NO_PAYLOAD_TAGS = (T_27, T_END, T_30, T_31)

# 版本元组（格式文档 §4.1）：**两种**，写错存储就不自洽。
OBJ_VERSION = (8, 0, 5, 0, 50001)   # 对象流 / document.settings / widgetinfo / 生成器配置
DIR_VERSION = (0, 0, 3, 0, 50001)   # 目录流（存储第 0 页）

NULL_GUID = bytes(16)


def i32(buf, off):
    return struct.unpack_from("<i", buf, off)[0]


def parse_item(buf, pos):
    """解析一个条目，返回 (item, next_pos)。"""
    raw = i32(buf, pos)
    pos += 4
    tag = raw & 31
    if tag == T_DD:
        count = i32(buf, pos)
        pos += 4
        pairs = []
        for _ in range(count):
            key, pos = parse_item(buf, pos)
            value, pos = parse_item(buf, pos)
            pairs.append([key, value])
        return [T_DD, pairs, raw], pos
    if tag == T_LIST:
        count = i32(buf, pos)
        pos += 4
        items = []
        for _ in range(count):
            item, pos = parse_item(buf, pos)
            items.append(item)
        return [T_LIST, items, raw], pos
    if tag in _INT32_TAGS:
        return [tag, i32(buf, pos), raw], pos + 4
    if tag == T_F32:
        return [tag, struct.unpack_from("<f", buf, pos)[0], raw], pos + 4
    if tag == T_F64:
        return [tag, struct.unpack_from("<d", buf, pos)[0], raw], pos + 8
    if tag == T_I64:
        return [tag, struct.unpack_from("<q", buf, pos)[0], raw], pos + 8
    if tag == T_BOOL:
        return [tag, buf[pos], raw], pos + 1
    if tag == T_BLOB:
        size = i32(buf, pos)
        return [tag, bytes(buf[pos + 4:pos + 4 + size]), raw], pos + 4 + size
    if tag == T_OBJ:
        guid_idx = i32(buf, pos)
        type_idx = i32(buf, pos + 4)
        body, pos = parse_item(buf, pos + 8)
        return [tag, guid_idx, type_idx, body, raw], pos
    if tag in (T_AH, T_FX):
        return [tag, i32(buf, pos), i32(buf, pos + 4), raw], pos + 8
    if tag == T_PKGCTX:
        return [tag, *struct.unpack_from("<4i", buf, pos), raw], pos + 16
    if tag in _NO_PAYLOAD_TAGS:
        return [tag, raw], pos
    raise ValueError("unknown tag raw=%d tag=%d at %d" % (raw, tag, pos - 4))


def emit(item):
    """把一个条目写回字节（raw 原样写出）。"""
    tag = item[0]
    out = bytearray(struct.pack("<i", item[-1]))
    if tag == T_DD:
        out += struct.pack("<i", len(item[1]))
        for key, value in item[1]:
            out += emit(key) + emit(value)
    elif tag == T_LIST:
        out += struct.pack("<i", len(item[1]))
        for child in item[1]:
            out += emit(child)
    elif tag in _INT32_TAGS:
        out += struct.pack("<i", item[1])
    elif tag == T_F32:
        out += struct.pack("<f", item[1])
    elif tag == T_F64:
        out += struct.pack("<d", item[1])
    elif tag == T_I64:
        out += struct.pack("<q", item[1])
    elif tag == T_BOOL:
        out += struct.pack("<B", item[1])
    elif tag == T_BLOB:
        out += struct.pack("<i", len(item[1])) + item[1]
    elif tag == T_OBJ:
        out += struct.pack("<ii", item[1], item[2]) + emit(item[3])
    elif tag in (T_AH, T_FX):
        out += struct.pack("<ii", item[1], item[2])
    elif tag == T_PKGCTX:
        out += struct.pack("<4i", item[1], item[2], item[3], item[4])
    elif tag in _NO_PAYLOAD_TAGS:
        pass
    else:
        raise ValueError("unhandled tag %d" % tag)
    return bytes(out)


def read_header(buf):
    """读信封，返回 (ver, names, guids, 条目流起始偏移)。池都是 1-based。"""
    if i32(buf, 0) != T_27:
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


def serialize(ver, names, guids, items):
    """把 (version, 名字池, guid 池, 条目流) 写回字节。"""
    out = bytearray(struct.pack("<i", T_27) + struct.pack("<5i", *ver))
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


def parse_stream(buf):
    """完整解析一条 c1 流，返回 (ver, names, guids, items)。"""
    ver, names, guids, pos = read_header(buf)
    items = []
    while pos < len(buf):
        item, pos = parse_item(buf, pos)
        items.append(item)
    return ver, names, guids, items


def dd_get(item, names, key):
    """按字符串键取 dd 成员；不是 dd 或没有该键返回 None。"""
    if item is None or item[0] != T_DD:
        return None
    for k, v in item[1]:
        if k[0] == T_STR and names[k[1]] == key:
            return v
    return None


def dd_items(item):
    if item is None or item[0] != T_DD:
        return []
    return item[1]


def iter_objects(items):
    """深度优先产出所有 `tag 9` 对象（不进入对象的 dd 体之外的结构）。"""
    for item in items:
        if item[0] == T_OBJ:
            yield item
            yield from iter_objects([item[3]])
        elif item[0] == T_LIST:
            yield from iter_objects(item[1])
        elif item[0] == T_DD:
            for _, value in item[1]:
                yield from iter_objects([value])
