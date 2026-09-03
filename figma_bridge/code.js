// Figma 插件主线程：接收来自 UI 的命令，调用 Figma API 创建/修改节点。

figma.showUI(__html__, { width: 200, height: 100 });

figma.ui.onmessage = async (msg) => {
  const { action, params } = msg;
  try {
    const result = await handleAction(action, params);
    figma.ui.postMessage({ type: "response", result });
  } catch (err) {
    figma.ui.postMessage({ type: "response", error: err.message });
  }
};

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
    default:
      throw new Error(`未知命令: ${action}`);
  }
}

function hexToRgb(hex) {
  hex = hex.replace("#", "");
  if (hex.length === 3) {
    hex = hex.split("").map((c) => c + c).join("");
  }
  const r = parseInt(hex.substring(0, 2), 16) / 255;
  const g = parseInt(hex.substring(2, 4), 16) / 255;
  const b = parseInt(hex.substring(4, 6), 16) / 255;
  return { r, g, b };
}

function applyStyle(node, params) {
  if (params.fillColor) {
    node.fills = [{ type: "SOLID", color: hexToRgb(params.fillColor) }];
  }
  if (params.borderColor && params.borderWidth > 0) {
    node.strokes = [{ type: "SOLID", color: hexToRgb(params.borderColor) }];
    node.strokeWeight = params.borderWidth;
  }
  if (params.borderRadius && node.type === "RECTANGLE") {
    node.topLeftRadius = params.borderRadius;
    node.topRightRadius = params.borderRadius;
    node.bottomLeftRadius = params.borderRadius;
    node.bottomRightRadius = params.borderRadius;
  }
}

function applyGeometry(node, params) {
  node.x = params.x || 0;
  node.y = params.y || 0;
  node.resize(params.width || 100, params.height || 40);
}

function appendToParent(node, parentId) {
  if (parentId) {
    const parent = figma.getNodeById(parentId);
    if (parent && "appendChild" in parent) {
      parent.appendChild(node);
      return;
    }
  }
  figma.currentPage.appendChild(node);
}

async function createFrame(params) {
  const frame = figma.createFrame();
  applyGeometry(frame, params);
  frame.name = params.name || "Screen";
  frame.layoutMode = "NONE";  // 不启用 Auto Layout
  appendToParent(frame, params.parentId);
  return frame.id;
}

async function createRectangle(params) {
  const rect = figma.createRectangle();
  applyGeometry(rect, params);
  applyStyle(rect, params);
  appendToParent(rect, params.parentId);
  return rect.id;
}

async function createEllipse(params) {
  const ellipse = figma.createEllipse();
  applyGeometry(ellipse, params);
  applyStyle(ellipse, params);
  appendToParent(ellipse, params.parentId);
  return ellipse.id;
}

async function createText(params) {
  const text = figma.createText();
  await figma.loadFontAsync({ family: "Inter", style: "Regular" });
  text.x = params.x || 0;
  text.y = params.y || 0;
  text.characters = params.text || "";
  text.fontSize = params.fontSize || 16;
  if (params.textColor) {
    text.fills = [{ type: "SOLID", color: hexToRgb(params.textColor) }];
  }
  appendToParent(text, params.parentId);
  return text.id;
}

async function createImage(params) {
  const imageBase64 = params.imageBase64 || "";
  if (!imageBase64) {
    throw new Error("create_image 缺少 imageBase64 参数");
  }
  const bytes = Uint8Array.from(atob(imageBase64), (c) => c.charCodeAt(0));
  const image = figma.createImage(bytes);
  const rect = figma.createRectangle();
  applyGeometry(rect, params);
  rect.fills = [{ type: "IMAGE", imageHash: image.hash, scaleMode: "FIT" }];

  // avatar 圆形蒙版：四个角圆角半径设为宽度一半
  if (params.isAvatar && rect.type === "RECTANGLE") {
    const r = (params.width || 100) / 2;
    rect.topLeftRadius = r;
    rect.topRightRadius = r;
    rect.bottomLeftRadius = r;
    rect.bottomRightRadius = r;
  }

  appendToParent(rect, params.parentId);
  return rect.id;
}
