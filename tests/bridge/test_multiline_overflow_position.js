const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const textNode = {
  fontName: null,
  characters: "",
  fontSize: 14,
  fills: [],
  width: 84,
  height: 40,
  x: 0,
  y: 0,
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
};

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: {
    appendChild() {},
    children: [],
  },
  getNodeById() {
    return null;
  },
  createText() {
    return textNode;
  },
  async listAvailableFontsAsync() {
    return [{ fontName: { family: "Arial", style: "Regular" } }];
  },
  async loadFontAsync() {},
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

context.createText({
  text: "Missing asset",
  lines: ["Missing", "asset"],
  fontFamily: "Arial, sans-serif",
  fontWeight: "normal",
  fontSize: 14,
  lineHeight: 20,
  x: 58,
  y: 160,
  width: 84,
  height: 36,
  textColor: "#64748b",
}).then(() => {
  if (textNode.y !== 160) {
    throw new Error(`overflowing multiline text moved upward: y=${textNode.y}`);
  }
  console.log("multiline overflow keeps top edge");
}).catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
