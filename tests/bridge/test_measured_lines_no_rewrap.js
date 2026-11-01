const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");

const text = {
  type: "TEXT",
  fontName: null,
  characters: "",
  fontSize: 24,
  fills: [],
  width: 280,
  height: 34,
  x: 0,
  y: 0,
  textAutoResize: "NONE",
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
  setRangeFontName() {},
  setRangeFontSize() {},
  setRangeFills() {},
};

const figma = {
  showUI() {},
  ui: { onmessage: null, postMessage() {} },
  currentPage: { appendChild() {}, children: [] },
  getNodeById() { return null; },
  createText() { return text; },
  async listAvailableFontsAsync() {
    return [{ fontName: { family: "Arial", style: "Regular" } }];
  },
  async loadFontAsync() {},
};

const context = vm.createContext({ __html__: "", figma, console });
vm.runInContext(fs.readFileSync(codePath, "utf8"), context, { filename: codePath });

async function main() {
  await context.createText({
    text: "Write components\nwith code and markup",
    lines: ["Write components", "with code and markup"],
    fontFamily: "Arial",
    fontSize: 24,
    fontWeight: "400",
    x: 20,
    y: 30,
    width: 280,
    height: 68,
    textColor: "#111111",
    baselineSource: "browser-measured",
  });

  if (text.textAutoResize !== "NONE") {
    throw new Error(`measured lines were allowed to rewrap: ${text.textAutoResize}`);
  }
  if (text.characters !== "Write components\nwith code and markup") {
    throw new Error(`measured lines changed: ${text.characters}`);
  }
  if (text.width !== 280 || text.height !== 68) {
    throw new Error(`measured text box changed: ${text.width}x${text.height}`);
  }

  text.characters = "";
  text.width = 280;
  text.height = 34;
  await context.createText({
    text: "A very long headline that must be clipped",
    lines: ["A very long headline…"],
    fontFamily: "Arial",
    fontSize: 16,
    fontWeight: "400",
    x: 20,
    y: 30,
    width: 180,
    height: 30,
    textColor: "#111111",
    baselineSource: "browser-measured",
  });
  if (text.characters !== "A very long headline…") {
    throw new Error(`single-line ellipsis was ignored: ${text.characters}`);
  }
  if (text.textAutoResize !== "NONE" || text.width !== 180) {
    throw new Error(`single-line truncation was not bounded: ${text.textAutoResize} ${text.width}`);
  }
  console.log("measured lines kept fixed-width");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
