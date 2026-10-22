"""组装 `.rp`：模板常量 + 生成的 Page 包 + 注册表改写 + 写 ZIP + 自检。

三类成员（方案 §4）：

| 来源 | 成员 | 做法 |
|---|---|---|
| 字节常量 | `8.0.0.3400.version`、Page 包里的 `widgetinfo` / `thumbnail` | 存进 `assets/axure/rp8/` |
| 结构常量 | `document.settings`、4 组 generator-configuration、`PrintConfig` | 从 `base.rp` 原样搬运（只改当前打开的页） |
| **完全生成** | `Page/<guid>.rppkg`、`DesignDocument` 里的页面注册项 | 本模块改写 |

页面注册表结构（实测）：`DesignDocument.PackageInfos` = 一串指向 `Axure:PackageInfo`
对象的引用；`SiteTreeMap.node-table` = `{节点 GUID -> fx(Axure:PackageInfo, 包 GUID)}`；
`SiteTreeMap.tree` 指向一棵 `Axure:Tree`，其 `children` 是根 `Axure:Node`。

页面包的成员路径 `<2h>` = **GUID 的末尾 2 个 hex 字符**（7 个样本全部实测通过）。
"""
from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

from . import c1, model, store

VERSION_FILE = "8.0.0.3400.version"
SETTINGS_MEMBER = "document.settings"
DESIGN_DOC_DIR = "DesignDocument"
PAGE_DIR = "Page"
MASTER_DIR = "Master"
VERSION_SUFFIX = ".version"

_ASSET_DIR = Path(__file__).resolve().parents[5] / "assets" / "axure" / "rp8"

# 默认模板：文档级成员（version / document.settings / DesignDocument / 生成器配置 /
# PrintConfig）全部来自**原生** Axure 文件（`首页原型.rp`，8.0.0.3400），由
# `scripts/axure_rp8_import_template.py` 抽出，没有 v1 的改写痕迹。
NATIVE_BASE_RP = _ASSET_DIR / "base_native.rp"
NATIVE_WIDGETINFO_BIN = _ASSET_DIR / "widgetinfo_native.bin"
NATIVE_THUMBNAIL_BIN = _ASSET_DIR / "thumbnail_native.bin"

# 成员顺序（与 Axure 自己写出的 7 个样本一致）
_MEMBER_ORDER = (
    (VERSION_FILE, 0),
    (SETTINGS_MEMBER, 1),
    ("CsvAnnotationReportGeneratorConfiguration/", 2),
    (DESIGN_DOC_DIR + "/", 3),
    ("HtmlPrototypeGeneratorConfiguration/", 4),
    (PAGE_DIR + "/", 5),
    ("PrintConfig/", 6),
    ("Word2007SpecificationGeneratorConfiguration/", 7),
)


# ZIP 成员时间戳：固定值 -> 逐字节可回归（`writestr` 缺省会写当前时间）。
ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def package_member_path(kind, guid) -> str:
    """`<kind>/<2h>/<guid>/<guid>.rppkg`；`<2h>` = GUID 末尾 2 个 hex。"""
    h = guid.hex if isinstance(guid, uuid.UUID) else str(guid)
    return "%s/%s/%s/%s.rppkg" % (kind, h[-2:], h, h)


def member_order_key(name: str):
    for prefix, rank in _MEMBER_ORDER:
        if name == prefix or name.startswith(prefix):
            return (rank, name)
    return (99, name)


# ------------------------------------------------------------------ 模板

class Template:
    """文档级模板：`.rp` 的文档级成员 + Page 包常量（widgetinfo / thumbnail）。"""

    def __init__(self, members: dict, widgetinfo: bytes = b"", thumbnail: bytes = b""):
        self.members = dict(members)
        self.widgetinfo = bytes(widgetinfo)
        self.thumbnail = bytes(thumbnail)

    @classmethod
    def load(cls, path) -> "Template":
        with zipfile.ZipFile(path) as zf:
            members = {name: zf.read(name) for name in zf.namelist()}
        return cls(members)

    @property
    def design_document_name(self) -> str:
        for name in self.members:
            if name.startswith(DESIGN_DOC_DIR + "/"):
                return name
        raise KeyError("模板里没有 DesignDocument 成员")

    def page_constant_names(self) -> list:
        return [n for n in self.members if n.startswith(PAGE_DIR + "/")]


def _template_of(rp, widgetinfo_bin, thumbnail_bin) -> Template:
    template = Template.load(rp)
    template.widgetinfo = Path(widgetinfo_bin).read_bytes()
    template.thumbnail = Path(thumbnail_bin).read_bytes()
    return template


def native_template() -> Template:
    """v2 默认模板：文档级成员来自原生 Axure 文件（`assets/axure/rp8/base_native.rp`）。"""
    return _template_of(NATIVE_BASE_RP, NATIVE_WIDGETINFO_BIN, NATIVE_THUMBNAIL_BIN)



def default_template() -> Template:
    """仓库默认模板 = `native_template()`（v2 路线）。"""
    return native_template()


# ------------------------------------------------------- 对象图：查找 / 改写

def _find_object(items, names, type_name, guid_index=None):
    for it in items:
        if it[0] != c1.T_OBJ or names[it[2]] != type_name:
            continue
        if guid_index is None or it[1] == guid_index:
            return it
    return None


def _dd_replace(dd, names, key, value_item):
    """改写 dd 里某个键的值（键必须已存在）。"""
    for pair in dd[1]:
        if pair[0][0] == c1.T_STR and names[pair[0][1]] == key:
            pair[1] = value_item
            return
    raise KeyError("dd 里没有键 %r" % key)


def _package_info_desc(name: str, package_guid):
    return ("dd", [
        ("package-id", ("fx", model.PAGE_KIND, package_guid)),
        ("package-name", ("str", name)),
        ("dependencies", ("list", [])),
        ("root-panel-infos", ("list", [])),
        ("diagram-type", ("int", 0)),
        ("LoadedRdoPackages", ("list", [])),
        ("LoadedScreenshotPackages", ("list", [])),
        ("PackageSavedVersion", ("dd", [
            ("Major", ("int", 0)), ("Minor", ("int", 0)),
            ("Build", ("int", 0)), ("Revision", ("int", 0)),
        ])),
    ])


def _sitemap_nodes(items, names, sitemap_dd):
    """收集 sitemap 现有的全部节点 GUID 池下标（node-table 键 + tree/nodes 的 children）。"""
    out = set()
    frontier = [k[1] for k, _v in c1.dd_get(sitemap_dd, names, "node-table")[1]]
    tree_idx = c1.dd_get(sitemap_dd, names, "tree")[1]
    tree = _find_object(items, names, "Axure:Tree", guid_index=tree_idx)
    if tree is not None:
        frontier += [r[1] for r in c1.dd_get(tree[3], names, "children")[1]]
    while frontier:
        idx = frontier.pop()
        if idx in out:
            continue
        out.add(idx)
        node = _find_object(items, names, "Axure:Node", guid_index=idx)
        if node is not None:
            frontier += [r[1] for r in c1.dd_get(node[3], names, "children")[1]]
    return out, tree_idx


def _rewrite_package_member(raw: bytes, fn) -> bytes:
    """`DesignDocument` / 生成器配置这类成员 = 单 part 存储（part 名 `package`）。

    取出净荷交给 `fn`，再用规范布局重新铺页。
    """
    parts = store.parts_of(raw)
    if len(parts) != 1:
        raise ValueError("期望单 part 存储，实际 %d 个" % len(parts))
    name, payload = parts[0]
    return store.lay_store([(name, fn(payload))])


def rewrite_design_document(raw: bytes, registrations) -> bytes:
    """把 `DesignDocument` 的页面注册项改成 `registrations` = [(页名, 包 GUID), ...]。

    模板提供的文档级对象（StyleSheet / PageStyleSheet / 标注字段集 / 生成器配置 …）
    原样保留；只替换 `PackageInfos` 与 `sitemap`，以及它们专属的
    `Axure:PackageInfo` / `Axure:Node` / `Axure:Tree` 对象。

    例外：`StyleSheet.CustomStyles` 会补上 `Button` / `Text Field` 两条（模板没有，
    缺了按钮 / 输入框就发不出 `.button` / `.text_field` 类，见 `_ensure_style_sheet_styles`）。
    """
    return _rewrite_package_member(
        raw, lambda payload: _rewrite_design_document_stream(payload, registrations))


def _ensure_style_sheet_styles(b, items, names):
    """把 `model.STYLE_SHEET_EXTRAS` 补进 `DesignDocument.StyleSheet.CustomStyles`。

    真机实测（`归档文档 axure_rp8_format.md` §11.8）：Axure 发布时按控件命中的**样式名**
    给元素加 CSS 类（`Button` -> `class="ax_default button"`、`Text Field` ->
    `text_field`），**样式名要能从项目样式表里查到**；模板 `base_native.rp` 里没有这
    两条，所以按钮 / 输入框只会发成 `class="ax_default"`（m8ctl 实测 `button=False`）。
    样式表里已有的同名条目不动 —— 模板换成带这两条的原生文件时也不会撞车。
    """
    sheet = _find_object(items, names, "Axure:StyleSheet")
    if sheet is None:
        raise ValueError("模板里没有 Axure:StyleSheet")
    custom = c1.dd_get(sheet[3], names, "CustomStyles")
    if custom is None or custom[0] != c1.T_LIST:
        raise ValueError("模板的 StyleSheet 没有 CustomStyles 列表")
    present = set()
    for ref in custom[1]:
        style = _find_object(items, names, "Axure:Style", guid_index=ref[1])
        label = (c1.dd_get(style[3], names, "style-name")
                 if style is not None else None)
        if label is not None:
            present.add(names[label[1]])
    for name, style_id, props in model.STYLE_SHEET_EXTRAS:
        if name in present:
            continue
        guid = model.new_guid()
        b.add(b.build(("obj", "Axure:Style", guid,
                       model.style_sheet_entry_descriptor(name, style_id, props))))
        custom[1].append(b.ref_(guid))
    return present


def _rewrite_design_document_stream(raw: bytes, registrations) -> bytes:
    ver, names, guids, items = c1.parse_stream(raw)
    doc = _find_object(items, names, "Axure:DesignDocument")
    if doc is None:
        raise ValueError("模板里没有 Axure:DesignDocument")
    doc_dd = doc[3]

    # 1) 模板里的「页面」注册项：package-id 的类型是 Axure:Page
    dropped = set()
    kept_refs = []
    for ref in c1.dd_get(doc_dd, names, "PackageInfos")[1]:
        pi = _find_object(items, names, "Axure:PackageInfo", guid_index=ref[1])
        pid = c1.dd_get(pi[3], names, "package-id") if pi is not None else None
        if pid is not None and names[pid[1]] == model.PAGE_KIND:
            dropped.add(ref[1])
        else:
            kept_refs.append(ref)

    sitemap = _find_object(items, names, "Axure:SiteTreeMap")
    if sitemap is None:
        raise ValueError("模板里没有 Axure:SiteTreeMap")
    sm_dd = sitemap[3]
    old_nodes, old_tree = _sitemap_nodes(items, names, sm_dd)
    remove = dropped | old_nodes | {old_tree}

    kept_items = [it for it in items
                  if not (it[0] == c1.T_OBJ and it[1] in remove)]
    # 条目流以 tag 28 结尾；新对象必须插在终止符**之前**（Axure 读到 tag28 就结束）。
    while kept_items and kept_items[-1][0] == c1.T_END:
        kept_items.pop()
    b = model.StreamBuilder.seeded(ver, names, guids, kept_items)

    # 2) 项目样式表：补 `Button` / `Text Field`（发布出的类名来源，见 §11.8）。
    #    插在页面注册项**之前**：原生文件里 `Axure:Style` 就紧跟在 StyleSheet 后面，
    #    而且这样能保住「条目流末尾是 Axure:Tree」那条不变式（见 test_axure_rp8_gen）。
    _ensure_style_sheet_styles(b, items, names)

    # 3) 新页面：每个页一个 PackageInfo + 一个 Node，再加一棵 Tree
    pi_guids = []
    for name, _pkg in registrations:
        guid = model.new_guid()
        b.add(b.build(("obj", "Axure:PackageInfo", guid,
                       _package_info_desc(name, _pkg))))
        pi_guids.append(guid)
    tree_guid = model.new_guid()
    node_guids = [model.new_guid() for _ in registrations]
    for node in node_guids:
        b.add(b.build(("obj", "Axure:Node", node, ("dd", [
            ("children", ("list", [])),
            ("parent-node", ("ref", tree_guid)),
            ("tree", ("ref", tree_guid)),
        ]))))
    b.add(b.build(("obj", "Axure:Tree", tree_guid, ("dd", [
        ("children", ("list", [("ref", n) for n in node_guids])),
        ("tree", ("ref", tree_guid)),
    ]))))

    # 4) 改写两处引用
    _dd_replace(doc_dd, names, "PackageInfos",
                b.list_(list(kept_refs) + [b.ref_(g) for g in pi_guids]))
    _dd_replace(sm_dd, names, "node-table",
                b.dd_([(b.ref_(node), b.fx_("Axure:PackageInfo", pkg))
                       for node, (_name, pkg) in zip(node_guids, registrations)]))
    _dd_replace(sm_dd, names, "tree", b.ref_(tree_guid))
    b.add_end()
    return c1.serialize(ver, b.names, b.guids, b.items)


def rewrite_document_settings(raw: bytes, page_guid) -> bytes:
    """把「当前打开的页 / 已打开的页」指向 `page_guid`（其余照抄模板）。"""
    ver, names, guids, items = c1.parse_stream(raw)
    ds = _find_object(items, names, "Axure:DocumentSettings")
    if ds is None:
        raise ValueError("模板里没有 Axure:DocumentSettings")
    b = model.StreamBuilder.seeded(ver, names, guids, items)
    _dd_replace(ds[3], names, "selected-tab-package-id", b.guid_(page_guid))
    _dd_replace(ds[3], names, "selected-tab-object-id", b.guid_(c1.NULL_GUID))
    _dd_replace(ds[3], names, "open-tab-package-ids", b.list_([b.guid_(page_guid)]))
    _dd_replace(ds[3], names, "open-tab-object-ids", b.list_([b.guid_(c1.NULL_GUID)]))
    return c1.serialize(ver, b.names, b.guids, b.items)


# ------------------------------------------------------------- 生成 / 写盘

def build_page_member(spec, thumbnail: bytes, widgetinfo: bytes) -> bytes:
    """一个 `Page/<guid>.rppkg`：L1 一层包 L2，L2 = thumbnail + widgetinfo + package。"""
    stream = model.build_page_stream(spec)
    layer2 = store.lay_store([("thumbnail", bytes(thumbnail)),
                              ("widgetinfo", bytes(widgetinfo)),
                              ("package", stream)])
    return store.lay_store([(spec.package_guid.hex, layer2)])


def _page_thumbnail(page, thumbnails, fallback: bytes) -> bytes:
    """这一页的页包缩略图：外部按页渲染的优先，缺了/画不出就退回模板常量（P4）。

    `thumbnails` 是 `{package_guid: jpeg 字节}`（键也接受 guid 的 hex 串）；`generate`
    只认字节、不认识画法 —— 页面内容的渲染在调用方（`axure_adapter.flush`）那边做。
    """
    if thumbnails:
        for key in (page.package_guid, page.package_guid.hex):
            data = thumbnails.get(key)
            if data:
                return bytes(data)
    return fallback


def generate(template: Template, pages, verify: bool = True,
             thumbnails=None) -> dict:
    """`Template` + `[model.PageSpec]` -> 成员字典（尚未写盘）。

    `verify=True`（默认）时先跑 `integrity_check`，不通过就抛 `ValueError`——完整性问题
    会一路带到 Axure 里才炸，不如在生成时就拦住。
    """
    if not pages:
        raise ValueError("至少要有一个页面")
    members = {}
    for name, data in template.members.items():
        if (name == VERSION_FILE or name == SETTINGS_MEMBER
                or name.startswith(PAGE_DIR + "/")
                or name.startswith(DESIGN_DOC_DIR + "/")):
            continue
        members[name] = data
    members[VERSION_FILE] = template.members[VERSION_FILE]
    members[SETTINGS_MEMBER] = rewrite_document_settings(
        template.members[SETTINGS_MEMBER], pages[0].package_guid)
    members[template.design_document_name] = rewrite_design_document(
        template.members[template.design_document_name],
        [(page.name, page.package_guid) for page in pages])
    for page in pages:
        members[package_member_path(PAGE_DIR, page.package_guid)] = build_page_member(
            page, _page_thumbnail(page, thumbnails, template.thumbnail),
            template.widgetinfo)
    if verify:
        report = integrity_check(members)
        if not report["ok"]:
            raise ValueError("生成结果未通过完整性自检: %s"
                             % "; ".join(report["errors"]))
    return members


def write_rp(members: dict, path) -> Path:
    """按样本成员顺序写 ZIP（普通 deflate 即可）。

    时间戳固定成 DOS 纪元：`writestr` 给字符串补的 `ZipInfo` 会写**当前时间**，
    那样即使 GUID 确定，两次产出的字节还是不同（P5 的第二个泄漏点）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(members, key=member_order_key):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16   # 与 `writestr` 的默认值一致
            zf.writestr(info, members[name])
    return path


# ------------------------------------------------------------------ 自检

def _walk(data, acc):
    if store.is_store(data):
        acc["stores"] += 1
        acc["pages"] += len(data) // store.BLOCK
        if store.rebuild(data) == data:
            acc["stores_ok"] += 1
        for _name, _id, first, length in store.entries_of(data):
            _walk(store.part_stream(data, first)[:length], acc)
        return
    try:
        ver, names, guids, items = c1.parse_stream(data)
    except Exception:
        return
    acc["c1"] += 1
    if c1.serialize(ver, names, guids, items) == data:
        acc["c1_ok"] += 1


def self_check(members: dict) -> dict:
    """离线自检：每个 c1 流与每个分页存储都「读 -> 写」逐字节一致。"""
    acc = {"members": len(members), "c1": 0, "c1_ok": 0,
           "stores": 0, "stores_ok": 0, "pages": 0, "version_bytes": 0}
    for name, data in members.items():
        if name.endswith(VERSION_SUFFIX):
            acc["version_bytes"] = len(data)
            continue
        _walk(data, acc)
    acc["ok"] = (acc["c1"] == acc["c1_ok"] and acc["stores"] == acc["stores_ok"]
                 and acc["members"] > 0)
    return acc


# --------------------------------------------------- 引用完整性 / 注册表自检
#
# 下列规则全部来自**原生 Axure RP8 文件**的实测（5 个文档、最多 221 页），
# 不是从 v1 样本反推的：

# 对象引用 tag（指向本流内某个 `tag 9` 对象）。tag 17 是「纯 guid 值」，不算。
_OBJ_REF_TAGS = (c1.T_REF, c1.T_REF20, c1.T_DJ, c1.T_PK)

_NULL_GUID = uuid.UUID(int=0)


def _collect_object_refs(item, out):
    tag = item[0]
    if tag == c1.T_DD:
        for key, value in item[1]:
            _collect_object_refs(key, out)
            _collect_object_refs(value, out)
    elif tag == c1.T_LIST:
        for child in item[1]:
            _collect_object_refs(child, out)
    elif tag == c1.T_OBJ:
        _collect_object_refs(item[3], out)
    elif tag in _OBJ_REF_TAGS:
        out.append(item[1])


def dangling_object_refs(guids, items):
    """「指向本流内对象、但该对象不存在」的对象引用下标（空 GUID 不算）。

    实测：5 个原生文档（含 221 页）的全部页面流都是 0 个非空悬挂对象引用，唯一
    例外是 `VectorShape.Annotation` / `SubmitButton` 指向空 GUID。

    注意 `tag 17`（`Axure:Style.Id`、库 id 这类**纯 guid 值**）不算对象引用：真机文件
    里这类值大量指向本流之外（库样式 / 其它页），属于正常写法。
    """
    defined = {it[1] for it in items if it[0] == c1.T_OBJ}
    refs = []
    for it in items:
        _collect_object_refs(it, refs)
    return sorted({i for i in refs if i not in defined and guids[i] != c1.NULL_GUID})


def _page_guids_of(members):
    """`Page/<2h>/<guid>/<guid>.rppkg` -> {包 GUID: 成员名}。"""
    out = {}
    for name in members:
        if name.startswith(PAGE_DIR + "/"):
            out[uuid.UUID(name.split("/")[-1].split(".")[0])] = name
    return out


def _page_c1_streams(data):
    """一个 `Page/...`（或 `Master/...`）成员里的全部 c1 流。

    实测真机的页面成员 = 外层存储，part 数可变（1..n）：主 part 是内层存储
    `{thumbnail, widgetinfo, package}`（顺序不固定，母版没有 `widgetinfo`），其余
    part 是动态面板子图（只含 `package`）。所以按「存储 -> 取 package」递归一层取流，
    不假设布局。
    """
    out = []
    for name, payload in store.parts_of(data):
        if store.is_store(payload):
            for sub_name, sub in store.parts_of(payload):
                if sub_name == "package":
                    out.append(("%s/%s" % (name, sub_name), sub))
        else:
            out.append((name, payload))
    return out


def _single_part_payload(data):
    """单 part 存储的净荷（`DesignDocument` / 生成器配置都是这种）。"""
    parts = store.parts_of(data)
    if len(parts) != 1:
        raise ValueError("期望单 part 存储，实际 %d 个" % len(parts))
    return parts[0][1]


def _obj_index(item):
    """条目若是对象引用则返回 guid 池下标，否则 None。"""
    return item[1] if item is not None and item[0] in _OBJ_REF_TAGS else None


def _page_registry(names, guids, items):
    """DD 注册表：{页包 GUID: PackageInfo 对象}（`package-id` 是 `fx(Axure:Page, g)`）。"""
    out = {}
    for it in items:
        if it[0] != c1.T_OBJ or names[it[2]] != "Axure:PackageInfo":
            continue
        pid = c1.dd_get(it[3], names, "package-id")
        if pid is None:
            continue
        if pid[0] == c1.T_FX and names[pid[1]] == model.PAGE_KIND:
            out[uuid.UUID(bytes_le=guids[pid[2]])] = it
        elif pid[0] == c1.T_GUID:
            out[uuid.UUID(bytes_le=guids[pid[1]])] = it
    return out


def _check_tree_map(names, guids, items, tree_map, label, errors):
    """校验一个 `{node-table, tree}` 映射（站点树 / 母版树同构）。"""
    table = c1.dd_get(tree_map[3], names, "node-table")
    tree_ref = c1.dd_get(tree_map[3], names, "tree")
    tree = (_find_object(items, names, "Axure:Tree", guid_index=tree_ref[1])
            if tree_ref is not None else None)
    if tree is None:
        errors.append("%s: tree 未指向 Axure:Tree" % label)
        return
    if table is None or table[0] != c1.T_DD:
        errors.append("%s: 缺 node-table" % label)
        return
    nodes = {it[1]: it for it in items
             if it[0] == c1.T_OBJ and names[it[2]] == "Axure:Node"}
    keys = [k[1] for k, _v in table[1]]
    for key in keys:
        if key not in nodes:
            errors.append("%s: node-table 键 %d 不是 Axure:Node" % (label, key))
    # Tree.children == 顶层节点（parent-node == tree）；真机的站点树就是这样，
    # 多级结构靠 Node.children 表达，不是把全部节点铺平。
    top = [r[1] for r in c1.dd_get(tree[3], names, "children")[1]]
    want = sorted(idx for idx in nodes
                  if _obj_index(c1.dd_get(nodes[idx][3], names, "parent-node")) == tree_ref[1])
    if sorted(top) != want:
        errors.append("%s: Tree.children(%d) != {parent==tree 的节点}(%d)"
                      % (label, len(top), len(want)))
    reach, stack = set(), list(top)
    while stack:
        idx = stack.pop()
        if idx in reach:
            continue
        reach.add(idx)
        node = nodes.get(idx)
        if node is None:
            errors.append("%s: Tree 的子节点 %d 不是 Axure:Node" % (label, idx))
            continue
        stack += [r[1] for r in c1.dd_get(node[3], names, "children")[1]]
    for idx in sorted(reach - set(keys)):
        errors.append("%s: 可达节点 %d 不在 node-table" % (label, idx))


def integrity_check(members: dict) -> dict:
    """离线完整性自检：对象引用闭合 + 注册表一致 + 站点树自洽。

    与 `self_check`（逐字节读写自洽）互补：字节往返抓不到悬挂引用与注册表错配。
    规则来自原生 Axure RP8 文件的实测，其中三条容易反直觉：

    1. **注册了却没有 Page 成员是合法的**（= 空页）。真机 `首页原型.rp` 注册 4 页
       只有 1 个成员；221 页的文档注册 262 页只有 221 个成员。反向（有成员未注册）才非法。
    2. `Tree.children` 只列**顶层**节点；`node-table` 覆盖整棵可达树。
    3. `tag 17` 的纯 guid 值可以指向本流之外，不算悬挂引用。
    """
    errors = []
    page_members = _page_guids_of(members)
    registry = {}
    dd_pool = set()

    # 1) 每条 c1 流：非空悬挂对象引用
    for name in sorted(members):
        data = members[name]
        if name.endswith(VERSION_SUFFIX):
            continue
        if name.startswith(PAGE_DIR + "/") or name.startswith(MASTER_DIR + "/"):
            # `Page/*` 与 `Master/*` 同构：外层存储 -> 内层存储 -> `package`。
            pairs = _page_c1_streams(data)
        elif name == SETTINGS_MEMBER:
            pairs = [(name, data)]
        else:
            if not store.is_store(data):
                errors.append("%s: 既不是分页存储也不是 c1 流" % name)
                continue
            try:
                pairs = [(name, _single_part_payload(data))]
            except ValueError as exc:
                errors.append("%s: %s" % (name, exc))
                continue
        for stream_name, raw in pairs:
            try:
                _ver, names, guids, items = c1.parse_stream(raw)
            except Exception as exc:
                errors.append("%s: 不是 c1 流（%s）" % (stream_name, exc))
                continue
            for idx in dangling_object_refs(guids, items):
                errors.append("%s: 悬挂对象引用 idx=%d guid=%s"
                              % (stream_name, idx, uuid.UUID(bytes_le=guids[idx])))
            if name.startswith(DESIGN_DOC_DIR + "/"):
                registry = _page_registry(names, guids, items)
                dd_pool = {uuid.UUID(bytes_le=g) for g in guids[1:] if g}
                _check_design_document(names, guids, items, registry, errors)

    # 2) Page 成员必须已注册（未注册的成员 = 真机不会出现的状态）
    for guid, member in sorted(page_members.items(), key=lambda kv: kv[1]):
        if guid not in registry:
            errors.append("%s: Page 成员未在 DD 注册表里" % member)

    # 3) document.settings 指向的包必须存在于 DD 池
    if SETTINGS_MEMBER in members and dd_pool:
        _ver, names, guids, items = c1.parse_stream(members[SETTINGS_MEMBER])
        settings = _find_object(items, names, "Axure:DocumentSettings")
        if settings is None:
            errors.append("%s: 缺 Axure:DocumentSettings" % SETTINGS_MEMBER)
        else:
            for key in ("selected-tab-package-id", "selected-tab-object-id"):
                value = c1.dd_get(settings[3], names, key)
                if value is None or value[0] not in _OBJ_REF_TAGS + (c1.T_GUID,):
                    errors.append("%s.%s 不是 guid" % (SETTINGS_MEMBER, key))
                elif uuid.UUID(bytes_le=guids[value[1]]) not in dd_pool:
                    errors.append("%s.%s 的 guid 不在 DD 池里" % (SETTINGS_MEMBER, key))
            tabs = c1.dd_get(settings[3], names, "open-tab-package-ids")
            if tabs is not None:
                for item in tabs[1]:
                    if item[0] in _OBJ_REF_TAGS + (c1.T_GUID,) \
                            and uuid.UUID(bytes_le=guids[item[1]]) not in dd_pool:
                        errors.append("%s.open-tab-package-ids 有 guid 不在 DD 池里"
                                      % SETTINGS_MEMBER)

    return {"ok": not errors, "errors": errors, "members": len(members),
            "pages": len(page_members), "registered": len(registry)}


def _check_design_document(names, guids, items, registry, errors):
    """`DesignDocument` / `SiteTreeMap` / `MasterTreeMap` / `PackageInfos` 自洽性。"""
    doc = _find_object(items, names, "Axure:DesignDocument")
    if doc is None:
        errors.append("DesignDocument: 缺 Axure:DesignDocument")
        return
    objects = {it[1] for it in items if it[0] == c1.T_OBJ}
    infos = c1.dd_get(doc[3], names, "PackageInfos")
    referenced = set()
    if infos is None or infos[0] != c1.T_LIST:
        errors.append("DesignDocument.PackageInfos 不是列表")
    else:
        for ref in infos[1]:
            idx = _obj_index(ref)
            if idx is None:
                errors.append("DesignDocument.PackageInfos 元素不是对象引用 tag=%d" % ref[0])
            elif idx not in objects:
                errors.append("DesignDocument.PackageInfos 指向不存在的对象 idx=%d" % idx)
            else:
                referenced.add(idx)
    for it in items:
        if (it[0] == c1.T_OBJ and names[it[2]] == "Axure:PackageInfo"
                and it[1] not in referenced):
            errors.append("DesignDocument: PackageInfo idx=%d 未被 PackageInfos 引用" % it[1])
    for guid in registry:
        if guid not in {uuid.UUID(bytes_le=g) for g in guids[1:] if g}:
            errors.append("DesignDocument: 页包 %s 不在 guid 池里" % guid)

    sitemap = _find_object(items, names, "Axure:SiteTreeMap")
    if sitemap is None:
        errors.append("DesignDocument: 缺 Axure:SiteTreeMap")
    else:
        _check_tree_map(names, guids, items, sitemap, "SiteTreeMap", errors)
        table = c1.dd_get(sitemap[3], names, "node-table")
        if table is not None and table[0] == c1.T_DD:
            for _key, value in table[1]:
                if value[0] == c1.T_FX:
                    if names[value[1]] != "Axure:PackageInfo":
                        errors.append("SiteTreeMap: node-table fx 类型 %s" % names[value[1]])
                        continue
                    guid = uuid.UUID(bytes_le=guids[value[2]])
                    if guid not in registry:
                        errors.append("SiteTreeMap: node-table 指向未注册页包 %s" % guid)
                elif _obj_index(value) not in objects:
                    errors.append("SiteTreeMap: node-table 值不是本流内的对象引用")

    master = c1.dd_get(doc[3], names, "mastermap")
    if master is not None and _obj_index(master) is not None:
        tree_map = _find_object(items, names, "Axure:MasterTreeMap",
                                guid_index=master[1])
        if tree_map is None:
            errors.append("DesignDocument: mastermap 未指向 Axure:MasterTreeMap")
        else:
            _check_tree_map(names, guids, items, tree_map, "MasterTreeMap", errors)
