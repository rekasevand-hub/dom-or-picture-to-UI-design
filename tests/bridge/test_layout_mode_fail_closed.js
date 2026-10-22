const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const frame = {
  id: "frame-1",
  type: "FRAME",
  name: "Probe",
  x: 0,
  y: 0,
  width: 320,
  height: 200,
  layoutMode: "NONE",
  children: [],
};

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: {
    children: [],
    appendChild() {},
  },
  getNodeById(id) {
    return id === frame.id ? frame : null;
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

context.setLayoutFlow({
  nodeId: frame.id,
  layout: { mode: "MASONRY" },
}).then(() => {
  throw new Error("unsupported MASONRY mode unexpectedly succeeded");
}).catch((error) => {
  if (!String(error.message).includes("UNSUPPORTED_LAYOUT_MODE: MASONRY")) {
    console.error(error.stack || error.message);
    process.exitCode = 1;
    return;
  }
  if (frame.layoutMode !== "NONE") {
    console.error(`frame layoutMode mutated: ${frame.layoutMode}`);
    process.exitCode = 1;
    return;
  }
  console.log("unsupported layout mode failed closed");
});
