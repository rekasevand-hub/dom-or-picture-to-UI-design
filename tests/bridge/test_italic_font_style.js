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
      { fontName: { family: "Arial", style: "Bold" } },
      { fontName: { family: "Arial", style: "Italic" } },
      { fontName: { family: "Arial", style: "Bold Italic" } },
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

async function createWithStyle(weight) {
  await context.createText({
    text: "Italic run",
    fontFamily: "Arial, sans-serif",
    fontWeight: weight,
    fontStyle: "italic",
    fontSize: 18,
    lineHeight: 28,
    height: 28,
    y: 0,
    textColor: "#17212b",
  });
  return createdText.fontName;
}

async function main() {
  const regular = await createWithStyle("normal");
  if (regular.family !== "Arial" || regular.style !== "Italic") {
    throw new Error(`normal italic resolved incorrectly: ${JSON.stringify(regular)}`);
  }
  const bold = await createWithStyle("bold");
  if (bold.family !== "Arial" || bold.style !== "Bold Italic") {
    throw new Error(`bold italic resolved incorrectly: ${JSON.stringify(bold)}`);
  }
  console.log("italic font style resolved");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
