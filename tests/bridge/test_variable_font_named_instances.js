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
      "Light Text",
      "Semilight Text",
      "Regular",
      "Semibold Text",
      "Bold Text",
    ].map((style) => ({
      fontName: { family: "Segoe UI Variable", style },
    })).concat(
      ["DemiLight", "Regular", "Medium"].map((style) => ({
        fontName: { family: "Noto Sans SC", style },
      })),
    );
  },
  async loadFontAsync() {},
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

async function createWithWeight(weight, family = "Segoe UI Variable") {
  await context.createText({
    text: "Variable run",
    fontFamily: family,
    fontWeight: weight,
    fontWeightValue: Number(weight),
    fontStyle: "normal",
    fontSize: 18,
    lineHeight: 28,
    height: 28,
    y: 0,
    textColor: "#17212b",
  });
  return createdText.fontName;
}

async function main() {
  const light = await createWithWeight("350");
  if (light.style !== "Semilight Text") {
    throw new Error(
      `350 did not use Semilight Text: ${JSON.stringify(light)}`,
    );
  }
  const demi = await createWithWeight("350", "Noto Sans SC");
  if (demi.style !== "DemiLight") {
    throw new Error(
      `Noto Sans SC 350 did not use DemiLight: ${JSON.stringify(demi)}`,
    );
  }
  const semibold = await createWithWeight("650");
  if (semibold.style !== "Semibold Text") {
    throw new Error(
      `650 did not use Semibold Text: ${JSON.stringify(semibold)}`,
    );
  }
  console.log("variable named instances resolved");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
