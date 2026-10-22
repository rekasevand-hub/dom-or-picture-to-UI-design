const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const frame = {
  type: "FRAME",
  name: "",
  fills: [],
  x: 0,
  y: 0,
  width: 0,
  height: 0,
  layoutMode: "NONE",
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
  createFrame() {
    return frame;
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

context.createFrame({
  name: "Mobile",
  width: 390,
  height: 844,
  backgroundColor: "#f7f8fa",
});

const fill = frame.fills[0];
const expected = {
  r: 247 / 255,
  g: 248 / 255,
  b: 250 / 255,
};
if (
  !fill
  || fill.type !== "SOLID"
  || Math.abs(fill.color.r - expected.r) > 1e-6
  || Math.abs(fill.color.g - expected.g) > 1e-6
  || Math.abs(fill.color.b - expected.b) > 1e-6
) {
  throw new Error(`frame backgroundColor was not applied: ${JSON.stringify(frame.fills)}`);
}

console.log("frame backgroundColor applied");
