# -*- coding: utf-8 -*-
"""Playwright 抓取：同一次会话产出截图 + DOM JSON，dsf=1 保证坐标对齐。"""

from __future__ import annotations
import json
import logging
import shutil
from urllib.parse import unquote, urlparse
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.config import Config

from src.app import tuning
from src.app.services.structure.diagnostics import (
    DOM_STRUCTURE_PROBE_JS,
    build_dom_diagnostics,
)
from src.app.services.structure.capture_state import (
    classify_capture_navigation,
    state_window_is_stable,
)
from src.app.services.structure.capture_bundle import write_capture_bundle
from src.app.services.structure.font_bundle import build_font_manifest
from src.app.services.structure.frames import (
    capture_frame_state,
    collect_frame_dom,
    summarize_frame_inventory,
)
from src.app.services.structure.font_provenance import PlatformFontProbe
from src.app.services.structure.layer_tree import build_layer_tree
from src.app.services.structure.navigation_timeline import NavigationTimeline

logger = logging.getLogger(__name__)

DEFAULT_BROWSER_ENGINE = "chromium"
SUPPORTED_BROWSER_ENGINES = ("chromium", "webkit", "firefox")


def normalize_browser_engine(value: str | None) -> str:
    engine = str(value or DEFAULT_BROWSER_ENGINE).strip().lower()
    if engine not in SUPPORTED_BROWSER_ENGINES:
        raise ValueError(
            f"unsupported Playwright browser engine: {value!r}; "
            f"expected one of {SUPPORTED_BROWSER_ENGINES}"
        )
    return engine


LOGIN_PROMPT = (
    "\n请在已打开的浏览器窗口里完成登录，进入目标页面后回到这里按回车，"
    "我会把登录态（cookie / localStorage）保存到 JSON 文件。\n> "
)

# 页面状态：URL 采集后先回答“我们到底抓到了什么”，再决定走 DOM 还是截图降级。
PAGE_STATE_CONTENT = "content"
PAGE_STATE_SOFT_BLOCK = "soft_block"
PAGE_STATE_HARD_LOGIN = "hard_login"

# 登录/拦截关键词只做“信号”，最终判定还要结合密码框、正文量与 HTTP 状态。
# 单独的“登录”二字在内容页页头很常见，不能直接判成登录墙。
LOGIN_PATH_SEGMENTS = (
    "login",
    "signin",
    "sign-in",
    "sign_in",
    "passport",
    "sso",
    "auth",
)
LOGIN_TITLE_MARKERS = (
    "login",
    "sign in",
    "log in",
    "signin",
    "sign-in",
    "登录",
    "登陆",
    "账号登录",
    "用户登录",
)
LOGIN_BODY_MARKERS = (
    "密码",
    "password",
    "扫码登录",
    "二维码",
    "手机号",
    "验证码",
    "账号登录",
    "sign in",
    "log in",
)
# 比 LOGIN_BODY_MARKERS 更明确指向“这就是登录页”的词：二维码/账号登录页
# 往往没有密码框，正文里还可能同时出现“验证码”，不能因此误判成反爬拦截页。
LOGIN_STRONG_BODY_MARKERS = (
    "扫码登录",
    "二维码登录",
    "账号登录",
    "用户登录",
    "密码登录",
    "手机号登录",
    "微信登录",
    "qq登录",
    "登录后",
    "请登录",
    "立即登录",
    "马上登录",
    "password",
    "sign in to continue",
    "log in to continue",
    "please sign in",
    "please log in",
)
BLOCK_MARKERS = (
    "captcha",
    "验证码",
    "人机验证",
    "安全验证",
    "访问验证",
    "滑动验证",
    "cloudflare",
    "just a moment",
    "checking your browser",
    "verify you are human",
    "verification required",
    "unusual traffic",
    "too many requests",
    "access denied",
    "403 forbidden",
    "are you a robot",
    "robot check",
    "请稍候",
    "正在验证",
    "环境异常",
    "访问受限",
    "请求过于频繁",
    "网络异常",
    "拒绝访问",
)

PROBE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const passwordInputs = Array.from(document.querySelectorAll('input[type=password]'))
    .filter(visible).length;
  const bodyText = ((document.body && document.body.innerText) || '').trim();
  const captchaSelectors = [
    'iframe[src*="captcha" i]', '[class*="captcha" i]', '[id*="captcha" i]',
    '[class*="geetest" i]', '[id*="geetest" i]', '[class*="turnstile" i]',
    '[class*="cf-challenge" i]', '#challenge-form', '#challenge-stage',
    '[class*="nc_1" i]', '[id*="nc_1" i]',
  ];
  let captcha = false;
  for (const sel of captchaSelectors) {
    try {
      const el = document.querySelector(sel);
      if (el && visible(el)) { captcha = true; break; }
    } catch (e) {}
  }
  return {
    finalUrl: location.href,
    title: document.title || '',
    passwordInputs,
    hasForm: document.querySelectorAll('form').length > 0,
    elementCount: document.querySelectorAll('*').length,
    imageCount: document.querySelectorAll('img,svg,canvas,picture').length,
    bodyTextLen: bodyText.length,
    bodyTextSample: bodyText.slice(0, 4000),
    hasCaptchaElement: captcha,
  };
}
"""

DOM_JS = r"""
(fontProbePrefix = '') => {
  const out = [];
  const genericFontFamilies = new Set([
    'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy',
    'system-ui', 'ui-serif', 'ui-sans-serif', 'ui-monospace',
  ]);
  const fontProbeSeen = new Set();
  const fontMetricsCanvas = document.createElement('canvas');
  const fontMetricsContext = fontMetricsCanvas.getContext('2d');
  const fontMetricsFor = (text, cs) => {
    if (!fontMetricsContext) return null;
    try {
      fontMetricsContext.font = [
        cs.fontStyle || 'normal',
        cs.fontWeight || '400',
        cs.fontSize || '16px',
        cs.fontFamily || 'sans-serif',
      ].join(' ');
      const metrics = fontMetricsContext.measureText(String(text || 'Mg'));
      let ascent = Number(metrics.fontBoundingBoxAscent);
      let descent = Number(metrics.fontBoundingBoxDescent);
      if (!Number.isFinite(ascent) || !Number.isFinite(descent)
          || ascent + descent <= 0) {
        ascent = Number(metrics.actualBoundingBoxAscent) || 0;
        descent = Number(metrics.actualBoundingBoxDescent) || 0;
      }
      if (ascent + descent <= 0) return null;
      return {
        ascent: round2(ascent),
        descent: round2(descent),
        method: 'canvas-font-metrics',
      };
    } catch (e) {
      return null;
    }
  };
  const isGenericFontStack = (value) => {
    const families = String(value || '')
      .split(',')
      .map((item) => item.trim().replace(/^["']|["']$/g, '').toLowerCase())
      .filter(Boolean);
    return families.length > 0
      && families.every((family) => genericFontFamilies.has(family));
  };
  const SVG_NS = 'http://www.w3.org/2000/svg';
  // These SVG containers define paint geometry but do not render their children.
  // WebKit can report a non-zero rect for <clipPath><rect> while Chromium reports
  // 0x0; excluding the container keeps the visible DOM capture engine-neutral.
  const NON_RENDERED_SVG_CONTAINERS = new Set([
    'defs', 'clipPath', 'mask', 'symbol', 'pattern',
    'linearGradient', 'radialGradient', 'filter', 'marker'
  ]);
  const isNonRenderedSvgContainer = (el) => {
    if (!el || el.namespaceURI !== SVG_NS) return false;
    return NON_RENDERED_SVG_CONTAINERS.has(el.localName);
  };
  // 元素 → 它在 out 里的下标。querySelectorAll('*') 是文档序，祖先必先于后代入表，
  // 所以查表即得"最近的已采集祖先"，据此重建容器→子元素的树（Auto Layout 推断的
  // 输入，见 src/app/services/rendering/layout_infer.py）。
  const indexOf = new WeakMap();
  const round2 = (v) => Math.round(v * 100) / 100;
  const CONTENT_SIZED = new Set(['auto', 'min-content', 'max-content', 'fit-content']);
  // 声明为"内容驱动"的轴：getComputedStyle 已经把 auto/min-content 解析成宽高像素了，
  // 只有 Typed OM（computedStyleMap）还留着关键字。返回 'w' / 'h' / 'wh' / null。
  // 只采"关键字有没有"，父级上下文（flex 主轴/交叉轴、stretch 与否）的判断留给
  // 推断器做——采集端保持只读事实。
  const contentSizedAxes = (el) => {
    if (typeof el.computedStyleMap !== 'function') return null;
    const view = el.ownerDocument && el.ownerDocument.defaultView;
    const KW = view ? view.CSSKeywordValue : undefined;
    if (!KW) return null;
    let map;
    try { map = el.computedStyleMap(); } catch (e) { return null; }
    const hit = (prop) => {
      let v;
      try { v = map.get(prop); } catch (e) { return false; }
      return v instanceof KW && CONTENT_SIZED.has(v.value);
    };
    const w = hit('width'), h = hit('height');
    return w && h ? 'wh' : w ? 'w' : h ? 'h' : null;
  };
  // 祖先裁剪矩形：overflow ≠ visible 的祖先会把后代裁掉（antd 表格的横向滚动容器
  // 就是这种——采购表横向内容宽到 3329px，滚出可视区的“工艺/线别”列在
  // getBoundingClientRect 里仍然报着布局矩形）。不采这个信息，直出就会把滚出列画
  // 到容器外（真实页 x=1348..1452 漏出一截尾巴）。按父链记忆化求所有裁剪祖先
  // client rect（= padding box，已扣 border 与滚动条）的交集；无裁剪祖先返回 null。
  // 根元素（html/body）除外：截图是 full_page（视口会被撑到文档尺寸），而根元素的
  // client rect 在采集时只有视口大小——拿它当裁剪边会把文档溢出区里**截图
  // 里真实可见**的内容（真实页底部那个 © 图标）误删。
  const clipCache = new WeakMap();
  // 逻辑父链：Shadow DOM 里 element 的 parentElement 是 null（挂在 ShadowRoot 下），
  // 直接沿 parentElement 上溯会断在组件边界。遍历时把「宿主 → 影子子节点」也记进
  // 这张表，裁剪矩形、父子层级和 Auto Layout 推断就能跨 Shadow 边界继续成立。
  const logicalParentOf = new WeakMap();
  const clipOf = (el) => {
    const hit = clipCache.get(el);
    if (hit !== undefined) return hit;
    const p = logicalParentOf.get(el) || el.parentElement;
    let res = p ? clipOf(p) : null;
    if (p instanceof Element
        && p !== document.documentElement && p !== document.body) {
      const pcs = getComputedStyle(p);
      if (pcs.overflowX !== 'visible' || pcs.overflowY !== 'visible') {
        const pr = p.getBoundingClientRect();
        const bl = parseFloat(pcs.borderLeftWidth) || 0;
        const bt = parseFloat(pcs.borderTopWidth) || 0;
        const bx0 = pr.left + bl, by0 = pr.top + bt;
        const bx1 = bx0 + p.clientWidth, by1 = by0 + p.clientHeight;
        res = res ? [Math.max(res[0], bx0), Math.max(res[1], by0),
                     Math.min(res[2], bx1), Math.min(res[3], by1)]
                  : [bx0, by0, bx1, by1];
      }
    }
    clipCache.set(el, res);
    return res;
  };
  const pageBg = document.body instanceof Element
    ? getComputedStyle(document.body).backgroundColor
    : 'rgba(0, 0, 0, 0)';
  const richInlineConsumed = new WeakSet();
  const richRunStyle = (node) => {
    const s = getComputedStyle(node);
    return {
      fontSize: s.fontSize,
      fontWeight: s.fontWeight,
      fontStyle: s.fontStyle,
      fontFamily: s.fontFamily,
      textColor: s.color,
      letterSpacing: s.letterSpacing,
      textDecoration: s.textDecorationLine,
    };
  };
  const inlineTextOnly = (el) => {
    const s = getComputedStyle(el);
    if (!['inline', 'inline-block'].includes(s.display)) return false;
    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') {
      return false;
    }
    const bg = (s.backgroundColor || '').replace(/\s+/g, '');
    const hasPaint = bg && bg !== 'transparent'
      && bg !== 'rgba(0,0,0,0)' && bg !== 'rgb(0,0,0,0)';
    if (hasPaint || (parseFloat(s.borderTopWidth) || 0) > 0
        || (parseFloat(s.borderRightWidth) || 0) > 0
        || (parseFloat(s.borderBottomWidth) || 0) > 0
        || (parseFloat(s.borderLeftWidth) || 0) > 0) {
      return false;
    }
    for (const child of el.childNodes) {
      if (child.nodeType === 3) continue;
      if (child.nodeType !== 1 || !inlineTextOnly(child)) return false;
    }
    return true;
  };
  const flattenInlineTag = (el) => /^(CODE|KBD|SAMP|VAR|SUB|SUP)$/i.test(el.tagName);
  const inlineImageBoundaryNode = (node) => {
    if (!node || !['IMG', 'SVG'].includes(node.tagName)) return false;
    const style = getComputedStyle(node);
    if (!['inline', 'inline-block'].includes(style.display)) return false;
    const parent = node.parentElement;
    if (!parent) return false;
    return Array.from(parent.childNodes).some(
      (child) => child.nodeType === 3 && (child.textContent || '').trim(),
    );
  };
  const semanticTextRoleHint = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea') return 'input-value';
    if (tag === 'figcaption' || tag === 'caption') return 'caption';
    let current = el;
    while (current) {
      const name = current.tagName.toLowerCase();
      const role = (current.getAttribute('role') || '').toLowerCase();
      if (/^h[1-6]$/.test(name) || role === 'heading') return 'heading';
      if (name === 'button' || role === 'button') return 'button-label';
      current = current.parentElement;
    }
    return '';
  };
  const flattenedInlineText = (el) => {
    if (/^(IMG|SVG|VIDEO|CANVAS|INPUT|BUTTON|SELECT|TEXTAREA)$/i.test(el.tagName)) {
      return false;
    }
    const s = getComputedStyle(el);
    if (!['inline', 'inline-block'].includes(s.display)) return false;
    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') {
      return false;
    }
    // 行内代码、上下标等伪样式不再单独落层：并入父段落文本流，避免离线输出
    // 重新排版后这些窄层压住正文。图片、控件和块级子树仍保持独立结构。
    let hasFlattenedDescendant = flattenInlineTag(el);
    for (const child of el.childNodes) {
      if (child.nodeType === 3) continue;
      if (child.nodeType !== 1) return false;
      if (flattenedInlineText(child)) {
        hasFlattenedDescendant = true;
      } else if (!inlineTextOnly(child)) {
        return false;
      }
    }
    return hasFlattenedDescendant;
  };
  const collectRichRuns = (el) => {
    const runs = [];
    const parentStyle = richRunStyle(el);
    const visit = (node, flattenStyle) => {
      if (node.nodeType === 3) {
        const value = node.textContent || '';
        if (value) {
          runs.push({
            kind: 'text',
            text: value,
            style: flattenStyle
              ? parentStyle
              : richRunStyle(node.parentElement || el),
          });
        }
        return;
      }
      if (node.nodeType !== 1 || node === el) return;
      if (inlineImageBoundaryNode(node)) {
        runs.push({
          kind: 'inline-image',
          text: '',
          style: richRunStyle(node),
          tag: node.tagName.toLowerCase(),
          assetSrc: String(
            node.currentSrc || node.src || node.getAttribute('src') || '',
          ).slice(0, 20000),
        });
        return;
      }
      const flatten = flattenedInlineText(node);
      if (!inlineTextOnly(node) && !flatten) return;
      richInlineConsumed.add(node);
      for (const child of node.childNodes) visit(child, flattenStyle || flatten);
    };
    for (const child of el.childNodes) visit(child, false);
    while (runs.length && runs[0].kind === 'text' && !runs[0].text.trim()) {
      runs.shift();
    }
    while (
      runs.length
      && runs[runs.length - 1].kind === 'text'
      && !runs[runs.length - 1].text.trim()
    ) {
      runs.pop();
    }
    if (runs.length && runs[0].kind === 'text') {
      runs[0].text = runs[0].text.replace(/^\s+/, '');
    }
    if (runs.length && runs[runs.length - 1].kind === 'text') {
      runs[runs.length - 1].text = runs[runs.length - 1].text.replace(/\s+$/, '');
    }
    const filtered = runs.filter(
      (run) => run.text || run.kind === 'inline-image',
    );
    let offset = 0;
    return filtered.map((run) => {
      const start = offset;
      offset += run.text.length;
      return {
        kind: run.kind,
        start,
        end: offset,
        text: run.text,
        style: run.style,
        ...(run.assetSrc ? { assetSrc: run.assetSrc } : {}),
        ...(run.tag ? { tag: run.tag } : {}),
      };
    });
  };
  const ellipsizeText = (value, el, cs) => {
    const available = Math.max(
      0,
      el.clientWidth - (parseFloat(cs.paddingLeft) || 0)
        - (parseFloat(cs.paddingRight) || 0),
    );
    if (available <= 0 || !value) return value;
    const context = document.createElement('canvas').getContext('2d');
    if (!context) return value;
    context.font = `${cs.fontStyle || 'normal'} ${cs.fontWeight || '400'} `
      + `${cs.fontSize || '16px'} ${cs.fontFamily || 'sans-serif'}`;
    if (context.measureText(value).width <= available) return value;
    let lo = 0, hi = value.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (context.measureText(value.slice(0, mid) + '…').width <= available) {
        lo = mid;
      } else {
        hi = mid - 1;
      }
    }
    return value.slice(0, lo).trimEnd() + '…';
  };
  const styleSnapshotFor = (el, cs) => {
    const snapshot = {};
    const put = (key, value) => {
      if (value !== null && value !== undefined && value !== '') {
        snapshot[key] = value;
      }
    };
    if (cs.display && cs.display !== 'block') put('display', cs.display);
    if (cs.position && cs.position !== 'static') put('position', cs.position);
    const inset = {};
    for (const side of ['top', 'right', 'bottom', 'left']) {
      const value = cs[side];
      if (value && value !== 'auto') inset[side] = value;
    }
    if (Object.keys(inset).length) snapshot.inset = inset;
    if (cs.visibility && cs.visibility !== 'visible') {
      put('visibility', cs.visibility);
    }
    if (cs.direction && cs.direction !== 'ltr') put('direction', cs.direction);
    if (cs.flexDirection && cs.flexDirection !== 'row') {
      put('flexDirection', cs.flexDirection);
    }
    if (cs.flexWrap && cs.flexWrap !== 'nowrap') put('flexWrap', cs.flexWrap);
    if (cs.justifyContent && cs.justifyContent !== 'normal') {
      put('justifyContent', cs.justifyContent);
    }
    if (cs.alignItems && cs.alignItems !== 'normal') {
      put('alignItems', cs.alignItems);
    }
    if (cs.alignSelf && cs.alignSelf !== 'auto') put('alignSelf', cs.alignSelf);
    if ((parseFloat(cs.rowGap) || 0) > 0) put('rowGap', cs.rowGap);
    if ((parseFloat(cs.columnGap) || 0) > 0) put('columnGap', cs.columnGap);
    if (cs.gridTemplateColumns && cs.gridTemplateColumns !== 'none') {
      put('gridTemplateColumns', cs.gridTemplateColumns);
    }
    if (cs.gridTemplateRows && cs.gridTemplateRows !== 'none') {
      put('gridTemplateRows', cs.gridTemplateRows);
    }
    if (cs.transform && cs.transform !== 'none') {
      put('transform', cs.transform);
      if (cs.transformOrigin) put('transformOrigin', cs.transformOrigin);
    }
    if (cs.textDecorationLine && cs.textDecorationLine !== 'none') {
      put('textDecorationLine', cs.textDecorationLine);
    }
    const customProperties = {};
    for (let i = 0; i < cs.length; i++) {
      const name = cs.item(i);
      if (!name || !name.startsWith('--')) continue;
      const value = String(cs.getPropertyValue(name) || '').trim();
      if (value) customProperties[name] = value;
    }
    if (Object.keys(customProperties).length) {
      snapshot.customProperties = customProperties;
    }
    return snapshot;
  };
  const pseudoStyleSnapshot = (el, which) => {
    let cs;
    try {
      cs = getComputedStyle(el, which);
    } catch (e) {
      return null;
    }
    const content = String(cs.content || 'none').trim();
    if (!content || content === 'none' || content === 'normal') return null;
    return {
      content: content,
      display: cs.display,
      position: cs.position,
      color: cs.color,
      backgroundColor: cs.backgroundColor,
      font: cs.font,
      width: cs.width,
      height: cs.height,
      transform: cs.transform,
      zIndex: cs.zIndex,
    };
  };
  const collect = (el, inShadow) => {
    if (richInlineConsumed.has(el)) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    // 开放影子根里的元素同样算子元素：自定义组件宿主自己没有 light DOM 子节点，
    // 但视觉内容全在 shadowRoot 里，不能因此被当成叶子。
    let shadow = null;
    try { shadow = el.shadowRoot; } catch (e) {}
    const hasElementChildren = el.childElementCount > 0
      || !!(shadow && shadow.childElementCount > 0);
    // 直接文本节点（不含后代文本）。叶子取 textContent；“混合内容”节点（既有子元素、
    // 又有直接文本，如 antd 操作列的 <a>编辑<i class="anticon"/></a>）原先整个丢文本：
    // childElementCount>0 就让 text=''，而“编辑”又不是任何叶子元素的文本，最终 SoM 里
    // 根本没有这两个字。只取直接子文本、不含后代文本，父子不会重复采（父取自己的、
    // 子取子的）。
    const ownNodes = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3 && (n.textContent || '').trim());
    const ownText = ownNodes.map((n) => n.textContent || '').join('').trim();
    let richRuns = null;
    if (hasElementChildren && ownText
        && Array.from(el.children).some(
          (child) => inlineTextOnly(child) || flattenedInlineText(child)
            || inlineImageBoundaryNode(child),
        )) {
      const collected = collectRichRuns(el);
      if (collected.length) {
        richRuns = collected;
      }
    }
    let rawText = hasElementChildren ? ownText : (el.textContent || '').trim();
    if (richRuns) {
      rawText = richRuns.map((run) => run.text).join('').trim();
    }
    // <input> 没有子节点，可见文本来自 value；只取会按文本排版的类型
    // （text/search/... 与不带 type）。checkbox/radio 的 value="on" 与密码框的
    // 圆点都不是可见文本，采进来会污染 text。
    const textTypes = /^(|text|search|email|number|tel|url|date|datetime-local|month|week|time)$/;
    const isTextField = el.tagName === 'TEXTAREA'
      || (el.tagName === 'INPUT' && textTypes.test((el.getAttribute('type') || '').toLowerCase()));
    const fieldValue = (isTextField && typeof el.value === 'string')
      ? el.value.trim().slice(0, 200) : '';
    // 可见文本：叶子元素取 textContent，输入类元素退回 value（textarea 的可见内容
    // 通常只存在于 value 里），两者都没有才是空文本。
    const visible = rawText || fieldValue;
    const hasText = visible.length > 0;
    const placeholder = (el.getAttribute('placeholder') || '').trim().slice(0, 200);
    // 文本排版盒（textBox）：输入类是“内容盒里放一行行框”的位置（placeholder/value
    // 都从该盒左沿起排，按元素盒落字会整体偏出 border+padding 的宽度）；混合内容
    // 节点是它自己那几段文本的 Range 行框。
    let textBox = null;
    let textRuns = null;
    // 叶子块级文本的“可排盒”：折行仍要按盒子宽度正常折，与上面的“行框”
    // （一段文字已经排好的一行）区别开，provider 用它决定是否折行。
    let textFlow = false;
    if (isTextField) {
      const pl = parseFloat(cs.paddingLeft) || 0;
      const pr = parseFloat(cs.paddingRight) || 0;
      const pt = parseFloat(cs.paddingTop) || 0;
      const pb = parseFloat(cs.paddingBottom) || 0;
      const cw = el.clientWidth - pl - pr;
      const ch = el.clientHeight - pt - pb;
      const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) || 0;
      const boxH = (ch > 0 && lh > 0 && lh < ch) ? lh : ch;
      textBox = [Math.round(r.x + el.clientLeft + pl),
                 Math.round(r.y + el.clientTop + pt + (ch - boxH) / 2),
                 Math.round(cw), Math.round(boxH)];
    }
    else if (hasElementChildren && ownText) {
      // “混合内容”节点的文本排版盒：按**文本运行**分段量 Range 行框——相邻的直接文本
      // 节点算一段，被子元素隔开就是两段（如 跳至<input/>页：一段“跳至”、一段“页”）。
      // 元素盒可能比一行高很多（大容器里一段游离直接文本），而输出端的基线按
      // “行框中心 + 0.375em”估——拿元素盒去估会飘到容器中部。textBox 取第一段（单段
      // 时就是它本身，与老版本一致）；多段时另带 textRuns，供 provider 逐段成元素：
      // 一段文本只能画一次，拼成一个字符串画在合并框里第二段的位置必然错。
      const runBoxes = [];
      try {
        const groups = [];
        let group = [];
        for (const n of el.childNodes) {
          if (n.nodeType === 3 && (n.textContent || '').trim()) group.push(n);
          else if (group.length) { groups.push(group); group = []; }
        }
        if (group.length) groups.push(group);
        for (const grp of groups) {
          const rng = document.createRange();
          rng.setStartBefore(grp[0]);
          rng.setEndAfter(grp[grp.length - 1]);
          const b = rng.getBoundingClientRect();
          if (b.width < 1 || b.height < 1) continue;
          runBoxes.push([grp.map((n) => n.textContent || '').join(''),
                         [Math.round(b.x), Math.round(b.y),
                          Math.round(b.width), Math.round(b.height)]]);
        }
      } catch (e) {}
      if (runBoxes.length) {
        textBox = runBoxes[0][1];
        if (runBoxes.length > 1) textRuns = runBoxes;
      }
    }
    else if (!hasElementChildren && rawText) {
      // 叶子文本的“文本行框”：块级盒与浮动元素同行时，盒子的 getBoundingClientRect
      // 仍是整块宽度（左缘落在浮动块之下），真实行框却被推到浮动块右侧——输出端按
      // 盒子左缘落字会整体左移、压到浮动图上（dushu 卡片作者/简介实测左移 162px）。
      // 判据用**元素盒（边框盒）左缘** `r.left`，不用内容盒左缘：输出端就是按元素盒
      // 落字的，所以 padding-left 造成的偏移同样得带 textBox——`rec.padding` 只在
      // `isContainer` 分支里记，**叶子上的 padding 整批丢**，dushu 卡片作者行
      // （`.bookauthor`，padding-left: 8px）实测因此左移 8px、下移 2px。
      // 只在行框左缘确实偏离元素盒时才带 textBox（否则近 500 个叶子全带、体积
      // 翻倍）；宽度取“内容盒右缘 - 行框左缘”（块级盒剩余可排宽度），不用 Range
      // 的并集宽度——短行只有几个字宽，输出端按它折行会把整段重新折错。
      const ta = (cs.textAlign || '').toLowerCase();
      if ((ta === '' || ta === 'start' || ta === 'left' || ta === 'justify')
          && (cs.direction || 'ltr') !== 'rtl'
          && !(parseFloat(cs.textIndent) > 0)) {
        try {
          const rng = document.createRange();
          rng.selectNodeContents(el);
          const b = rng.getBoundingClientRect();
          const brw = parseFloat(cs.borderRightWidth) || 0;
          const pr = parseFloat(cs.paddingRight) || 0;
          const contentRight = r.left + r.width - brw - pr;
          if (b.width > 1 && b.height > 1 && b.left > r.left + 1
              && contentRight - b.left > 2) {
            textBox = [Math.round(b.left), Math.round(b.top),
                       Math.round(contentRight - b.left), Math.round(b.height)];
            textFlow = true;
          }
        } catch (e) {}
      }
    }
    // 「第一行行框」+ 行数：给输出端一个真实落字基准（Axure 出口用，见
    // 归档文档 axure_rp8_plan.md §9.21）。发布端把文字面板在控件盒里**垂直居中**
    // （`#uN_text{top:(控件高-行盒高)/2}`），控件高与真实行盒高差了多少就整块挪多少；
    // IR 只有元素盒时无从知道真实行盒落在哪，1px 的差就永久留在字形上。
    // 只量**自身的直接文本节点**（叶子就是整段；混合内容节点是它自己那几段），与
    // textBox / textRuns 同一口径；量到的记第一行行框 + 行数，多行没有"一行"可对齐。
    // <input> 的可见文本来自 value、没有文本节点，自然量不到 —— 输入框不在本机制内。
    let textEmBox = null, textEmLines = 0, textBaseline = null;
    let textLines = null;
    if (ownNodes.length) {
      try {
        const lastText = ownNodes[ownNodes.length - 1];
        const emRange = document.createRange();
        emRange.setStart(ownNodes[0], 0);
        emRange.setEnd(lastText, (lastText.textContent || '').length);
        const emRects = emRange.getClientRects();
        const emRect = emRects.length ? emRects[0] : null;
        if (emRect && emRect.width >= 1 && emRect.height >= 1) {
          textEmBox = [Math.round(emRect.left), Math.round(emRect.top),
                       Math.round(emRect.width), Math.round(emRect.height)];
          textEmLines = emRects.length;
          const metrics = fontMetricsFor(visible, cs);
          if (metrics) {
            textBaseline = {
              y: round2(emRect.top + metrics.ascent),
              ascent: metrics.ascent,
              descent: metrics.descent,
              method: metrics.method,
              lineCount: emRects.length,
            };
          }
        }
      } catch (e) {}
    }
    // Inputs and textareas have no text nodes, so their value/placeholder cannot
    // use Range.getClientRects(). Their content box already identifies the one
    // browser line; pair it with the same Canvas font metrics used for text nodes.
    if (isTextField && !textEmBox && textBox && (fieldValue || placeholder)) {
      const metrics = fontMetricsFor(fieldValue || placeholder, cs);
      if (metrics) {
        textEmBox = Array.from(textBox);
        textEmLines = 1;
        textBaseline = {
          y: round2(textBox[1] + metrics.ascent),
          ascent: metrics.ascent,
          descent: metrics.descent,
          method: metrics.method,
          lineCount: 1,
        };
      }
    }
    // 多行叶子文本的真实分行：逐字符 Range 按 top 分组成行。
    // 这是浏览器自己的换行结果，输出端可直接复用，避免离线字体估宽产生不同断点。
    if (textEmLines >= 1 && ownNodes.length === 1 && !hasElementChildren) {
      try {
        const textNode = ownNodes[0];
        const raw = textNode.data || '';
        const rng = document.createRange();
        const lines = [];
        let current = null;
        for (let i = 0; i < raw.length;) {
          const cp = raw.codePointAt(i);
          const step = cp > 0xFFFF ? 2 : 1;
          rng.setStart(textNode, i);
          rng.setEnd(textNode, i + step);
          const cr = rng.getBoundingClientRect();
          const hasRect = cr.width >= 0.5 && cr.height >= 0.5;
          const top = hasRect ? cr.top : (current ? current.top : null);
          if (top !== null && (!current || Math.abs(top - current.top) > 1.0)) {
            if (current) lines.push(current);
            current = {
              top,
              text: '',
              x0: hasRect ? cr.left : 0,
              y0: hasRect ? cr.top : 0,
              x1: hasRect ? cr.right : 0,
              y1: hasRect ? cr.bottom : 0,
            };
          }
          if (current) {
            current.text += raw.slice(i, i + step);
            if (hasRect) {
              current.x0 = Math.min(current.x0, cr.left);
              current.y0 = Math.min(current.y0, cr.top);
              current.x1 = Math.max(current.x1, cr.right);
              current.y1 = Math.max(current.y1, cr.bottom);
            }
          }
          i += step;
        }
        if (current) lines.push(current);
        const clean = lines
          .map((line) => {
            const metrics = fontMetricsFor(line.text, cs);
            return {
              text: line.text.trim(),
              box: [
                Math.round(line.x0),
                Math.round(line.y0),
                Math.round(line.x1 - line.x0),
                Math.round(line.y1 - line.y0),
              ],
              ...(metrics ? {
                baseline: {
                  y: round2(line.y0 + metrics.ascent),
                  ascent: metrics.ascent,
                  descent: metrics.descent,
                  method: metrics.method,
                },
              } : {}),
            };
          })
          .filter((line) => line.text && line.box[2] > 0 && line.box[3] > 0);
        if (clean.length > 1
            || (clean.length === 1 && raw.trim().length > 40)) {
          textLines = clean;
        }
      } catch (e) {}
    }
    // placeholder 的颜色来自 ::placeholder 伪元素，与输入态文字色不同（antd 灰字）。
    let placeholderColor = '';
    if (placeholder) {
      try { placeholderColor = getComputedStyle(el, '::placeholder').color; } catch (e) {}
    }
    // 图标字体（anticon / el-icon / iconfont …）把字形映射到私有区码位，或用 ::before
    // 注入字形：截图上是小图标，采成文本只会得到乱码/豆腐块。标出来交给 provider 走
    // “按 bbox 裁原图像素”的同一回填链（与 img/svg 一致）。
    const puaFree = (s) => Array.from(s || '').filter((ch) => {
      const cp = ch.codePointAt(0);
      return !((cp >= 0xE000 && cp <= 0xF8FF) || (cp >= 0xF0000 && cp <= 0xFFFFD)
               || (cp >= 0x100000 && cp <= 0x10FFFD));
    }).join('').trim();
    const hasPseudoGlyph = (which) => {
      let c = '';
      try { c = getComputedStyle(el, which).content || ''; } catch (e) { return false; }
      if (!c || c === 'none' || c === 'normal') return false;
      return c.replace(/^["']|["']$/g, '').trim().length > 0;
    };
    let iconBox = false;
    if (!hasElementChildren && r.width <= 48 && r.height <= 48) {
      const leafText = (el.textContent || '').trim();
      iconBox = (leafText.length > 0 && puaFree(leafText).length === 0)
                || (leafText.length === 0 && (hasPseudoGlyph('::before')
                                             || hasPseudoGlyph('::after')));
    }
    // 图标/图片的 DOM 标识：图标字体与组件库会直接标注元素（class 带 icon/anticon/
    // iconfont，或 type="icon"、role="img"）。有标识就不必靠像素猜——DOM 路线据此
    // 自动判成图标走像素回填，不需要用户框选。
    const clsRaw = (typeof el.className === 'string' ? el.className : '').trim();
    const elType = (el.getAttribute('type') || '').trim();
    const roleAttr = (el.getAttribute('role') || '').trim().toLowerCase();
    const iconHint = /(^|[\s_-])(icon|anticon|iconfont|glyphicon|fa-|el-icon|material-icons)/.test(clsRaw.toLowerCase())
                     || elType.toLowerCase() === 'icon'
                     || roleAttr === 'img';
    if (!iconBox && !hasElementChildren && iconHint
        && (el.textContent || '').trim().length === 0) {
      iconBox = true;
    }
    // CSS 背景图（sprite 图标 / 照片层）：DOM 自己就能判出来，按 bbox 裁原图像素即可。
    // 只在“自身没有可见文本、也没有子元素”时打标：带文字的卡片连字一起裁会重复画。
    const bgImage = !hasText && !hasElementChildren
                    && /url\(/i.test(cs.backgroundImage || '');
    const bgUrls = [];
    {
      const rawBg = cs.backgroundImage || '';
      const bgRe = /url\((['"]?)(.*?)\1\)/gi;
      let bgMatch;
      while ((bgMatch = bgRe.exec(rawBg)) && bgUrls.length < 4) {
        const url = (bgMatch[2] || '').trim();
        if (url) bgUrls.push(url.slice(0, 20000));
      }
    }
    const backgroundLayers = [];
    {
      const rawBg = String(cs.backgroundImage || '');
      const sizes = String(cs.backgroundSize || '').split(',');
      const positions = String(cs.backgroundPosition || '').split(',');
      const repeats = String(cs.backgroundRepeat || '').split(',');
      if (/gradient\(/i.test(rawBg)) {
        backgroundLayers.push({
          kind: 'gradient',
          css: rawBg.slice(0, 4000),
        });
      }
      bgUrls.forEach((url) => {
        const layerIndex = backgroundLayers.length;
        backgroundLayers.push({
          kind: 'image',
          source: url,
          size: String(sizes[layerIndex] || sizes[0] || 'auto').trim(),
          position: String(
            positions[layerIndex] || positions[0] || '0% 0%',
          ).trim(),
          repeat: String(repeats[layerIndex] || repeats[0] || 'repeat').trim(),
        });
      });
    }
    // 非均匀边框（表格行的 1px 分隔线：四边里只有 1~2 边有，简写作 "0px 1px 1px 0px"）。
    // computed borderWidth 简写在四边不一致时既可能是空串、也可能是带 0 的多值——
    // 只判“空串”会让整排分隔线一直采不到（真实页 9 条行线）。这里逐边读 used 值，
    // 只有“四边同宽同色”才继续交给 borderWidth/borderColor（老数据形状不变），
    // 其余情况逐边补采。
    const _sides = [['t', 'Top'], ['r', 'Right'], ['b', 'Bottom'], ['l', 'Left']];
    const _bw = {}, _bc = {}, _bs = {};
    for (const [k, S] of _sides) {
      const w = parseFloat(cs['border' + S + 'Width']) || 0;
      const st = cs['border' + S + 'Style'];
      _bw[k] = (w > 0 && st && st !== 'none' && st !== 'hidden') ? w : 0;
      _bc[k] = cs['border' + S + 'Color'];
      _bs[k] = st || '';
    }
    const _wid = _sides.map(([k]) => _bw[k]);
    const _col = _sides.map(([k]) => _bc[k]);
    const _sty = _sides.map(([k]) => _bs[k]);
    const borderUniform = _wid[0] === _wid[1] && _wid[1] === _wid[2]
                          && _wid[2] === _wid[3] && _col[0] === _col[1]
                          && _col[1] === _col[2] && _col[2] === _col[3]
                          && _sty[0] === _sty[1] && _sty[1] === _sty[2]
                          && _sty[2] === _sty[3];
    const borderStyle = (borderUniform && _wid[0] > 0
                         && !['solid', 'none', 'hidden'].includes(_sty[0]))
                        ? _sty[0] : '';
    let edges = null;
    if (!borderUniform) {
      for (const [k] of _sides) {
        // <0.75px 的“发丝线”在 DPR=1 下多数不落地，采进来会平白多出一条浅线
        if (_bw[k] < 0.75) continue;
        (edges = edges || []).push([k, _bw[k], _bc[k]]);
      }
    }
    // 祖先裁剪：只在真的会切到本节点时才写（1px 容差吸收取整噪声）。不需要裁剪的
    // 节点、以及旧抓取数据都不新增字段，DOM JSON / SoM 的形状保持不变。
    let clip = null;
    {
      const c = clipOf(el);
      if (c && (c[0] > r.left + 1 || c[1] > r.top + 1
                || c[2] < r.right - 1 || c[3] < r.bottom - 1)) {
        const cw = Math.round(c[2] - c[0]), ch = Math.round(c[3] - c[1]);
        if (cw >= 1 && ch >= 1) {
          clip = [Math.round(c[0]), Math.round(c[1]), cw, ch];
        }
      }
    }
    // 最近的"已采集祖先"在 out 里的下标；没有（html/body/被跳过的祖先）不写。
    let parentIdx = -1;
    for (let p = logicalParentOf.get(el) || el.parentElement; p;
         p = logicalParentOf.get(p) || p.parentElement) {
      const hit = indexOf.get(p);
      if (hit !== undefined) { parentIdx = hit; break; }
    }
    const isContainer = hasElementChildren;
    const styleSnapshot = styleSnapshotFor(el, cs);
    const pseudoBefore = pseudoStyleSnapshot(el, '::before');
    const pseudoAfter = pseudoStyleSnapshot(el, '::after');
    // A srcdoc document without a doctype is rendered in quirks mode.  In
    // Chromium its default text face is the generic sans-serif face even
    // though getComputedStyle(fontFamily) reports "Times New Roman"; using
    // that computed string in SVG/Figma makes child text visibly narrower.
    const srcdocDefaultFont = location.href === 'about:srcdoc'
                               && /^["']?Times New Roman["']?$/i.test(
                                    String(cs.fontFamily || '').trim())
                               && !String(el.style.fontFamily || '').trim();
    const effectiveFontFamily = srcdocDefaultFont ? 'sans-serif' : cs.fontFamily;
    const fontKey = [
      cs.fontStyle || 'normal',
      cs.fontWeight || '400',
      cs.fontStretch || 'normal',
      cs.fontSize || '16px',
      effectiveFontFamily,
    ].join('|');
    const shouldProbeFont = (hasText || placeholder) && fontProbePrefix
      && (isGenericFontStack(effectiveFontFamily) || !fontProbeSeen.has(fontKey));
    if (shouldProbeFont) fontProbeSeen.add(fontKey);
    const fontProbeId = shouldProbeFont
      ? `${fontProbePrefix}-${out.length}` : '';
    const rec = {
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      ariaLabel: el.getAttribute('aria-label') || '',
      title: el.getAttribute('title') || '',
      text: hasText ? visible.slice(0, 200) : '',
      placeholder: placeholder,
      placeholderColor: placeholderColor,
      alt: (el.getAttribute('alt') || '').trim().slice(0, 200),
      textBox: textBox,
      textAlign: cs.textAlign,
      lineHeight: cs.lineHeight,
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
      bg: cs.backgroundColor, pageBg: pageBg,
      color: cs.color, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
      fontStyle: cs.fontStyle,
      // 字体栈只对真的会渲染文字的节点有意义：可见文本，或带 placeholder 的输入框
      // （placeholder 也要按输入框自己的字体排版，否则会掉到输出端兜底栈）。
      // 其余节点写空串，避免上千个节点各带一份字体栈把 DOM/SoM 撑大。
      fontFamily: (hasText || placeholder) ? effectiveFontFamily : '',
      ...(fontProbeId ? { fontProbeId } : {}),
      borderRadius: cs.borderRadius,
      borderColor: cs.borderColor, borderWidth: cs.borderWidth,
      position: cs.position, zIndex: parseInt(cs.zIndex, 10) || 0,
      interactive: /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)
    };
    const textRoleHint = semanticTextRoleHint(el);
    if (textRoleHint && (hasText || placeholder || isTextField)) {
      rec.textRoleHint = textRoleHint;
    }
    if (el.id) rec.id = el.id.slice(0, 200);
    rec.styleSnapshot = styleSnapshot;
    if (pseudoBefore) rec.pseudoBefore = pseudoBefore;
    if (pseudoAfter) rec.pseudoAfter = pseudoAfter;
    if (borderStyle) rec.borderStyle = borderStyle;
    if (_wid.some((value) => value > 0)) {
      rec.borderTopWidth = _bw.t;
      rec.borderLeftWidth = _bw.l;
    }
    if (['IMG', 'SOURCE', 'VIDEO'].includes(el.tagName)) {
      const assetSrc = String(el.currentSrc || el.src || el.getAttribute('src') || '').trim();
      if (assetSrc) rec.assetSrc = assetSrc.slice(0, 20000);
      if (el.tagName === 'IMG') {
        rec.naturalWidth = Number(el.naturalWidth || 0);
        rec.naturalHeight = Number(el.naturalHeight || 0);
        rec.objectFit = String(cs.objectFit || 'fill');
        rec.objectPosition = String(cs.objectPosition || '50% 50%');
      }
    } else if (el.tagName === 'INPUT'
               && (el.getAttribute('type') || '').toLowerCase() === 'image') {
      const assetSrc = String(el.src || el.getAttribute('src') || '').trim();
      if (assetSrc) rec.assetSrc = assetSrc.slice(0, 20000);
    }
    if (String(el.tagName).toLowerCase() === 'svg') {
      try {
        rec.svgSource = el.outerHTML.slice(0, 200000);
      } catch (e) {}
    }
    if (inlineImageBoundaryNode(el)) rec.inlineImageBoundary = true;
    if (el.tagName === 'LI') {
      const marker = String(cs.listStyleType || '').toLowerCase();
      let markerType = '';
      if (/(decimal|roman|alpha)/.test(marker)) markerType = 'ordered';
      else if (/(disc|circle|square)/.test(marker)) markerType = 'unordered';
      if (markerType && marker !== 'none') {
        let level = 1;
        for (let p = el.parentElement; p; p = p.parentElement) {
          if (p.tagName === 'LI') level += 1;
        }
        rec.listMarker = {type: markerType, level: level};
      }
    }
    // 只有 Shadow DOM 里的节点才带这个标记（普通页面 DOM JSON 形状不变），
    // 用于结构诊断与分层调试：哪些可见内容原先完全抓不到。
    if (inShadow) rec.shadow = true;
    // ── 布局信息（Auto Layout 推断的输入，见 rendering/layout_infer.py）
    // 只写非默认值：没有这类属性的页面，DOM JSON 与老版本逐字节一致（老产物可复现）。
    // 约定：**没有 display 字段 = block 级**；inline 级会出现并触发推断器的 bail。
    if (parentIdx >= 0) rec.pIdx = parentIdx;
    if (isContainer) {
      if (cs.display !== 'block') rec.display = cs.display;
      if (cs.flexDirection !== 'row') rec.flexDirection = cs.flexDirection;
      if (cs.flexWrap !== 'nowrap') rec.flexWrap = cs.flexWrap;
      const rg = parseFloat(cs.rowGap) || 0;
      const cg = parseFloat(cs.columnGap) || 0;
      if (rg || cg) rec.gap = [round2(rg), round2(cg)];
      const pad = ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft']
        .map((k) => round2(parseFloat(cs[k]) || 0));
      if (pad.some((v) => v)) rec.padding = pad;
      if (cs.justifyContent !== 'normal') rec.justifyContent = cs.justifyContent;
      if (cs.alignItems !== 'normal') rec.alignItems = cs.alignItems;
    } else if (cs.display !== 'block') {
      rec.display = cs.display;   // 非容器也可能是布局参与者（flex 子项 / 行内元素）
    }
    const flt = (cs.cssFloat || '').trim();
    if (flt && flt !== 'none') rec.cssFloat = flt;
    const fg = parseFloat(cs.flexGrow) || 0;
    if (fg > 0) rec.flexGrow = fg;
    if (cs.alignSelf !== 'auto') rec.alignSelf = cs.alignSelf;
    const ord = parseInt(cs.order, 10) || 0;
    if (ord) rec.order = ord;
    const sized = contentSizedAxes(el);
    if (sized) rec.contentSize = sized;
    // 换行/截断：只带非默认值（normal / none），绝大多数节点是默认值，全带上
    // 会让上千节点的 DOM JSON 白涨几十 KB。IR 侧据此决定文字折不折行、最多几行
    // ——直出稿原先完全没有这两个字段，宽盒子里的长标题只能画成一行溢出压到邻居。
    if (cs.whiteSpace && cs.whiteSpace !== 'normal') rec.whiteSpace = cs.whiteSpace;
    const lineClamp = (cs.getPropertyValue('-webkit-line-clamp') || '').trim();
    if (lineClamp && lineClamp !== 'none') rec.lineClamp = lineClamp;
    const overflowX = String(cs.overflowX || 'visible').toLowerCase();
    const overflowY = String(cs.overflowY || 'visible').toLowerCase();
    const textOverflow = String(cs.textOverflow || 'clip').toLowerCase();
    if (overflowX !== 'visible') rec.overflowX = overflowX;
    if (overflowY !== 'visible') rec.overflowY = overflowY;
    if (textOverflow !== 'clip') rec.textOverflow = textOverflow;
    const clipsToBounds = overflowX !== 'visible' || overflowY !== 'visible';
    if (clipsToBounds) rec.clipToBounds = true;
    if (clipsToBounds || el.scrollWidth > el.clientWidth + 1
        || el.scrollHeight > el.clientHeight + 1) {
      rec.clientWidth = el.clientWidth;
      rec.clientHeight = el.clientHeight;
      rec.scrollWidth = el.scrollWidth;
      rec.scrollHeight = el.scrollHeight;
    }
    if (!richRuns && !hasElementChildren
        && overflowX === 'hidden'
        && String(cs.whiteSpace || '').toLowerCase() === 'nowrap'
        && textOverflow === 'ellipsis'
        && el.scrollWidth > el.clientWidth + 1) {
      const fullText = visible;
      const clippedText = ellipsizeText(fullText, el, cs);
      if (clippedText !== fullText) {
        rec.text = clippedText;
        rec.fullText = fullText;
      }
    }
    // 祖先裁剪矩形（只有被滚动/隐藏容器切到的节点才带）
    if (clip) rec.clip = clip;
    // 只有“多段直接文本”的节点才带 textRuns：单段节点的 JSON 与老版本逐字节一致
    if (textRuns) rec.textRuns = textRuns;
    if (richRuns) rec.richRuns = richRuns;
    if (textLines) rec.textLines = textLines;
    // 同理：只有量到「第一行行框」的节点才多带这两个（其余节点 / 老产物逐字节不变）
    if (textEmBox) { rec.textEmBox = textEmBox; rec.textEmLines = textEmLines; }
    if (textBaseline) rec.textBaseline = textBaseline;
    if (textFlow) rec.textFlow = true;
    // 同理：只有图标字形叶子 / 非均匀边框的节点才多带字段
    if (iconBox) rec.iconBox = true;
    if (bgImage) rec.bgImage = true;
    if (bgUrls.length) rec.bgUrls = bgUrls;
    if (backgroundLayers.length) rec.backgroundLayers = backgroundLayers;
    if (edges) rec.edges = edges;
    // 图标标识随节点带出（只给判定成图标的节点写，避免上千个节点都挂一份 class）
    if (iconBox && clsRaw) rec.cls = clsRaw.slice(0, 160);
    // 图层可读名用：所有节点都留一份 class。刻意不复用 cls——cls 是
    // “图标判定”的输入，给非图标节点补上会改变识别结果；这个字段只喂
    // provider 起名字。裁到 200 字符控制体积。
    if (clsRaw) rec.clsAll = clsRaw.slice(0, 200);
    if (iconBox && elType) rec.elType = elType.slice(0, 40);
    // 盒子投影：antd 固定列 / fixed 表头的“滚动阴影”就是它，直出端原先完全不采，
    // 表格左右缘那几条 2~4px 渐变竖线因此一直缺失。原样带字符串，由 provider 解析。
    const boxShadow = (cs.boxShadow || '').trim();
    if (boxShadow && boxShadow !== 'none') rec.boxShadow = boxShadow.slice(0, 400);
    // 字距 / 元素透明度：computed 默认值（letter-spacing: normal / opacity: 1）不写，
    // 没有这两个属性的页面 DOM JSON 与老版本逐字节一致。字距是元素的排版属性，
    // 由 IR 决定给哪些节点透传；opacity 是整棵子树的合成系数，0（完全透明）的节点
    // 上面已经被 display/visibility 那条判掉，这里只带 0<op<1 的。
    const ls = (cs.letterSpacing || '').trim();
    if (ls && ls !== 'normal') rec.letterSpacing = ls;
    const op = parseFloat(cs.opacity);
    if (isFinite(op) && op > 0 && op < 1) rec.opacity = op;
    if (fontProbeId) el.setAttribute('data-p1-font-probe-id', fontProbeId);
    indexOf.set(el, out.length);
    out.push(rec);
  };
  // 递归遍历 light DOM + 开放 Shadow DOM。无 Shadow 的普通页面里，前序遍历与
  // document.querySelectorAll('*') 完全同序，老产物保持可复现。
  const visit = (el, logicalParent, inShadow) => {
    if (!(el instanceof Element) || el.ownerDocument !== document) return;
    if (isNonRenderedSvgContainer(el)) return;
    if (logicalParent) logicalParentOf.set(el, logicalParent);
    try {
      collect(el, inShadow);
    } catch (e) {
      // Detached/navigated elements must not abort the whole DOM snapshot.
      return;
    }
    let shadow = null;
    try { shadow = el.shadowRoot; } catch (e) {}
    if (shadow && shadow.children) {
      for (const child of Array.from(shadow.children)) visit(child, el, true);
    }
    if (el.children) {
      for (const child of Array.from(el.children)) visit(child, el, inShadow);
    }
  };
  if (document.documentElement) visit(document.documentElement, null, false);
  return out;
}
"""

CAPTURE_STATE_JS = r"""
() => {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const NON_RENDERED_SVG_CONTAINERS = new Set([
    'defs', 'clipPath', 'mask', 'symbol', 'pattern',
    'linearGradient', 'radialGradient', 'filter', 'marker'
  ]);
  const inNonRenderedSvgContainer = (el) => {
    let current = el;
    while (current) {
      if (current.namespaceURI === SVG_NS
          && NON_RENDERED_SVG_CONTAINERS.has(current.localName)) return true;
      current = current.parentElement;
    }
    return false;
  };
  let hash = 2166136261 >>> 0;
  const mix = (value) => {
    const text = String(value);
    for (let i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619) >>> 0;
    }
    hash ^= 10;
    hash = Math.imul(hash, 16777619) >>> 0;
  };
  let visibleNodes = 0;
  const elements = Array.from(document.querySelectorAll('*'));
  for (const el of elements) {
    if (!(el instanceof Element) || el.ownerDocument !== document) continue;
    if (inNonRenderedSvgContainer(el)) continue;
    let cs, rect;
    try {
      cs = getComputedStyle(el);
      rect = el.getBoundingClientRect();
    } catch (e) {
      // A navigation can detach elements while the probe is running.
      continue;
    }
    if (cs.display === 'none' || cs.visibility === 'hidden'
        || parseFloat(cs.opacity) <= 0) continue;
    if (rect.width < 2 || rect.height < 2) continue;
    visibleNodes++;
    const text = el.childElementCount
      ? ''
      : String(el.textContent || '').trim().slice(0, 200);
    const asset = String(
      el.currentSrc || el.getAttribute('src') || ''
    ).trim().slice(0, 500);
    const cls = typeof el.className === 'string' ? el.className : '';
    mix([
      el.tagName, el.id || '', cls.slice(0, 200),
      el.getAttribute('role') || '',
      el.getAttribute('aria-label') || '',
      el.getAttribute('title') || '',
      el.getAttribute('alt') || '',
      text, asset,
      Math.round(rect.x), Math.round(rect.y),
      Math.round(rect.width), Math.round(rect.height)
    ].join('|'));
  }
  return {
    total_nodes: document.querySelectorAll('*').length,
    visible_nodes: visibleNodes,
    hash: hash.toString(16).padStart(8, '0')
  };
}
"""

FONT_READY_JS = r"""
() => {
  try {
    if (!document.fonts || !document.fonts.status) return 'unavailable';
    return String(document.fonts.status);
  } catch (e) {
    return 'unavailable';
  }
}
"""

FONT_RESOURCES_JS = r"""
() => {
  const faces = [];
  try {
    for (const face of document.fonts || []) {
      faces.push({
        family: String(face.family || ''),
        style: String(face.style || 'normal'),
        weight: String(face.weight || '400'),
        stretch: String(face.stretch || 'normal'),
        status: String(face.status || 'unknown'),
        unicodeRange: String(face.unicodeRange || ''),
      });
    }
  } catch (e) {}
  const resources = [];
  try {
    for (const entry of performance.getEntriesByType('resource') || []) {
      const url = String(entry.name || '');
      if (!/\.(woff2?|ttf|otf|eot)(?:[?#].*)?$/i.test(url)
          && String(entry.initiatorType || '').toLowerCase() !== 'css') continue;
      resources.push({
        source_url: url,
        initiatorType: String(entry.initiatorType || ''),
        transferSize: Number(entry.transferSize || 0),
        encodedBodySize: Number(entry.encodedBodySize || 0),
        decodedBodySize: Number(entry.decodedBodySize || 0),
        startTime: Number(entry.startTime || 0),
        responseEnd: Number(entry.responseEnd || 0),
      });
    }
  } catch (e) {}
  return faces.map((face, index) => ({
    ...face,
    ...(resources[index] || {}),
    source_status: resources[index] ? 'reference-only' : 'unavailable',
  }));
}
"""


def _resolve_storage_state(path_value: str | None) -> str | None:
    """校验 Playwright storageState JSON；文件缺失时提前报错，避免启动浏览器后才发现。"""
    if not path_value:
        return None
    p = Path(path_value)
    if not p.is_file():
        raise ValueError(
            f"storage_state 文件不存在: {p}（请先运行 --login-state 导出登录态，"
            "或用 PLAYWRIGHT_STORAGE_STATE 指向已导出的 JSON）"
        )
    return str(p)


def _page_has_password_input(page) -> bool:
    try:
        return bool(
            page.evaluate("document.querySelectorAll('input[type=password]').length")
        )
    except Exception:
        return False


def _hits(text: str, markers: tuple[str, ...]) -> list[str]:
    low = (text or "").lower()
    return [marker for marker in markers if marker in low]


def _same_origin(left: str, right: str) -> bool:
    a, b = urlparse(left or ""), urlparse(right or "")
    return (a.scheme.lower(), a.netloc.lower()) == (b.scheme.lower(), b.netloc.lower())


def _install_cross_origin_frame_document_policy(
    context,
    page,
    target_url: str,
    blocked: list[dict],
) -> None:
    def handle(route, request):
        try:
            frame = request.frame
            is_frame_document = (
                request.resource_type == "document" and frame != page.main_frame
            )
            if is_frame_document and not _same_origin(request.url, target_url):
                blocked.append(
                    {
                        "url": request.url,
                        "resource_type": request.resource_type,
                        "frame_url": frame.url,
                    }
                )
                route.abort("blockedbyclient")
                return
        except Exception:  # noqa: BLE001 - routing must not break capture
            pass
        route.continue_()

    context.route("**/*", handle)


def _url_changed(requested: str, final: str) -> bool:
    def norm(value: str):
        parsed = urlparse(value or "")
        return (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            parsed.query,
            parsed.fragment,
        )

    return bool(final) and norm(requested) != norm(final)


def _login_url_hits(final_url: str) -> list[str]:
    """登录地址信号：路径段优先，避免把 `/author/...` 里的 `auth` 当成登录。"""
    parsed = urlparse(final_url or "")
    path = unquote(parsed.path or "").lower()
    host = (parsed.netloc or "").lower()
    segments = {part for part in path.split("/") if part}
    hits = [marker for marker in LOGIN_PATH_SEGMENTS if marker in segments]
    for marker in ("account/login", "user/login", "登录", "登陆"):
        if marker in path and marker not in hits:
            hits.append(marker)
    for marker in ("login", "signin", "passport", "sso", "auth"):
        if host.startswith(marker + ".") and marker not in hits:
            hits.append(marker)
    return hits


def _page_probe(page) -> dict:
    try:
        probe = page.evaluate(PROBE_JS)
        return probe if isinstance(probe, dict) else {}
    except Exception as exc:  # noqa: BLE001 - 探测失败按空页面处理
        logger.warning("页面状态探测失败：%s", exc)
        return {}


def classify_page_state(
    probe: dict,
    requested_url: str,
    *,
    status: int | None = None,
    error: str | None = None,
    navigation_budget_exhausted: bool = False,
) -> dict:
    """把抓到的页面分成 content / soft_block / hard_login 三种状态。

    判定顺序是刻意的：先认登录墙，再认拦截页，最后才把“空壳”算作软拦截。
    这样登录页不会被误报成反爬，内容页页头的“登录/注册”链接也不会被误报成登录墙。
    """
    final_url = str(probe.get("finalUrl") or requested_url or "")
    title = str(probe.get("title") or "")
    body = str(probe.get("bodyTextSample") or "")
    body_low = body.lower()
    password_inputs = int(probe.get("passwordInputs") or 0)
    element_count = int(probe.get("elementCount") or 0)
    body_text_len = int(probe.get("bodyTextLen") or 0)
    image_count = int(probe.get("imageCount") or 0)
    has_captcha = bool(probe.get("hasCaptchaElement"))
    has_form = bool(probe.get("hasForm"))

    meaningful = body_text_len >= 80 or image_count >= 3 or element_count >= 100
    low_content = body_text_len < 40 and image_count < 2
    empty_shell = element_count < 30 and body_text_len < 40 and image_count < 2

    login_url_hits = _login_url_hits(final_url)
    login_title_hits = _hits(title, LOGIN_TITLE_MARKERS)
    login_body_hits = _hits(body, LOGIN_BODY_MARKERS)
    login_strong_hits = _hits(body, LOGIN_STRONG_BODY_MARKERS)
    login_form = (
        password_inputs > 0
        and has_form
        and any(
            marker in body_low
            for marker in ("登录", "登陆", "sign in", "log in", "login")
        )
    )
    login_form_evidence = (
        password_inputs > 0 or login_form or (has_form and bool(login_body_hits))
    )
    block_hits = _hits(final_url + "\n" + title + "\n" + body, BLOCK_MARKERS)
    http_block = status in (400, 401, 403, 404, 410, 429) or (
        isinstance(status, int) and status >= 500
    )
    redirected = _url_changed(requested_url, final_url)
    screenshot_error = bool(error) and "screenshot" in str(error).lower()
    navigation = classify_capture_navigation(
        requested_url,
        final_url,
        error=str(probe.get("navigationError") or "") or None,
        timed_out=bool(probe.get("navigationTimedOut")),
        navigation_budget_exhausted=navigation_budget_exhausted,
    )

    signals = {
        "final_url": final_url,
        "requested_url": requested_url,
        "title": title,
        "http_status": status,
        "redirected": redirected,
        "same_origin": _same_origin(requested_url, final_url),
        "password_inputs": password_inputs,
        "has_login_form": login_form,
        "login_url_hits": login_url_hits,
        "login_title_hits": login_title_hits,
        "login_body_hits": login_body_hits,
        "login_strong_body_hits": login_strong_hits,
        "block_hits": block_hits,
        "has_captcha_element": has_captcha,
        "element_count": element_count,
        "body_text_len": body_text_len,
        "image_count": image_count,
        "meaningful_content": meaningful,
        "empty_shell": empty_shell,
        "navigation_error": error,
        "navigation_status": navigation["status"],
        "navigation_reason": navigation["reason"],
        "screenshot_error": screenshot_error,
    }

    if navigation["status"] == "browser-navigation-failed":
        return {
            "kind": PAGE_STATE_SOFT_BLOCK,
            "confidence": 0.9,
            "reason": (
                "browser-navigation-failed: "
                + str(navigation.get("reason") or "navigation left a blank page")
            ),
            "signals": signals,
        }
    login_route_signal = bool(login_url_hits or login_title_hits)
    if password_inputs > 0 and (login_route_signal or login_form or low_content):
        return {
            "kind": PAGE_STATE_HARD_LOGIN,
            "confidence": 0.95 if (login_route_signal or login_form) else 0.8,
            "reason": "检测到可见密码框，且页面呈现登录表单/登录地址",
            "signals": signals,
        }
    if login_route_signal and login_form_evidence:
        return {
            "kind": PAGE_STATE_HARD_LOGIN,
            "confidence": 0.8,
            "reason": "页面落在登录路由/登录标题，且呈现登录表单或登录文案",
            "signals": signals,
        }
    if login_route_signal and login_strong_hits and not meaningful:
        # 扫码/账号登录页可能既没有密码框也没有 form，正文里还会带“验证码”；
        # 只要路由/标题是登录页、主体又几乎没有内容，就按登录墙处理。
        return {
            "kind": PAGE_STATE_HARD_LOGIN,
            "confidence": 0.85,
            "reason": "页面落在登录路由/登录标题，且主体是扫码/账号登录引导",
            "signals": signals,
        }
    if login_route_signal and low_content and not block_hits:
        return {
            "kind": PAGE_STATE_HARD_LOGIN,
            "confidence": 0.75,
            "reason": "最终地址落在登录路由，且页面没有正文内容",
            "signals": signals,
        }
    if block_hits or has_captcha or http_block:
        if has_captcha:
            reason = "检测到验证码/人机验证组件"
        elif block_hits:
            reason = "命中拦截页关键词：" + ", ".join(block_hits[:3])
        else:
            reason = f"页面返回 HTTP {status}"
        return {
            "kind": PAGE_STATE_SOFT_BLOCK,
            "confidence": 0.95,
            "reason": reason,
            "signals": signals,
        }
    if not meaningful:
        return {
            "kind": PAGE_STATE_SOFT_BLOCK,
            "confidence": 0.65,
            "reason": "页面接近空壳（正文与可见元素都很少）",
            "signals": signals,
        }
    if screenshot_error:
        return {
            "kind": PAGE_STATE_CONTENT,
            "confidence": 0.7,
            "reason": "页面内容已读取，但截图异常：" + str(error),
            "signals": signals,
        }
    if error:
        return {
            "kind": PAGE_STATE_SOFT_BLOCK,
            "confidence": 0.7,
            "reason": "导航异常，只能抓到当前残留页面：" + error,
            "signals": signals,
        }
    return {
        "kind": PAGE_STATE_CONTENT,
        "confidence": 0.95,
        "reason": "页面正文与可见元素满足内容页判定",
        "signals": signals,
    }


class PageAccessError(RuntimeError):
    """URL 采集后页面状态不允许继续（登录墙 / 反爬拦截 / 空壳）。"""

    def __init__(self, message: str, *, state: dict | None = None) -> None:
        super().__init__(message)
        self.state = state or {}


def page_access_error_message(
    page_state: dict, *, requested_route: str = "auto"
) -> str:
    """把页面状态翻译成给用户看的下一步动作。"""
    kind = page_state.get("kind")
    signals = page_state.get("signals") or {}
    final_url = page_state.get("final_url") or signals.get("final_url") or ""
    status = signals.get("http_status")
    retried = bool(page_state.get("fallback_used"))
    if kind == PAGE_STATE_HARD_LOGIN:
        base = "目标页面本身需要登录，自主截图也只能看到登录页"
    elif kind == PAGE_STATE_SOFT_BLOCK:
        if signals.get("block_hits") or signals.get("has_captcha_element"):
            base = "站点拦截了自动访问（验证码/人机验证/反爬）"
        elif signals.get("empty_shell"):
            base = "自动采集未拿到有效内容（页面可能是空壳/SPA 未加载/反爬）"
        else:
            base = "站点拦截了自动访问"
        if retried:
            base += (
                "；真实浏览器会话重试后仍为空"
                if signals.get("empty_shell")
                else "；真实浏览器会话重试后仍未拿到目标内容"
            )
        elif not signals.get("empty_shell"):
            base += "；当前采集未拿到目标内容"
        if isinstance(status, int) and status >= 400:
            base += f"（HTTP {status}）"
    else:
        base = "URL 采集未拿到可复刻的页面内容"
    if requested_route == "dom":
        if kind == PAGE_STATE_HARD_LOGIN:
            return (
                f"{base}；最终地址：{final_url}。显式 --route dom 不会静默切换路线；"
                "即使改用 --route auto，自主截图也只能看到登录页。请先用 --login-state "
                "导出登录态并通过 --storage-state 重试，或手动上传目标页截图。"
            )
        return (
            f"{base}；最终地址：{final_url}。显式 --route dom 不会静默切换路线，"
            "请改用 --route auto 让系统自动降级为自主截图，或先完成登录/验证后用 "
            "--storage-state 重试。"
        )
    if kind == PAGE_STATE_HARD_LOGIN:
        return (
            f"{base}；最终地址：{final_url}。请先用 --login-state 导出登录态并通过 "
            "--storage-state 重试，或手动上传目标页截图。"
        )
    return (
        f"{base}；最终地址：{final_url}。请手动上传目标页截图，或在可见浏览器中完成"
        "验证后用 --storage-state 重试。"
    )


def _browser_context_options(cfg: "Config", viewport: dict[str, int]) -> dict:
    return {
        "viewport": viewport,
        "device_scale_factor": cfg.device_scale_factor,
        "locale": cfg.playwright_locale,
        "timezone_id": cfg.playwright_timezone,
    }


def export_login_state(
    url: str, output_path: str, cfg: "Config", *, headless: bool = False, ask=None
) -> str:
    """打开（默认有头）浏览器让用户登录，回车后把登录态导出为 Playwright storageState JSON。"""
    if ask is None:
        ask = input
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page(
                **_browser_context_options(
                    cfg,
                    {
                        "width": cfg.playwright_viewport_width,
                        "height": cfg.playwright_viewport_height,
                    },
                )
            )
            page.goto(
                url, wait_until="domcontentloaded", timeout=cfg.wait_networkidle_timeout
            )
            page.wait_for_timeout(tuning.LOGIN_SHELL_MS)  # 给 SPA 首屏/跳转一点时间
            ask(LOGIN_PROMPT)
            page.wait_for_timeout(tuning.LOGIN_PROMPT_MS)
            page.context.storage_state(path=str(out))
        finally:
            browser.close()
    state = json.loads(out.read_text(encoding="utf-8"))
    cookies = state.get("cookies") or []
    origins = state.get("origins") or []
    domains = sorted({c.get("domain", "") for c in cookies if c.get("domain")})
    logger.info(
        "已保存登录态 %s：cookies=%d, localStorage origins=%d",
        out,
        len(cookies),
        len(origins),
    )
    if domains:
        logger.info("cookie 域：%s", ", ".join(domains))
    if not cookies and not origins:
        logger.warning(
            "导出内容为空：可能尚未真正登录成功，请重跑 --login-state 并在登录后再回车"
        )
    return str(out)


# 导航/等待参数：networkidle 对“请求轮询型 SPA”永远不出现（心跳/长轮询），
# 所以它只作为“资源都加载完了”的首选信号，带上限；真正的就绪信号是 DOM 不再增长。
# 等待时长全部单一定义在 `src/app/tuning.py`（env 可覆盖），这里调用时读。


def _element_count(page) -> int:
    """页面里的元素数；拿不到时返回 0（不因为探测失败而中断采集）。"""
    try:
        return int(page.evaluate("document.querySelectorAll('*').length"))
    except Exception:
        return 0


def _wait_dom_settled(page, cfg: "Config") -> int:
    """等 DOM 不再增长，返回稳定后的元素数。

    SPA 首屏是分批铺的（先应用壳、再路由内容、再表格数据），networkidle 之后
    仍可能继续长；节点数稳定才是“可截图/可采集”的信号。
    """
    budget = max(
        tuning.SETTLE_MIN_MS,
        min(int(cfg.wait_networkidle_timeout), tuning.SETTLE_CAP_MS),
    )
    last, waited, stable = _element_count(page), 0, 0
    while waited < budget:
        page.wait_for_timeout(tuning.SETTLE_POLL_MS)
        waited += tuning.SETTLE_POLL_MS
        n = _element_count(page)
        if n == last:
            stable += tuning.SETTLE_POLL_MS
            if stable >= tuning.SETTLE_STABLE_MS:
                return n
        else:
            stable, last = 0, n
    return last


def _wait_capture_state(
    page,
    *,
    poll_ms: int | None = None,
    stable_ms: int | None = None,
    cap_ms: int | None = None,
) -> dict:
    """Wait for the visible DOM signature to remain unchanged for a short window."""
    poll = max(10, int(tuning.CAPTURE_STATE_POLL_MS if poll_ms is None else poll_ms))
    required = max(
        poll,
        int(tuning.CAPTURE_STATE_STABLE_MS if stable_ms is None else stable_ms),
    )
    budget = max(
        required,
        int(tuning.CAPTURE_STATE_CAP_MS if cap_ms is None else cap_ms),
    )
    samples: list[dict] = []
    waited = 0
    probe_errors = 0
    last_error = None
    while True:
        try:
            signature = page.evaluate(CAPTURE_STATE_JS)
            frame_state: list[dict] = []
            try:
                frame_state = capture_frame_state(
                    page,
                    CAPTURE_STATE_JS,
                    include_unrendered=False,
                )
            except Exception:
                frame_state = []
            if frame_state:
                signature = {
                    "main": signature,
                    "frames": frame_state,
                }
            samples.append(signature)
        except Exception as exc:  # noqa: BLE001 - navigation can replace the document
            probe_errors += 1
            last_error = f"{type(exc).__name__}: {exc}"
            samples.clear()
        if state_window_is_stable(samples, poll_ms=poll, stable_ms=required):
            return {
                "stable": True,
                "stable_ms": (len(samples) - 1) * poll,
                "waited_ms": waited,
                "samples": len(samples),
                "signature": samples[-1],
                "probe_errors": probe_errors,
            }
        if waited >= budget:
            return {
                "stable": False,
                "stable_ms": 0,
                "waited_ms": waited,
                "samples": len(samples),
                "signature": samples[-1] if samples else None,
                "probe_errors": probe_errors,
                "last_probe_error": last_error,
            }
        page.wait_for_timeout(poll)
        waited += poll


def _wait_document_fonts(
    page,
    *,
    poll_ms: int | None = None,
    timeout_ms: int | None = None,
) -> dict:
    """Wait for document.fonts within a bounded budget before the state probe."""
    poll = max(10, int(tuning.CAPTURE_FONT_POLL_MS if poll_ms is None else poll_ms))
    budget = max(
        poll,
        int(tuning.CAPTURE_FONT_WAIT_MS if timeout_ms is None else timeout_ms),
    )
    waited = 0
    status = "unknown"
    while True:
        try:
            status = str(page.evaluate(FONT_READY_JS) or "unknown")
        except Exception as exc:  # noqa: BLE001 - navigation can replace the document
            status = f"error:{type(exc).__name__}"
        if status in {"loaded", "unavailable"}:
            return {
                "ready": True,
                "status": status,
                "waited_ms": waited,
            }
        if waited >= budget:
            return {
                "ready": False,
                "status": status,
                "waited_ms": waited,
            }
        page.wait_for_timeout(poll)
        waited += poll


def _load_url(page, url: str, cfg: "Config"):
    """导航一次：优先等 networkidle（经典页面：资源都到位），超时退回 domcontentloaded。

    轮询型 SPA 永远不会 networkidle（实测目标页 30s 超时直接让整次采集失败），
    但文档其实早就可以用了——交给 _wait_dom_settled 判就绪。

    返回 `page.goto` 的 Response（拿 HTTP 状态码用）；超时/无响应返回 None。
    """
    from playwright.sync_api import TimeoutError as PWTimeout

    response = None
    try:
        response = page.goto(
            url,
            wait_until="networkidle",
            timeout=max(
                1000, min(int(cfg.wait_networkidle_timeout), tuning.NAV_IDLE_CAP_MS)
            ),
        )
    except PWTimeout:
        logger.info(
            "networkidle 未出现（轮询型 SPA 常见），退回 domcontentloaded 判就绪"
        )
        try:
            page.wait_for_load_state(
                "domcontentloaded", timeout=max(1000, int(cfg.wait_networkidle_timeout))
            )
        except PWTimeout:
            logger.warning("domcontentloaded 也未在超时内出现，按当前 DOM 继续")
    try:
        current_url = str(page.url or "")
    except Exception:
        current_url = ""
    if _url_is_blank(current_url) and not _url_is_blank(url):
        # WebKit can leave the document at about:blank after the networkidle wait
        # times out. One bounded re-navigation is enough to distinguish that
        # browser-navigation failure from a real DOM mismatch.
        try:
            retry_response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=max(
                    1000,
                    min(
                        int(cfg.wait_networkidle_timeout),
                        tuning.NAV_IDLE_CAP_MS,
                    ),
                ),
            )
            response = retry_response or response
        except PWTimeout:
            logger.warning("blank 文档重试仍超时，保留导航失败证据")
    return response


def _url_is_blank(value: str) -> bool:
    normalized = str(value or "").strip().lower().replace("about://", "about:")
    return normalized in {"", "about:blank", "about:srcdoc"}


def _looks_like_navigation_error(error: str | None) -> bool:
    text = str(error or "").lower()
    return bool(text) and "screenshot" not in text


def _hash_deep_link(url: str) -> bool:
    """是否“哈希路由深链”（SPA 深链）：有 # 且 # 后面不止 /。"""
    parsed = urlparse(url)
    return bool(parsed.fragment) and parsed.fragment.strip("/") != ""


def _origin_root(url: str) -> str:
    """站点根（scheme://host[:port]/），用于引导 SPA。"""
    parsed = urlparse(url)
    return "%s://%s/" % (parsed.scheme, parsed.netloc)


_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_STEALTH_INIT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


def _capture_session(
    url: str,
    cfg: "Config",
    out: Path,
    *,
    label: str,
    headless: bool,
    storage_state: str | None = None,
    user_data_dir: str | None = None,
    attempts: int = 1,
    browser_engine: str = DEFAULT_BROWSER_ENGINE,
    capture_early_state: bool = False,
    screenshot_timeout_ms: int = 30000,
    navigation_sync: Callable[[Any], None] | None = None,
    snapshot_sync: Callable[[Any], None] | None = None,
    block_cross_origin_frame_documents: bool = False,
    capture_navigation_timeline: bool = False,
) -> dict:
    """一次浏览器会话：导航 -> 等 DOM -> 截图 + DOM -> 页面状态判定。

    每次尝试写到 `capture_attempts/<label>.png|_dom.json`，成功后再由调用方
    promote 成 `00_screenshot.png` / `00_dom.json`。这样降级失败时还能回看
    每一层到底看到了什么（无头拦截页 / 有头登录页 / 真实会话内容页）。
    """
    from playwright.sync_api import sync_playwright

    browser_engine = normalize_browser_engine(browser_engine)
    attempt_dir = out / "capture_attempts"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in label)
    image_p = attempt_dir / f"{safe_label}.png"
    dom_p = attempt_dir / f"{safe_label}_dom.json"
    diagnostics_p = attempt_dir / f"{safe_label}_dom_diagnostics.json"
    m0_image_p = attempt_dir / f"{safe_label}_m0.png"
    m0_dom_p = attempt_dir / f"{safe_label}_m0_dom.json"
    # 同目录重跑时先清掉旧诊断，避免本次探针失败却 promote 出上一轮的结果。
    diagnostics_p.unlink(missing_ok=True)
    page_title = ""
    final_url = url
    status = None
    error = None
    capture_stability = None
    frame_inventory: list[dict] = []
    frame_snapshot_errors: list[dict] = []
    frame_capture_truncated = False
    font_resolution: dict[str, Any] = {}
    font_resources: list[dict] = []
    blocked_frame_documents: list[dict] = []
    timeline: NavigationTimeline | None = None
    navigation_timeline: dict | None = None
    navigation_timeline_error: str | None = None
    viewport = {
        "width": cfg.playwright_viewport_width,
        "height": cfg.playwright_viewport_height,
    }

    with sync_playwright() as p:
        browser = None
        context = None
        try:
            browser_type = getattr(p, browser_engine)
            context_options = _browser_context_options(cfg, viewport)
            if user_data_dir:
                Path(user_data_dir).mkdir(parents=True, exist_ok=True)
                launch_options = {
                    "user_data_dir": user_data_dir,
                    "headless": headless,
                    **context_options,
                }
                if browser_engine == "chromium":
                    launch_options["args"] = list(_LAUNCH_ARGS)
                context = browser_type.launch_persistent_context(**launch_options)
                page = context.pages[0] if context.pages else context.new_page()
            else:
                launch_options = {"headless": headless}
                if browser_engine == "chromium":
                    launch_options["args"] = list(_LAUNCH_ARGS)
                browser = browser_type.launch(**launch_options)
                context_opts = {**context_options}
                if storage_state:
                    context_opts["storage_state"] = storage_state
                context = browser.new_context(**context_opts)
                page = context.new_page()
            try:
                page.add_init_script(_STEALTH_INIT)
            except Exception:  # noqa: BLE001 - 老浏览器不支持就算了
                pass
            if capture_navigation_timeline:
                try:
                    timeline = NavigationTimeline(page, max_events=128)
                except Exception as exc:  # noqa: BLE001 - diagnostic evidence only
                    navigation_timeline_error = f"{type(exc).__name__}: {exc}"
            font_probe = None
            if browser_engine == "chromium":
                try:
                    font_probe = PlatformFontProbe(page)
                except Exception as exc:  # noqa: BLE001 - font evidence is optional
                    logger.debug("[%s] 平台字体探针初始化失败：%s", label, exc)
            if block_cross_origin_frame_documents:
                _install_cross_origin_frame_document_policy(
                    context,
                    page,
                    url,
                    blocked_frame_documents,
                )

            try:
                if navigation_sync is not None:
                    navigation_sync(page)
                if _hash_deep_link(url):
                    # 哈希深链在冷上下文里很脆：先访问站点根把应用引导起来再进深链
                    # （实测目标页少了这一步，抓到的永远是只铺了壳的空页）。
                    root = _origin_root(url)
                    logger.info("[%s] 哈希深链：先访问 %s 引导应用", label, root)
                    _load_url(page, root, cfg)
                    _wait_dom_settled(page, cfg)
                # 懒加载路由的 SPA：某一遍进来可能只铺出应用壳（内容区空、且不报错），
                # 而铺开的那一遍很快就把节点数顶上去（实测 551 壳 -> 2261 铺开）。所以
                # 抓最多 N 遍、每遍就地留档、最后留下的就是“内容最全的那一遍”，DOM 与
                # 截图因此始终同源；一旦某遍不再变多就收工。
                best, prev = -1, -1
                for attempt in range(max(1, int(attempts))):
                    response = _load_url(page, url, cfg)
                    if response is not None:
                        status = response.status
                        try:
                            final_url = response.url or page.url
                        except Exception:  # noqa: BLE001
                            pass
                    if capture_early_state and attempt == 0 and not m0_dom_p.exists():
                        try:
                            early_snapshot = collect_frame_dom(
                                page,
                                DOM_JS,
                                font_probe=font_probe,
                            )
                            early_nodes = early_snapshot.nodes
                            frame_inventory = early_snapshot.inventory
                            frame_snapshot_errors = early_snapshot.errors
                            frame_capture_truncated = early_snapshot.truncated
                            page.screenshot(
                                path=str(m0_image_p),
                                full_page=True,
                                timeout=max(1000, int(screenshot_timeout_ms)),
                            )
                            m0_dom_p.write_text(
                                json.dumps(early_nodes, ensure_ascii=False),
                                encoding="utf-8",
                            )
                            logger.info(
                                "[%s] 已保存 M0 早期状态：%d 个节点",
                                label,
                                len(early_nodes),
                            )
                        except Exception as exc:  # noqa: BLE001 - M0 是可选证据
                            logger.debug("[%s] M0 早期状态采集失败：%s", label, exc)
                    count = _wait_dom_settled(page, cfg)
                    logger.info("[%s] 第 %d 遍：节点数 %d", label, attempt + 1, count)
                    if count >= best:
                        best = count
                        page.add_style_tag(
                            content="*,*::before,*::after"
                            "{transition:none!important;animation:none!important}"
                        )
                        page.wait_for_timeout(tuning.RESTYLE_SETTLE_MS)
                        font_state = _wait_document_fonts(page)
                        capture_stability = _wait_capture_state(page)
                        capture_stability["fonts"] = font_state
                        logger.info(
                            "[%s] 状态稳定：%s，字体 %s，可见节点 %s，等待 %sms",
                            label,
                            capture_stability["stable"],
                            font_state["status"],
                            (capture_stability.get("signature") or {}).get(
                                "visible_nodes"
                            ),
                            capture_stability["waited_ms"],
                        )
                        if snapshot_sync is not None:
                            try:
                                barrier_result = snapshot_sync(page)
                                if isinstance(barrier_result, dict):
                                    capture_stability["frame_barrier"] = barrier_result
                            except Exception as exc:  # noqa: BLE001 - keep capture evidence
                                capture_stability["frame_barrier"] = {
                                    "synchronized": False,
                                    "frame_tree_match": False,
                                    "reasons": ["barrier-error"],
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                        # 先取 DOM 再截图：DOM 坐标与像素尽量同一时刻（差 1px 就会让
                        # 基线/几何评估失真）。整页截图：DOM_JS 坐标为整文档几何，画布
                        # 必须覆盖整页（否则视口以下区域的 bbox 会落在画布之外）。
                        frame_snapshot = collect_frame_dom(
                            page,
                            DOM_JS,
                            font_probe=font_probe,
                        )
                        nodes = frame_snapshot.nodes
                        font_resolution = frame_snapshot.font_resolution
                        try:
                            font_resources = page.evaluate(FONT_RESOURCES_JS)
                        except Exception:  # noqa: BLE001 - font evidence is optional
                            font_resources = []
                        frame_inventory = (
                            timeline.enrich_frame_inventory(frame_snapshot.inventory)
                            if timeline is not None
                            else frame_snapshot.inventory
                        )
                        frame_snapshot_errors = frame_snapshot.errors
                        frame_capture_truncated = frame_snapshot.truncated
                        page.screenshot(
                            path=str(image_p),
                            full_page=True,
                            timeout=max(1000, int(screenshot_timeout_ms)),
                        )
                        dom_p.write_text(
                            json.dumps(nodes, ensure_ascii=False), encoding="utf-8"
                        )
                        try:
                            diagnostics = build_dom_diagnostics(
                                page.evaluate(DOM_STRUCTURE_PROBE_JS),
                                nodes,
                                page.url,
                                frames=frame_inventory,
                            )
                            diagnostics_p.write_text(
                                json.dumps(diagnostics, ensure_ascii=False, indent=1),
                                encoding="utf-8",
                            )
                            logger.info(
                                "[%s] 结构诊断：capture_gaps=%s unsupported=%s",
                                label,
                                json.dumps(
                                    diagnostics.get("capture_gaps", {}),
                                    ensure_ascii=False,
                                ),
                                json.dumps(
                                    diagnostics.get("unsupported", {}),
                                    ensure_ascii=False,
                                ),
                            )
                        except Exception as exc:  # noqa: BLE001 - 诊断失败不影响采集
                            logger.debug("[%s] 结构诊断失败：%s", label, exc)
                        try:
                            final_url = page.url
                        except Exception:  # noqa: BLE001
                            pass
                        try:
                            page_title = (page.title() or "").strip()
                        except Exception:  # noqa: BLE001 - 拿不到页名不影响采集
                            page_title = ""
                    if attempts <= 1:
                        break
                    if attempt >= 1 and count <= prev:
                        logger.info(
                            "[%s] 节点数不再变多，采用最全的一遍：%d 个节点",
                            label,
                            best,
                        )
                        break
                    prev = count
            except Exception as exc:  # noqa: BLE001 - 导航异常也要留证
                error = f"{type(exc).__name__}: {exc}"
                logger.warning("[%s] 采集异常：%s", label, error)

            probe = _page_probe(page)
            final_url = str(probe.get("finalUrl") or final_url)
            page_title = str(probe.get("title") or page_title)
            if not image_p.exists():
                try:
                    page.screenshot(
                        path=str(image_p),
                        full_page=True,
                        timeout=max(1000, int(screenshot_timeout_ms)),
                    )
                except Exception as exc:  # noqa: BLE001
                    error = error or f"{type(exc).__name__}: {exc}"
            if not dom_p.exists():
                try:
                    frame_snapshot = collect_frame_dom(
                        page,
                        DOM_JS,
                        font_probe=font_probe,
                    )
                    nodes = frame_snapshot.nodes
                    font_resolution = frame_snapshot.font_resolution
                    frame_inventory = (
                        timeline.enrich_frame_inventory(frame_snapshot.inventory)
                        if timeline is not None
                        else frame_snapshot.inventory
                    )
                    frame_snapshot_errors = frame_snapshot.errors
                    frame_capture_truncated = frame_snapshot.truncated
                    dom_p.write_text(
                        json.dumps(nodes, ensure_ascii=False), encoding="utf-8"
                    )
                    try:
                        diagnostics = build_dom_diagnostics(
                            page.evaluate(DOM_STRUCTURE_PROBE_JS),
                            nodes,
                            page.url,
                            frames=frame_inventory,
                        )
                        diagnostics_p.write_text(
                            json.dumps(diagnostics, ensure_ascii=False, indent=1),
                            encoding="utf-8",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[%s] 结构诊断失败：%s", label, exc)
                except Exception:  # noqa: BLE001
                    pass
            state = classify_page_state(
                probe,
                url,
                status=status,
                error=error,
                navigation_budget_exhausted=True,
            )
            if font_resolution:
                state["font_resolution"] = font_resolution
            logger.info(
                "[%s] 页面状态=%s（%s），最终地址=%s",
                label,
                state["kind"],
                state["reason"],
                final_url,
            )
        finally:
            if timeline is not None:
                try:
                    navigation_timeline = timeline.snapshot()
                except Exception as exc:  # noqa: BLE001 - keep capture evidence
                    navigation_timeline_error = f"{type(exc).__name__}: {exc}"
            try:
                if context is not None:
                    context.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:  # noqa: BLE001
                pass

    if not image_p.exists():
        raise RuntimeError(f"[{label}] 未能截取页面：{error or 'unknown error'}")
    from PIL import Image

    with Image.open(image_p) as im:
        width, height = im.size
    return {
        "label": label,
        "browser_engine": browser_engine,
        "headless": headless,
        "profile": bool(user_data_dir),
        "storage_state": bool(storage_state),
        "image": str(image_p),
        "dom": str(dom_p) if dom_p.exists() else None,
        "diagnostics": str(diagnostics_p) if diagnostics_p.exists() else None,
        "m0_image": str(m0_image_p) if m0_image_p.exists() else None,
        "m0_dom": str(m0_dom_p) if m0_dom_p.exists() else None,
        "width": width,
        "height": height,
        "device_scale_factor": cfg.device_scale_factor,
        "viewport": viewport,
        "title": page_title,
        "final_url": final_url,
        "status": status,
        "page_state": state,
        "error": error,
        "capture_stability": capture_stability,
        "frame_inventory": frame_inventory,
        "frame_summary": summarize_frame_inventory(frame_inventory),
        "frame_snapshot_errors": frame_snapshot_errors,
        "frame_capture_truncated": frame_capture_truncated,
        "font_resolution": font_resolution,
        "font_resources": font_resources,
        "navigation_timeline": navigation_timeline,
        "navigation_timeline_error": navigation_timeline_error,
        "capture_profile": (
            "first-party-frame-strict/1.0"
            if block_cross_origin_frame_documents
            else "rendered-frame-state-strict/1.0"
        ),
        "frame_request_policy": {
            "profile_id": (
                "first-party-frame-strict/1.0"
                if block_cross_origin_frame_documents
                else "full-visible-frame-documents/1.0"
            ),
            "block_cross_origin_frame_documents": bool(
                block_cross_origin_frame_documents
            ),
            "blocked_document_count": len(blocked_frame_documents),
            "blocked_documents": blocked_frame_documents[:64],
            "truncated": len(blocked_frame_documents) > 64,
        },
        "navigation": classify_capture_navigation(
            url,
            final_url,
            error=error if _looks_like_navigation_error(error) else None,
            navigation_budget_exhausted=True,
        ),
    }


def _promote_attempt(result: dict, out: Path) -> None:
    """把选中的一次尝试复制成稳定的 00_* 产物。"""
    out.mkdir(parents=True, exist_ok=True)
    image = result.get("image")
    dom = result.get("dom")
    diagnostics = result.get("diagnostics")
    m0_image = result.get("m0_image")
    m0_dom = result.get("m0_dom")
    if image and Path(image).is_file():
        target = out / "00_screenshot.png"
        if Path(image).resolve() != target.resolve():
            shutil.copyfile(image, target)
    if dom and Path(dom).is_file():
        target = out / "00_dom.json"
        if Path(dom).resolve() != target.resolve():
            shutil.copyfile(dom, target)
    if diagnostics and Path(diagnostics).is_file():
        target = out / "00_dom_diagnostics.json"
        if Path(diagnostics).resolve() != target.resolve():
            shutil.copyfile(diagnostics, target)
    if m0_image and Path(m0_image).is_file():
        target = out / "00_screenshot_m0.png"
        if Path(m0_image).resolve() != target.resolve():
            shutil.copyfile(m0_image, target)
    if m0_dom and Path(m0_dom).is_file():
        target = out / "00_dom_m0.json"
        if Path(m0_dom).resolve() != target.resolve():
            shutil.copyfile(m0_dom, target)
    dom_target = out / "00_dom.json"
    if dom_target.is_file():
        try:
            nodes = json.loads(dom_target.read_text(encoding="utf-8"))
            layer_tree = build_layer_tree(nodes)
            (out / "00_layer_tree.json").write_text(
                json.dumps(layer_tree, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("层级树生成失败：%s", exc)


def _attempt_record(result: dict) -> dict:
    return {
        "label": result.get("label"),
        "browser_engine": result.get("browser_engine"),
        "headless": result.get("headless"),
        "profile": result.get("profile"),
        "storage_state": result.get("storage_state"),
        "final_url": result.get("final_url"),
        "http_status": result.get("status"),
        "title": result.get("title"),
        "page_state": result.get("page_state"),
        "image": result.get("image"),
        "dom": result.get("dom"),
        "diagnostics": result.get("diagnostics"),
        "m0_image": result.get("m0_image"),
        "m0_dom": result.get("m0_dom"),
        "device_scale_factor": result.get("device_scale_factor"),
        "viewport": result.get("viewport"),
        "error": result.get("error"),
        "capture_stability": result.get("capture_stability"),
        "navigation": result.get("navigation"),
        "frame_summary": result.get("frame_summary"),
        "frame_inventory": result.get("frame_inventory"),
        "frame_snapshot_errors": result.get("frame_snapshot_errors"),
        "frame_capture_truncated": result.get("frame_capture_truncated"),
        "font_resolution": result.get("font_resolution"),
        "navigation_timeline": result.get("navigation_timeline"),
        "navigation_timeline_error": result.get("navigation_timeline_error"),
        "capture_profile": result.get("capture_profile"),
        "frame_request_policy": result.get("frame_request_policy"),
    }


def _write_page_state(out: Path, page_state: dict) -> None:
    (out / "00_page_state.json").write_text(
        json.dumps(page_state, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _write_font_manifest(out: Path, result: dict) -> dict | None:
    dom_path = out / "00_dom.json"
    if not dom_path.is_file():
        return None
    try:
        nodes = json.loads(dom_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    resources = result.get("font_resources")
    if not isinstance(resources, list):
        resources = []
    manifest = build_font_manifest(resources, nodes)
    (out / "00_fonts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _real_session_candidates(cfg: "Config", storage_state: str | None) -> list[tuple]:
    """真实会话候选：持久化用户目录 > 登录态 JSON > 全新有头浏览器。"""
    candidates = []
    user_data_dir = getattr(cfg, "playwright_user_data_dir", None)
    if user_data_dir:
        candidates.append(("real_session_profile", False, None, user_data_dir))
    if storage_state:
        candidates.append(("real_session_state", False, storage_state, None))
    if getattr(cfg, "playwright_headed_fallback", True):
        candidates.append(("real_session_headed", False, None, None))
    return candidates


def capture_page(
    url: str,
    cfg: "Config",
    output_dir: str,
    *,
    browser_engine: str | None = None,
    capture_early_state: bool = False,
    screenshot_timeout_ms: int = 30000,
    capture_attempts: int | None = None,
    navigation_sync: Callable[[Any], None] | None = None,
    snapshot_sync: Callable[[Any], None] | None = None,
    block_cross_origin_frame_documents: bool = False,
    capture_navigation_timeline: bool = False,
) -> dict:
    """旧入口：单次采集，保留原有返回形状；额外带 page_state 等诊断字段。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    storage_state = _resolve_storage_state(cfg.playwright_storage_state)
    engine = normalize_browser_engine(
        browser_engine or getattr(cfg, "playwright_browser", DEFAULT_BROWSER_ENGINE)
    )
    label = "headless" if cfg.playwright_headless else "browser"
    result = _capture_session(
        url,
        cfg,
        out,
        label=label,
        headless=cfg.playwright_headless,
        storage_state=storage_state,
        attempts=(
            tuning.CAPTURE_ATTEMPTS
            if capture_attempts is None
            else max(1, int(capture_attempts))
        ),
        browser_engine=engine,
        capture_early_state=capture_early_state,
        screenshot_timeout_ms=screenshot_timeout_ms,
        navigation_sync=navigation_sync,
        snapshot_sync=snapshot_sync,
        block_cross_origin_frame_documents=block_cross_origin_frame_documents,
        capture_navigation_timeline=capture_navigation_timeline,
    )
    _promote_attempt(result, out)
    state = result.get("page_state") or {}
    page_state = {
        "requested_url": url,
        "final_url": result.get("final_url") or url,
        "kind": state.get("kind"),
        "confidence": state.get("confidence"),
        "reason": state.get("reason"),
        "signals": state.get("signals"),
        "attempts": [_attempt_record(result)],
        "fallback_used": False,
        "screenshot_source": result.get("label"),
        "screenshot_only": False,
        "requested_route": None,
        "browser_engine": engine,
        "capture_early_state": capture_early_state,
        "capture_stability": result.get("capture_stability"),
        "navigation": result.get("navigation"),
        "frame_inventory": result.get("frame_inventory") or [],
        "frame_summary": result.get("frame_summary")
        or summarize_frame_inventory(result.get("frame_inventory")),
        "frame_snapshot_errors": result.get("frame_snapshot_errors") or [],
        "frame_capture_truncated": bool(result.get("frame_capture_truncated")),
        "font_resolution": result.get("font_resolution") or {},
        "navigation_timeline": result.get("navigation_timeline"),
        "navigation_timeline_error": result.get("navigation_timeline_error"),
        "capture_profile": result.get("capture_profile"),
        "frame_request_policy": result.get("frame_request_policy"),
    }
    _write_page_state(out, page_state)
    result["page_state"] = page_state
    result["screenshot_only"] = False
    result["font_manifest"] = _write_font_manifest(out, result)
    result["capture_bundle"] = write_capture_bundle(
        out,
        requested_url=url,
        page_state={
            **page_state,
            "viewport": result.get("viewport"),
            "device_scale_factor": result.get("device_scale_factor"),
            "canvas_size": [result.get("width"), result.get("height")],
        },
        artifact_paths={
            "screenshot": out / "00_screenshot.png",
            "dom": out / "00_dom.json",
            "page_state": out / "00_page_state.json",
            "diagnostics": out / "00_dom_diagnostics.json",
            "m0_screenshot": out / "00_screenshot_m0.png",
            "m0_dom": out / "00_dom_m0.json",
            "layer_tree": out / "00_layer_tree.json",
            "fonts": out / "00_fonts.json",
        },
    )
    return result


def capture_page_with_fallback(
    url: str,
    cfg: "Config",
    output_dir: str,
    *,
    requested_route: str = "auto",
    allow_real_session: bool = True,
    browser_engine: str | None = None,
    capture_early_state: bool = False,
    screenshot_timeout_ms: int = 30000,
    capture_attempts: int | None = None,
    navigation_sync: Callable[[Any], None] | None = None,
    snapshot_sync: Callable[[Any], None] | None = None,
    block_cross_origin_frame_documents: bool = False,
    capture_navigation_timeline: bool = False,
) -> dict:
    """URL 采集 + 页面状态判定 + 真实浏览器会话降级。

    返回的 `page_state` 是最终状态（含所有尝试）。只有最终 `kind == content`
    才允许继续；若最终来自真实会话，`screenshot_only=True`，调用方应把截图
    当作输入，不要再用 DOM 直出。
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    storage_state = _resolve_storage_state(cfg.playwright_storage_state)
    engine = normalize_browser_engine(
        browser_engine or getattr(cfg, "playwright_browser", DEFAULT_BROWSER_ENGINE)
    )
    initial_label = "headless" if cfg.playwright_headless else "browser"
    initial = _capture_session(
        url,
        cfg,
        out,
        label=initial_label,
        headless=cfg.playwright_headless,
        storage_state=storage_state,
        attempts=(
            tuning.CAPTURE_ATTEMPTS
            if capture_attempts is None
            else max(1, int(capture_attempts))
        ),
        browser_engine=engine,
        capture_early_state=capture_early_state,
        screenshot_timeout_ms=screenshot_timeout_ms,
        navigation_sync=navigation_sync,
        snapshot_sync=snapshot_sync,
        block_cross_origin_frame_documents=block_cross_origin_frame_documents,
        capture_navigation_timeline=capture_navigation_timeline,
    )
    attempts = [initial]
    selected = initial
    screenshot_only = False

    initial_key = (engine, cfg.playwright_headless, storage_state, None)
    if initial["page_state"]["kind"] != PAGE_STATE_CONTENT and allow_real_session:
        for label, headless, state, user_data_dir in _real_session_candidates(
            cfg, storage_state
        ):
            if (engine, headless, state, user_data_dir) == initial_key:
                continue
            logger.info(
                "页面状态 %s，尝试真实浏览器会话：%s",
                initial["page_state"]["kind"],
                label,
            )
            try:
                result = _capture_session(
                    url,
                    cfg,
                    out,
                    label=label,
                    headless=headless,
                    storage_state=state,
                    user_data_dir=user_data_dir,
                    attempts=1,
                    browser_engine=engine,
                    capture_early_state=capture_early_state,
                    screenshot_timeout_ms=screenshot_timeout_ms,
                    navigation_sync=navigation_sync,
                    snapshot_sync=snapshot_sync,
                    block_cross_origin_frame_documents=block_cross_origin_frame_documents,
                    capture_navigation_timeline=capture_navigation_timeline,
                )
            except Exception as exc:  # noqa: BLE001 - 单次失败继续下一个候选
                error = f"{type(exc).__name__}: {exc}"
                result = {
                    "label": label,
                    "browser_engine": engine,
                    "headless": headless,
                    "profile": bool(user_data_dir),
                    "storage_state": bool(state),
                    "image": None,
                    "dom": None,
                    "width": 0,
                    "height": 0,
                    "title": "",
                    "final_url": url,
                    "status": None,
                    "page_state": {
                        "kind": PAGE_STATE_SOFT_BLOCK,
                        "confidence": 0.5,
                        "reason": "真实会话启动/采集失败：" + error,
                        "signals": {"navigation_error": error},
                    },
                    "error": error,
                }
            attempts.append(result)
            selected = result
            if (result.get("page_state") or {}).get("kind") == PAGE_STATE_CONTENT:
                screenshot_only = True
                break

    final_state = selected.get("page_state") or {}
    if final_state.get("kind") != PAGE_STATE_CONTENT:
        # 只要有任何一层看到了登录页，最终提示就按“需要登录”走，避免后续的
        # 验证码页把真正原因盖掉。
        login_attempt = next(
            (
                item
                for item in attempts
                if (item.get("page_state") or {}).get("kind") == PAGE_STATE_HARD_LOGIN
            ),
            None,
        )
        if login_attempt is not None:
            selected = login_attempt
            final_state = selected.get("page_state") or {}
        # 失败时也保留最后一张可见页面（通常是登录页/拦截页）作证据。
        promote = (
            selected
            if selected.get("image")
            else next((item for item in reversed(attempts) if item.get("image")), None)
        )
        if promote:
            _promote_attempt(promote, out)
    else:
        _promote_attempt(selected, out)

    page_state = {
        "requested_url": url,
        "final_url": selected.get("final_url") or url,
        "kind": final_state.get("kind"),
        "confidence": final_state.get("confidence"),
        "reason": final_state.get("reason"),
        "signals": final_state.get("signals"),
        "attempts": [_attempt_record(item) for item in attempts],
        "fallback_used": len(attempts) > 1,
        "screenshot_source": selected.get("label"),
        "screenshot_only": screenshot_only,
        "requested_route": requested_route,
        "browser_engine": engine,
        "capture_early_state": capture_early_state,
        "capture_stability": selected.get("capture_stability"),
        "navigation": selected.get("navigation"),
        "frame_inventory": selected.get("frame_inventory") or [],
        "frame_summary": selected.get("frame_summary")
        or summarize_frame_inventory(selected.get("frame_inventory")),
        "frame_snapshot_errors": selected.get("frame_snapshot_errors") or [],
        "frame_capture_truncated": bool(selected.get("frame_capture_truncated")),
        "font_resolution": selected.get("font_resolution") or {},
        "navigation_timeline": selected.get("navigation_timeline"),
        "navigation_timeline_error": selected.get("navigation_timeline_error"),
        "capture_profile": selected.get("capture_profile"),
        "frame_request_policy": selected.get("frame_request_policy"),
    }
    _write_page_state(out, page_state)
    result = dict(selected)
    result["page_state"] = page_state
    result["screenshot_only"] = screenshot_only
    result["font_manifest"] = _write_font_manifest(out, result)
    result["capture_bundle"] = write_capture_bundle(
        out,
        requested_url=url,
        page_state={
            **page_state,
            "viewport": selected.get("viewport"),
            "device_scale_factor": selected.get("device_scale_factor"),
            "canvas_size": [selected.get("width"), selected.get("height")],
        },
        artifact_paths={
            "screenshot": out / "00_screenshot.png",
            "dom": out / "00_dom.json",
            "page_state": out / "00_page_state.json",
            "diagnostics": out / "00_dom_diagnostics.json",
            "m0_screenshot": out / "00_screenshot_m0.png",
            "m0_dom": out / "00_dom_m0.json",
            "layer_tree": out / "00_layer_tree.json",
            "fonts": out / "00_fonts.json",
        },
    )
    return result
