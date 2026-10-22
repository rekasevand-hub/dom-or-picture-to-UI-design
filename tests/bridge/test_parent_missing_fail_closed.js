const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const textNode = {
  fontName: null,
  characters: "",
  fontSize: 16,
  fills: [],
  width: 100,
  height: 24,
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
    appendChild() {
      throw new Error("must not fall back to currentPage");
    },
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
  text: "Detached text",
  parentId: "missing-parent",
  fontFamily: "Arial",
  fontWeight: "normal",
  fontSize: 16,
  height: 24,
}).then(() => {
  throw new Error("missing parent unexpectedly succeeded");
}).catch((error) => {
  if (!String(error.message).includes("PARENT_NOT_FOUND")) {
    console.error(error.stack || error.message);
    process.exitCode = 1;
    return;
  }
  console.log("missing parent failed closed");
});
