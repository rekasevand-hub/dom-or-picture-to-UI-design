const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

let activeFontLoads = 0;
let maxActiveFontLoads = 0;
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
  async listAvailableFontsAsync() {
    activeFontLoads += 1;
    maxActiveFontLoads = Math.max(maxActiveFontLoads, activeFontLoads);
    await new Promise((resolve) => setTimeout(resolve, 40));
    activeFontLoads -= 1;
    return [{ fontName: { family: "Arial", style: "Regular" } }];
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

async function run() {
  const first = figma.ui.onmessage({
    action: "font_report",
    requestId: "queue-1",
    params: { families: ["Arial"] },
  });
  const second = figma.ui.onmessage({
    action: "font_report",
    requestId: "queue-2",
    params: { families: ["Arial"] },
  });
  await Promise.all([first, second]);

  if (maxActiveFontLoads !== 1) {
    throw new Error(`plugin actions overlapped: max=${maxActiveFontLoads}`);
  }
  if (responses.length !== 2) {
    throw new Error(`expected two responses: ${JSON.stringify(responses)}`);
  }
  const ids = responses.map((response) => response.requestId).sort();
  if (ids[0] !== "queue-1" || ids[1] !== "queue-2") {
    throw new Error(`responses lost request ids: ${JSON.stringify(ids)}`);
  }

  console.log("plugin actions serialized");
}

run().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
