const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const calls = [];
const textNode = {
  fontName: null,
  characters: "",
  fontSize: 16,
  fills: [],
  width: 300,
  height: 48,
  x: 0,
  y: 0,
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
  setRangeFontName(start, end, value) {
    calls.push(["font", start, end, value]);
  },
  setRangeFontSize(start, end, value) {
    calls.push(["size", start, end, value]);
  },
  setRangeFills(start, end, value) {
    calls.push(["fill", start, end, value]);
  },
};

const figma = {
  showUI() {},
  ui: { onmessage: null, postMessage() {} },
  currentPage: { appendChild() {}, children: [] },
  getNodeById() { return null; },
  createText() { return textNode; },
  async listAvailableFontsAsync() {
    return [
      { fontName: { family: "Arial", style: "Regular" } },
      { fontName: { family: "Arial", style: "Bold" } },
    ];
  },
  async loadFontAsync() {},
};

const context = vm.createContext({ __html__: "", figma, console });
vm.runInContext(code, context, { filename: codePath });

async function main() {
  await context.createText({
    text: "Alpha Bold Omega",
    richRuns: [
      { start: 0, end: 6, style: { fontSize: 16, fontWeight: "400", textColor: "#111111" } },
      { start: 6, end: 10, style: { fontSize: 18, fontWeight: "700", textColor: "#ff0000" } },
      { start: 10, end: 16, style: { fontSize: 16, fontWeight: "400", textColor: "#111111" } },
    ],
    fontFamily: "Arial",
    fontSize: 16,
    x: 0,
    y: 0,
    width: 300,
    height: 48,
    textColor: "#111111",
    textAnchor: "start",
    boundedText: true,
  });

  const boldFont = calls.find((call) =>
    call[0] === "font"
    && call[1] === 6
    && call[2] === 10
    && call[3]?.style === "Bold"
  );
  const boldSize = calls.find((call) =>
    call[0] === "size" && call[1] === 6 && call[2] === 10 && call[3] === 18
  );
  const boldFill = calls.find((call) =>
    call[0] === "fill" && call[1] === 6 && call[2] === 10
  );
  if (!boldFont || !boldSize || !boldFill) {
    throw new Error(`rich text ranges not applied: ${JSON.stringify(calls)}`);
  }
  if (textNode.textAutoResize !== "NONE" || textNode.width !== 300) {
    throw new Error(`bounded rich text was not fixed-width: ${JSON.stringify(textNode)}`);
  }

  await context.createText({
    text: "Plus Member",
    richRuns: [
      { start: 0, end: 4, style: { fontSize: 14, fontWeight: "400", textColor: "#ffa116" } },
      { start: 4, end: 11, style: { fontSize: 14, fontWeight: "400", textColor: "#ffa116" } },
    ],
    fontFamily: "Arial",
    fontSize: 14,
    x: 20,
    y: 5,
    width: 56,
    height: 19,
    textColor: "#ffa116",
    textAnchor: "start",
    boundedText: true,
    singleLine: true,
  });
  if (textNode.textAutoResize !== "WIDTH_AND_HEIGHT") {
    throw new Error(`single-line rich text should keep overflowing width: ${JSON.stringify(textNode)}`);
  }
  console.log("rich text runs applied");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
