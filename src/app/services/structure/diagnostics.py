# -*- coding: utf-8 -*-
"""DOM 结构诊断：量化 2.0 需要补的结构能力缺口。

采集结果只回答“抓到了什么”，不回答“页面用了哪些我们还不支持的结构”。
这份诊断在同一个页面上额外跑一次只读探针，输出两组数：

- `page`：页面里实际存在多少 grid / flex-wrap / open Shadow DOM / gradient /
  pseudo-element；
- `captured`：真正进入 `00_dom.json` 的节点里，各类结构还剩多少。

两组数之间的差额就是当前 DOM → Figma 链路的确定性缺口。诊断只读页面，
不改变 DOM、截图或渲染结果，也不参与路线决策。
"""
from __future__ import annotations

from typing import Any

from src.app.services.structure.frames import summarize_frame_inventory

DIAGNOSTICS_SCHEMA = 1
MAX_SAMPLES = 12

DOM_STRUCTURE_PROBE_JS = r"""
() => {
  const MAX_SAMPLES = 12;
  const counts = {
    lightElements: 0,
    shadowRoots: 0,
    shadowElements: 0,
    customElements: 0,
    gridElements: 0,
    inlineGridElements: 0,
    flexWrapElements: 0,
    gradientElements: 0,
    pseudoElements: 0,
    maxDepth: 0,
  };
  const samples = { grid: [], wrap: [], shadow: [], gradient: [], pseudo: [] };
  const desc = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const raw = (typeof el.className === 'string' ? el.className : '').trim();
    const cls = raw ? raw.split(/\s+/).filter(Boolean).slice(0, 2) : [];
    if (cls.length) s += '.' + cls.join('.');
    return s.slice(0, 120);
  };
  const push = (arr, el) => { if (arr.length < MAX_SAMPLES) arr.push(desc(el)); };
  const inspect = (el, depth, inShadow) => {
    if (depth > counts.maxDepth) counts.maxDepth = depth;
    let cs;
    try { cs = getComputedStyle(el); } catch (e) { return; }
    // 只统计“会参与渲染”的元素：采集端同样会跳过 display:none / 0×0 节点，
    // 两边口径一致，gap 才是真实缺口而不是隐藏 <style> 之类的噪声。
    let visible = cs.display !== 'none' && cs.visibility !== 'hidden'
      && cs.opacity !== '0';
    if (visible) {
      try {
        const r = el.getBoundingClientRect();
        visible = r.width >= 2 && r.height >= 2;
      } catch (e) { visible = false; }
    }
    if (visible) {
      if (inShadow) counts.shadowElements += 1;
      else counts.lightElements += 1;
      if (el.tagName && el.tagName.includes('-')) counts.customElements += 1;
    }
    const display = cs.display || '';
    if (visible && display === 'grid') {
      counts.gridElements += 1; push(samples.grid, el);
    }
    if (visible && display === 'inline-grid') {
      counts.inlineGridElements += 1; push(samples.grid, el);
    }
    if (visible && (display === 'flex' || display === 'inline-flex')
        && cs.flexWrap && cs.flexWrap !== 'nowrap') {
      counts.flexWrapElements += 1;
      push(samples.wrap, el);
    }
    if (visible && /gradient\(/i.test(cs.backgroundImage || '')) {
      counts.gradientElements += 1;
      push(samples.gradient, el);
    }
    if (!visible) return;
    for (const which of ['::before', '::after']) {
      let ps;
      try { ps = getComputedStyle(el, which); } catch (e) { continue; }
      const content = ps.content || 'none';
      // `content:""` 的 clearfix / 占位伪元素没有可见像素；必须把空字符串
      // 与真正的字形内容区分开，否则 Bootstrap .row 之类会虚报几十个缺口。
      const contentText = content.replace(/^["']|["']$/g, '').trim();
      const border = (parseFloat(ps.borderTopWidth) || 0)
        + (parseFloat(ps.borderRightWidth) || 0)
        + (parseFloat(ps.borderBottomWidth) || 0)
        + (parseFloat(ps.borderLeftWidth) || 0);
      const bgColor = (ps.backgroundColor || '').toLowerCase();
      const decorated = (content !== 'none' && content !== 'normal'
                         && contentText.length > 0)
        || (ps.backgroundImage && ps.backgroundImage !== 'none')
        || (bgColor && bgColor !== 'transparent' && bgColor !== 'rgba(0, 0, 0, 0)')
        || border > 0;
      if (decorated) { counts.pseudoElements += 1; push(samples.pseudo, el); break; }
    }
  };
  const walk = (el, depth, inShadow) => {
    inspect(el, depth, inShadow);
    let shadow = null;
    try { shadow = el.shadowRoot; } catch (e) {}
    if (shadow) {
      counts.shadowRoots += 1;
      push(samples.shadow, el);
      for (const child of Array.from(shadow.children || [])) {
        walk(child, depth + 1, true);
      }
    }
    for (const child of Array.from(el.children || [])) {
      walk(child, depth + 1, inShadow);
    }
  };
  if (document.documentElement) walk(document.documentElement, 0, false);
  return {
    counts: counts,
    samples: samples,
    url: location.href,
    // 关闭模式的 shadowRoot 对脚本不可见，无法与“没有 Shadow DOM”区分。
    closedShadowRootsObservable: false,
  };
}
"""


def summarize_captured_nodes(nodes: list[dict[str, Any]] | None) -> dict[str, Any]:
    """从真正落盘的 DOM 快照统计结构，回答“这些结构有没有进入渲染链路”。"""
    nodes = nodes or []
    grid = inline_grid = wrap = shadow = bg_image = with_parent = 0
    for node in nodes:
        display = str(node.get("display") or "").strip().lower()
        if display == "grid":
            grid += 1
        elif display == "inline-grid":
            inline_grid += 1
        if str(node.get("flexWrap") or "nowrap").strip().lower() != "nowrap":
            wrap += 1
        if node.get("shadow"):
            shadow += 1
        if node.get("bgImage"):
            bg_image += 1
        if node.get("pIdx") is not None:
            with_parent += 1
    return {
        "elements": len(nodes),
        "with_parent": with_parent,
        "grid": grid,
        "inline_grid": inline_grid,
        "flex_wrap": wrap,
        "shadow": shadow,
        "background_image": bg_image,
    }


def build_dom_diagnostics(probe: dict[str, Any] | None,
                          nodes: list[dict[str, Any]] | None,
                          url: str = "",
                          *,
                          frames: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """合并页面探针与落盘快照，产出可直接写文件的诊断对象。"""
    probe = probe or {}
    counts = probe.get("counts") or {}
    captured = summarize_captured_nodes(nodes)

    def as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    page_grid = as_int(counts.get("gridElements")) + as_int(counts.get("inlineGridElements"))
    page_wrap = as_int(counts.get("flexWrapElements"))
    page_shadow = as_int(counts.get("shadowElements"))
    page_gradient = as_int(counts.get("gradientElements"))
    page_pseudo = as_int(counts.get("pseudoElements"))
    frame_inventory = [
        dict(item) for item in (frames or []) if isinstance(item, dict)
    ]

    return {
        "schema": DIAGNOSTICS_SCHEMA,
        "url": probe.get("url") or url,
        "page": counts,
        "captured": captured,
        "frames": {
            "summary": summarize_frame_inventory(frame_inventory),
            "inventory": frame_inventory,
            "scope_rule": "recursive same-origin; cross-origin or inaccessible is opaque-frame",
        },
        # “抓不到”与“抓到了但画不出”是两类问题，分开报，避免把 grid 的缺口
        # 误记成采集失败。
        "capture_gaps": {
            "shadow": max(0, page_shadow - captured["shadow"]),
        },
        "unsupported": {
            # 已进入快照，但 layout_infer 会 bail 的布局。
            "grid": page_grid,
            "flex_wrap": page_wrap,
            # 尚未进入 DesignSpec 的视觉能力。
            "gradient": page_gradient,
            "pseudo": page_pseudo,
        },
        "samples": probe.get("samples") or {},
        "notes": {
            "closed_shadow_roots_observable": bool(
                probe.get("closedShadowRootsObservable")),
            "gradient_captured": "只统计 background-image 是否作为像素回填层采集；"
                                 "矢量渐变尚未进入 DesignSpec。",
            "pseudo_captured": "伪元素目前只参与图标判定，未作为独立图层采集。",
            "frame_scope": "仅同源且浏览器允许父文档访问的 frame 递归采集；"
                           "跨源、sandbox opaque origin 与不可访问 frame 保留边界证据。",
        },
    }
