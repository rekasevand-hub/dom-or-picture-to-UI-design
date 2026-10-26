const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const pluginData = new Map();
const rectangle = {
  id: "RECTANGLE:1",
  type: "RECTANGLE",
  name: "Region member",
  x: 12,
  y: 14,
  width: 30,
  height: 20,
  fills: [],
  setPluginData(key, value) {
    pluginData.set(key, String(value));
  },
  getPluginData(key) {
    return pluginData.get(key) || "";
  },
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
};

const text = {
  id: "TEXT:1",
  type: "TEXT",
  name: "Text",
  x: 0,
  y: 0,
  width: 80,
  height: 20,
  visible: true,
  fontSize: 16,
  fontName: { family: "Arial", style: "Regular" },
  _characters: "before",
  get characters() {
    return this._characters;
  },
  set characters(value) {
    if (value === "FAIL") throw new Error("INJECTED_TEXT_FAILURE");
    this._characters = value;
  },
};

const nodes = new Map([
  [rectangle.id, rectangle],
  [text.id, text],
]);

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: {
    children: [rectangle, text],
    appendChild() {},
  },
  mixed: Symbol("mixed"),
  getNodeById(id) {
    return nodes.get(id) || null;
  },
  async loadFontAsync() {},
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
  atob,
});

vm.runInContext(code, context, { filename: codePath });

async function run() {
  const applied = await context.applyEditBatch({
    transactionId: "region-bounds",
    actions: [
      {
        action: "set_bounds",
        params: {
          nodeId: rectangle.id,
          x: 20,
          y: 24,
          width: 40,
          height: 30,
          regionId: "region-a",
        },
      },
    ],
  });
  if (applied.status !== "committed") {
    throw new Error(`expected bounds commit: ${JSON.stringify(applied)}`);
  }
  const readback = await context.getNodeTree({
    nodeId: rectangle.id,
    depth: 0,
  });
  if (
    readback.bounds.x !== 20
    || readback.bounds.y !== 24
    || readback.bounds.width !== 40
    || readback.bounds.height !== 30
  ) {
    throw new Error(`bounds did not commit: ${JSON.stringify(readback.bounds)}`);
  }
  if (
    !readback.regionMembership
    || readback.regionMembership.regionId !== "region-a"
    || readback.regionMembership.member !== true
  ) {
    throw new Error(
      `region membership did not commit: ${JSON.stringify(readback.regionMembership)}`
    );
  }

  const rolledBack = await context.applyEditBatch({
    transactionId: "region-bounds-rollback",
    actions: [
      {
        action: "set_bounds",
        params: {
          nodeId: rectangle.id,
          x: 99,
          y: 99,
          width: 99,
          height: 99,
          regionId: "region-b",
        },
      },
      {
        action: "set_text",
        params: {
          nodeId: text.id,
          text: "FAIL",
        },
      },
    ],
  });
  if (rolledBack.status !== "rolled-back") {
    throw new Error(
      `expected region rollback: ${JSON.stringify(rolledBack)}`
    );
  }
  if (
    rectangle.x !== 20
    || rectangle.y !== 24
    || rectangle.width !== 40
    || rectangle.height !== 30
  ) {
    throw new Error(
      `overlapping bounds action was not restored: ${JSON.stringify(rectangle)}`
    );
  }
  if (rectangle.getPluginData("figma_auto_agent.region_id") !== "region-a") {
    throw new Error(
      `region marker was not restored: ${rectangle.getPluginData(
        "figma_auto_agent.region_id"
      )}`
    );
  }

  console.log("region bounds and rollback completed");
}

run().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
