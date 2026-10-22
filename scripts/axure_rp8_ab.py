# -*- coding: utf-8 -*-
"""Axure 出口的 A/B：报「两份 `.rp` 字节是否相同 / 差异落在哪些成员」。

**为什么现在能用**（2026-10-15 起，plan §9.14 `P5`）：`.rp` 已经是**确定性**的 —— GUID 由
`(seed, 计数器)` 派生、ZIP 成员时间戳固定，所以「同一份 IR + 同一份代码」两次生成**逐字节相同**，
于是**任何**字节差异都来自你刚改的那行代码。以前比不了（页包 GUID 随机 + 写盘带当前时间），
只能退回模型层逐控件比。

三种用法：

```powershell
# ① 确定性自检：同一份 IR 连生两次，应当逐字节相同（不给 --flip）
& $PY scripts/axure_rp8_ab.py --design output/_dushu2/12_design.json

# ② 开关 A/B：先不 flip 生成一份，flip 之后再生成一份，直接给差异报告
& $PY scripts/axure_rp8_ab.py --design output/_dushu2/12_design.json `
      --flip src.app.services.rendering.text_wrap.box_is_own_line=false

# ③ 两个现成文件的对比（改代码**前**先存一份，回来再比）
& $PY scripts/axure_rp8_ab.py --a output/_axure_ab/baseline.rp --b output/_axure_ab/flipped.rp

# ④ 打印成员级 sha256 基准（给 `tests/test_axure_rp8_baseline.py` 粘贴用）
& $PY scripts/axure_rp8_ab.py --baseline output/_dushu2/prototype.rp --name BASELINE_CORPUS
```

`--flip` 的语法是 `模块.属性[=值]`（可重复）：

* **不给值** -> 取反：`bool` 取 `not`；**函数**换成恒返回 `False` 的桩（用来「关掉某条判据」）。
* **给值** -> 当常量：`true` / `false` / `none` / 数字 / 字符串（`ast.literal_eval`，失败按字符串）；
  原值是**函数**时会自动包成恒返回该常量的函数。

差异分三档（也是退出码）：**0** = 逐字节相同；**1** = 差异只涉及 GUID 值 / ZIP 时间戳（内容等价，
由「把 GUID 池的值按下标换成合成值后重发」判定）；**2** = 内容有差异；**3** = 参数 / 生成出错。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.services.rendering.axure import c1, store, writer  # noqa: E402

DEFAULT_OUT = "output/_axure_ab"

# 包成员路径 `<kind>/<2h>/<guid>/<guid>.rppkg`；`<2h>` 是 GUID 末尾两个 hex，
# 所以换 GUID 时它也跟着换 —— 两者都要打码才能让「同一页」配得上。
_PKG_RE = re.compile(r"^([^/]+)/[0-9a-f]{2}/([0-9a-f]{32})/([0-9a-f]{32})\.rppkg$")
_GUID_RE = re.compile(r"[0-9a-f]{32}")


def _normalized(name: str) -> str:
    """成员名把 GUID 打码（含 `<2h>` 目录）。"""
    match = _PKG_RE.match(name)
    if match:
        return "%s/<guid>/<guid>.rppkg" % match.group(1)
    return _GUID_RE.sub("<guid>", name)


def _canon_key(data: bytes):
    """配对的键：**GUID 归一化后**的内容，同键 = 只差 GUID 值（或逐字节相同）。

    **不要**改用「首个 c1 流的名字池 + 数值」当签名：同一份 IR 的多页常常名字池与数值
    完全一样（`output/_dushu2` 之外的探针里 3 个 Page 就撞在一起，签名全同 -> 两页错位
    -> 把「只差 GUID」误报成「内容不同」）。canonical 是**全套**字段，不会撞。
    """
    return tuple(canonical(data))


# ------------------------------------------------------------------ 成员级读

def member_hashes(path) -> dict:
    """`{成员名: sha256(member bytes)}`（名里带页包 GUID —— 那也是产物的一部分）。"""
    with zipfile.ZipFile(path) as zf:
        return {name: hashlib.sha256(zf.read(name)).hexdigest() for name in zf.namelist()}


def _segments(data: bytes, acc: list) -> list:
    """成员里的每一段 `(part 名, 净荷)`（顺序 = 分页存储的遍历顺序）：

    * c1 流 -> `(名, (ver, names, guids, items))`（顶层非存储流的名是 `""`）
    * **非 c1 净荷**（页包里的 `thumbnail` 就是这种，一段 256x190 的 JPEG）
      -> `(名, b"RAW:<sha256>")`

    第二条是 2026-10-15（P4）补的：以前非 c1 净荷被**静默跳过**，于是「只换了
    `thumbnail`」的改动会被配对规则算成「只差 GUID 值」，直接漏报（P4 第一次 A/B 就撞上）。
    二进制净荷没有 GUID 可归一化，只能按内容摘要比；带上 part 名是为了报出差异落在哪一块。
    """
    if store.is_store(data):
        for name, _ident, first, length in store.entries_of(data):
            payload = store.part_stream(data, first)[:length]
            if store.is_store(payload):
                _segments(payload, acc)
                continue
            try:
                acc.append((name, c1.parse_stream(payload)))
            except Exception:
                acc.append((name, b"RAW:" + hashlib.sha256(payload).digest()))
        return acc
    try:
        acc.append(("", c1.parse_stream(data)))
    except Exception:
        pass
    return acc


def canonical(data: bytes) -> list:
    """成员的「GUID 值无关」表示：每条 c1 流把 GUID **池里的值**按下标换成合成值
    （池的位置、所有引用下标、其余字段一律不动），再重新序列化；非 c1 净荷按内容摘要
    （`RAW:<sha256>`）原样参与比较。

    两份产物在这里相等，就说明差异**只是 GUID 值不同**（结构与数值都一样）。
    """
    segments = _segments(data, [])
    if not segments:
        return [("", b"RAW:" + data)]
    out = []
    for name, payload in segments:
        if isinstance(payload, bytes):
            out.append((name, payload))
            continue
        ver, names, guids, items = payload
        pool = [c1.NULL_GUID if i == 0 else hashlib.sha256(b"g:%d" % i).digest()
                for i in range(len(guids))]
        out.append((name, c1.serialize(ver, names, pool, items)))
    return out


def _zip_stamps(path) -> list:
    with zipfile.ZipFile(path) as zf:
        return sorted({info.date_time for info in zf.infolist()})


def _stream_diff(ca: list, cb: list) -> str:
    if len(ca) != len(cb):
        return "段数 %d vs %d" % (len(ca), len(cb))
    for i, (x, y) in enumerate(zip(ca, cb)):
        if x != y:
            where = x[0] or y[0] or "顶层"
            if x[1].startswith(b"RAW:") and y[1].startswith(b"RAW:"):
                return "第 %d 段（%s）不同（非 c1 净荷，按内容摘要比）" % (i + 1, where)
            return "第 %d 段（%s）不同（%d B vs %d B）" % (i + 1, where, len(x[1]), len(y[1]))
    return "逐段相同（差异在成员外壳 / 存储层）"


# ------------------------------------------------------------------ 对比

def _pair_members(raw_a: dict, raw_b: dict):
    """配对规则：① **名字完全相同**的先配上（正常 A/B 走这条 —— GUID 已经是确定的）；
    ② 剩下的按**打码后的名字**分组（`Page/<2h>/<guid>/<guid>.rppkg` 全打码），组内先用
    **GUID 归一化内容**配 —— 只换 GUID 的场景（跟 A7 之前的产物比）走这条，同一页能对上，
    页与页不会错位。③ 剩下还没配上的按成员顺序兜底一对一配，这样**内容真变了**的成员
    才报「内容不同」，而不是误报成「只在 A / 只在 B」。
    """
    pairs, only_a, only_b = [], [], []
    left_a = dict(raw_a)
    left_b = dict(raw_b)
    for name in sorted(set(raw_a) & set(raw_b), key=writer.member_order_key):
        pairs.append((name, name, name))
        left_a.pop(name)
        left_b.pop(name)

    def bucket(left):
        out = {}
        for name in sorted(left, key=writer.member_order_key):
            out.setdefault(_normalized(name), []).append(name)
        return out

    ba, bb = bucket(left_a), bucket(left_b)
    for base in sorted(set(ba) | set(bb)):
        names_a, names_b = ba.get(base, []), bb.get(base, [])
        by_key = {}
        for name in names_b:
            by_key.setdefault(_canon_key(left_b[name]), []).append(name)
        rest_a = []
        for name in names_a:
            matched = by_key.get(_canon_key(left_a[name]))
            if matched:
                pairs.append((base, name, matched.pop(0)))
            else:
                rest_a.append(name)
        rest_b = [name for names in by_key.values() for name in names]
        for name_a, name_b in zip(rest_a, rest_b):
            pairs.append((base, name_a, name_b))
        only_a.extend(rest_a[len(rest_b):])
        only_b.extend(rest_b[len(rest_a):])
    return pairs, only_a, only_b


def compare(a_path, b_path) -> int:
    a, b = Path(a_path), Path(b_path)
    for path in (a, b):
        if not path.is_file():
            print("找不到文件：%s" % path)
            return 3

    bytes_a, bytes_b = a.read_bytes(), b.read_bytes()
    same_file = bytes_a == bytes_b
    print("A: %s  %d B  sha256 %s" % (a, len(bytes_a), hashlib.sha256(bytes_a).hexdigest()[:16]))
    print("B: %s  %d B  sha256 %s" % (b, len(bytes_b), hashlib.sha256(bytes_b).hexdigest()[:16]))
    print("整文件逐字节相同: %s" % same_file)
    print("ZIP 时间戳: A=%s  B=%s" % (_zip_stamps(a), _zip_stamps(b)))

    with zipfile.ZipFile(a) as zf_a, zipfile.ZipFile(b) as zf_b:
        raw_a = {name: zf_a.read(name) for name in zf_a.namelist()}
        raw_b = {name: zf_b.read(name) for name in zf_b.namelist()}

    pairs, only_a, only_b = _pair_members(raw_a, raw_b)
    print("成员: A=%d  B=%d  配对 %d 对"
          % (len(raw_a), len(raw_b), len(pairs)))

    same, guid_only, changed = [], [], []
    for base, name_a, name_b in pairs:
        if raw_a[name_a] == raw_b[name_b]:
            same.append(base)
        elif canonical(raw_a[name_a]) == canonical(raw_b[name_b]):
            guid_only.append((base, name_a != name_b))
        else:
            changed.append((base,
                            _stream_diff(canonical(raw_a[name_a]), canonical(raw_b[name_b]))))
    print("逐成员: 相同 %d / 只差 GUID 值 %d / 内容不同 %d"
          % (len(same), len(guid_only), len(changed)))

    for base, name_moved in guid_only:
        print("  只差 GUID 值  %s%s" % (base, "   （成员名里的 GUID 也跟着变了）" if name_moved else ""))
    for name in only_a:
        print("  只在 A        %s" % name)
    for name in only_b:
        print("  只在 B        %s" % name)
    for base, why in changed:
        print("  内容不同      %s   （%s）" % (base, why))

    if same_file:
        print("结论: 逐字节相同")
        return 0
    if not (only_a or only_b or changed):
        print("结论: 差异只涉及 GUID 值 / ZIP 时间戳 —— 内容等价")
        return 1
    print("结论: 内容有差异 —— 上面逐条列出")
    return 2


# ------------------------------------------------------------------ 生成

def _const_lambda(value):
    return lambda *args, **kwargs: value


def _literal(text):
    low = text.strip().lower()
    if low in ("true", "false", "none"):
        return {"true": True, "false": False, "none": None}[low]
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def _parse_flip(text: str):
    spec, sep, value = text.partition("=")
    module_name, _, attr = spec.rpartition(".")
    if not module_name or not attr:
        raise ValueError("`--flip` 要写成 `模块.属性[=值]`，收到 %r" % text)
    return module_name, attr, (value if sep else None)


def apply_flips(flips) -> list:
    """按 `--flip` 改内存里的模块属性，返回 [(module, attr, old)] 供还原。"""
    saved = []
    for module_name, attr, value_text in flips:
        module = importlib.import_module(module_name)
        old = getattr(module, attr)
        if value_text is None:
            new = (not old) if isinstance(old, bool) else _const_lambda(False)
        else:
            new = _literal(value_text)
            if callable(old) and not callable(new):
                new = _const_lambda(new)
        setattr(module, attr, new)
        print("flip: %s.%s = %r -> %r" % (module_name, attr, old, new))
        saved.append((module, attr, old))
    return saved


def render_design(design: dict, path) -> Path:
    """走真实出口（`AxureRPAdapter`）把 IR 写成 `.rp`；出口自检不过会直接抛。"""
    from src.app.services.rendering.axure_adapter import AxureRPAdapter
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    AxureRPAdapter(path).render_design(design)
    return path


# ------------------------------------------------------------------ 基准打印

def print_baseline(path, name: str) -> int:
    """打印可直接粘进 `tests/test_axure_rp8_baseline.py` 的三个常量
    （`<name>_BYTES` / `<name>_SHA256` / `<name>_MEMBERS`）。"""
    data = Path(path).read_bytes()
    hashes = member_hashes(path)
    print("%s_BYTES = %d" % (name, len(data)))
    print("%s_SHA256 = %r" % (name, hashlib.sha256(data).hexdigest()))
    print("%s_MEMBERS = {" % name)
    for member in sorted(hashes, key=writer.member_order_key):
        print("    %r: %r," % (member, hashes[member]))
    print("}")
    return 0


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Axure 出口 A/B：两份 .rp 的成员级差异（GUID 值归一化后分档）")
    parser.add_argument("--design", help="DesignSpec JSON：走真实出口生成 baseline / flipped 两份")
    parser.add_argument("--flip", action="append", default=[], metavar="模块.属性[=值]",
                        help="生成第二份前改掉的模块属性（可重复）；不给就是两次同样的生成")
    parser.add_argument("--out", default=DEFAULT_OUT, help="两份 .rp 落在哪（默认 %s）" % DEFAULT_OUT)
    parser.add_argument("--a", help="已存在的 .rp（改代码前存的那份）")
    parser.add_argument("--b", help="另一个 .rp")
    parser.add_argument("--baseline", metavar="RP", help="只打印该 .rp 的成员级基准（不对比）")
    parser.add_argument("--name", default="BASELINE", help="--baseline 打印的变量名")
    args = parser.parse_args(argv)

    if args.baseline:
        return print_baseline(args.baseline, args.name)

    if args.a or args.b:
        if not (args.a and args.b):
            print("--a 与 --b 要成对给")
            return 3
        return compare(args.a, args.b)

    if not args.design:
        parser.print_help()
        return 3

    design_path = Path(args.design)
    if not design_path.is_file():
        print("找不到 IR：%s" % design_path)
        return 3
    design = json.loads(design_path.read_text(encoding="utf-8"))

    out = Path(args.out)
    a_path, b_path = out / "baseline.rp", out / "flipped.rp"
    try:
        flips = [_parse_flip(text) for text in args.flip]
    except ValueError as exc:
        print(exc)
        return 3

    render_design(design, a_path)
    saved = []
    try:
        saved = apply_flips(flips)
        render_design(design, b_path)
    except (ImportError, AttributeError) as exc:
        print("`--flip` 落不下去：%s" % exc)
        return 3
    finally:
        for module, attr, old in saved:
            setattr(module, attr, old)
    if not args.flip:
        print("（没给 --flip：这是同一份 IR 的两次生成，等于确定性自检）")
    return compare(a_path, b_path)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
