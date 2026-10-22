const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const nodes = new Map();
let nextId = 1;

function makeNode(type) {
  const pluginData = new Map();
  const node = {
    id: `${type}:${nextId++}`,
    type,
    name: "",
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    fills: [],
    strokes: [],
    children: [],
    setPluginData(key, value) {
      pluginData.set(key, String(value));
    },
    getPluginData(key) {
      return pluginData.get(key) || "";
    },
    remove() {
      this.removed = true;
      nodes.delete(this.id);
    },
    resize(width, height) {
      this.width = width;
      this.height = height;
    },
    appendChild(child) {
      if (!this.children.includes(child)) this.children.push(child);
      child.parent = this;
    },
  };
  nodes.set(node.id, node);
  return node;
}

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: {
    children: [],
    appendChild(node) {
      if (!this.children.includes(node)) this.children.push(node);
      node.parent = this;
    },
  },
  getNodeById(id) {
    return nodes.get(id) || null;
  },
  createFrame() {
    return makeNode("FRAME");
  },
  createRectangle() {
    return makeNode("RECTANGLE");
  },
  createEllipse() {
    return makeNode("ELLIPSE");
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

context.applyBatch({
  transactionId: "tx-1",
  actions: [
    {
      action: "create_frame",
      params: { name: "Root", width: 100, height: 100 },
    },
    {
      action: "create_rectangle",
      params: { name: "Child", width: 20, height: 20 },
    },
    {
      action: "create_frame",
      params: {
        name: "Missing parent child",
        width: 20,
        height: 20,
        parentId: "missing-parent",
      },
    },
  ],
}).then((result) => {
  if (result.status !== "partial") {
    throw new Error(`expected partial status: ${JSON.stringify(result)}`);
  }
  if (result.rollback.removed !== 2) {
    throw new Error(`expected 2 rollback removals: ${JSON.stringify(result)}`);
  }
  if (nodes.size !== 0) {
    throw new Error(`transaction left nodes behind: ${nodes.size}`);
  }
  console.log("batch rollback completed");
}).catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
