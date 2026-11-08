const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

let createdText = null;

function makeTextNode() {
  return {
    fontName: null,
    characters: "",
    fontSize: 16,
    fills: [],
    width: 120,
    height: 28,
    x: 0,
    y: 0,
    resize(width, height) {
      this.width = width;
      this.height = height;
    },
  };
}

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
    createdText = makeTextNode();
    return createdText;
  },
  async listAvailableFontsAsync() {
    return [
      { fontName: { family: "Arial", style: "Regular" } },
      { fontName: { family: "Arial", style: "Light" } },
      { fontName: { family: "Arial", style: "Medium" } },
      { fontName: { family: "Arial", style: "Bold" } },
    ];
  },
  async loadFontAsync() {},
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

async function resolvedStyle(weight) {
  await context.createText({
    text: "Weight fallback",
    fontFamily: "Arial, sans-serif",
    fontWeight: weight,
    fontWeightValue: null,
    fontSize: 16,
    y: 0,
    textColor: "#333333",
  });
  return createdText.fontName;
}

async function main() {
  const light = await resolvedStyle(300);
  if (light.family !== "Arial" || light.style !== "Light") {
    throw new Error(`null fontWeightValue lost weight 300: ${JSON.stringify(light)}`);
  }
  const medium = await resolvedStyle(500);
  if (medium.family !== "Arial" || medium.style !== "Medium") {
    throw new Error(`null fontWeightValue lost weight 500: ${JSON.stringify(medium)}`);
  }
  console.log("null fontWeightValue falls back to fontWeight");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
