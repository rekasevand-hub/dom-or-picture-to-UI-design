// Figma 插件主线程：接收来自 UI 的命令，调用 Figma API 创建/修改节点。

figma.showUI(__html__, { width: 320, height: 220 });

let actionQueue = Promise.resolve();
const PLUGIN_CONFIG_KEY = "figmaBridgePluginConfig";

function classifyFigmaError(err) {
  const message = String((err && err.message) || err || "unknown error");
  const lower = message.toLowerCase();
  if (lower.includes("view-only") || lower.includes("read-only")) {
    return { code: "VIEW_ONLY", category: "view-only", retryable: false, noResend: true, manualReview: true };
  }
  if (lower.includes("rate limit") || lower.includes("too many requests")) {
    return { code: "RATE_LIMITED", category: "rate-limited", retryable: true, noResend: false, manualReview: false };
  }
  if (lower.includes("token revoked") || lower.includes("unauthorized")) {
    return { code: "PLUGIN_TOKEN_REVOKED", category: "plugin-token-revoked", retryable: false, noResend: true, manualReview: true };
  }
  if (lower.includes("takeover") || lower.includes("connection replaced")) {
    return { code: "PLUGIN_TAKEOVER", category: "plugin-takeover", retryable: false, noResend: true, manualReview: true };
  }
  if (lower.includes("permission") || lower.includes("forbidden") || lower.includes("access denied")) {
    return { code: "PERMISSION_DENIED", category: "permission-denied", retryable: false, noResend: true, manualReview: true };
  }
  if (lower.includes("precondition") || lower.includes("modified") || lower.includes("conflict")) {
    return { code: "USER_MODIFICATION", category: "user-modification", retryable: false, noResend: true, manualReview: true };
  }
  if (lower.includes("not found") || lower.includes("node_not_found")) {
    return { code: "USER_MODIFICATION", category: "user-modification", retryable: false, noResend: true, manualReview: true };
  }
  return { code: "PLUGIN_OPERATION_FAILED", category: "unknown", retryable: false, noResend: true, manualReview: true };
}

figma.ui.onmessage = (msg) => {
  if (msg && msg.type === "plugin-config-request") {
    const configTask = actionQueue.then(() => loadPluginConfig());
    actionQueue = configTask.catch(() => {});
    return configTask;
  }
  if (msg && msg.type === "save-plugin-config") {
    const saveTask = actionQueue.then(() => savePluginConfig(msg.config));
    actionQueue = saveTask.catch(() => {});
    return saveTask;
  }
  // Figma dispatches UI messages as independent async tasks. Serializing here
  // keeps multi-client edit batches from interleaving on the same nodes.
  const task = actionQueue.then(() => handleIncomingMessage(msg));
  actionQueue = task.catch(() => {});
  return task;
};

async function loadPluginConfig() {
  let config = {
    bridgeUrl: "ws://localhost:8765",
    pluginToken: "",
  };
  try {
    const stored = await figma.clientStorage.getAsync(PLUGIN_CONFIG_KEY);
    if (stored && typeof stored === "object") {
      config = { ...config, ...stored };
    }
  } catch (err) {
    // Development plugin storage may be unavailable in a test harness.
  }
  figma.ui.postMessage({ type: "plugin-config", config });
}

async function savePluginConfig(config) {
  const normalized = {
    bridgeUrl: String((config && config.bridgeUrl) || "ws://localhost:8765").trim(),
    pluginToken: String((config && config.pluginToken) || "").trim(),
  };
  if (!normalized.bridgeUrl) {
    throw new Error("bridge URL is required");
  }
  await figma.clientStorage.setAsync(PLUGIN_CONFIG_KEY, normalized);
  figma.ui.postMessage({ type: "plugin-config-saved", config: normalized });
}

async function handleIncomingMessage(msg) {
  const { action, params } = msg;
  const requestId = msg && msg.requestId;
  try {
    const result = await handleAction(action, params);
    figma.ui.postMessage({
      type: "response",
      ...(requestId ? { requestId } : {}),
      result,
    });
  } catch (err) {
    const classification = classifyFigmaError(err);
    figma.ui.postMessage({
      type: "response",
      ...(requestId ? { requestId } : {}),
      error: err.message,
      code: classification.code,
      permissionOutcome: {
        category: classification.category,
        retryable: classification.retryable,
        no_resend: classification.noResend,
        manual_review: classification.manualReview,
      },
    });
  }
}

async function handleAction(action, params) {
  switch (action) {
    case "create_frame":
      return await createFrame(params);
    case "create_rectangle":
      return await createRectangle(params);
    case "create_ellipse":
      return await createEllipse(params);
    case "create_text":
      return await createText(params);
    case "create_image":
      return await createImage(params);
    case "apply_batch":
      return await applyBatch(params);
    case "apply_edit_batch":
      return await applyEditBatch(params);
    case "component_instance_probe":
      return await componentInstanceProbe(params);
    case "set_text":
      return await setText(params);
    case "set_name":
      return await setName(params);
    case "set_bounds":
      return await setBounds(params);
    case "set_visibility":
      return await setVisibility(params);
    case "replace_image_fill":
      return await replaceImageFill(params);
    case "image_fill_report":
      return await imageFillReport(params);
    case "export_frame":
      return await exportFrame(params);
    case "font_report":
      return await fontReport(params);
    case "font_probe":
      return await fontProbe(params);
    case "resolve_font":
      return await resolveFont(params);
    case "remove_nodes_by_name":
      return await removeNodesByName(params);
    case "cleanup_owned_job":
      return await cleanupOwnedJob(params);
    case "ownership_report":
      return await ownershipReport(params);
    case "set_autolayout":
      return await setAutoLayout(params);
    case "set_layout_flow":
      return await setLayoutFlow(params);
    case "set_grid_child_overrides":
      return await setGridChildOverrides(params);
    case "font_strict_probe":
      return await fontStrictProbe(params);
    case "get_node_tree":
      return await getNodeTree(params);
    default:
      throw new Error(`未知命令: ${action}`);
  }
}

// CSS color -> Figma RGB(0..1)。只认 #RGB/#RRGGBB；transparent/空/非法返回 null，
// 调用方按“无填充”处理（DesignSpec 的 fillColor 是 computed style 原值，
// 输入框/描边按钮会是 transparent）——不能直接 parseInt 否则 NaN 会让 set_fills 报错。
function hexToRgb(hex) {
  if (!hex || typeof hex !== "string") return null;
  const rgbMatch = hex.trim().match(
    /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*[\d.]+)?\s*\)$/i,
  );
  if (rgbMatch) {
    return {
      r: Math.max(0, Math.min(255, Number(rgbMatch[1]))) / 255,
      g: Math.max(0, Math.min(255, Number(rgbMatch[2]))) / 255,
      b: Math.max(0, Math.min(255, Number(rgbMatch[3]))) / 255,
    };
  }
  const s = hex.trim().replace("#", "");
  if (!/^([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(s)) return null;
  const full = s.length === 3 ? s.split("").map((c) => c + c).join("") : s;
  return {
    r: parseInt(full.substring(0, 2), 16) / 255,
    g: parseInt(full.substring(2, 4), 16) / 255,
    b: parseInt(full.substring(4, 6), 16) / 255,
  };
}

function gradientStopsFrom(params) {
  const source = Array.isArray(params.detailedStops)
    ? params.detailedStops
    : Array.isArray(params.stops)
      ? params.stops.map((color, index, all) => ({
        color,
        offset: all.length <= 1 ? 0 : index / (all.length - 1),
      }))
      : [];
  const stops = [];
  for (const item of source) {
    const color = hexToRgb(item && item.color);
    if (!color) continue;
    const rawPosition = Number(item.offset);
    stops.push({
      color: { ...color, a: 1 },
      position: Math.max(0, Math.min(1, isFinite(rawPosition) ? rawPosition : 0)),
    });
  }
  stops.sort((a, b) => a.position - b.position);
  return stops;
}

function gradientTransformForAngle(value) {
  const angle = Number(value);
  const radians = (isFinite(angle) ? angle : 90) * Math.PI / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return [
    [cos, -sin, 0.5 - 0.5 * cos + 0.5 * sin],
    [sin, cos, 0.5 - 0.5 * sin - 0.5 * cos],
  ];
}

function gradientPaint(params) {
  if (!params || typeof params !== "object") return null;
  const stops = gradientStopsFrom(params);
  if (stops.length < 2) return null;
  return {
    type: String(params.type || "").toLowerCase() === "radial"
      ? "GRADIENT_RADIAL"
      : "GRADIENT_LINEAR",
    gradientTransform: gradientTransformForAngle(params.angle),
    gradientStops: stops,
  };
}

function applyStyle(node, params) {
  const gradient = gradientPaint(params.gradient);
  const fill = hexToRgb(params.fillColor);
  if (gradient) {
    node.fills = [gradient];
  } else if (fill) {
    node.fills = [{ type: "SOLID", color: fill }];
  } else if (params.fillColor) {
    node.fills = [];  // transparent / 非法值 -> 无填充（描边按钮、纯边框输入框）
  }
  const stroke = hexToRgb(params.borderColor);
  if (stroke && params.borderWidth > 0) {
    node.strokes = [{ type: "SOLID", color: stroke }];
    node.strokeWeight = params.borderWidth;
    // CSS 的 border 画在盒子**内侧**；Figma 默认 CENTER 会让边框每边外扩
    // borderWidth/2（1px 边框即每边 0.5px），几何上与原页对不上。
    try {
      node.strokeAlign = "INSIDE";
    } catch (err) {
      // 个别节点类型不支持 strokeAlign：保持默认
    }
  }
  applyRadius(node, params);
  applyOpacity(node, params);
  applyEffects(node, params);
}

function mixHex(hex, whiteWeight) {
  const rgb = hexToRgb(hex) || { r: 0, g: 0, b: 0 };
  const weight = Math.max(0, Math.min(1, Number(whiteWeight) || 0));
  return {
    r: rgb.r * (1 - weight) + weight,
    g: rgb.g * (1 - weight) + weight,
    b: rgb.b * (1 - weight) + weight,
  };
}

// CSS inset/outset borders are two-color bevels, while Figma strokes have one
// color. Build the four visible edge bands as a transparent frame so the
// browser's default iframe border is not flattened into a solid black box.
async function createBevelBorder(params) {
  const width = Number(params.width) || 100;
  const height = Number(params.height) || 40;
  const borderWidth = Math.max(1, Math.min(
    Number(params.borderWidth) || 1, Math.floor(Math.min(width, height) / 2)));
  const style = String(params.borderStyle || "inset").toLowerCase();
  const dark = mixHex(params.borderColor, 154 / 255);
  const light = mixHex(params.borderColor, 238 / 255);
  const topLeft = style === "outset" || style === "ridge" ? light : dark;
  const bottomRight = style === "outset" || style === "ridge" ? dark : light;

  const frame = figma.createFrame();
  applyGeometry(frame, { ...params, width, height });
  frame.name = params.name || "Bevel border";
  frame.layoutMode = "NONE";
  frame.clipsContent = false;
  const fill = hexToRgb(params.fillColor);
  frame.fills = fill ? [{ type: "SOLID", color: fill }] : [];
  appendToParent(frame, params);
  applyPluginData(frame, params);

  const bands = [
    { x: 0, y: 0, width, height: borderWidth, color: topLeft },
    { x: 0, y: 0, width: borderWidth, height, color: topLeft },
    { x: 0, y: height - borderWidth, width, height: borderWidth, color: bottomRight },
    { x: width - borderWidth, y: 0, width: borderWidth, height, color: bottomRight },
  ];
  for (const band of bands) {
    const edge = figma.createRectangle();
    edge.x = band.x;
    edge.y = band.y;
    edge.resize(band.width, band.height);
    edge.fills = [{ type: "SOLID", color: band.color }];
    edge.name = `${frame.name} border`;
    frame.appendChild(edge);
  }
  applyOpacity(frame, params);
  return frame.id;
}

// 圆角：IR 的 borderRadius 是均匀标量；四角不同时另带 borderRadiusCorners
// [tl,tr,br,bl]（computed `border-radius: 4px 4px 0 0` 在采集侧解出来的）。
// 旧实现只写标量，非均匀简写整条丢圆角 —— 顶部圆角的卡片/标签页会画成直角。
function applyRadius(node, params) {
  // FRAME 也支持圆角：容器当 Auto Layout Frame 用时，圆角要画在 Frame 上
  if (node.type !== "RECTANGLE" && node.type !== "FRAME") return;
  const corners = radiusCorners(params);
  if (!corners) return;
  try {
    node.topLeftRadius = corners[0];
    node.topRightRadius = corners[1];
    node.bottomRightRadius = corners[2];
    node.bottomLeftRadius = corners[3];
  } catch (err) {
    // 个别节点类型不支持圆角：保持默认
  }
}

function radiusCorners(params) {
  const list = params && params.borderRadiusCorners;
  if (list && list.length === 4) {
    const nums = [];
    for (const v of list) nums.push(Math.max(0, Number(v) || 0));
    if (nums.some((v) => v > 0)) return nums;
    return null;
  }
  const scalar = Number(params && params.borderRadius) || 0;
  if (scalar > 0) return [scalar, scalar, scalar, scalar];
  return null;
}

// 元素透明度（computed `opacity`）：整棵子树的合成系数，Figma 用 node.opacity。
// 采集侧只带 0<op<1 的值；缺失 / 1 时不动（保持默认 1，老产物无差异）。
function applyOpacity(node, params) {
  const op = Number(params && params.opacity);
  if (isFinite(op) && op > 0 && op < 1) {
    try {
      node.opacity = op;
    } catch (err) {}
  }
}

// 盒子投影（computed box-shadow 解析结果）：antd 固定列滚动阴影、卡片/菜单投影。
function applyEffects(node, params) {
  if (!params.shadows || !params.shadows.length || !("effects" in node)) return;
  node.effects = params.shadows.map((s) => {
    const rgb = hexToRgb(s.color) || { r: 0, g: 0, b: 0 };
    return {
      type: "DROP_SHADOW",
      color: { r: rgb.r, g: rgb.g, b: rgb.b, a: s.alpha === undefined ? 1 : s.alpha },
      offset: { x: s.dx || 0, y: s.dy || 0 },
      radius: s.blur || 0,
      spread: s.spread || 0,
      visible: true,
      blendMode: "NORMAL",
    };
  });
}

function applyGeometry(node, params) {
  node.x = params.x || 0;
  node.y = params.y || 0;
  node.resize(params.width || 100, params.height || 40);
}

function appendToParent(node, params) {
  const parentId = params && params.parentId;
  const parent = parentId ? figma.getNodeById(parentId) : null;
  if (parentId) {
    if (!parent || !("appendChild" in parent)) {
      throw new Error(`PARENT_NOT_FOUND: ${parentId}`);
    }
    parent.appendChild(node);
  } else {
    figma.currentPage.appendChild(node);
  }
  applyName(node, params);
}

function applyPluginData(node, params) {
  const values = params && params.pluginData;
  if (!values || typeof values !== "object"
      || typeof node.setPluginData !== "function") {
    return;
  }
  for (const [key, value] of Object.entries(values)) {
    if (!String(key).startsWith("figma_auto_agent.")) continue;
    if (value === null || value === undefined) continue;
    node.setPluginData(String(key), String(value));
  }
}

function validateParent(params) {
  const parentId = params && params.parentId;
  if (!parentId) return;
  const parent = figma.getNodeById(parentId);
  if (!parent || !("appendChild" in parent)) {
    throw new Error(`PARENT_NOT_FOUND: ${parentId}`);
  }
}

// DesignSpec 的 name（采集端算好的图层可读名，形如 `a.ant-btn "新建"`）。
// 没有就保留 Figma 默认名，不写空串。
function applyName(node, params) {
  if (params && params.name) {
    node.name = params.name;
  }
}

async function createFrame(params) {
  validateParent(params);
  const frame = figma.createFrame();
  applyGeometry(frame, params);
  frame.name = params.name || "Screen";
  frame.layoutMode = "NONE";  // 不启用 Auto Layout
  if (params.clipsContent !== undefined) {
    frame.clipsContent = params.clipsContent;
  }
  const frameFill = hexToRgb(params.fillColor || params.backgroundColor);
  if (frameFill) {
    frame.fills = [{ type: "SOLID", color: frameFill }];
  } else if (params.transparent) {
    // 裁剪容器不画底：figma.createFrame() 默认带白填充，
    // 不清掉会盖住它下面的内容。
    frame.fills = [];
  }
  if (params.applyStyle) {
    // 这个容器整体当 Auto Layout Frame 用：底色/描边/圆角/投影都画在 Frame 自身上
    // （fills 已按上面那条路设好；没有 fillColor 时 applyStyle 不碰 fills）。
    applyStyle(frame, params);
  }
  appendToParent(frame, params);
  applyPluginData(frame, params);
  return frame.id;
}

async function createRectangle(params) {
  validateParent(params);
  if (params.borderStyle && params.borderWidth > 0) {
    const bevelStyles = ["inset", "outset", "groove", "ridge"];
    if (bevelStyles.indexOf(String(params.borderStyle).toLowerCase()) >= 0) {
      return await createBevelBorder(params);
    }
  }
  const rect = figma.createRectangle();
  applyGeometry(rect, params);
  applyStyle(rect, params);
  appendToParent(rect, params);
  applyPluginData(rect, params);
  return rect.id;
}

async function createEllipse(params) {
  validateParent(params);
  const ellipse = figma.createEllipse();
  applyGeometry(ellipse, params);
  applyStyle(ellipse, params);
  appendToParent(ellipse, params);
  applyPluginData(ellipse, params);
  return ellipse.id;
}

const DEFAULT_TEXT_FONT = { family: "Inter", style: "Regular" };

// DesignSpec 的 fontFamily 是 CSS 字体栈（computed style 原值），Figma 只认
// 具体字体名：按顺序拆开逐个尝试，取第一个本机已安装的；都没有就退回 Inter。
function parseFontFamilies(fontFamily) {
  if (!fontFamily || typeof fontFamily !== "string") return [];
  return fontFamily
    .split(",")
    .map((family) => family.trim().replace(/^["']|["']$/g, ""))
    .filter(Boolean);
}

// 字重 → Figma 样式名阶梯（100..900 每档 100）。同一个字重在各个字体族里
// 的样式名写法不统一（Extra Light / ExtraLight / Ultra Light…），每档给几个别名。
const WEIGHT_LADDER = [
  { w: 100, names: ["Thin", "Hairline"] },
  { w: 200, names: ["Extra Light", "ExtraLight", "Ultra Light", "UltraLight"] },
  { w: 300, names: ["Light"] },
  { w: 350, names: ["Semilight", "Semi Light"] },
  { w: 400, names: ["Regular", "Normal", "Book", "Roman"] },
  { w: 500, names: ["Medium"] },
  { w: 600, names: ["Semi Bold", "SemiBold", "Demi Bold", "DemiBold"] },
  { w: 700, names: ["Bold"] },
  { w: 800, names: ["Extra Bold", "ExtraBold", "Ultra Bold", "UltraBold"] },
  { w: 900, names: ["Black", "Heavy"] },
];

// computed style 的字重可能是 "bold" / "normal" / "700" / 700，先归一成数值。
function normalizeWeight(fontWeight) {
  if (fontWeight === null || fontWeight === undefined || fontWeight === "") return null;
  if (typeof fontWeight === "number") return isNaN(fontWeight) ? null : fontWeight;
  const raw = String(fontWeight).trim().toLowerCase();
  if (raw === "bold" || raw === "bolder") return 700;
  if (raw === "normal" || raw === "regular") return 400;
  if (raw === "lighter") return 300;
  const num = parseFloat(raw);
  return isNaN(num) ? null : num;
}

// 目标字重 → 依次尝试的样式名，按与目标的距离从近到远（与 CSS 的字体匹配同向：
// 600 在只有 Regular/Bold 的族里应落到 Bold，而不是 Regular）。
function fontStyleIsItalic(fontStyle) {
  const raw = String(fontStyle || "").trim().toLowerCase();
  return raw === "italic" || raw === "oblique";
}

function styleCandidates(fontWeight, fontStyle) {
  const want = normalizeWeight(fontWeight);
  const base = want === null ? ["Regular", "Bold"] : (() => {
    const ordered = WEIGHT_LADDER.slice().sort(
      (a, b) => Math.abs(a.w - want) - Math.abs(b.w - want));
    const out = [];
    const addStyle = (name) => {
      for (const candidate of [
        name,
        `${name} Text`,
        `${name} Small`,
        `${name} Display`,
      ]) {
        if (out.indexOf(candidate) < 0) out.push(candidate);
      }
    };
    for (const step of ordered) {
      for (const name of step.names) {
        addStyle(name);
      }
    }
    return out;
  })();
  if (!fontStyleIsItalic(fontStyle)) return base;
  const regularNames = new Set(["regular", "normal", "book", "roman"]);
  const italicNames = base.map((name) => (
    regularNames.has(name.toLowerCase()) ? "Italic" : `${name} Italic`
  ));
  return Array.from(new Set([...italicNames, ...base]));
}

// 本机真实可用的 face 表：族名小写 → { family, styles: 小写样式名 → 真实样式名 }。
//
// 必须查真表而不是拿 CSS 原文去 loadFontAsync：fontFamily 是 CSS 字体栈，
// 族名的大小写/别名跟 Figma 的不一定一致（典型：CSS 写 `simsun`，Figma 里叫
// `SimSun`）。旧实现匹配不上就一路退到栈尾的 Arial —— 拉丁字形能用，CJK 只能
// 落到 Figma 的默认兜底字，字重与字形都和原页对不上（实测同一段 16px bold 标题
// 墨量比原页多 35%、笔画中位宽 2px→3px）。
let _faceTable = null;
async function loadFaceTable() {
  if (_faceTable) return _faceTable;
  const all = (await figma.listAvailableFontsAsync()) || [];
  const table = new Map();
  for (const item of all) {
    const name = (item && item.fontName) || {};
    if (!name.family) continue;
    const key = String(name.family).toLowerCase();
    let entry = table.get(key);
    if (!entry) {
      entry = { family: name.family, styles: new Map() };
      table.set(key, entry);
    }
    entry.styles.set(String(name.style || "Regular").toLowerCase(), name.style);
  }
  _faceTable = table;
  return table;
}

// 按 CSS 字体栈的语义解析：**先按顺序找第一个本机存在的族**，再在该族内部挑最
// 接近目标字重的 face（浏览器就是这么做的，不会因为缺字重跳到下一个族）。
async function loadFirstAvailableFont(fontFamily, fontWeight, strict, fontStyle) {
  const table = await loadFaceTable();
  const requested = parseFontFamilies(fontFamily);
  for (const family of parseFontFamilies(fontFamily)) {
    const entry = table.get(family.toLowerCase());
    if (!entry) continue;
    for (const style of styleCandidates(fontWeight, fontStyle)) {
      const real = entry.styles.get(style.toLowerCase());
      if (real !== undefined) {
        await figma.loadFontAsync({ family: entry.family, style: real });
        return { family: entry.family, style: real };
      }
    }
    // 族在、但一个候选档位都没有：留在本族里取一个，别跨族跳到没有 CJK 的 Arial
    const first = entry.styles.values().next();
    if (!first.done) {
      await figma.loadFontAsync({ family: entry.family, style: first.value });
      return { family: entry.family, style: first.value };
    }
  }
  if (strict) {
    throw new Error(`FONT_NOT_AVAILABLE: ${requested.join(", ") || "(empty family)"}`);
  }
  await figma.loadFontAsync(DEFAULT_TEXT_FONT);
  return DEFAULT_TEXT_FONT;
}

async function resolveFont(params) {
  const table = await loadFaceTable();
  const requestedFamilies = parseFontFamilies(params && params.family);
  const requestedStyle = String((params && params.style) || "Regular");
  const requestedWeight = normalizeWeight(params && params.weight);
  const candidates = [];
  for (const family of requestedFamilies) {
    const entry = table.get(family.toLowerCase());
    if (entry) candidates.push({ requested: family, entry });
  }
  if (!candidates.length) {
    for (const entry of table.values()) candidates.push({ requested: null, entry });
  }
  if (!candidates.length) {
    return {
      requested: {
        family: requestedFamilies.join(", "),
        style: requestedStyle,
        weight: requestedWeight,
      },
      selected: null,
      status: "blocked",
      candidateCount: 0,
    };
  }
  const candidate = candidates[0];
  const entry = candidate.entry;
  const styles = styleCandidates(requestedWeight, requestedStyle);
  let selectedStyle = entry.styles.get(requestedStyle.toLowerCase());
  let status = "exact";
  if (selectedStyle === undefined) {
    for (const style of styles) {
      selectedStyle = entry.styles.get(style.toLowerCase());
      if (selectedStyle !== undefined) break;
    }
    status = "style-fallback";
  }
  if (selectedStyle === undefined) {
    const first = entry.styles.values().next();
    selectedStyle = first.done ? "Regular" : first.value;
    status = "style-fallback";
  }
  if (candidate.requested === null) {
    status = "family-fallback";
  }
  const selected = { family: entry.family, style: selectedStyle };
  try {
    await figma.loadFontAsync(selected);
  } catch (err) {
    return {
      requested: {
        family: requestedFamilies.join(", "),
        style: requestedStyle,
        weight: requestedWeight,
      },
      selected,
      status: "blocked",
      candidateCount: candidates.length,
      error: String(err && err.message ? err.message : err),
    };
  }
  return {
    requested: {
      family: requestedFamilies.join(", "),
      style: requestedStyle,
      weight: requestedWeight,
    },
    selected,
    status,
    candidateCount: candidates.length,
  };
}

// 字距：IR 的 letterSpacing 是 px（可负），Figma 用 {unit:"PIXELS"}。CSS 的
// `letter-spacing` 本来就以 px 计，两端（Figma / SVG）都按同一口径落。
function applyLetterSpacing(text, params) {
  const ls = Number(params && params.letterSpacing);
  if (isFinite(ls) && ls !== 0) {
    try {
      text.letterSpacing = { unit: "PIXELS", value: ls };
    } catch (err) {}
  }
}

async function createText(params) {
  validateParent(params);
  // 先解析字体再建节点：strict 失败时不留下未挂载的孤立文本节点。
  const resolvedFont = await loadFirstAvailableFont(
    params.fontFamily,
    params.fontWeightValue === undefined
      ? params.fontWeight
      : params.fontWeightValue,
    params.fontPolicy === "strict",
    params.fontStyle
  );
  const text = figma.createText();
  // 必须先落地字体，再写 characters（否则按创建时的默认字体排版）
  text.fontName = resolvedFont;
  text.characters = params.text || "";
  text.fontSize = params.fontSize || 16;
  const richRuns = Array.isArray(params.richRuns) ? params.richRuns : [];
  for (const run of richRuns) {
    const start = Math.max(0, Math.min(text.characters.length, Number(run.start) || 0));
    const end = Math.max(start, Math.min(text.characters.length, Number(run.end) || start));
    if (end <= start) continue;
    const style = run.style || {};
    const runFont = await loadFirstAvailableFont(
      style.fontFamily || params.fontFamily,
      style.fontWeight === undefined ? params.fontWeightValue : style.fontWeight,
      params.fontPolicy === "strict",
      style.fontStyle || params.fontStyle,
    );
    try { text.setRangeFontName(start, end, runFont); } catch (err) {}
    const runSize = Number(style.fontSize);
    if (runSize > 0) {
      try { text.setRangeFontSize(start, end, runSize); } catch (err) {}
    }
    const runColor = hexToRgb(style.textColor || params.textColor);
    if (runColor) {
      try {
        text.setRangeFills(start, end, [{ type: "SOLID", color: runColor }]);
      } catch (err) {}
    }
  }
  // CSS line-height affects the glyph position even for single-line text.
  // Apply it before the single/multi-line branches so Figma does not use its
  // default line box for one-line blocks.
  const lineHeight = Number(params.lineHeight);
  if (lineHeight > 0) {
    try {
      text.lineHeight = { unit: "PIXELS", value: lineHeight };
    } catch (err) {}
  }
  applyLetterSpacing(text, params);
  const textColor = hexToRgb(params.textColor);
  if (textColor) {
    text.fills = [{ type: "SOLID", color: textColor }];
  }
  // 先挂树再定位：x/y 是相对父级的坐标，appendChild 不会保留绝对位置，
  // 先 append 才不会在非原点父级下跳位。
  appendToParent(text, params);
  applyPluginData(text, params);
  const singleLine = !!params.singleLine;
  const boundedText = !!params.boundedText && !singleLine;
  if (boundedText) {
    try {
      text.textAutoResize = "NONE";
      text.resize(
        Math.max(1, Number(params.width) || text.width),
        Math.max(1, Number(params.height) || text.height),
      );
    } catch (err) {}
  } else if (singleLine) {
    try {
      text.textAutoResize = "WIDTH_AND_HEIGHT";
    } catch (err) {}
  }
  const lines = params.lines;
  if (lines && lines.length > 1) {
    // 折行文本：断点已经由 IR（text_wrap）按估算字宽算好，这里只负责落地。
    // 显式换行 + 固定宽度 + 只让高度自适应：Figma 若再按真实字宽自动换行，
    // 会多折出一行把盒子撑破（估算再准也不敢保证与真实字体度量逐字一致）。
    text.characters = lines.join("\n");
    const boxWidth = params.width || text.width;
    try {
      text.textAutoResize = boundedText ? "NONE" : "HEIGHT";
      text.resize(boxWidth, text.height);
    } catch (err) {}
    const align = params.textAlign === "center" ? "CENTER"
                : params.textAlign === "end" ? "RIGHT" : "LEFT";
    try { text.textAlignHorizontal = align; } catch (err) {}
    text.x = params.x || 0;
    text.y = (params.y || 0) + Math.max(
      0,
      ((params.height || 0) - text.height) / 2
    );
    return text.id;
  }
  if (params.textAnchor === "start") {
    // 行框文本（混合内容控件里的一段直接文本，如 <a><i/>编辑</a>）：横向从行框
    // 左缘起排。A browser-measured single line already carries its real
    // text line box, so keep its top edge instead of centering it in the
    // larger element box.
    text.x = params.x || 0;
    text.y = Array.isArray(params.lines) && params.lines.length === 1
      ? (params.y || 0)
      : (params.y || 0) + ((params.height || 0) - text.height) / 2;
  } else if (params.textAnchor === "middle") {
    // 控件文字：DesignSpec 给的是盒子中心 x + 盒子 y/height，
    // 要按实测宽高反算左上角（SVG 用 text-anchor=middle 天然就对）。
    text.x = (params.x || 0) - text.width / 2;
    text.y = (params.y || 0) + ((params.height || 0) - text.height) / 2;
  } else {
    // 单行块级文本的 CSS text-align 也必须落地：Figma 文本默认 WIDTH_AND_HEIGHT，
    // 只把 x 设成盒子左缘会永远左对齐（页脚版权行就是这样整体左偏的）。
    // 这里保持自动宽高、不强制换行，只按盒子宽与实测文字宽反算落点，
    // 与 CSS 单行居中的像素结果一致，也不会把 nowrap 文本挤折行。
    let tx = params.x || 0;
    const boxWidth = Number(params.width) || 0;
    const align = String(params.textAlign || "").toLowerCase();
    if (boxWidth > text.width + 0.5) {
      if (align === "center") tx += (boxWidth - text.width) / 2;
      else if (align === "right" || align === "end") tx += boxWidth - text.width;
    }
    text.x = tx;
    text.y = params.y || 0;
  }
  return text.id;
}

async function createImage(params) {
  validateParent(params);
  const imageBase64 = params.imageBase64 || "";
  if (!imageBase64) {
    throw new Error("create_image 缺少 imageBase64 参数");
  }
  const bytes = Uint8Array.from(atob(imageBase64), (c) => c.charCodeAt(0));
  const image = figma.createImage(bytes);
  const rect = figma.createRectangle();
  applyGeometry(rect, params);
  // FILL(cover)：crop 是按元素盒子裁好的像素，必须铺满；
  // FIT 在宽高比不匹配时会留白边，与截图对不上。
  rect.fills = [{ type: "IMAGE", imageHash: image.hash, scaleMode: "FILL" }];

  // avatar 圆形蒙版：四个角圆角半径设为宽度一半
  if (params.isAvatar && rect.type === "RECTANGLE") {
    const r = (params.width || 100) / 2;
    rect.topLeftRadius = r;
    rect.topRightRadius = r;
    rect.bottomLeftRadius = r;
    rect.bottomRightRadius = r;
  }
  applyEffects(rect, params);      // 像素底/图片上的滚动阴影

  appendToParent(rect, params);
  applyPluginData(rect, params);
  return rect.id;
}

const TRANSACTION_CREATE_ACTIONS = new Set([
  "create_frame",
  "create_rectangle",
  "create_ellipse",
  "create_text",
  "create_image",
]);

const OWNERSHIP_OWNER = "figma_auto_agent";
const OWNERSHIP_OWNER_KEY = "figma_auto_agent.owner";
const OWNERSHIP_JOB_KEY = "figma_auto_agent.job_id";
const OWNERSHIP_REGION_KEY = "figma_auto_agent.region_id";

function markOwnedNode(node, jobId, regionId) {
  if (!node || typeof node.setPluginData !== "function") {
    throw new Error(`OWNERSHIP_MARKER_UNSUPPORTED: ${node && node.id}`);
  }
  node.setPluginData(OWNERSHIP_OWNER_KEY, OWNERSHIP_OWNER);
  node.setPluginData(OWNERSHIP_JOB_KEY, jobId);
  if (regionId) {
    node.setPluginData(OWNERSHIP_REGION_KEY, String(regionId));
  }
}

async function applyBatch(params) {
  const transactionId = String(params.transactionId || "");
  const actions = Array.isArray(params.actions) ? params.actions : [];
  if (!transactionId) {
    return {
      status: "rejected",
      transactionId,
      error: "transactionId is required for ownership marking",
      committed: [],
      rollback: { attempted: 0, removed: 0, failed: [] },
    };
  }
  if (!actions.length) {
    return {
      status: "rejected",
      transactionId,
      error: "empty transaction",
      committed: [],
      rollback: { attempted: 0, removed: 0, failed: [] },
    };
  }
  const unsupported = actions
    .map((item) => String((item && item.action) || ""))
    .filter((action) => !TRANSACTION_CREATE_ACTIONS.has(action));
  if (unsupported.length) {
    return {
      status: "rejected",
      transactionId,
      error: "transaction contains unsupported actions",
      unsupportedActions: Array.from(new Set(unsupported)),
      committed: [],
      rollback: { attempted: 0, removed: 0, failed: [] },
    };
  }

  const committed = [];
  const createdNodeIds = [];
  let markedCount = 0;
  for (let index = 0; index < actions.length; index += 1) {
    const item = actions[index] || {};
    const action = String(item.action || "");
    const actionParams = item.params || {};
    try {
      const result = await handleAction(action, actionParams);
      committed.push({ index, action, result });
      if (typeof result === "string" && result) {
        createdNodeIds.push(result);
        markOwnedNode(
          figma.getNodeById(result),
          transactionId,
          actionParams.regionId
        );
        markedCount += 1;
      }
    } catch (err) {
      const rollbackFailures = [];
      let removed = 0;
      for (const nodeId of createdNodeIds.slice().reverse()) {
        const node = figma.getNodeById(nodeId);
        if (!node) continue;
        try {
          node.remove();
          removed += 1;
        } catch (removeError) {
          rollbackFailures.push({
            nodeId,
            error: removeError.message,
          });
        }
      }
      return {
        status: "partial",
        transactionId,
        committed,
        failed: {
          index,
          action,
          error: err.message,
        },
        rollback: {
          attempted: createdNodeIds.length,
          removed,
          failed: rollbackFailures,
        },
        ownership: {
          marker: "plugin-data-v1",
          owner: OWNERSHIP_OWNER,
          jobId: transactionId,
          marked: markedCount,
        },
      };
    }
  }
  return {
    status: "committed",
    transactionId,
    committed,
    rollback: { attempted: 0, removed: 0, failed: [] },
    ownership: {
      marker: "plugin-data-v1",
      owner: OWNERSHIP_OWNER,
      jobId: transactionId,
      marked: markedCount,
    },
  };
}

function collectOwnedNodes(node, jobId, output) {
  const children = Array.isArray(node.children) ? node.children : [];
  for (const child of children) {
    collectOwnedNodes(child, jobId, output);
  }
  if (
    typeof node.getPluginData === "function" &&
    node.getPluginData(OWNERSHIP_OWNER_KEY) === OWNERSHIP_OWNER &&
    node.getPluginData(OWNERSHIP_JOB_KEY) === jobId
  ) {
    output.push(node);
  }
}

async function cleanupOwnedJob(params) {
  const jobId = String((params && params.jobId) || "");
  if (!jobId) {
    return {
      status: "rejected",
      jobId,
      error: "jobId is required",
      matched: 0,
      removed: 0,
      failed: [],
    };
  }
  const matchedNodes = [];
  collectOwnedNodes(figma.currentPage, jobId, matchedNodes);
  let removed = 0;
  const failed = [];
  for (const node of matchedNodes) {
    try {
      node.remove();
      removed += 1;
    } catch (err) {
      failed.push({ nodeId: node.id, error: err.message });
    }
  }
  return {
    status: failed.length ? "partial" : "cleaned",
    jobId,
    owner: OWNERSHIP_OWNER,
    matched: matchedNodes.length,
    removed,
    failed,
  };
}

async function ownershipReport(params) {
  const jobId = String((params && params.jobId) || "");
  if (!jobId) {
    return {
      status: "rejected",
      jobId,
      error: "jobId is required",
      matched: 0,
      nodes: [],
    };
  }
  const matchedNodes = [];
  collectOwnedNodes(figma.currentPage, jobId, matchedNodes);
  return {
    status: "reported",
    jobId,
    owner: OWNERSHIP_OWNER,
    matched: matchedNodes.length,
    nodes: matchedNodes.map((node) => ({
      nodeId: node.id,
      name: node.name,
      type: node.type,
      owner: node.getPluginData(OWNERSHIP_OWNER_KEY),
      jobId: node.getPluginData(OWNERSHIP_JOB_KEY),
      regionId: node.getPluginData(OWNERSHIP_REGION_KEY) || null,
    })),
  };
}

const TRANSACTION_EDIT_ACTIONS = new Set([
  "set_text",
  "replace_image_fill",
  "set_name",
  "set_visible",
  "set_visibility",
  "set_layout_flow",
  "set_bounds",
]);

const MAX_EDIT_BATCH_ACTIONS = 50;

async function applyEditBatch(params) {
  const transactionId = String(params.transactionId || "");
  const actions = Array.isArray(params.actions) ? params.actions : [];
  if (!transactionId) {
    return editBatchRejected(
      transactionId,
      "transactionId is required",
      [],
      null
    );
  }
  if (!actions.length) {
    return editBatchRejected(transactionId, "empty edit transaction", [], null);
  }
  if (actions.length > MAX_EDIT_BATCH_ACTIONS) {
    return editBatchRejected(
      transactionId,
      `edit transaction exceeds ${MAX_EDIT_BATCH_ACTIONS} actions`,
      [],
      null
    );
  }
  const unsupported = actions
    .map((item) => String((item && item.action) || ""))
    .filter((action) => !TRANSACTION_EDIT_ACTIONS.has(action));
  if (unsupported.length) {
    return editBatchRejected(
      transactionId,
      "edit transaction contains unsupported actions",
      Array.from(new Set(unsupported)),
      null
    );
  }

  // Validate every operation before the first mutation. Runtime failures can
  // still happen after preflight; those are handled by the snapshot rollback.
  for (let index = 0; index < actions.length; index += 1) {
    const item = actions[index] || {};
    const action = String(item.action || "");
    try {
      await preflightEditAction(action, item.params || {});
    } catch (err) {
      return editBatchRejected(
        transactionId,
        err.message,
        [],
        { index, action, error: err.message }
      );
    }
  }

  const committed = [];
  const applied = [];
  for (let index = 0; index < actions.length; index += 1) {
    const item = actions[index] || {};
    const action = String(item.action || "");
    const actionParams = item.params || {};
    try {
      const snapshot = captureEditSnapshot(action, actionParams);
      applied.push(snapshot);
      const result = await applyEditAction(action, actionParams);
      committed.push({ index, action, result });
    } catch (err) {
      const rollbackFailures = [];
      let restored = 0;
      for (const snapshot of applied.slice().reverse()) {
        try {
          await restoreEditSnapshot(snapshot);
          restored += 1;
        } catch (rollbackError) {
          rollbackFailures.push({
            nodeId: snapshot.nodeId,
            action: snapshot.action,
            error: rollbackError.message,
          });
        }
      }
      return {
        status: rollbackFailures.length ? "rollback-incomplete" : "rolled-back",
        transactionId,
        committed,
        failed: {
          index,
          action,
          error: err.message,
        },
        rollback: {
          attempted: applied.length,
          restored,
          failed: rollbackFailures,
        },
      };
    }
  }
  return {
    status: "committed",
    transactionId,
    committed,
    rollback: {
      attempted: 0,
      restored: 0,
      failed: [],
    },
  };
}

function editBatchRejected(transactionId, error, unsupportedActions, failed) {
  return {
    status: "rejected",
    transactionId,
    error,
    ...(unsupportedActions.length ? { unsupportedActions } : {}),
    ...(failed ? { failed } : {}),
    committed: [],
    rollback: {
      attempted: 0,
      restored: 0,
      failed: [],
    },
  };
}

async function preflightEditAction(action, params) {
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    throw new Error("edit action params must be an object");
  }
  const nodeId = String(params.nodeId || "");
  if (!nodeId) throw new Error(`EDIT_NODE_ID_REQUIRED: ${action}`);
  const node = figma.getNodeById(nodeId);
  if (!node) throw new Error(`NODE_NOT_FOUND: ${nodeId}`);
  if (action === "set_text") {
    if (node.type !== "TEXT") throw new Error(`NODE_NOT_TEXT: ${nodeId}`);
    if (node.fontName === figma.mixed) {
      throw new Error(`MIXED_FONT_TEXT_UNSUPPORTED: ${nodeId}`);
    }
    await figma.loadFontAsync(node.fontName);
    return;
  }
  if (action === "replace_image_fill") {
    if (!("fills" in node) || !Array.isArray(node.fills)) {
      throw new Error(`NODE_HAS_NO_FILLS: ${nodeId}`);
    }
    const fillIndex = params.fillIndex === undefined ? 0 : params.fillIndex;
    if (!Number.isInteger(fillIndex)) {
      throw new Error(`INVALID_FILL_INDEX: ${String(fillIndex)}`);
    }
    const fill = node.fills[fillIndex];
    if (!fill || fill.type !== "IMAGE") {
      throw new Error(`FILL_IS_NOT_IMAGE: ${nodeId}[${fillIndex}]`);
    }
    const imageBase64 = String(params.imageBase64 || "");
    if (!imageBase64) {
      throw new Error("IMAGE_BASE64_REQUIRED");
    }
    try {
      atob(imageBase64);
    } catch (err) {
      throw new Error("IMAGE_BASE64_INVALID");
    }
    return;
  }
  if (action === "set_name") {
    if (typeof params.name !== "string") {
      throw new Error("NAME_STRING_REQUIRED");
    }
    if (params.name.length > 1024) {
      throw new Error("NAME_TOO_LONG");
    }
    return;
  }
  if (action === "set_visible" || action === "set_visibility") {
    if (typeof params.visible !== "boolean") {
      throw new Error("VISIBLE_BOOLEAN_REQUIRED");
    }
    if (!("visible" in node)) {
      throw new Error(`NODE_HAS_NO_VISIBILITY: ${nodeId}`);
    }
    return;
  }
  if (action === "set_layout_flow") {
    if (node.type !== "FRAME") {
      throw new Error(`NODE_NOT_FRAME: ${nodeId}`);
    }
    const layout = params.layout || {};
    const layoutMode = normalizedLayoutMode(layout.mode);
    const grid = validateGridLayout(layoutMode, layout);
    validateLayoutFlowRequest(node, layoutMode, layout, grid, params);
    return;
  }
  if (action === "set_bounds") {
    for (const name of ["x", "y", "width", "height"]) {
      if (!Number.isFinite(Number(params[name]))) {
        throw new Error(`BOUNDS_NUMBER_REQUIRED: ${name}`);
      }
    }
    if (Number(params.width) <= 0 || Number(params.height) <= 0) {
      throw new Error("BOUNDS_DIMENSIONS_MUST_BE_POSITIVE");
    }
  }
}

function captureEditSnapshot(action, params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`NODE_NOT_FOUND: ${params.nodeId}`);
  if (action === "set_text") {
    return {
      action,
      nodeId: node.id,
      node,
      text: textSnapshot(node),
    };
  }
  if (action === "replace_image_fill") {
    return {
      action,
      nodeId: node.id,
      node,
      fills: clonePaints(node.fills),
    };
  }
  if (action === "set_name") {
    return { action, nodeId: node.id, node, name: node.name };
  }
  if (action === "set_visible" || action === "set_visibility") {
    return { action, nodeId: node.id, node, visible: node.visible };
  }
  if (action === "set_layout_flow") {
    return {
      action,
      nodeId: node.id,
      node,
      layout: captureLayoutSnapshot(node),
    };
  }
  if (action === "set_bounds") {
    return {
      action,
      nodeId: node.id,
      node,
      bounds: {
        x: node.x,
        y: node.y,
        width: node.width,
        height: node.height,
      },
      regionId: node.getPluginData(OWNERSHIP_REGION_KEY) || "",
    };
  }
  throw new Error(`UNSUPPORTED_EDIT_ACTION: ${action}`);
}

async function applyEditAction(action, params) {
  if (action === "set_text") return await setText(params);
  if (action === "replace_image_fill") return await replaceImageFill(params);
  if (action === "set_name") return await setName(params);
  if (action === "set_visible" || action === "set_visibility") {
    return await setVisibility(params);
  }
  if (action === "set_layout_flow") return await setLayoutFlow(params);
  if (action === "set_bounds") return await setBounds(params);
  throw new Error(`UNSUPPORTED_EDIT_ACTION: ${action}`);
}

async function restoreEditSnapshot(snapshot) {
  const node = figma.getNodeById(snapshot.nodeId);
  if (node !== snapshot.node || !node) {
    throw new Error(`ROLLBACK_NODE_NOT_FOUND: ${snapshot.nodeId}`);
  }
  if (snapshot.action === "set_text") {
    await figma.loadFontAsync(snapshot.text.fontName);
    node.characters = snapshot.text.characters;
    node.fontName = snapshot.text.fontName;
    node.fontSize = snapshot.text.fontSize;
    return;
  }
  if (snapshot.action === "replace_image_fill") {
    node.fills = clonePaints(snapshot.fills);
    return;
  }
  if (snapshot.action === "set_name") {
    node.name = snapshot.name;
    return;
  }
  if (snapshot.action === "set_visible" || snapshot.action === "set_visibility") {
    node.visible = snapshot.visible;
    return;
  }
  if (snapshot.action === "set_layout_flow") {
    restoreLayoutSnapshot(node, snapshot.layout);
    return;
  }
  if (snapshot.action === "set_bounds") {
    node.x = snapshot.bounds.x;
    node.y = snapshot.bounds.y;
    node.resize(snapshot.bounds.width, snapshot.bounds.height);
    node.setPluginData(OWNERSHIP_REGION_KEY, snapshot.regionId);
    return;
  }
  throw new Error(`UNSUPPORTED_EDIT_ACTION: ${snapshot.action}`);
}

function clonePaints(paints) {
  return paints.map((paint) => {
    const copy = { ...paint };
    if (paint && paint.color) copy.color = { ...paint.color };
    if (paint && paint.gradientTransform) {
      copy.gradientTransform = paint.gradientTransform.map((row) => [...row]);
    }
    if (paint && paint.gradientStops) {
      copy.gradientStops = paint.gradientStops.map((stop) => ({
        ...stop,
        color: stop.color ? { ...stop.color } : stop.color,
      }));
    }
    return copy;
  });
}

const FRAME_LAYOUT_PROPERTIES = [
  "layoutMode",
  "layoutWrap",
  "itemSpacing",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "primaryAxisSizingMode",
  "counterAxisSizingMode",
  "primaryAxisAlignItems",
  "counterAxisAlignItems",
  "layoutSizingHorizontal",
  "layoutSizingVertical",
  "gridRowCount",
  "gridColumnCount",
  "gridRowGap",
  "gridColumnGap",
  "gridItemsPositioning",
  "gridAutoTracks",
  "gridRowSizes",
  "gridColumnSizes",
];

const CHILD_LAYOUT_PROPERTIES = [
  "layoutAlign",
  "layoutGrow",
  "layoutPositioning",
  "layoutSizingHorizontal",
  "layoutSizingVertical",
  "minWidth",
  "maxWidth",
  "gridRowAnchorIndex",
  "gridColumnAnchorIndex",
  "gridRowSpan",
  "gridColumnSpan",
  "gridChildHorizontalAlign",
  "gridChildVerticalAlign",
];

function captureLayoutSnapshot(node) {
  const properties = {};
  for (const name of FRAME_LAYOUT_PROPERTIES) {
    if (name in node) properties[name] = cloneSnapshotValue(node[name]);
  }
  return {
    x: node.x,
    y: node.y,
    width: node.width,
    height: node.height,
    properties,
    children: Array.from(node.children || []).map((child) => ({
      nodeId: child.id,
      x: child.x,
      y: child.y,
      width: child.width,
      height: child.height,
      properties: captureAvailableProperties(child, CHILD_LAYOUT_PROPERTIES),
    })),
  };
}

function restoreLayoutSnapshot(node, snapshot) {
  const layoutMode = snapshot.properties.layoutMode;
  if (layoutMode) {
    setRollbackProperty(node, "layoutMode", layoutMode);
  }
  for (const [name, value] of Object.entries(snapshot.properties)) {
    if (name === "layoutMode" || name === "gridRowSizes"
        || name === "gridColumnSizes") continue;
    setRollbackProperty(node, name, cloneSnapshotValue(value));
  }
  if (snapshot.properties.gridRowSizes) {
    applyGridTrackSizes(
      node,
      "gridRowSizes",
      cloneSnapshotValue(snapshot.properties.gridRowSizes)
    );
  }
  if (snapshot.properties.gridColumnSizes) {
    applyGridTrackSizes(
      node,
      "gridColumnSizes",
      cloneSnapshotValue(snapshot.properties.gridColumnSizes)
    );
  }
  node.x = snapshot.x;
  node.y = snapshot.y;
  node.resize(snapshot.width, snapshot.height);
  for (const childSnapshot of snapshot.children) {
    const child = figma.getNodeById(childSnapshot.nodeId);
    if (!child) {
      throw new Error(`LAYOUT_ROLLBACK_CHILD_NOT_FOUND: ${childSnapshot.nodeId}`);
    }
    const properties = childSnapshot.properties;
    if (typeof properties.gridColumnSpan === "number") {
      setRollbackProperty(
        child,
        "gridColumnSpan",
        cloneSnapshotValue(properties.gridColumnSpan)
      );
    }
    if (typeof properties.gridRowSpan === "number") {
      setRollbackProperty(
        child,
        "gridRowSpan",
        cloneSnapshotValue(properties.gridRowSpan)
      );
    }
    const rowAnchor = properties.gridRowAnchorIndex;
    const columnAnchor = properties.gridColumnAnchorIndex;
    if (typeof rowAnchor === "number" && typeof columnAnchor === "number") {
      if (typeof child.setGridChildPosition === "function") {
        try {
          child.setGridChildPosition(rowAnchor, columnAnchor);
        } catch (err) {
          throw new Error(
            `LAYOUT_ROLLBACK_FAILED: grid position: ${err.message}`
          );
        }
      } else {
        setRollbackProperty(child, "gridRowAnchorIndex", rowAnchor);
        setRollbackProperty(child, "gridColumnAnchorIndex", columnAnchor);
      }
    }
    child.x = childSnapshot.x;
    child.y = childSnapshot.y;
    child.resize(childSnapshot.width, childSnapshot.height);
    for (const [name, value] of Object.entries(properties)) {
      if (
        name === "gridRowAnchorIndex"
        || name === "gridColumnAnchorIndex"
        || name === "gridRowSpan"
        || name === "gridColumnSpan"
      ) {
        continue;
      }
      setRollbackProperty(child, name, cloneSnapshotValue(value));
    }
  }
}

function captureAvailableProperties(node, names) {
  const properties = {};
  for (const name of names) {
    if (name in node) properties[name] = cloneSnapshotValue(node[name]);
  }
  return properties;
}

function cloneSnapshotValue(value) {
  if (Array.isArray(value)) return value.map(cloneSnapshotValue);
  if (value && typeof value === "object") {
    const copy = {};
    for (const [key, item] of Object.entries(value)) {
      copy[key] = cloneSnapshotValue(item);
    }
    return copy;
  }
  return value;
}

function setRollbackProperty(node, name, value) {
  try {
    node[name] = value;
  } catch (err) {
    throw new Error(`LAYOUT_ROLLBACK_FAILED: ${name}: ${err.message}`);
  }
}

async function componentInstanceProbe(params) {
  const rootName = String(params.rootName || "P3 Component Instance Probe");
  let root = null;
  try {
    await figma.loadFontAsync({ family: "Arial", style: "Regular" });
    root = figma.createFrame();
    root.name = rootName;
    root.resize(420, 220);
    root.fills = [];
    figma.currentPage.appendChild(root);

    const component = figma.createComponent();
    component.name = `${rootName} Component`;
    component.resize(240, 80);
    component.x = 16;
    component.y = 16;
    component.fills = [{ type: "SOLID", color: hexToRgb("#ffffff") }];
    root.appendChild(component);

    const sourceText = figma.createText();
    sourceText.name = `${rootName} Source Text`;
    sourceText.fontName = { family: "Arial", style: "Regular" };
    sourceText.fontSize = 16;
    sourceText.characters = "Component source";
    sourceText.x = 12;
    sourceText.y = 12;
    component.appendChild(sourceText);

    const instance = component.createInstance();
    instance.name = `${rootName} Instance`;
    instance.x = 16;
    instance.y = 120;
    root.appendChild(instance);
    const instanceText = instance.findOne((node) => node.type === "TEXT");
    if (!instanceText) throw new Error("component instance text not found");
    const before = String(instanceText.characters || "");
    instanceText.characters = "Instance override";
    const after = String(instanceText.characters || "");
    const sourceAfter = String(sourceText.characters || "");
    return {
      status: (
        instance.type === "INSTANCE"
        && after === "Instance override"
        && sourceAfter === "Component source"
      ) ? "pass" : "fail",
      rootId: root.id,
      componentId: component.id,
      instanceId: instance.id,
      instanceType: instance.type,
      before,
      after,
      sourceAfter,
      overrideApplied: after === "Instance override",
      sourceUnchanged: sourceAfter === "Component source",
    };
  } finally {
    if (root) {
      try { root.remove(); } catch (err) {}
    }
  }
}

async function setText(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`找不到节点: ${params.nodeId}`);
  if (node.type !== "TEXT") throw new Error(`节点不是 TEXT: ${params.nodeId}`);
  if (node.fontName === figma.mixed) {
    throw new Error(`混合字体文本不支持严格编辑: ${params.nodeId}`);
  }
  await figma.loadFontAsync(node.fontName);
  const before = textSnapshot(node);
  node.characters = String(params.text === undefined ? "" : params.text);
  const after = textSnapshot(node);
  return {
    nodeId: node.id,
    before,
    after,
    typePreserved: node.type === "TEXT",
    fontPreserved: sameFont(before.fontName, after.fontName),
  };
}

async function setName(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`NODE_NOT_FOUND: ${params.nodeId}`);
  if (typeof params.name !== "string") {
    throw new Error("NAME_STRING_REQUIRED");
  }
  const before = node.name;
  node.name = params.name;
  return {
    nodeId: node.id,
    before,
    after: node.name,
  };
}

async function setVisibility(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`NODE_NOT_FOUND: ${params.nodeId}`);
  if (typeof params.visible !== "boolean") {
    throw new Error("VISIBLE_BOOLEAN_REQUIRED");
  }
  if (!("visible" in node)) {
    throw new Error(`NODE_HAS_NO_VISIBILITY: ${params.nodeId}`);
  }
  const before = node.visible;
  node.visible = params.visible;
  return {
    nodeId: node.id,
    before,
    after: node.visible,
  };
}

function textSnapshot(node) {
  return {
    characters: node.characters,
    fontName: {
      family: node.fontName.family,
      style: node.fontName.style,
    },
    fontSize: node.fontSize,
    x: node.x,
    y: node.y,
    width: node.width,
    height: node.height,
  };
}

function sameFont(a, b) {
  return !!a && !!b
    && a.family === b.family
    && a.style === b.style;
}

async function replaceImageFill(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`找不到节点: ${params.nodeId}`);
  if (!("fills" in node) || !Array.isArray(node.fills)) {
    throw new Error(`节点不支持图片填充: ${params.nodeId}`);
  }
  const imageBase64 = params.imageBase64 || "";
  if (!imageBase64) throw new Error("replace_image_fill 缺少 imageBase64 参数");
  const fillIndex = Number.isInteger(params.fillIndex) ? params.fillIndex : 0;
  const fills = [...node.fills];
  const previous = fills[fillIndex];
  if (!previous || previous.type !== "IMAGE") {
    throw new Error(`fillIndex ${fillIndex} 不是 IMAGE 填充`);
  }
  const bytes = Uint8Array.from(atob(imageBase64), (c) => c.charCodeAt(0));
  const image = figma.createImage(bytes);
  fills[fillIndex] = { ...previous, imageHash: image.hash };
  node.fills = fills;
  const current = node.fills[fillIndex];
  return {
    nodeId: node.id,
    fillIndex,
    before: {
      type: previous.type,
      imageHash: previous.imageHash || null,
      scaleMode: previous.scaleMode || null,
    },
    after: {
      type: current.type,
      imageHash: current.imageHash || null,
      scaleMode: current.scaleMode || null,
    },
    typePreserved: node.type === "RECTANGLE"
      || node.type === "FRAME"
      || node.type === "ELLIPSE",
    scaleModePreserved: previous.scaleMode === current.scaleMode,
  };
}

async function setBounds(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`NODE_NOT_FOUND: ${params.nodeId}`);
  const x = Number(params.x);
  const y = Number(params.y);
  const width = Number(params.width);
  const height = Number(params.height);
  if (![x, y, width, height].every(Number.isFinite)) {
    throw new Error("BOUNDS_NUMBER_REQUIRED");
  }
  if (width <= 0 || height <= 0) {
    throw new Error("BOUNDS_DIMENSIONS_MUST_BE_POSITIVE");
  }
  node.x = x;
  node.y = y;
  node.resize(width, height);
  const regionId = String(params.regionId || "");
  if (regionId) {
    node.setPluginData(OWNERSHIP_REGION_KEY, regionId);
  }
  return {
    nodeId: node.id,
    bounds: { x: node.x, y: node.y, width: node.width, height: node.height },
    regionMembership: regionId
      ? { regionId, member: true }
      : { regionId: null, member: false },
  };
}

async function imageFillReport(params) {
  const root = figma.getNodeById(params.nodeId);
  if (!root) throw new Error(`找不到节点: ${params.nodeId}`);
  const nodes = typeof root.findAll === "function"
    ? [root, ...root.findAll(() => true)]
    : [root];
  const fills = [];
  for (const node of nodes) {
    if (!("fills" in node) || !Array.isArray(node.fills)) continue;
    for (let fillIndex = 0; fillIndex < node.fills.length; fillIndex += 1) {
      const fill = node.fills[fillIndex];
      if (!fill || fill.type !== "IMAGE" || !fill.imageHash) continue;
      const image = figma.getImageByHash(fill.imageHash);
      if (!image) continue;
      const bytes = await image.getBytesAsync();
      fills.push({
        nodeId: node.id,
        nodeType: node.type,
        fillIndex,
        imageHash: fill.imageHash,
        scaleMode: fill.scaleMode || null,
        byteLength: bytes.length,
        byteBase64: toBase64(bytes),
      });
    }
  }
  return { nodeId: root.id, fillCount: fills.length, fills };
}

// 把「子元素已经按绝对坐标挂完」的容器改成 Auto Layout。
//
// 两个硬约束，都来自真机教训（见 归档文档 figma_layout_upgrade_audit.md §4.3）：
// 1) **必须最后调用** —— Figma 一旦 layoutMode 不为 NONE 就立刻按 padding/间距重排
//    子元素，所以顺序只能是「先把子元素按绝对坐标全部挂完 → 再打开布局」；
// 2) 打开布局后必须显式把 sizing 写死成 FIXED —— 否则主轴默认是 AUTO（hug），画板会
//    被内容缩回去。写完再 resize 一次，钉住容器原本的尺寸。
//
// 子元素是按顺序连续挂进来的（中间不会有别人，见 adapter_base.resolve_frames），所以
// 覆盖项直接用「在容器 children 里的序号」。数量对不上（有图元被跳过没画出来）就整个不
// 动，保持绝对定位 —— 观感与不开 Auto Layout 时逐像素相同。
async function setAutoLayout(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`找不到节点: ${params.nodeId}`);
  const layout = params.layout || {};
  const layoutMode = normalizedLayoutMode(layout.mode);
  const children = node.children || [];
  // expectChildren 是**下界**：一个成员可能落多个节点（控件 = 底框 + 文本），子节点数
  // 只会 >= 成员数。少了说明有成员没画出来，整块不动（layoutMode 留在 NONE）。
  if (typeof params.expectChildren === "number"
      && children.length < params.expectChildren) {
    return { nodeId: node.id, applied: false, reason: "child-count",
             children: children.length, expected: params.expectChildren };
  }
  // 打开 layoutMode 的瞬间 Figma 会立刻按自己的算法重排子节点。先快照每个子节点
  // 当前（扁平绝对定位时代的）x/y，等布局打开后原样写回 —— 快照就是「不开 Auto
  // Layout」时的落点，写回后与扁平渲染逐像素相同。
  const parentBox = node.absoluteBoundingBox;
  const before = children.map((child) => {
    const childBox = child.absoluteBoundingBox;
    if (parentBox && childBox) {
      return [childBox.x - parentBox.x, childBox.y - parentBox.y];
    }
    return [child.x, child.y];
  });
  node.layoutMode = layoutMode;
  node.primaryAxisSizingMode = "FIXED";
  node.counterAxisSizingMode = "FIXED";
  node.itemSpacing = Number(layout.itemSpacing) || 0;
  node.paddingTop = Number(layout.paddingTop) || 0;
  node.paddingRight = Number(layout.paddingRight) || 0;
  node.paddingBottom = Number(layout.paddingBottom) || 0;
  node.paddingLeft = Number(layout.paddingLeft) || 0;
  if (layout.primaryAlign) node.primaryAxisAlignItems = layout.primaryAlign;
  if (layout.counterAlign) node.counterAxisAlignItems = layout.counterAlign;
  // 子项一律钉死：**全部**子节点 ABSOLUTE + 复位到快照 x/y，绝不交给布局引擎摆放。
  // 真机实测（2026-10-12）：让引擎按 spacing 流式摆，子项落在「自己的 x/y + 引擎
  // 偏移」上，整组右移一个 itemSpacing（dushu 书架格 +18px，整图均差 2.176→4.615）。
  // mode/spacing/padding/align 只当结构信息留给设计师，几何只认快照。
  // 早先版本按「成员序号」只钉成员表里的那一个节点，一个成员落多个节点（控件 =
  // 底框 + 文本）时就对不上号，多出来的节点会被引擎摆到别处（audit §12）。改成全量快照。
  children.forEach((child, i) => {
    child.layoutPositioning = "ABSOLUTE";
    child.x = before[i][0];
    child.y = before[i][1];
  });
  node.resize(params.width || node.width, params.height || node.height);
  return { nodeId: node.id, applied: true, mode: node.layoutMode,
           children: children.length };
}

// 实验用：打开真正的 Auto Layout 流式布局，不把子项钉成 ABSOLUTE。
// 与 set_autolayout 分开，避免影响生产渲染的逐像素落点。
async function setLayoutFlow(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`找不到节点: ${params.nodeId}`);
  if (node.type !== "FRAME") throw new Error(`set_layout_flow 只接受 FRAME: ${node.type}`);
  const layout = params.layout || {};
  const layoutMode = normalizedLayoutMode(layout.mode);
  const layoutWrap = normalizedLayoutWrap(layout.wrap);
  const grid = validateGridLayout(layoutMode, layout);
  const resolvedChildren = validateLayoutFlowRequest(
    node,
    layoutMode,
    layout,
    grid,
    params
  );
  node.layoutMode = layoutMode;
  node.itemSpacing = Number(layout.itemSpacing) || 0;
  node.paddingTop = Number(layout.paddingTop) || 0;
  node.paddingRight = Number(layout.paddingRight) || 0;
  node.paddingBottom = Number(layout.paddingBottom) || 0;
  node.paddingLeft = Number(layout.paddingLeft) || 0;
  if (layout.primaryAlign) node.primaryAxisAlignItems = layout.primaryAlign;
  if (layout.counterAlign) node.counterAxisAlignItems = layout.counterAlign;
  if (layoutWrap) node.layoutWrap = layoutWrap;

  if (layoutMode === "GRID") {
    if (node.gridColumnCount !== grid.columns) {
      try {
        node.gridColumnCount = grid.columns;
      } catch (err) {
        throw new Error(
          `set_grid_column_count current=${node.gridColumnCount} target=${grid.columns}: ${err.message}`
        );
      }
    }
    if (node.gridRowCount !== grid.rows) {
      try {
        node.gridRowCount = grid.rows;
      } catch (err) {
        throw new Error(
          `set_grid_row_count current=${node.gridRowCount} target=${grid.rows}: ${err.message}`
        );
      }
    }
    node.gridRowGap = Number(layout.gridRowGap) || 0;
    node.gridColumnGap = Number(layout.gridColumnGap) || 0;
    if (layout.gridItemsPositioning) {
      node.gridItemsPositioning = grid.itemsPositioning;
    }
    if (layout.gridAutoTracks) {
      node.gridAutoTracks = grid.autoTracks;
    }
    applyGridTrackSizes(node, "gridRowSizes", grid.rowSizes);
    applyGridTrackSizes(node, "gridColumnSizes", grid.columnSizes);
  }

  applyLayoutFlowChildOverrides(node, layoutMode, resolvedChildren);

  if (typeof params.width === "number" || typeof params.height === "number") {
    node.resize(
      typeof params.width === "number" ? params.width : node.width,
      typeof params.height === "number" ? params.height : node.height
    );
  }
  if (layout.primaryAxisSizingMode) node.primaryAxisSizingMode = layout.primaryAxisSizingMode;
  if (layout.counterAxisSizingMode) node.counterAxisSizingMode = layout.counterAxisSizingMode;
  if (layout.layoutSizingHorizontal) {
    node.layoutSizingHorizontal = normalizedSizingMode(
      layout.layoutSizingHorizontal,
      "layoutSizingHorizontal"
    );
  }
  if (layout.layoutSizingVertical) {
    node.layoutSizingVertical = normalizedSizingMode(
      layout.layoutSizingVertical,
      "layoutSizingVertical"
    );
  }
  return readNodeTree(node, Number.isFinite(params.depth) ? params.depth : 2);
}

async function setGridChildOverrides(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) throw new Error(`找不到节点: ${params.nodeId}`);
  if (node.type !== "FRAME" || node.layoutMode !== "GRID") {
    throw new Error(`set_grid_child_overrides requires a GRID frame: ${params.nodeId}`);
  }
  const grid = {
    rows: positiveInteger(node.gridRowCount, "gridRowCount"),
    columns: positiveInteger(node.gridColumnCount, "gridColumnCount"),
    itemsPositioning: node.gridItemsPositioning || "MANUAL",
    autoTracks: node.gridAutoTracks || "NONE",
    rowSizes: [],
    columnSizes: [],
  };
  const layout = {
    mode: "GRID",
    gridRowCount: grid.rows,
    gridColumnCount: grid.columns,
  };
  const resolvedChildren = validateLayoutFlowRequest(
    node,
    "GRID",
    layout,
    grid,
    params
  );
  applyLayoutFlowChildOverrides(node, "GRID", resolvedChildren);
  return readNodeTree(node, Number.isFinite(params.depth) ? params.depth : 2);
}

function applyLayoutFlowChildOverrides(node, layoutMode, resolvedChildren) {
  for (const override of resolvedChildren) {
    const child = override.child;
    if (override.layoutAlign) child.layoutAlign = override.layoutAlign;
    if (typeof override.layoutGrow === "number") child.layoutGrow = override.layoutGrow;
    if (override.layoutPositioning) child.layoutPositioning = override.layoutPositioning;
    if (override.layoutSizingHorizontal) child.layoutSizingHorizontal = override.layoutSizingHorizontal;
    if (override.layoutSizingVertical) child.layoutSizingVertical = override.layoutSizingVertical;
    if (typeof override.minWidth === "number") child.minWidth = override.minWidth;
    if (typeof override.maxWidth === "number") child.maxWidth = override.maxWidth;
    if (layoutMode === "GRID") {
      if (override.rowAnchor !== undefined || override.columnAnchor !== undefined) {
        if (!Number.isInteger(override.rowAnchor)
            || !Number.isInteger(override.columnAnchor)) {
          throw new Error("GRID_ANCHORS_MUST_BE_INTEGERS");
        }
        child.setGridChildPosition(override.rowAnchor, override.columnAnchor);
      }
      if (override.rowSpan !== undefined) {
        child.gridRowSpan = positiveInteger(override.rowSpan, "gridRowSpan");
      }
      if (override.columnSpan !== undefined) {
        child.gridColumnSpan = positiveInteger(
          override.columnSpan,
          "gridColumnSpan"
        );
      }
      if (override.gridChildHorizontalAlign) {
        child.gridChildHorizontalAlign = normalizedGridAlignment(
          override.gridChildHorizontalAlign,
          "gridChildHorizontalAlign"
        );
      }
      if (override.gridChildVerticalAlign) {
        child.gridChildVerticalAlign = normalizedGridAlignment(
          override.gridChildVerticalAlign,
          "gridChildVerticalAlign"
        );
      }
    }
  }
}

function normalizedLayoutMode(value) {
  const mode = String(value || "").trim().toUpperCase();
  if (mode !== "VERTICAL" && mode !== "HORIZONTAL" && mode !== "GRID") {
    throw new Error(`UNSUPPORTED_LAYOUT_MODE: ${mode || "(empty)"}`);
  }
  return mode;
}

function validateLayoutFlowRequest(node, layoutMode, layout, grid, params) {
  if (layoutMode === "GRID" && layout.wrap) {
    throw new Error("GRID_LAYOUT_DOES_NOT_SUPPORT_LAYOUT_WRAP");
  }
  if (typeof params.width === "number" && params.width <= 0) {
    throw new Error("LAYOUT_WIDTH_MUST_BE_POSITIVE");
  }
  if (typeof params.height === "number" && params.height <= 0) {
    throw new Error("LAYOUT_HEIGHT_MUST_BE_POSITIVE");
  }
  for (const name of [
    "itemSpacing",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "gridRowGap",
    "gridColumnGap",
  ]) {
    if (layout[name] !== undefined
        && (!isFinite(Number(layout[name])) || Number(layout[name]) < 0)) {
      throw new Error(`LAYOUT_${name.toUpperCase()}_MUST_BE_NON_NEGATIVE`);
    }
  }
  if (grid) {
    if (grid.rowSizes.length > grid.rows) {
      throw new Error("GRID_ROW_SIZES_EXCEED_ROW_COUNT");
    }
    if (grid.columnSizes.length > grid.columns) {
      throw new Error("GRID_COLUMN_SIZES_EXCEED_COLUMN_COUNT");
    }
  }
  if (!Array.isArray(params.children || [])) {
    throw new Error("LAYOUT_CHILDREN_MUST_BE_ARRAY");
  }
  const children = Array.from(node.children || []);
  return (params.children || []).map((override, index) => {
    if (!override || typeof override !== "object" || Array.isArray(override)) {
      throw new Error(`LAYOUT_CHILD_OVERRIDE_INVALID: ${index}`);
    }
    let child = null;
    if (override.childId) {
      child = figma.getNodeById(String(override.childId));
      if (!child) {
        throw new Error(`LAYOUT_CHILD_NOT_FOUND: ${override.childId}`);
      }
      if (!children.includes(child)) {
        throw new Error(`LAYOUT_CHILD_NOT_OWNED: ${override.childId}`);
      }
    } else if (Number.isInteger(override.index)) {
      child = children[override.index];
      if (!child) {
        throw new Error(`LAYOUT_CHILD_INDEX_OUT_OF_RANGE: ${override.index}`);
      }
    } else {
      throw new Error(`LAYOUT_CHILD_SELECTOR_REQUIRED: ${index}`);
    }
    if (override.layoutSizingHorizontal) {
      normalizedSizingMode(
        override.layoutSizingHorizontal,
        "layoutSizingHorizontal"
      );
    }
    if (override.layoutSizingVertical) {
      normalizedSizingMode(
        override.layoutSizingVertical,
        "layoutSizingVertical"
      );
    }
    if (layoutMode === "GRID") {
      if (override.rowAnchor !== undefined || override.columnAnchor !== undefined) {
        if (!Number.isInteger(override.rowAnchor)
            || !Number.isInteger(override.columnAnchor)) {
          throw new Error("GRID_ANCHORS_MUST_BE_INTEGERS");
        }
        if (override.rowAnchor < 0 || override.columnAnchor < 0) {
          throw new Error("GRID_ANCHORS_MUST_BE_NON_NEGATIVE");
        }
        if (override.rowAnchor >= grid.rows
            || override.columnAnchor >= grid.columns) {
          throw new Error("GRID_ANCHOR_OUT_OF_RANGE");
        }
      }
      if (override.rowSpan !== undefined) {
        positiveInteger(override.rowSpan, "gridRowSpan");
      }
      if (override.columnSpan !== undefined) {
        positiveInteger(override.columnSpan, "gridColumnSpan");
      }
      if (override.gridChildHorizontalAlign) {
        normalizedGridAlignment(
          override.gridChildHorizontalAlign,
          "gridChildHorizontalAlign"
        );
      }
      if (override.gridChildVerticalAlign) {
        normalizedGridAlignment(
          override.gridChildVerticalAlign,
          "gridChildVerticalAlign"
        );
      }
    }
    return { ...override, child };
  });
}

function normalizedLayoutWrap(value) {
  if (value === undefined || value === null || value === "") return null;
  const mode = String(value).trim().toUpperCase();
  if (mode !== "NO_WRAP" && mode !== "WRAP") {
    throw new Error(`UNSUPPORTED_LAYOUT_WRAP: ${mode}`);
  }
  return mode;
}

function validateGridLayout(layoutMode, layout) {
  if (layoutMode !== "GRID") return null;
  const rows = positiveInteger(layout.gridRowCount, "gridRowCount");
  const columns = positiveInteger(layout.gridColumnCount, "gridColumnCount");
  const itemsPositioning = layout.gridItemsPositioning
    ? String(layout.gridItemsPositioning).trim().toUpperCase()
    : "MANUAL";
  if (itemsPositioning !== "MANUAL"
      && itemsPositioning !== "ROW_AUTO_FLOW") {
    throw new Error(`UNSUPPORTED_GRID_ITEMS_POSITIONING: ${itemsPositioning}`);
  }
  const autoTracks = layout.gridAutoTracks
    ? String(layout.gridAutoTracks).trim().toUpperCase()
    : "NONE";
  if (autoTracks !== "NONE" && autoTracks !== "ROWS") {
    throw new Error(`UNSUPPORTED_GRID_AUTO_TRACKS: ${autoTracks}`);
  }
  return {
    rows,
    columns,
    itemsPositioning,
    autoTracks,
    rowSizes: validateGridTrackSizes(layout.gridRowSizes, "gridRowSizes"),
    columnSizes: validateGridTrackSizes(
      layout.gridColumnSizes,
      "gridColumnSizes"
    ),
  };
}

function positiveInteger(value, name) {
  const number = Number(value);
  if (!Number.isInteger(number) || number <= 0) {
    throw new Error(`${name.toUpperCase()}_MUST_BE_POSITIVE_INTEGER`);
  }
  return number;
}

function validateGridTrackSizes(sizes, name) {
  if (sizes === undefined || sizes === null) return [];
  if (!Array.isArray(sizes)) {
    throw new Error(`${name.toUpperCase()}_MUST_BE_ARRAY`);
  }
  return sizes.map((size, index) => {
    const type = String(size && size.type || "").trim().toUpperCase();
    if (type !== "FIXED" && type !== "FLEX" && type !== "HUG") {
      throw new Error(`UNSUPPORTED_GRID_TRACK_TYPE: ${name}[${index}]`);
    }
    if (type === "HUG") return { type };
    const value = Number(size && size.value);
    if (!isFinite(value) || value <= 0) {
      throw new Error(`GRID_TRACK_VALUE_INVALID: ${name}[${index}]`);
    }
    return { type, value };
  });
}

function applyGridTrackSizes(node, property, sizes) {
  if (!sizes.length) return;
  const tracks = node[property];
  if (!Array.isArray(tracks) || tracks.length < sizes.length) {
    throw new Error(`GRID_TRACK_READBACK_UNAVAILABLE: ${property}`);
  }
  sizes.forEach((size, index) => {
    tracks[index].type = size.type;
    if (size.type !== "HUG") tracks[index].value = size.value;
  });
}

function normalizedGridAlignment(value, name) {
  const align = String(value || "").trim().toUpperCase();
  if (align !== "AUTO" && align !== "MIN"
      && align !== "CENTER" && align !== "MAX") {
    throw new Error(`UNSUPPORTED_${name.toUpperCase()}: ${align}`);
  }
  return align;
}

function normalizedSizingMode(value, name) {
  const mode = String(value || "").trim().toUpperCase();
  if (mode !== "FIXED" && mode !== "HUG" && mode !== "FILL") {
    throw new Error(`UNSUPPORTED_${name.toUpperCase()}: ${mode}`);
  }
  return mode;
}

// 导出节点为 PNG（base64）：供 Python 侧自动化视觉回归（与采集截图逐像素差分）。
async function exportFrame(params) {
  const node = figma.getNodeById(params.nodeId);
  if (!node) {
    throw new Error(`找不到节点: ${params.nodeId}`);
  }
  const bytes = await node.exportAsync({
    format: "PNG",
    constraint: { type: "SCALE", value: params.scale || 1 },
  });
  return { nodeId: params.nodeId, base64: toBase64(bytes) };
}

function rgbToHex(color) {
  const channel = (v) => {
    const n = Math.round(Math.max(0, Math.min(1, Number(v) || 0)) * 255);
    return n.toString(16).padStart(2, "0");
  };
  return `#${channel(color && color.r)}${channel(color && color.g)}${channel(color && color.b)}`;
}

// fills/strokes 是 Figma 的只读代理对象，不能直接 JSON 化；这里只保留
// 验收需要的类型、颜色、图片哈希与可见性。
function paintSummary(paints) {
  if (!Array.isArray(paints) || !paints.length) return [];
  return paints.map((p) => {
    if (!p) return { type: "UNKNOWN" };
    if (p.type === "SOLID") {
      return {
        type: "SOLID",
        color: rgbToHex(p.color),
        opacity: p.opacity === undefined ? 1 : p.opacity,
        visible: p.visible === undefined ? true : p.visible,
      };
    }
    if (p.type === "IMAGE") {
      return {
        type: "IMAGE",
        imageHash: p.imageHash || null,
        scaleMode: p.scaleMode || null,
        visible: p.visible === undefined ? true : p.visible,
      };
    }
    return { type: p.type || "UNKNOWN" };
  });
}

function readNodeTree(node, depth) {
  const box = node.absoluteBoundingBox;
  const summary = {
    id: node.id,
    name: node.name,
    type: node.type,
    x: Math.round(node.x * 1000) / 1000,
    y: Math.round(node.y * 1000) / 1000,
    width: Math.round(node.width * 1000) / 1000,
    height: Math.round(node.height * 1000) / 1000,
    absolute: box
      ? { x: box.x, y: box.y, width: box.width, height: box.height }
      : null,
  };
  if ("fills" in node) summary.fills = paintSummary(node.fills);
  if ("strokes" in node) summary.strokes = paintSummary(node.strokes);
  if ("opacity" in node) summary.opacity = node.opacity;
  if ("visible" in node) summary.visible = node.visible;
  if (node.type === "FRAME") {
    summary.layoutMode = node.layoutMode;
    summary.itemSpacing = node.itemSpacing;
    summary.paddingTop = node.paddingTop;
    summary.paddingRight = node.paddingRight;
    summary.paddingBottom = node.paddingBottom;
    summary.paddingLeft = node.paddingLeft;
    summary.primaryAxisSizingMode = node.primaryAxisSizingMode;
    summary.counterAxisSizingMode = node.counterAxisSizingMode;
    summary.primaryAxisAlignItems = node.primaryAxisAlignItems;
    summary.counterAxisAlignItems = node.counterAxisAlignItems;
    summary.layoutWrap = node.layoutWrap;
    summary.clipsContent = node.clipsContent;
    summary.gridRowCount = node.gridRowCount;
    summary.gridColumnCount = node.gridColumnCount;
    summary.gridRowGap = node.gridRowGap;
    summary.gridColumnGap = node.gridColumnGap;
    summary.gridItemsPositioning = node.gridItemsPositioning;
    summary.gridAutoTracks = node.gridAutoTracks;
    summary.gridRowSizes = node.gridRowSizes;
    summary.gridColumnSizes = node.gridColumnSizes;
  }
  if ("layoutAlign" in node) summary.layoutAlign = node.layoutAlign;
  if ("layoutGrow" in node) summary.layoutGrow = node.layoutGrow;
  if ("layoutPositioning" in node) summary.layoutPositioning = node.layoutPositioning;
  if ("layoutSizingHorizontal" in node) summary.layoutSizingHorizontal = node.layoutSizingHorizontal;
  if ("layoutSizingVertical" in node) summary.layoutSizingVertical = node.layoutSizingVertical;
  if (typeof node.gridRowAnchorIndex === "number") {
    summary.gridRowAnchorIndex = node.gridRowAnchorIndex;
  }
  if (typeof node.gridColumnAnchorIndex === "number") {
    summary.gridColumnAnchorIndex = node.gridColumnAnchorIndex;
  }
  if (typeof node.gridRowSpan === "number") summary.gridRowSpan = node.gridRowSpan;
  if (typeof node.gridColumnSpan === "number") {
    summary.gridColumnSpan = node.gridColumnSpan;
  }
  if (node.gridChildHorizontalAlign) {
    summary.gridChildHorizontalAlign = node.gridChildHorizontalAlign;
  }
  if (node.gridChildVerticalAlign) {
    summary.gridChildVerticalAlign = node.gridChildVerticalAlign;
  }
  if (node.type === "TEXT") {
    summary.characters = node.characters;
    summary.fontName = node.fontName && node.fontName !== figma.mixed ? node.fontName : null;
    summary.fontSize = typeof node.fontSize === "number" ? node.fontSize : null;
    summary.textAlignHorizontal = node.textAlignHorizontal || null;
    if (typeof node.getStyledTextSegments === "function") {
      try {
        summary.textRuns = node
          .getStyledTextSegments(["characters", "fontName", "fontSize"])
          .map((run) => ({
            characters: run.characters,
            fontName: run.fontName === figma.mixed ? null : run.fontName,
            fontSize: typeof run.fontSize === "number" ? run.fontSize : null,
          }));
      } catch (err) {
        summary.textRuns = null;
      }
    }
  }
  summary.bounds = { x: summary.x, y: summary.y, width: summary.width, height: summary.height };
  summary.layoutSnapshot = {
    layoutMode: summary.layoutMode || "NONE",
    itemSpacing: summary.itemSpacing,
    paddingTop: summary.paddingTop,
    paddingRight: summary.paddingRight,
    paddingBottom: summary.paddingBottom,
    paddingLeft: summary.paddingLeft,
    primaryAxisSizingMode: summary.primaryAxisSizingMode,
    counterAxisSizingMode: summary.counterAxisSizingMode,
    primaryAxisAlignItems: summary.primaryAxisAlignItems,
    counterAxisAlignItems: summary.counterAxisAlignItems,
    layoutWrap: summary.layoutWrap,
    layoutSizingHorizontal: summary.layoutSizingHorizontal,
    layoutSizingVertical: summary.layoutSizingVertical,
    gridRowCount: summary.gridRowCount,
    gridColumnCount: summary.gridColumnCount,
    gridRowGap: summary.gridRowGap,
    gridColumnGap: summary.gridColumnGap,
    gridItemsPositioning: summary.gridItemsPositioning,
    gridAutoTracks: summary.gridAutoTracks,
    gridRowSizes: summary.gridRowSizes,
    gridColumnSizes: summary.gridColumnSizes,
  };
  if (typeof node.getPluginData === "function") {
    const regionId = node.getPluginData(OWNERSHIP_REGION_KEY);
    if (regionId) {
      summary.regionMembership = { regionId, member: true };
    }
  }
  if ((node.type === "RECTANGLE" || node.type === "FRAME")
      && typeof node.topLeftRadius === "number") {
    summary.cornerRadius = {
      topLeft: node.topLeftRadius,
      topRight: node.topRightRadius,
      bottomRight: node.bottomRightRadius,
      bottomLeft: node.bottomLeftRadius,
    };
  }
  if ("children" in node && depth > 0) {
    summary.children = node.children.map((child) => readNodeTree(child, depth - 1));
  }
  return summary;
}

// 回读真实节点树：Smoke B 用它验证写入后的属性，而不是只看导出 PNG。
// 参数：{ nodeId?, depth? }；省略 nodeId 时回读当前页。
function getNodeTree(params) {
  const nodeId = params && params.nodeId;
  const node = nodeId ? figma.getNodeById(nodeId) : figma.currentPage;
  if (!node) throw new Error(`找不到节点: ${nodeId}`);
  const depth = params && Number.isFinite(params.depth) ? params.depth : 4;
  return readNodeTree(node, depth);
}

// 诊断：报告本页文本节点实际用的字体，以及 DesignSpec 字体栈里
// 哪些本机可用。用来区分"选错字体"与"光栅化差异"。
async function fontReport(params) {
  const all = await figma.listAvailableFontsAsync();
  const families = {};
  all.forEach((f) => {
    families[f.fontName.family] = (families[f.fontName.family] || 0) + 1;
  });
  const used = {};
  figma.currentPage.findAll((n) => n.type === "TEXT").forEach((n) => {
    const key = `${n.fontName.family} / ${n.fontName.style}`;
    used[key] = (used[key] || 0) + 1;
  });
  // 图层名在导出的 PNG 里看不见，只能从插件这边问；顺手回一份样本。
  const allNames = figma.currentPage.findAll(() => true).map((n) => n.name);
  const DEFAULT_RE = /^(Rectangle|Ellipse|Text|Frame|Group|Vector|Line|Star|Polygon)( \d+)?$/;
  const named = allNames.filter((n) => !DEFAULT_RE.test(n) && n !== "");
  return {
    textNodes: Object.values(used).reduce((a, b) => a + b, 0),
    usedFonts: used,
    totalFamilies: Object.keys(families).length,
    stackProbe: ((params && params.families) || []).map((f) => [f, families[f] || 0]),
    layerCount: allNames.length,
    namedCount: named.length,
    sampleNames: named.slice(0, 14),
  };
}

// 诊断：给一串 (fontFamily, fontWeight)，回报插件会解析到哪个 face、字体栈里
// 每个族本机有没有、有哪些样式。用来判定「Figma 画得比原页粗/细」到底是
// 选错了族、还是选错了档位。
async function fontProbe(params) {
  const table = await loadFaceTable();
  const probes = (params && params.probes) || [];
  const results = [];
  for (const item of probes) {
    const resolved = await loadFirstAvailableFont(
      item.fontFamily,
      item.fontWeight,
      false,
      item.fontStyle
    );
    const picked = resolved || DEFAULT_TEXT_FONT;
    const available = parseFontFamilies(item.fontFamily).map((family) => {
      const entry = table.get(family.toLowerCase());
      return [family, entry ? Array.from(entry.styles.values()) : null];
    });
    results.push({
      request: { fontFamily: item.fontFamily, fontWeight: item.fontWeight },
      picked,
      // picked 不在请求的字体栈里 = 整栈都没命中，退到了默认字体
      fallback: !available.some((pair) => pair[1] && pair[0].toLowerCase() === String(picked.family).toLowerCase()),
      available,
    });
  }
  return { probed: results.length, totalFamilies: table.size, results };
}

// 严格字体探测：请求字体栈完全不存在时返回 available=false，不退回 Inter。
async function fontStrictProbe(params) {
  const table = await loadFaceTable();
  const probes = (params && params.probes) || [];
  const results = [];
  for (const item of probes) {
    const requested = parseFontFamilies(item.fontFamily);
    const available = requested.map((family) => {
      const entry = table.get(family.toLowerCase());
      return [family, entry ? Array.from(entry.styles.values()) : null];
    });
    try {
      const picked = await loadFirstAvailableFont(
        item.fontFamily,
        item.fontWeight,
        true,
        item.fontStyle
      );
      results.push({
        request: { fontFamily: item.fontFamily, fontWeight: item.fontWeight },
        available: true,
        picked,
        fallback: false,
        families: available,
      });
    } catch (err) {
      results.push({
        request: { fontFamily: item.fontFamily, fontWeight: item.fontWeight },
        available: false,
        picked: null,
        error: err.message,
        families: available,
      });
    }
  }
  return { probed: results.length, results };
}

function toBase64(bytes) {
  if (typeof figma.base64Encode === "function") {
    return figma.base64Encode(bytes);
  }
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

// 按名字清掉上一次的产物，让重复跑测试不会叠加一堆旧画板。
async function removeNodesByName(params) {
  const name = params.name;
  if (!name) {
    throw new Error("remove_nodes_by_name 缺少 name 参数");
  }
  // 画板名现在带覆盖率后缀（Screen 1452×933 · 337/536），清理走前缀匹配
  const prefix = !!params.prefix;
  const victims = figma.currentPage.children.filter(
    (n) => (prefix ? n.name.indexOf(name) === 0 : n.name === name));
  victims.forEach((n) => n.remove());
  return { removed: victims.length };
}
