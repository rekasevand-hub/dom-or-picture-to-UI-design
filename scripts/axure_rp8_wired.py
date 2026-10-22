# -*- coding: utf-8 -*-
"""端到端冒烟（真机发布用）：`Config/--tool axure` -> `DesignSpec` -> `.rp`。

走**真实入口**（`adapter_factory.build_adapter`）而不是直接调适配器，所以它同时覆盖
工厂接线、绘制序、颜色 / 圆角 / 文字 / 图片四条下发路径。产物拿去真机发布：

    & $PY scripts/axure_rp8_wired.py --out output/_axure_proto/m6_wired.rp
    powershell -File scripts/axure_publish_html.ps1 -Path output/_axure_proto/m6_wired.rp -Tag m6wired

判据在发布出来的 `files/<page>/styles.css` / `<page>.html`：底色 / 圆角 / 边框逐值命中，
`images/<page>/uN.png` 与塞进去的字节**逐字节相同**，控件内的文字**不折行**（宽度要自己
估，见 `AxureRPAdapter._text`）。

设计里那个圆（`ELLIPSE_LABEL`）用 `--check <发布目录>` 核对：Axure 只把矩形类控件写成
`<div>` + CSS，非矩形形状可能被栅格化成 PNG——两种形态都认，PNG 就做像素探针
（四角透明 / 中心 = 指定底色 / 不透明面积 ≈ π/4）。按钮 / 输入框也在同一个
`--check` 里核：按钮要发成 `class="ax_default button"` 且标题在 `#uN_text` 里，
输入框要发成 `class="ax_default text_field"` + `<input id="uN_input" type="text">`。
"""
from __future__ import annotations

import argparse
import base64
import io
import math
import os
import re
import sys
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.services.rendering.adapter_factory import build_adapter   # noqa: E402
from src.app.services.rendering.axure import c1, constants, model, store  # noqa: E402
from src.config import Config                                          # noqa: E402


# 圆探针：控件名（发布产物里靠它认元素）+ 几何 + 颜色。给的是**正方形 + 不透明底色**，
# 这样栅格化出来的 PNG 才能直接量「不透明面积 ≈ π/4」。
ELLIPSE_LABEL = "\u56fe\u5f62\u5706"
ELLIPSE_BOX = (480, 400, 200, 200)
ELLIPSE_FILL = "#EA4335"
ELLIPSE_BORDER = "#202124"

# 按钮 / 输入框探针（§3.2）：名字用来在发布产物里认元素（`data-label`）。
BUTTON_LABEL = "\u4e0b\u5355\u6309\u94ae"
BUTTON_TEXT = "\u4e0b\u5355"
BUTTON_BOX = (328, 248, 120, 40)
BUTTON_FILL = "#34A853"
INPUT_LABEL = "\u641c\u7d22\u6846"
INPUT_BOX = (480, 248, 200, 40)
INPUT_FILL = "#FFFFFF"
INPUT_BORDER = "#DADCE0"


def probe_png(width=240, height=160, rgb=(76, 139, 245), label="WIRED IMAGE"):
    """现造一张真图：只有真字节才能验证「图片原样落盘」。"""
    from PIL import Image as PILImage, ImageDraw
    image = PILImage.new("RGB", (width, height), rgb)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(255, 255, 255), width=4)
    draw.text((12, 12), "%s %dx%d" % (label, width, height), fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_design():
    """一份把四条路径都踩到的固定设计（容器 / 标题 / 图片 / 文字 / 按钮 / 分隔线）。"""
    png = probe_png()
    b64 = base64.b64encode(png).decode("ascii")
    return png, {
        "canvas": {"width": 1024, "height": 768},
        "elements": [
            {"type": "container", "x": 32, "y": 32, "width": 960, "height": 704,
             "style": {"fillColor": "#FFFFFF", "borderColor": "#DADCE0",
                       "borderWidth": 1, "borderRadius": 12}},
            {"type": "rectangle", "x": 64, "y": 64, "width": 896, "height": 64,
             "style": {"fillColor": "#4C8BF5", "borderRadius": 8}},
            {"type": "text", "x": 88, "y": 78, "width": 400, "height": 36,
             "text": "\u9996\u9875\u00b7\u4ea7\u54c1\u7f16\u7801",
             "style": {"textColor": "#FFFFFF", "fontSize": 20, "fontWeight": 700,
                       "fontFamily": "\u5fae\u8f6f\u96c5\u9ed1, Arial",
                       "textAlign": "left"}},
            {"type": "image", "x": 64, "y": 160, "width": 240, "height": 160,
             "imageBase64": b64},
            {"type": "text", "x": 328, "y": 160, "width": 320, "height": 28,
             "text": "\u4ea7\u54c1\u7f16\u7801\uff1aA-1024",
             "style": {"textColor": "#202124", "fontSize": 14, "textAlign": "left"}},
            {"type": "text", "x": 328, "y": 196, "width": 320, "height": 28,
             "text": "\u5e93\u5b58\uff1a120 \u4ef6",
             "style": {"textColor": "#5F6368", "fontSize": 14, "textAlign": "left"}},
            {"type": "button", "name": BUTTON_LABEL,
             "x": BUTTON_BOX[0], "y": BUTTON_BOX[1],
             "width": BUTTON_BOX[2], "height": BUTTON_BOX[3],
             "text": BUTTON_TEXT,
             "style": {"fillColor": BUTTON_FILL, "borderRadius": 20,
                       "textColor": "#FFFFFF", "fontSize": 14, "textAlign": "center"}},
            # 输入框：`Axure:DiagramObject:TextBox`（`Text Field` 库样式），`--check` 核它
            {"type": "input", "name": INPUT_LABEL,
             "x": INPUT_BOX[0], "y": INPUT_BOX[1],
             "width": INPUT_BOX[2], "height": INPUT_BOX[3],
             "style": {"fillColor": INPUT_FILL, "borderColor": INPUT_BORDER,
                       "borderWidth": 1, "borderRadius": 4,
                       "textColor": "#202124", "fontSize": 14, "textAlign": "left"}},
            {"type": "divider", "x": 64, "y": 360, "width": 896, "height": 1,
             "style": {"fillColor": "#E8EAED"}},
            # data URL 形态也要能过（基类两种都会给）
            {"type": "image", "x": 700, "y": 400, "width": 200, "height": 200,
             "imageBase64": "data:image/png;base64," + b64},
            # 圆：Shape=15 + 4 点圆路径（§3.1），`--check` 逐项核这一项
            {"type": "circle", "name": ELLIPSE_LABEL,
             "x": ELLIPSE_BOX[0], "y": ELLIPSE_BOX[1],
             "width": ELLIPSE_BOX[2], "height": ELLIPSE_BOX[3],
             "style": {"fillColor": ELLIPSE_FILL, "borderColor": ELLIPSE_BORDER,
                       "borderWidth": 2}},
        ],
    }


# --- M5 多页探针 ---------------------------------------------------------------

# 3 页，页名 / 画板尺寸 / 内容各不相同。每页**第一个**控件是铺满画板的底色矩形，
# 于是发布出来的 `body{width}` 就等于画板宽 —— 这是「画板尺寸」唯一能在真机产物里
# 核对到的地方：`.rp` 里**没有**页尺寸字段（4 个原生文件实测，见 format §11.9），
# Axure 的页宽 = 内容包围盒，所以只能靠内容把画板"顶"出来。
PAGE_PROBES = (
    {"name": "\u9996\u9875 Home", "width": 1024, "height": 768,
     "fill": "#FFFFFF", "label": "\u9875\u9762\u63a2\u9488-1", "color": "#4C8BF5"},
    {"name": "\u8ba2\u5355 Orders", "width": 375, "height": 812,
     "fill": "#F1F3F4", "label": "\u9875\u9762\u63a2\u9488-2", "color": "#34A853"},
    {"name": "\u62a5\u8868 Reports", "width": 1440, "height": 900,
     "fill": "#FFF7E6", "label": "\u9875\u9762\u63a2\u9488-3", "color": "#EA4335"},
)


def build_pages_design():
    """M5 多页设计：`design["pages"]` 的第 i 项 -> 站点树里的第 i 页（顺序 = 数组顺序）。"""
    pages = []
    for probe in PAGE_PROBES:
        width, height = probe["width"], probe["height"]
        pages.append({
            "name": probe["name"],
            "canvas": {"width": width, "height": height},
            "elements": [
                {"type": "rectangle", "name": "\u9875\u5e95 %s" % probe["name"],
                 "x": 0, "y": 0, "width": width, "height": height,
                 "style": {"fillColor": probe["fill"], "borderColor": "#DADCE0",
                           "borderWidth": 1}},
                {"type": "text", "name": "\u9875\u9898 %s" % probe["name"],
                 "x": 24, "y": 24, "width": max(0, width - 48), "height": 32,
                 "text": probe["name"],
                 "style": {"textColor": "#202124", "fontSize": 20,
                           "fontWeight": 700, "textAlign": "left"}},
                {"type": "rectangle", "name": probe["label"],
                 "x": 48, "y": 96, "width": 160, "height": 96,
                 "style": {"fillColor": probe["color"], "borderRadius": 8}},
            ],
        })
    return {"pages": pages}


def read_page_registry(path):
    """`DesignDocument` 的页面注册项 -> [(页名, 页包 GUID)]（顺序 = 写入顺序）。

    `.rp` 的 `Page/` 成员名是 GUID，`zipfile.namelist()` 排不出页序；页序只在
    `DesignDocument` 的 `PackageInfos` / `sitemap` 里。
    """
    with zipfile.ZipFile(path) as zf:
        member = [n for n in zf.namelist() if n.startswith("DesignDocument/")][0]
        _ver, names, guids, items = c1.parse_stream(store.parts_of(zf.read(member))[0][1])
    out = []
    for it in items:
        if it[0] != c1.T_OBJ or names[it[2]] != "Axure:PackageInfo":
            continue
        pid = c1.dd_get(it[3], names, "package-id")
        if pid is None or names[pid[1]] != model.PAGE_KIND:
            continue
        out.append((names[c1.dd_get(it[3], names, "package-name")[1]],
                    uuid.UUID(bytes_le=guids[pid[2]])))
    return out


def read_back(path):
    """读回产物：页面数、形状数（含圆 / 按钮）、输入框数、图片数、图片字节。"""
    shapes = boxes = ellipses = buttons = text_fields = 0
    blobs = []
    with zipfile.ZipFile(path) as zf:
        pages = [n for n in zf.namelist() if n.startswith("Page/")]
        for name in pages:
            l2 = store.parts_of(zf.read(name))[0][1]
            _ver, names, _guids, items = c1.parse_stream(store.parts_of(l2)[2][1])
            for it in items:
                if it[0] != c1.T_OBJ:
                    continue
                kind = names[it[2]]
                if kind == model.SHAPE_KIND:
                    shapes += 1
                    shape = c1.dd_get(it[3], names, "Shape")
                    if shape is not None and shape[1] == constants.SHAPE_ELLIPSE:
                        ellipses += 1
                    elif _style_name(it, names, items) == constants.BUTTON_STYLE_NAME:
                        buttons += 1
                elif kind == model.TEXT_BOX_KIND:
                    text_fields += 1
                elif kind == model.IMAGE_BOX_KIND:
                    boxes += 1
                    style_idx = c1.dd_get(it[3], names, "MyStyle")[1]
                    style = next(x for x in items
                                 if x[0] == c1.T_OBJ and x[1] == style_idx)
                    for row in c1.dd_get(style[3], names, "PropList")[1]:
                        if (c1.dd_get(row, names, "DOAName")[1]
                                & 0x3FFFFFFF) != constants.P_IMAGE:
                            continue
                        for key, value in c1.dd_get(row, names, "Value")[1]:
                            if names[key[1]] == "Stream":
                                blobs.append(value[1])
    return {"pages": len(pages), "shapes": shapes, "ellipses": ellipses,
            "buttons": buttons, "text_fields": text_fields,
            "images": boxes, "blobs": blobs}


def _style_name(obj, names, items):
    """对象命中的库样式名（`MatchInfo.Name`）——"是按钮 / 是形状"就看这个。"""
    style_ref = c1.dd_get(obj[3], names, "MyStyle")
    if style_ref is None:
        return ""
    style = next((x for x in items if x[0] == c1.T_OBJ and x[1] == style_ref[1]), None)
    if style is None:
        return ""
    match = c1.dd_get(style[3], names, "MatchInfo")
    value = None if match is None else c1.dd_get(match, names, "Name")
    return "" if value is None else names[value[1]]


def _hex_rgb(text):
    value = text.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def analyze_png(path, fill_rgb):
    """栅格化的圆形 PNG：四角透明、中心 = 底色、不透明面积 ≈ π/4。"""
    from PIL import Image as PILImage
    image = PILImage.open(path)
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    if width < 8 or height < 8:
        print("  RASTER %s %s 太小" % (image.mode, image.size))
        return False
    corners = [pixels[0, 0], pixels[width - 1, 0],
               pixels[0, height - 1], pixels[width - 1, height - 1]]
    center = pixels[width // 2, height // 2]
    opaque = sum(1 for x in range(width) for y in range(height)
                 if pixels[x, y][3] > 128)
    ratio = opaque / float(width * height)
    print("  RASTER %s %s %s" % (image.format, image.mode, image.size))
    print("     四角像素 = %s" % [tuple(c) for c in corners])
    print("     中心像素 = %s（期望 RGB %s）" % (tuple(center), fill_rgb))
    print("     不透明占比 = %.4f（整圆 π/4 = %.4f）" % (ratio, math.pi / 4.0))
    corners_clear = all(c[3] <= 8 for c in corners)
    center_ok = tuple(center[:3]) == tuple(fill_rgb) and center[3] > 200
    area_ok = abs(ratio - math.pi / 4.0) <= 0.03
    print("     角透明=%s 中心底色=%s 面积=%s" % (corners_clear, center_ok, area_ok))
    return corners_clear and center_ok and area_ok


def _element_of(html, label):
    """按 `data-label` 找控件元素：返回 (元素 id, 元素块起点) 或 None。

    标签先出现在 `<!-- 名字 (Ellipse) -->` 注释里，元素 div 在它**之后**。
    """
    at = html.find('data-label="%s"' % label)
    if at < 0:
        return None
    head = html.rfind("<div id=", 0, at)
    match = re.match(r'<div id="(u\d+)"', html[head:]) if head >= 0 else None
    if not match:
        return None
    return match.group(1), head


def check_ellipse(root, html, page):
    """圆：栅格化成 `<img>`（像素探针）还是 `<div>` + CSS（要 `border-radius`）。"""
    found = _element_of(html, ELLIPSE_LABEL)
    if not found:
        print("圆：页 %s 里没有控件名 %r 的元素" % (page, ELLIPSE_LABEL))
        return False
    elem, head = found
    img = re.search(r'<img id="%s_img"[^>]*src="([^"]+)"' % elem, html[head:head + 1200])
    print("圆 %s 的发布形态：" % elem)
    print(html[head:head + 400].rstrip())
    if img:
        print("  -> 栅格化成 <img>：%s" % img.group(1))
        return analyze_png(root / img.group(1), _hex_rgb(ELLIPSE_FILL))
    css = (root / "files" / page / "styles.css").read_text(encoding="utf-8")
    rule = re.search(r'#%s_div\s*\{[^}]*\}' % elem, css)
    print("  -> <div> + CSS：%s"
          % (rule.group(0).replace("\n", " ") if rule else "（styles.css 里没有这条规则）"))
    if rule and "border-radius" not in rule.group(0):
        print("     注意：规则里没有 border-radius —— 那多半不是圆")
    return bool(rule) and "border-radius" in rule.group(0)


def check_button(root, html):
    """按钮：`class="ax_default button"` + 标题在 `#uN_text` 里（不是另一个文本框）。"""
    found = _element_of(html, BUTTON_LABEL)
    if not found:
        print("按钮：发布产物里没有控件名 %r 的元素" % BUTTON_LABEL)
        return False
    elem, head = found
    block = html[head:head + 1400]
    print("按钮 %s 的发布形态：" % elem)
    print(block[:400].rstrip())
    cls = re.search(r'<div id="%s"[^>]*class="([^"]*)"' % elem, block)
    class_ok = bool(cls) and "button" in cls.group(1).split()
    caption = re.search(r'<div id="%s_text"[^>]*>\s*<p><span>([^<]*)</span>' % elem, block)
    caption_ok = bool(caption) and caption.group(1) == BUTTON_TEXT
    print("     类名含 button=%s（%s）；标题 = %r（期望 %r）"
          % (class_ok, cls.group(1) if cls else "-",
             caption.group(1) if caption else None, BUTTON_TEXT))
    return class_ok and caption_ok


def check_input(root, html):
    """输入框：`class="ax_default text_field"` + `<input id="uN_input" type="text">`。"""
    found = _element_of(html, INPUT_LABEL)
    if not found:
        print("输入框：发布产物里没有控件名 %r 的元素" % INPUT_LABEL)
        return False
    elem, head = found
    block = html[head:head + 1400]
    print("输入框 %s 的发布形态：" % elem)
    print(block[:400].rstrip())
    cls = re.search(r'<div id="%s"[^>]*class="([^"]*)"' % elem, block)
    class_ok = bool(cls) and "text_field" in cls.group(1).split()
    tag = re.search(r'<input id="%s_input"[^>]*>' % elem, block)
    print("     类名含 text_field=%s（%s）；%s"
          % (class_ok, cls.group(1) if cls else "-",
             tag.group(0) if tag else "没有 <input> 子元素"))
    return class_ok and bool(tag)


def check_publish(publish_dir, page="screen_1024_768"):
    """核对真机发布产物：圆（§3.1）+ 按钮 / 输入框（§3.2）。全部命中才 RESULT=OK。"""
    root = Path(publish_dir)
    html = (root / ("%s.html" % page)).read_text(encoding="utf-8")
    results = {
        "ellipse": check_ellipse(root, html, page),
        "button": check_button(root, html),
        "input": check_input(root, html),
    }
    failed = [name for name, ok in results.items() if not ok]
    print("RESULT=%s %s" % ("OK" if not failed else "FAIL",
                            " ".join("%s=%s" % (n, results[n]) for n in sorted(results))))
    return 0 if not failed else 1


# --- M5 多页核对（对着真机发布产物念判据） -------------------------------------

def _js_literal(text, key):
    """发布产物是压缩过的 JS：`"<key>",<var>=<字面量>` -> 字面量文本（去引号）。

    例：`data.js` 里的 `s="name",t="Home"` / `bg="size",bh="width",bi=280`。
    只认字面量；值是变量名（值在别处定义）时返回 None。
    """
    pattern = (r'"%s",[A-Za-z_$][\w$]*\s*=\s*'
               r'(?:"([^"]*)"|(-?(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?)))'
               % re.escape(key))
    match = re.search(pattern, text)
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _root_nodes(text):
    """`data/document.js` -> [(页名, url)]（顺序 = Axure 站点树顺序）。

    发布产物是压缩过的 JS，站点树长这样：
    `...t="rootNodes",u="pageName",v="Home",w="type",x="Wireframe",y="url",
    z="home.html",A="Page 2",B="page_2.html",...`。键名变量只定义一次（第一个节点），
    后面的节点只带新值。于是按字符串字面量的出现顺序扫：第一个 `.html` 之前紧邻的是
    键名变量 `url`，页名取 `pageName` 后的值；其余 `.html` 前紧邻的值就是页名。
    """
    at = text.find('"rootNodes"')
    if at < 0:
        return []
    tail = text[at:]
    stop = tail.find('"globalVariables"')
    if stop >= 0:
        tail = tail[:stop]
    values = [tok[1:-1] for tok in re.findall(r'"[^"]*"', tail)]
    nodes = []
    for index, value in enumerate(values):
        if index == 0 or not value.endswith(".html"):
            continue
        previous = values[index - 1]
        if previous == "url":
            key = values.index("pageName") if "pageName" in values else -2
            name = values[key + 1]
        else:
            name = previous
        nodes.append((name, value))
    return nodes


def check_pages(root, rp_path=None):
    """M5 判据：站点树页序 + 每页页名 / 画板尺寸 / 内容，全部命中才 RESULT=OK。

    「画板尺寸」用两层证据：`files/<page>/data.js` 里**第一个控件**（铺满画板的底色
    矩形）的 `size{width,height}`，以及 `files/<page>/styles.css` 的 `body{width}`。
    `.rp` 里没有页尺寸字段（format §11.9），Axure 的页宽 = 内容包围盒 —— 所以
    这两条才是「画板尺寸」真正的落点。

    传了 `rp_path` 就再核一层：发布出的 `packageId` 必须等于生成时写进 `.rp` 的页包 GUID。
    """
    root = Path(root)
    nodes = _root_nodes((root / "data" / "document.js").read_text(encoding="utf-8"))
    expected = [probe["name"] for probe in PAGE_PROBES]
    registry = {}
    if rp_path and Path(rp_path).is_file():
        registry = dict(read_page_registry(rp_path))
        print("`.rp` 页包注册表（写入顺序）：%s"
              % [(n, str(g)) for n, g in registry.items()])
    results = {"order": [name for name, _url in nodes] == expected}
    print("站点树：%s" % [name for name, _url in nodes])
    print("        期望页序 %s -> order=%s" % (expected, results["order"]))
    for index, probe in enumerate(PAGE_PROBES):
        tag = "page%d" % (index + 1)
        if index >= len(nodes):
            print("[%s] 站点树里没有第 %d 页" % (tag, index + 1))
            results[tag] = False
            continue
        url = nodes[index][1]
        page_dir = url[:-5] if url.endswith(".html") else url
        html_path = root / url
        data_path = root / "files" / page_dir / "data.js"
        css_path = root / "files" / page_dir / "styles.css"
        if not (html_path.is_file() and data_path.is_file() and css_path.is_file()):
            print("[%s] 缺文件：html=%s data=%s css=%s" % (
                tag, html_path.is_file(), data_path.is_file(), css_path.is_file()))
            results[tag] = False
            continue
        html = html_path.read_text(encoding="utf-8")
        data = data_path.read_text(encoding="utf-8")
        css = css_path.read_text(encoding="utf-8")
        name = _js_literal(data, "name")
        package = _js_literal(data, "packageId")
        width = _js_literal(data, "width")
        height = _js_literal(data, "height")
        found = re.search(r'body\s*\{[^}]*?width:(\d+)px', css)
        body_width = int(found.group(1)) if found else None
        # 发布产物里的写法：`0xAARRGGBB`（真机核对过，见 format §11.4）。
        color = "0x%08X" % int("FF" + probe["color"].lstrip("#"), 16)
        same_package = str(registry.get(probe["name"], "")).replace("-", "")
        checks = {
            "name": name == probe["name"],
            "package": bool(package) and (not registry
                                          or same_package == package),
            "canvas": (width == str(probe["width"])
                       and height == str(probe["height"])),
            "body": body_width == probe["width"],
            "color": color.lower() in data.lower(),
            "content": ('data-label="%s"' % probe["label"]) in html,
        }
        results[tag] = all(checks.values())
        print("[%s] %r  url=%s  dir=%s  package=%s" % (tag, name, url, page_dir, package))
        print("     data.js 首控件 size=%sx%s（期望 %dx%d）  styles.css body=%s（期望 %d）"
              % (width, height, probe["width"], probe["height"],
                 body_width, probe["width"]))
        print("     内容 %r 在 %s 里=%s；底色 %s 在 data.js 里=%s"
              % (probe["label"], url, checks["content"], color, checks["color"]))
        if not results[tag]:
            print("     -> FAIL %s" % {k: v for k, v in checks.items() if not v})
    failed = [key for key, value in results.items() if not value]
    print("RESULT=%s %s" % ("OK" if not failed else "FAIL",
                            " ".join("%s=%s" % (k, results[k]) for k in sorted(results))))
    return 0 if not failed else 1


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Axure v2 端到端冒烟（真机发布用）")
    parser.add_argument("--out",
                        default=os.path.join("output", "_axure_proto", "m6_wired.rp"))
    parser.add_argument("--check", default="",
                        help="核对真机发布产物目录（圆 / 按钮 / 输入框）而不是生成")
    parser.add_argument("--page", default="screen_1024_768",
                        help="发布产物里的页目录名（默认由画板名净化而来）")
    parser.add_argument("--pages", action="store_true",
                        help="M5 多页：生成时改发 3 页设计；配 --check 时按多页判据核对")
    args = parser.parse_args(argv)

    if args.check:
        if args.pages:
            return check_pages(args.check, args.out)
        return check_publish(args.check, args.page)

    if args.pages:
        png, design = b"", build_pages_design()
    else:
        png, design = build_design()
    config = Config(output_dir=Path(args.out).parent, prototype_tool="axure")
    build_adapter("axure", config).render_design(design)
    # 工厂写的是 `<output_dir>/prototype.rp`；按 --out 命名再放一份。
    produced = Path(config.output_dir) / "prototype.rp"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_bytes(produced.read_bytes())

    report = read_back(args.out)
    print("wrote %s (%d B)" % (args.out, os.path.getsize(args.out)))
    if args.pages:
        for name, package in read_page_registry(args.out):
            print("page: %-16s package=%s" % (name, package))
    print("pages %d  shapes %d (ellipse %d, button %d)  inputs %d  images %d"
          % (report["pages"], report["shapes"], report["ellipses"],
             report["buttons"], report["text_fields"], report["images"]))
    print("image bytes identical: %s" % [b == png for b in report["blobs"]])
    tag = Path(args.out).stem.replace("_", "")
    print("next: powershell -File scripts/axure_publish_html.ps1 -Path %s -Tag %s"
          % (args.out, tag))
    print("then: python scripts/axure_rp8_wired.py --check "
          + r"%USERPROFILE%\Documents\Axure\HTML" + "\\" + tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())