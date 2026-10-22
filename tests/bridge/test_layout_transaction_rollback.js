const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

let childRowAnchor = 0;
let childColumnAnchor = 0;
let childPositionWrites = 0;

const child = {
  id: "RECTANGLE:1",
  type: "RECTANGLE",
  name: "Child",
  x: 12,
  y: 14,
  width: 30,
  height: 20,
  layoutPositioning: "AUTO",
  layoutSizingHorizontal: "FIXED",
  layoutSizingVertical: "FIXED",
  gridRowSpan: 1,
  gridColumnSpan: 1,
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
  setGridChildPosition(row, column) {
    childRowAnchor = row;
    childColumnAnchor = column;
    childPositionWrites += 1;
  },
};

Object.defineProperties(child, {
  gridRowAnchorIndex: {
    configurable: true,
    get() {
      return childRowAnchor;
    },
  },
  gridColumnAnchorIndex: {
    configurable: true,
    get() {
      return childColumnAnchor;
    },
  },
});

const frame = {
  id: "FRAME:1",
  type: "FRAME",
  name: "Frame",
  x: 100,
  y: 200,
  width: 240,
  height: 160,
  layoutMode: "NONE",
  layoutWrap: "NO_WRAP",
  itemSpacing: 0,
  paddingTop: 0,
  paddingRight: 0,
  paddingBottom: 0,
  paddingLeft: 0,
  primaryAxisSizingMode: "FIXED",
  counterAxisSizingMode: "FIXED",
  primaryAxisAlignItems: "MIN",
  counterAxisAlignItems: "MIN",
  layoutSizingHorizontal: "FIXED",
  layoutSizingVertical: "FIXED",
  gridRowCount: 0,
  gridColumnCount: 0,
  gridRowGap: 0,
  gridColumnGap: 0,
  gridItemsPositioning: "MANUAL",
  gridAutoTracks: "NONE",
  gridRowSizes: [],
  gridColumnSizes: [],
  children: [child],
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
};

const text = {
  id: "TEXT:2",
  type: "TEXT",
  name: "Text",
  x: 0,
  y: 0,
  width: 80,
  height: 20,
  visible: true,
  fontSize: 16,
  fontName: { family: "Arial", style: "Regular" },
  get characters() {
    return this._characters;
  },
  set characters(value) {
    if (value === "FAIL") throw new Error("INJECTED_TEXT_FAILURE");
    this._characters = value;
  },
  _characters: "before",
};

const nodes = new Map([
  [frame.id, frame],
  [child.id, child],
  [text.id, text],
]);

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: {
    children: [frame, text],
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
  const result = await context.applyEditBatch({
    transactionId: "layout-rollback",
    actions: [
      {
        action: "set_layout_flow",
        params: {
          nodeId: frame.id,
          layout: {
            mode: "HORIZONTAL",
            itemSpacing: 24,
            paddingTop: 10,
            paddingRight: 10,
            paddingBottom: 10,
            paddingLeft: 10,
          },
          width: 240,
          depth: 1,
        },
      },
      {
        action: "set_text",
        params: { nodeId: text.id, text: "FAIL" },
      },
    ],
  });

  if (result.status !== "rolled-back") {
    throw new Error(`expected layout rollback: ${JSON.stringify(result)}`);
  }
  if (frame.layoutMode !== "NONE") {
    throw new Error(`layout mode not restored: ${frame.layoutMode}`);
  }
  if (frame.itemSpacing !== 0 || frame.paddingTop !== 0) {
    throw new Error(
      `layout spacing not restored: ${frame.itemSpacing}/${frame.paddingTop}`,
    );
  }
  if (child.x !== 12 || child.y !== 14) {
    throw new Error(`child position not restored: ${child.x}/${child.y}`);
  }
  if (childPositionWrites !== 1) {
    throw new Error(
      `grid anchors must use setGridChildPosition during rollback: ${childPositionWrites}`,
    );
  }
  if (text.characters !== "before") {
    throw new Error(`text changed after failed transaction: ${text.characters}`);
  }

  frame._paddingTop = frame.paddingTop;
  delete frame.paddingTop;
  Object.defineProperty(frame, "paddingTop", {
    configurable: true,
    get() {
      return this._paddingTop;
    },
    set(value) {
      this._paddingTop = value;
      if (this._failNextPaddingWrite) {
        this._failNextPaddingWrite = false;
        throw new Error("INJECTED_LAYOUT_PARTIAL_FAILURE");
      }
    },
  });
  frame._failNextPaddingWrite = true;

  const partial = await context.applyEditBatch({
    transactionId: "layout-partial-failure",
    actions: [
      {
        action: "set_text",
        params: { nodeId: text.id, text: "temporary" },
      },
      {
        action: "set_layout_flow",
        params: {
          nodeId: frame.id,
          layout: {
            mode: "HORIZONTAL",
            itemSpacing: 24,
            paddingTop: 10,
            paddingRight: 10,
            paddingBottom: 10,
            paddingLeft: 10,
          },
          width: 240,
          depth: 1,
        },
      },
    ],
  });
  if (partial.status !== "rolled-back") {
    throw new Error(
      `expected failed layout action rollback: ${JSON.stringify(partial)}`,
    );
  }
  if (partial.rollback.restored !== 2) {
    throw new Error(
      `failed layout action was not added to rollback stack: ${JSON.stringify(partial)}`,
    );
  }
  if (frame.layoutMode !== "NONE" || frame.itemSpacing !== 0) {
    throw new Error(
      `partial layout mutation survived rollback: ${frame.layoutMode}/${frame.itemSpacing}`,
    );
  }
  if (frame.paddingTop !== 0) {
    throw new Error(`partial padding mutation survived rollback: ${frame.paddingTop}`);
  }
  if (text.characters !== "before") {
    throw new Error(`text changed after partial layout failure: ${text.characters}`);
  }

  console.log("layout transaction rollback completed");
}

run().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
