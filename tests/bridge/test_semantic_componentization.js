const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");

let nextId = 1;
const state = {
  nodes: new Map(),
  failInstanceAt: null,
  instanceCount: 0,
};

function makeNode(type, width = 120, height = 40) {
  const node = {
    id: `${String(type).toLowerCase()}:${nextId++}`,
    type,
    name: "",
    x: 0,
    y: 0,
    width,
    height,
    visible: true,
    children: [],
    pluginData: new Map(),
    resize(w, h) {
      this.width = w;
      this.height = h;
    },
    appendChild(child) {
      if (child.parent) child.parent.children = child.parent.children.filter((item) => item !== child);
      this.children.push(child);
      child.parent = this;
    },
    insertChild(index, child) {
      if (child.parent) child.parent.children = child.parent.children.filter((item) => item !== child);
      this.children.splice(index, 0, child);
      child.parent = this;
    },
    findAll(predicate) {
      const result = [];
      const visit = (parent) => {
        for (const child of parent.children || []) {
          if (predicate(child)) result.push(child);
          visit(child);
        }
      };
      visit(this);
      return result;
    },
    setPluginData(key, value) {
      this.pluginData.set(key, value);
    },
    remove() {
      this.removed = true;
      if (this.parent) {
        this.parent.children = this.parent.children.filter((item) => item !== this);
      }
      state.nodes.delete(this.id);
    },
    clone() {
      const clone = makeNode(this.type, this.width, this.height);
      clone.name = this.name;
      clone.x = this.x;
      clone.y = this.y;
      clone.visible = this.visible;
      for (const [key, value] of this.pluginData.entries()) clone.pluginData.set(key, value);
      for (const child of this.children) clone.appendChild(child.clone());
      state.nodes.set(clone.id, clone);
      return clone;
    },
  };
  state.nodes.set(node.id, node);
  return node;
}

const originalPage = makeNode("PAGE", 1440, 900);
const componentsPage = makeNode("PAGE", 1440, 900);
componentsPage.name = "DOM Components";
state.nodes.set(originalPage.id, originalPage);
state.nodes.set(componentsPage.id, componentsPage);

function createComponent(node) {
  node.type = "COMPONENT";
  node.createInstance = () => {
    if (state.failInstanceAt === state.instanceCount) {
      throw new Error("simulated instance failure");
    }
    state.instanceCount += 1;
    const instance = makeNode("INSTANCE", node.width, node.height);
    instance.name = `${node.name} Instance`;
    instance.visible = true;
    for (const child of node.children) instance.appendChild(child.clone());
    return instance;
  };
  return node;
}

const figma = {
  root: null,
  currentPage: originalPage,
  showUI() {},
  ui: { onmessage: null, postMessage() {} },
  getNodeById(id) {
    return state.nodes.get(id) || null;
  },
  createPage() {
    const page = makeNode("PAGE", 1440, 900);
    figma.root.children.push(page);
    return page;
  },
  createComponentFromNode(node) {
    return createComponent(node);
  },
};
figma.root = { children: [originalPage, componentsPage] };

const context = vm.createContext({ __html__: "", figma, console });
vm.runInContext(fs.readFileSync(codePath, "utf8"), context, { filename: codePath });

function makeButton(label, x) {
  const frame = makeNode("FRAME", 120, 40);
  frame.x = x;
  frame.y = 10;
  frame.name = `Button ${label}`;
  const text = makeNode("TEXT", 60, 20);
  text.characters = label;
  text.x = 12;
  text.y = 10;
  frame.appendChild(text);
  return frame;
}

function resetPage() {
  state.failInstanceAt = null;
  state.instanceCount = 0;
  originalPage.children = [];
  componentsPage.children = [];
}

async function testTwoButtons() {
  resetPage();
  const first = makeButton("Save", 20);
  const second = makeButton("Cancel", 180);
  originalPage.appendChild(first);
  originalPage.appendChild(second);
  const result = await context.componentizeSemanticGroups({
    groups: [{
      groupId: "button-set-0",
      role: "button",
      structuralSignature: "visual:0|text:1|interactive:0",
      members: [
        { nodeId: first.id, sourceDomIndices: [4] },
        { nodeId: second.id, sourceDomIndices: [5] },
      ],
    }],
  });
  if (result.status !== "committed" || result.masters.length !== 1 || result.instances.length !== 1) {
    throw new Error(`two-button componentization failed: ${JSON.stringify(result)}`);
  }
  if (!first.visible || second.visible) {
    throw new Error("source visibility was not switched after commit");
  }
  const instanceText = figma.getNodeById(result.instances[0].nodeId)
    .findAll((node) => node.type === "TEXT")[0];
  if (instanceText.characters !== "Cancel") {
    throw new Error(`instance text override missing: ${instanceText.characters}`);
  }
}

async function testThreeCards() {
  resetPage();
  const cards = [20, 180, 340].map((x, index) => {
    const card = makeButton(`Card ${index + 1}`, x);
    originalPage.appendChild(card);
    return card;
  });
  const result = await context.componentizeSemanticGroups({
    groups: [{
      groupId: "card-set-0",
      role: "card",
      structuralSignature: "visual:1|text:2|interactive:1",
      members: cards.map((node, index) => ({
        nodeId: node.id,
        sourceDomIndices: [10 + index * 2],
      })),
    }],
  });
  if (result.masters.length !== 1 || result.instances.length !== 2) {
    throw new Error(`three-card componentization failed: ${JSON.stringify(result)}`);
  }
}

async function testRejectedGroupsDoNotMutate() {
  resetPage();
  const first = makeButton("Save", 20);
  const second = makeButton("Cancel", 180);
  originalPage.appendChild(first);
  originalPage.appendChild(second);
  const result = await context.componentizeSemanticGroups({
    groups: [{
      groupId: "button-set-0",
      structuralSignature: "visual:0|text:1|interactive:0",
      members: [
        { nodeId: first.id, structuralSignature: "visual:0|text:1|interactive:0" },
        { nodeId: second.id, structuralSignature: "visual:1|text:2|interactive:1" },
      ],
    }],
  });
  if (result.status !== "rejected" || result.rejected[0].code !== "STRUCTURAL_SIGNATURE_MISMATCH") {
    throw new Error(`mismatched signature was not rejected: ${JSON.stringify(result)}`);
  }
  if (!first.visible || !second.visible || componentsPage.children.length !== 0) {
    throw new Error("rejected group mutated rendered nodes");
  }
}

async function testMissingNodeIsRejectedWithoutMutation() {
  resetPage();
  const first = makeButton("Save", 20);
  originalPage.appendChild(first);
  const result = await context.componentizeSemanticGroups({
    groups: [{
      groupId: "button-set-0",
      structuralSignature: "visual:0|text:1|interactive:0",
      members: [
        { nodeId: first.id, sourceDomIndices: [4] },
        { nodeId: "missing:2", sourceDomIndices: [5] },
      ],
    }],
  });
  if (result.status !== "rejected" || result.rejected[0].code !== "NODE_NOT_FOUND") {
    throw new Error(`missing node was not rejected: ${JSON.stringify(result)}`);
  }
  if (!first.visible || componentsPage.children.length !== 0) {
    throw new Error("missing-node rejection mutated the rendered document");
  }
}

async function testPartialFailureRollsBackGroup() {
  resetPage();
  state.failInstanceAt = 1;
  const first = makeButton("Save", 20);
  const second = makeButton("Cancel", 180);
  const third = makeButton("Later", 340);
  originalPage.appendChild(first);
  originalPage.appendChild(second);
  originalPage.appendChild(third);
  const result = await context.componentizeSemanticGroups({
    groups: [{
      groupId: "button-set-0",
      structuralSignature: "visual:0|text:1|interactive:0",
      members: [
        { nodeId: first.id, sourceDomIndices: [4] },
        { nodeId: second.id, sourceDomIndices: [5] },
        { nodeId: third.id, sourceDomIndices: [6] },
      ],
    }],
  });
  if (result.status !== "rejected" || result.rejected[0].code !== "COMPONENTIZATION_FAILED") {
    throw new Error(`failure was not surfaced: ${JSON.stringify(result)}`);
  }
  if (!first.visible || !second.visible || !third.visible) {
    throw new Error("partial failure hid original rendered nodes");
  }
  if (componentsPage.children.length !== 0) {
    throw new Error("partial failure left a component master behind");
  }
  if (result.instances.length !== 0) {
    throw new Error("partial failure leaked instance metadata");
  }
}

async function main() {
  await testTwoButtons();
  await testThreeCards();
  await testRejectedGroupsDoNotMutate();
  await testMissingNodeIsRejectedWithoutMutation();
  await testPartialFailureRollsBackGroup();
  console.log("semantic componentization completed");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
