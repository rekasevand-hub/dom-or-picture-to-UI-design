const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

function makeNode(type) {
  return {
    id: `${type.toLowerCase()}-${Math.random().toString(16).slice(2)}`,
    type,
    name: "",
    x: 0,
    y: 0,
    width: 100,
    height: 40,
    fills: [],
    strokes: [],
    children: [],
    fontName: null,
    characters: "",
    fontSize: 16,
    resize(width, height) {
      this.width = width;
      this.height = height;
    },
    appendChild(child) {
      this.children.push(child);
      child.parent = this;
    },
    findOne(predicate) {
      return this.children.find(predicate) || null;
    },
    remove() {
      this.removed = true;
    },
  };
}

let sourceText;
let instanceText;

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: {
    children: [],
    appendChild(node) {
      node.parent = this;
    },
  },
  getNodeById() {
    return null;
  },
  createFrame() {
    return makeNode("FRAME");
  },
  createComponent() {
    const component = makeNode("COMPONENT");
    component.createInstance = () => {
      const instance = makeNode("INSTANCE");
      instanceText = makeNode("TEXT");
      instanceText.characters = "Component source";
      instance.findOne = (predicate) => (
        predicate(instanceText) ? instanceText : null
      );
      return instance;
    };
    return component;
  },
  createText() {
    const node = makeNode("TEXT");
    if (!sourceText) sourceText = node;
    else instanceText = node;
    return node;
  },
  async loadFontAsync() {},
  async listAvailableFontsAsync() {
    return [{ fontName: { family: "Arial", style: "Regular" } }];
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

context.componentInstanceProbe({}).then((result) => {
  if (result.status !== "pass") {
    throw new Error(`component probe failed: ${JSON.stringify(result)}`);
  }
  if (sourceText.characters !== "Component source") {
    throw new Error("source component text was mutated");
  }
  console.log("component instance probe completed");
}).catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
