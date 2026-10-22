const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const responses = [];
const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage(message) {
      responses.push(message);
    },
  },
  currentPage: {
    id: "0:0",
    name: "Page",
    type: "PAGE",
    x: 0,
    y: 0,
    width: 100,
    height: 100,
    children: [],
    findAll() {
      return [];
    },
  },
  getNodeById() {
    return null;
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

figma.ui.onmessage({
  action: "get_node_tree",
  requestId: "request-123",
  params: { depth: 1 },
}).then(() => {
  const response = responses[0];
  if (!response || response.requestId !== "request-123") {
    throw new Error(`requestId was not echoed: ${JSON.stringify(response)}`);
  }
  console.log("requestId echoed");
}).catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
