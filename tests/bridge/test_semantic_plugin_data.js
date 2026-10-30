const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const pluginData = new Map();
const textNode = {
  fontName: null,
  characters: "",
  fontSize: 16,
  fills: [],
  width: 120,
  height: 24,
  x: 0,
  y: 0,
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
  setRangeFontName() {},
  setRangeFontSize() {},
  setRangeFills() {},
  setPluginData(key, value) {
    pluginData.set(key, value);
  },
};

const figma = {
  showUI() {},
  ui: { onmessage: null, postMessage() {} },
  currentPage: { appendChild() {}, children: [] },
  getNodeById() { return null; },
  createText() { return textNode; },
  async listAvailableFontsAsync() {
    return [{ fontName: { family: "Arial", style: "Regular" } }];
  },
  async loadFontAsync() {},
};

const context = vm.createContext({ __html__: "", figma, console });
vm.runInContext(code, context, { filename: codePath });

async function main() {
  await context.createText({
    text: "Search",
    fontFamily: "Arial",
    fontSize: 16,
    x: 0,
    y: 0,
    width: 120,
    height: 24,
    textColor: "#111111",
    pluginData: {
      "figma_auto_agent.semantic_role": "button",
      "figma_auto_agent.semantic_group_id": "button-set-0",
      "figma_auto_agent.semantic_confidence": "0.94",
      "unrelated.key": "ignored",
    },
  });

  if (pluginData.get("figma_auto_agent.semantic_role") !== "button") {
    throw new Error(`semantic role missing: ${JSON.stringify([...pluginData])}`);
  }
  if (pluginData.get("figma_auto_agent.semantic_group_id") !== "button-set-0") {
    throw new Error(`semantic group missing: ${JSON.stringify([...pluginData])}`);
  }
  if (pluginData.has("unrelated.key")) {
    throw new Error("unscoped plugin data must be ignored");
  }
  console.log("semantic plugin data applied");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
