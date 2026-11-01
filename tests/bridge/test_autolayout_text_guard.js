const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");

function makeText() {
  return {
    id: "text:1",
    type: "TEXT",
    x: 12,
    y: 18,
    width: 220,
    height: 24,
    textAutoResize: "WIDTH_AND_HEIGHT",
    layoutPositioning: "AUTO",
    characters: "A browser measured heading",
    resize(width, height) {
      this.width = width;
      this.height = height;
    },
  };
}

const text = makeText();
const frame = {
  id: "frame:1",
  type: "FRAME",
  x: 0,
  y: 0,
  width: 320,
  height: 80,
  children: [text],
  absoluteBoundingBox: { x: 0, y: 0, width: 320, height: 80 },
  _layoutMode: "NONE",
  get layoutMode() {
    return this._layoutMode;
  },
  set layoutMode(value) {
    this._layoutMode = value;
    if (value !== "NONE") {
      text.layoutPositioning = "AUTO";
      text.width = 120;
      text.height = 48;
      text.textAutoResize = "HEIGHT";
    }
  },
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
};

const figma = {
  showUI() {},
  ui: { onmessage: null, postMessage() {} },
  currentPage: { children: [], appendChild() {} },
  getNodeById(id) {
    if (id === frame.id) return frame;
    if (id === text.id) return text;
    return null;
  },
};

const context = vm.createContext({ __html__: "", figma, console });
vm.runInContext(fs.readFileSync(codePath, "utf8"), context, { filename: codePath });

async function main() {
  const result = await context.setAutoLayout({
    nodeId: frame.id,
    layout: {
      mode: "HORIZONTAL",
      itemSpacing: 8,
      paddingTop: 0,
      paddingRight: 0,
      paddingBottom: 0,
      paddingLeft: 0,
    },
    width: 320,
    height: 80,
    expectChildren: 1,
  });

  if (result.applied !== false || result.reason !== "text-geometry-changed") {
    throw new Error(`text reflow was not rejected: ${JSON.stringify(result)}`);
  }
  if (frame.layoutMode !== "NONE") {
    throw new Error(`layout mode was not rolled back: ${frame.layoutMode}`);
  }
  if (text.x !== 12 || text.y !== 18 || text.width !== 220 || text.height !== 24) {
    throw new Error(`text geometry was not restored: ${JSON.stringify(text)}`);
  }
  if (text.textAutoResize !== "WIDTH_AND_HEIGHT"
      || text.layoutPositioning !== "AUTO") {
    throw new Error(`text layout state was not restored: ${JSON.stringify(text)}`);
  }
  console.log("autolayout text geometry guard completed");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
