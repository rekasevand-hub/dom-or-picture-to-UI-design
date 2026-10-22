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
    children: [],
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    fills: [],
    strokes: [],
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

const page = {
  children: [],
  appendChild(node) {
    if (!this.children.includes(node)) this.children.push(node);
    node.parent = this;
  },
};

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: page,
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

async function run() {
  const owned = await context.applyBatch({
    transactionId: "job-owned",
    actions: [
      {
        action: "create_frame",
        params: { name: "Owned root", width: 100, height: 100 },
      },
      {
        action: "create_rectangle",
        params: { name: "Owned child", width: 20, height: 20 },
      },
    ],
  });
  if (owned.status !== "committed") {
    throw new Error(`expected owned commit: ${JSON.stringify(owned)}`);
  }
  if (owned.ownership?.marker !== "plugin-data-v1") {
    throw new Error(`missing ownership marker receipt: ${JSON.stringify(owned)}`);
  }
  const ownedIds = owned.committed.map((item) => item.result);
  for (const nodeId of ownedIds) {
    const node = figma.getNodeById(nodeId);
    if (node.getPluginData("figma_auto_agent.owner") !== "figma_auto_agent") {
      throw new Error(`owner marker missing on ${nodeId}`);
    }
    if (node.getPluginData("figma_auto_agent.job_id") !== "job-owned") {
      throw new Error(`job marker missing on ${nodeId}`);
    }
  }
  const report = await context.ownershipReport({ jobId: "job-owned" });
  if (report.status !== "reported" || report.matched !== 2) {
    throw new Error(`unexpected ownership report: ${JSON.stringify(report)}`);
  }

  const unrelatedRoot = figma.createFrame();
  unrelatedRoot.name = "Unrelated root";
  page.appendChild(unrelatedRoot);
  unrelatedRoot.setPluginData("figma_auto_agent.owner", "other_owner");
  unrelatedRoot.setPluginData("figma_auto_agent.job_id", "job-owned");
  const unrelatedOtherJob = figma.createFrame();
  unrelatedOtherJob.name = "Unrelated other job";
  page.appendChild(unrelatedOtherJob);
  unrelatedOtherJob.setPluginData(
    "figma_auto_agent.owner",
    "figma_auto_agent"
  );
  unrelatedOtherJob.setPluginData("figma_auto_agent.job_id", "job-other");

  const cleanup = await context.cleanupOwnedJob({ jobId: "job-owned" });
  if (cleanup.status !== "cleaned" || cleanup.removed !== 2) {
    throw new Error(`unexpected cleanup: ${JSON.stringify(cleanup)}`);
  }
  if (!nodes.has(unrelatedRoot.id)) {
    throw new Error("cleanup removed a node with a different owner");
  }
  if (!nodes.has(unrelatedOtherJob.id)) {
    throw new Error("cleanup removed a node from a different job");
  }
  for (const nodeId of ownedIds) {
    if (nodes.has(nodeId)) {
      throw new Error(`owned node survived cleanup: ${nodeId}`);
    }
  }

  const rejected = await context.cleanupOwnedJob({ jobId: "" });
  if (rejected.status !== "rejected") {
    throw new Error(`empty job cleanup must reject: ${JSON.stringify(rejected)}`);
  }

  const originalCreateFrame = figma.createFrame;
  figma.createFrame = () => {
    const node = makeNode("FRAME");
    node.setPluginData = () => {
      throw new Error("injected marker failure");
    };
    return node;
  };
  const markerFailure = await context.applyBatch({
    transactionId: "job-marker-failure",
    actions: [
      {
        action: "create_frame",
        params: { name: "Marker failure", width: 10, height: 10 },
      },
    ],
  });
  figma.createFrame = originalCreateFrame;
  if (
    markerFailure.status !== "partial" ||
    markerFailure.rollback.removed !== 1 ||
    markerFailure.ownership.marked !== 0
  ) {
    throw new Error(
      `marker failure did not roll back: ${JSON.stringify(markerFailure)}`
    );
  }
  console.log("ownership marker and job cleanup completed");
}

run().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
