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
  width: 280,
  height: 32,
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

async function main() {
  await context.createText({
    text: "Remote asset holdout",
    fontFamily: "Arial, sans-serif",
    fontWeight: "bold",
    fontSize: 28,
    lineHeight: 38,
    x: 54,
    y: 38,
    width: 620,
    height: 38,
    textColor: "#17212b",
  });

  const lineHeight = textNode.lineHeight;
  if (
    !lineHeight
    || lineHeight.unit !== "PIXELS"
    || lineHeight.value !== 38
  ) {
    throw new Error(
      `single-line text lost explicit lineHeight: ${JSON.stringify(lineHeight)}`,
    );
  }
  console.log("single-line text lineHeight applied");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
