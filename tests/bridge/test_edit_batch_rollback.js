const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const nodes = new Map();
let nextId = 1;

function textNode(initial, { failOn } = {}) {
  const node = {
    id: `TEXT:${nextId++}`,
    type: "TEXT",
    name: "Editable text",
    x: 12,
    y: 24,
    width: 120,
    height: 20,
    visible: true,
    fontSize: 16,
    fontName: { family: "Arial", style: "Regular" },
    _characters: initial,
    get characters() {
      return this._characters;
    },
    set characters(value) {
      if (value === failOn) {
        throw new Error("INJECTED_TEXT_WRITE_FAILURE");
      }
      this._characters = value;
    },
    remove() {
      nodes.delete(this.id);
    },
  };
  nodes.set(node.id, node);
  return node;
}

function rectangleNode() {
  const node = {
    id: `RECTANGLE:${nextId++}`,
    type: "RECTANGLE",
    name: "Image",
    x: 0,
    y: 0,
    width: 64,
    height: 64,
    fills: [{
      type: "IMAGE",
      imageHash: "old-hash",
      scaleMode: "FILL",
    }],
    remove() {
      nodes.delete(this.id);
    },
  };
  nodes.set(node.id, node);
  return node;
}

const first = textNode("before-1");
const second = textNode("before-2", { failOn: "FAIL-SECOND" });
const image = rectangleNode();

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
  mixed: Symbol("mixed"),
  getNodeById(id) {
    return nodes.get(id) || null;
  },
  async loadFontAsync() {},
  createImage() {
    return { hash: "new-hash" };
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
  atob,
});

vm.runInContext(code, context, { filename: codePath });

async function run() {
  const rejected = await context.applyEditBatch({
    transactionId: "preflight",
    actions: [
      {
        action: "set_name",
        params: { nodeId: first.id, name: "must-not-commit" },
      },
      {
        action: "set_text",
        params: { nodeId: image.id, text: "not-a-text-node" },
      },
    ],
  });
  if (rejected.status !== "rejected") {
    throw new Error(`expected preflight rejection: ${JSON.stringify(rejected)}`);
  }
  if (first.name !== "Editable text") {
    throw new Error("preflight rejection mutated the first node");
  }

  const rolledBack = await context.applyEditBatch({
    transactionId: "mid-failure",
    actions: [
      {
        action: "set_name",
        params: { nodeId: first.id, name: "committed-name" },
      },
      {
        action: "set_visible",
        params: { nodeId: first.id, visible: false },
      },
      {
        action: "set_text",
        params: { nodeId: first.id, text: "committed-text" },
      },
      {
        action: "set_text",
        params: { nodeId: second.id, text: "FAIL-SECOND" },
      },
    ],
  });
  if (rolledBack.status !== "rolled-back") {
    throw new Error(`expected full rollback: ${JSON.stringify(rolledBack)}`);
  }
  if (rolledBack.rollback.restored !== 4) {
    throw new Error(
      `expected failed action and 3 prior edits restored: ${JSON.stringify(rolledBack)}`,
    );
  }
  if (first.name !== "Editable text") {
    throw new Error(`name not restored: ${first.name}`);
  }
  if (first.visible !== true) {
    throw new Error(`visibility not restored: ${first.visible}`);
  }
  if (first.characters !== "before-1") {
    throw new Error(`text not restored: ${first.characters}`);
  }
  if (second.characters !== "before-2") {
    throw new Error(`failed node mutated: ${second.characters}`);
  }

  const committed = await context.applyEditBatch({
    transactionId: "commit",
    actions: [
      {
        action: "set_name",
        params: { nodeId: image.id, name: "Updated image" },
      },
      {
        action: "replace_image_fill",
        params: {
          nodeId: image.id,
          imageBase64: "aW1hZ2U=",
          fillIndex: 0,
        },
      },
    ],
  });
  if (committed.status !== "committed") {
    throw new Error(`expected committed edit batch: ${JSON.stringify(committed)}`);
  }
  if (image.name !== "Updated image") {
    throw new Error(`name was not committed: ${image.name}`);
  }
  if (image.fills[0].imageHash !== "new-hash") {
    throw new Error(`image fill was not committed: ${image.fills[0].imageHash}`);
  }

  console.log("edit batch rollback completed");
}

run().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
