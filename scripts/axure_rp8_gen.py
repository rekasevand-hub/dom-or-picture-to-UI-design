# -*- coding: utf-8 -*-
"""从零生成一个 Axure RP 8 `.rp`（v2 写入层的最小入口 / 真机 oracle 用）。

用法：
    $PY = 'C:\\Users\\lzq\\.conda\\envs\\omni\\python.exe'
    & $PY scripts/axure_rp8_gen.py --out output/_axure_proto/m3_native.rp
    & $PY scripts/axure_rp8_gen.py --out output/_axure_proto/m2_pages.rp --pages 3 --rects 2 --color

文档级常量固定用**原生 Axure 文件**抽出的模板（`assets/axure/rp8/base_native.rp`）。

生成后跑真机 oracle（**会 kill AxureRP8，先存盘退出**）：
    powershell -File scripts/axure_publish_html.ps1 -Path <rp> -Tag <tag>
"""
from __future__ import annotations

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.services.rendering.axure import (doc, thumbnail,  # noqa: E402
                                              writer)

COLORS = (0xFF4C8BF5, 0xFF34A853, 0xFFEA4335, 0xFFFBBC05)


def build_spec(pages: int, rects: int, color: bool) -> doc.DesignSpec:
    frames = []
    for p in range(pages):
        name = "Home" if p == 0 else "Page %d" % (p + 1)
        widgets = []
        for i in range(rects):
            extra = {}
            if color:
                extra = {"fill": COLORS[i % len(COLORS)],
                         "border": 0xFF202124, "border_width": 1.0}
            widgets.append(doc.Rect(x=80, y=60 + i * 140, width=280, height=110,
                                    label="%s-%d" % (name, i + 1), **extra))
        frames.append(doc.Frame(name=name, width=800,
                                height=max(600, 160 + rects * 140), widgets=widgets))
    return doc.DesignSpec(frames=frames)


def build_text_spec() -> doc.DesignSpec:
    """M4 文字探针：一份「什么都要覆盖到」的文本页。

    判据在**发布出来的 HTML** 里（不是「看起来对」）：`files/<page>/styles.css`
    的 `#uN_text` 要有 `font-size` / `color` / `text-align`，`<page>.html` 里要有
    文字内容。见 `归档文档 axure_rp8_format.md` §11.5。
    """
    widgets = [
        doc.Text(text="首页", x=40, y=40, width=240, height=80,
                 family="微软雅黑", size=20, weight=700, color=0xFFFFFFFF,
                 align=1, fill=0xFF4C8BF5),
        doc.Text(text="Hello Axure 中文", x=40, y=160, width=320, height=40,
                 family="Arial", size=14, color=0xFF202124),
        doc.Text(text="第一行\n第二行\n第三行", x=40, y=220, width=320, height=90,
                 family="微软雅黑", size=12, color=0xFF34A853, align=1),
        doc.Text(text="右对齐 right", x=40, y=340, width=320, height=40,
                 family="Arial", size=12, color=0xFFEA4335, align=2),
        doc.Rect(x=420, y=40, width=200, height=80, label="纯矩形",
                 fill=0xFF34A853, border=0xFF202124, border_width=1.0),
    ]
    return doc.DesignSpec(frames=[doc.Frame(name="Home", width=800, height=600,
                                            widgets=widgets)])


def build_font_spec() -> doc.DesignSpec:
    """M4 字体探针：一次发布里把「字体属性到底从哪来」逐项分离。

    每行只动一个变量，看 `files/<page>/styles.css` 的 `#uN` / `#uN_div`
    / `<page>.html` 的 inline `<span style>`：
      * 字号是 pt 还是 px（10.5 -> 14px 是 4/3）
      * `P9` 是不是水平对齐（0 左 / 1 中 / 2 右）
      * 形状样式与 AxRun 不一致时是否补 inline span
    """
    widgets = [
        doc.Text(text="A20", x=40, y=40, width=200, height=40, family="Arial",
                 size=20, color=0xFF000000, align=0, line_spacing=20.0),
        doc.Text(text="B20", x=40, y=100, width=200, height=40, family="微软雅黑",
                 size=20, weight=700, color=0xFFFF0000, align=0, line_spacing=20.0),
        doc.Text(text="C-CENTER", x=40, y=160, width=240, height=40, family="微软雅黑",
                 size=14, color=0xFF34A853, align=1, line_spacing=14.0),
        doc.Text(text="D-RIGHT", x=40, y=220, width=240, height=40, family="微软雅黑",
                 size=14, color=0xFFEA4335, align=2, line_spacing=14.0),
        doc.Text(text="E10.5", x=40, y=280, width=200, height=40, family="Arial",
                 size=10.5, color=0xFF202124, align=0, line_spacing=10.5),
        doc.Text(text="F-BOX", x=40, y=340, width=200, height=60, family="微软雅黑",
                 size=18, weight=700, color=0xFFFFFFFF, align=1, line_spacing=18.0,
                 fill=0xFF4C8BF5),
    ]
    return doc.DesignSpec(frames=[doc.Frame(name="Home", width=800, height=600,
                                            widgets=widgets)])


def _probe_image(width, height, background, text, fmt="PNG"):
    """探针图：一段可识别的位图（白框 + 文字），而不是随便几个字节。

    **为什么用真图**：真机实测发现 Axure **原样**把 `IMAGE(27)` 槽里的字节写进
    `images/<page>/uN.png`（不重编码、不改分辨率），所以探针用真图才能同时验证
    「字节原样落盘」这件事。
    """
    from PIL import Image as PILImage, ImageDraw
    image = PILImage.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(255, 255, 255), width=3)
    draw.rectangle([6, 6, width - 7, 26], fill=(0, 0, 0))
    draw.text((10, 12), text, fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def build_image_spec() -> doc.DesignSpec:
    """M4 图片探针：一份把「图片控件配方」拆开的固定页。

    判据在**发布出来的产物**里（不是「看起来对」）：
      * `<page>.html` 有 `<div id="uN" class="ax_default _图片"><img id="uN_img" .../></div>`；
      * `images/<page>/uN.png` 与生成时塞进去的字节**逐字节相同**；
      * `files/<page>/styles.css` 的 `#uN` 有正确的 left/top/width/height。
    见 `归档文档 axure_rp8_format.md` §11.6。
    """
    widgets = [
        doc.Image(x=40, y=40, width=200, height=120, label="图片A",
                  data=_probe_image(200, 120, (76, 139, 245), "IMG A 200x120")),
        doc.Image(x=280, y=40, width=120, height=120, label="图片B",
                  data=_probe_image(120, 120, (52, 168, 83), "IMG B", fmt="JPEG")),
        doc.Image(x=40, y=200, width=240, height=80, label="图片C-fit",
                  fit_to_image=True,
                  data=_probe_image(240, 80, (234, 67, 53), "FIT-TO-IMAGE")),
        doc.Rect(x=320, y=200, width=160, height=80, label="纯矩形对照",
                 fill=0xFFFBBC05, border=0xFF202124, border_width=1.0),
    ]
    return doc.DesignSpec(frames=[doc.Frame(name="Home", width=800, height=600,
                                            widgets=widgets)])


# 折行探针的公共形态：**零余量**盒子 —— 真实字宽比盒宽大一丁点
# （dushu 实测「口袋典藏四大名著 三国演义」自然宽 172.16px 落在 172px 的盒子里，
# 页面自己 `white-space:nowrap` 不折，Axure 的自动排版却按盒宽折）。
_WRAP_TEXT = "口袋典藏四大名著 三国演义"
_WRAP_BOX = 172.0
_WRAP_FONT = "Microsoft YaHei"


def build_wrap_spec() -> doc.DesignSpec:
    """折行探针：把「谁在折行」逐项分离的固定页（一行只动一个变量）。

    判据在**发布出来的产物**里，不在「看起来对」：
      * `files/home/styles.css` 的 `#uN_text` 是 `white-space:nowrap` 还是
        `word-wrap:break-word`；
      * Chromium 量出来的**行数**（`Range.getClientRects()`）。
    见 `归档文档 axure_rp8_plan.md` §9.11。
    """
    t = _WRAP_TEXT
    widgets = [
        doc.Text(text=t, x=40, y=40, width=_WRAP_BOX, height=24, label="wrap-T-base",
                 family=_WRAP_FONT, size=14),
        doc.Text(text=t, x=40, y=84, width=_WRAP_BOX, height=24, label="wrap-T-af",
                 family=_WRAP_FONT, size=14, autofit_width=True),
        doc.Text(text=t, x=40, y=128, width=200.0, height=24, label="wrap-T-wide",
                 family=_WRAP_FONT, size=14),
        doc.Text(text=t, x=40, y=172, width=200.0, height=24, label="wrap-T-wide-af",
                 family=_WRAP_FONT, size=14, autofit_width=True),
        doc.Text(text=t, x=40, y=216, width=_WRAP_BOX, height=24, label="wrap-T-center-af",
                 family=_WRAP_FONT, size=14, align=1, autofit_width=True),
        doc.Text(text=t, x=40, y=260, width=_WRAP_BOX, height=24, label="wrap-T-right-af",
                 family=_WRAP_FONT, size=14, align=2, autofit_width=True),
        doc.Text(text=t + " 水浒传", x=40, y=304, width=_WRAP_BOX, height=24,
                 label="wrap-T-long-af", family=_WRAP_FONT, size=14, autofit_width=True),
        doc.Text(text="第一行\n第二行", x=40, y=348, width=_WRAP_BOX, height=24,
                 label="wrap-T-nl-af", family=_WRAP_FONT, size=14, autofit_width=True),
        doc.Button(text=t, x=40, y=392, width=_WRAP_BOX, height=24, label="wrap-B-base",
                   family=_WRAP_FONT, size=14),
        doc.Button(text=t, x=40, y=436, width=_WRAP_BOX, height=24, label="wrap-B-af",
                   family=_WRAP_FONT, size=14, autofit_width=True),
        doc.Text(text="01", x=40, y=480, width=20.0, height=24, label="wrap-X-base",
                 family="Arial", size=18),
        doc.Text(text="01", x=40, y=524, width=20.0, height=24, label="wrap-X-af",
                 family="Arial", size=18, autofit_width=True),
        doc.Text(text=t, x=40, y=568, width=_WRAP_BOX, height=24, label="wrap-S-shape-af",
                 family=_WRAP_FONT, size=14, shape_autofit=True),
        doc.Text(text=t, x=40, y=612, width=_WRAP_BOX, height=24, label="wrap-S-shape-af-panel",
                 family=_WRAP_FONT, size=14, shape_autofit=True, autofit_width=True),
        doc.Button(text=t, x=40, y=656, width=_WRAP_BOX, height=24, label="wrap-S-B-shape-af",
                   family=_WRAP_FONT, size=14, shape_autofit=True),
        doc.Text(text="01", x=40, y=700, width=20.0, height=24, label="wrap-S-X-shape-af",
                 family="Arial", size=18, shape_autofit=True),
        doc.Button(text=t, x=40, y=744, width=_WRAP_BOX, height=24, label="wrap-Q-B-base",
                   family=_WRAP_FONT, size=14),
        doc.Button(text=t, x=40, y=788, width=_WRAP_BOX, height=24, label="wrap-Q-B-box-saf",
                   family=_WRAP_FONT, size=14, shape_autofit=True, panel_box=(0.0, 2.0, 172.0, 20.0)),
        doc.Button(text=t, x=40, y=832, width=_WRAP_BOX, height=24, label="wrap-Q-B-box",
                   family=_WRAP_FONT, size=14, panel_box=(0.0, 2.0, 172.0, 20.0)),
        doc.Button(text=t, x=40, y=876, width=_WRAP_BOX, height=24, label="wrap-Q-B-padneg",
                   family=_WRAP_FONT, size=14, pad=-1.0),
        doc.Button(text=t, x=40, y=920, width=_WRAP_BOX, height=24, label="wrap-Q-B-padneg-saf",
                   family=_WRAP_FONT, size=14, pad=-1.0, shape_autofit=True),
        doc.Button(text=t, x=40, y=964, width=_WRAP_BOX, height=24, label="wrap-R-B-prod",
                   family=_WRAP_FONT, size=14, shape_autofit=True,
                   panel_box=(0.0, 0.0, _WRAP_BOX, 24.0)),
        doc.Text(text="第一行\n第二行", x=40, y=1008, width=_WRAP_BOX, height=24,
                 label="wrap-R-nl-saf", family=_WRAP_FONT, size=14, shape_autofit=True),
        doc.Text(text=t, x=40, y=1052, width=_WRAP_BOX, height=24, label="wrap-R-center-saf",
                 family=_WRAP_FONT, size=14, align=1, shape_autofit=True),
    ]
    return doc.DesignSpec(frames=[doc.Frame(name="Home", width=800, height=1120,
                                            widgets=widgets)])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="从零生成 Axure RP 8 .rp")
    parser.add_argument("--out", default=os.path.join("output", "_axure_proto", "m2_min.rp"))
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--rects", type=int, default=1)
    parser.add_argument("--color", action="store_true",
                        help="给矩形显式填充/描边（结构未经真机验证，默认走样本同形的无覆盖样式）")
    parser.add_argument("--fonts", action="store_true",
                        help="M4 字体探针：分离「字体属性来自哪里」的六行对照页")
    parser.add_argument("--text", action="store_true",
                        help="M4 文字探针：改成一份带文字的固定页（忽略 --pages/--rects/--color）")
    parser.add_argument("--images", action="store_true",
                        help="M4 图片探针：一份带 PNG/JPEG/fit-to-image 的固定页")
    parser.add_argument("--wrap", action="store_true",
                        help="折行探针：零余量盒子 / AutoFitWidth 的单变量对照页（§9.11）")
    args = parser.parse_args(argv)

    if args.fonts:
        spec = build_font_spec()
    elif args.wrap:
        spec = build_wrap_spec()
    elif args.images:
        spec = build_image_spec()
    elif args.text:
        spec = build_text_spec()
    else:
        spec = build_spec(args.pages, args.rects, args.color)
    pages = doc.build(spec)
    template = writer.native_template()
    thumbs = {page.package_guid: thumbnail.render(frame)
              for page, frame in zip(pages, spec.frames)}
    members = writer.generate(template, pages, thumbnails=thumbs)
    report = writer.self_check(members)
    integrity = writer.integrity_check(members)
    path = writer.write_rp(members, args.out)

    print("template: native (widgetinfo %d B, thumbnail %d B)"
          % (len(template.widgetinfo), len(template.thumbnail)))
    if args.fonts or args.images or args.text or args.wrap:
        which = ("font" if args.fonts else "wrap" if args.wrap
                 else ("image" if args.images else "text"))
        print("spec: %s probe (%d widgets)"
              % (which, sum(len(f.widgets) for f in spec.frames)))
    else:
        print("spec: %d page(s), %d rect(s), color=%s"
              % (args.pages, args.rects, args.color))
    print("pages: " + ", ".join("%s(%s)" % (p.name, p.package_guid) for p in pages))
    print("members: %d" % len(members))
    for name in sorted(members, key=writer.member_order_key):
        print("  %-70s %6d B" % (name, len(members[name])))
    print("self-check: c1 %d/%d  stores %d/%d  pages %d  ok=%s"
          % (report["c1_ok"], report["c1"], report["stores_ok"], report["stores"],
             report["pages"], report["ok"]))
    print("integrity: pages %d  registered %d  ok=%s"
          % (integrity["pages"], integrity["registered"], integrity["ok"]))
    for err in integrity["errors"]:
        print("   - %s" % err)
    print("wrote %s (%d B)" % (path, os.path.getsize(path)))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
