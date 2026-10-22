const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

function makeChild(index) {
  return {
    id: `RECTANGLE:${index + 1}`,
    type: "RECTANGLE",
    name: `Cell ${index + 1}`,
    x: 0,
    y: 0,
    width: 40,
    height: 30,
    layoutPositioning: "AUTO",
    layoutSizingHorizontal: "FIXED",
    layoutSizingVertical: "FIXED",
    gridRowSpan: 1,
    gridColumnSpan: 1,
    gridChildHorizontalAlign: "MIN",
    gridChildVerticalAlign: "MIN",
    setGridChildPosition(row, column) {
      this.gridRowAnchorIndex = row;
      this.gridColumnAnchorIndex = column;
    },
  };
}

const frame = {
  id: "FRAME:1",
  type: "FRAME",
  name: "Grid and Wrap",
  x: 0,
  y: 0,
  width: 320,
  height: 240,
  layoutMode: "NONE",
  layoutWrap: "NO_WRAP",
  itemSpacing: 0,
  counterAxisSpacing: 0,
  paddingTop: 0,
  paddingRight: 0,
  paddingBottom: 0,
  paddingLeft: 0,
  primaryAxisSizingMode: "FIXED",
  counterAxisSizingMode: "FIXED",
  primaryAxisAlignItems: "MIN",
  counterAxisAlignItems: "MIN",
  _gridRowCount: 0,
  _gridColumnCount: 0,
  gridRowGap: 0,
  gridColumnGap: 0,
  gridItemsPositioning: "MANUAL",
  gridAutoTracks: "NONE",
  gridRowSizes: [],
  gridColumnSizes: [],
  children: [0, 1, 2, 3].map(makeChild),
  resize(width, height) {
    this.width = width;
    this.height = height;
  },
};

Object.defineProperties(frame, {
  gridRowCount: {
    configurable: true,
    get() {
      return this._gridRowCount;
    },
    set(value) {
      this._gridRowCount = value;
      this.gridRowSizes = Array.from(
        { length: value },
        () => ({ type: "FIXED", value: 30 }),
      );
    },
  },
  gridColumnCount: {
    configurable: true,
    get() {
      return this._gridColumnCount;
    },
    set(value) {
      this._gridColumnCount = value;
      this.gridColumnSizes = Array.from(
        { length: value },
        () => ({ type: "FIXED", value: 40 }),
      );
    },
  },
});

Object.defineProperty(frame, "layoutMode", {
  configurable: true,
  get() {
    return this._layoutMode || "NONE";
  },
  set(value) {
    this._layoutMode = value;
    if (value === "GRID") {
      if (this.gridRowCount > 0) {
        this.gridRowSizes = Array.from(
          { length: this.gridRowCount },
          () => ({ type: "FIXED", value: 30 }),
        );
      }
      if (this.gridColumnCount > 0) {
        this.gridColumnSizes = Array.from(
          { length: this.gridColumnCount },
          () => ({ type: "FIXED", value: 40 }),
        );
      }
    }
  },
});

const nodes = new Map([[frame.id, frame]]);
for (const child of frame.children) nodes.set(child.id, child);
const gridDimensionWrites = [];
const gridRowCountDescriptor = Object.getOwnPropertyDescriptor(frame, "gridRowCount");
const gridColumnCountDescriptor = Object.getOwnPropertyDescriptor(
  frame,
  "gridColumnCount",
);
Object.defineProperty(frame, "gridRowCount", {
  configurable: true,
  get: gridRowCountDescriptor.get,
  set(value) {
    gridDimensionWrites.push("row");
    gridRowCountDescriptor.set.call(this, value);
  },
});
Object.defineProperty(frame, "gridColumnCount", {
  configurable: true,
  get: gridColumnCountDescriptor.get,
  set(value) {
    gridDimensionWrites.push("column");
    gridColumnCountDescriptor.set.call(this, value);
  },
});

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: {
    children: [frame],
    appendChild() {},
  },
  getNodeById(id) {
    return nodes.get(id) || null;
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

async function run() {
  await context.setLayoutFlow({
    nodeId: frame.id,
    layout: {
      mode: "HORIZONTAL",
      wrap: "WRAP",
      itemSpacing: 8,
    },
    width: 320,
    depth: 1,
  });
  if (frame.layoutMode !== "HORIZONTAL" || frame.layoutWrap !== "WRAP") {
    throw new Error(`wrap was not applied: ${frame.layoutMode}/${frame.layoutWrap}`);
  }

  gridDimensionWrites.length = 0;
  const tree = await context.setLayoutFlow({
    nodeId: frame.id,
    layout: {
      mode: "GRID",
      gridRowCount: 2,
      gridColumnCount: 2,
      gridRowGap: 6,
      gridColumnGap: 10,
      paddingTop: 4,
      paddingRight: 4,
      paddingBottom: 4,
      paddingLeft: 4,
      gridRowSizes: [{ type: "FIXED", value: 30 }, { type: "FLEX", value: 1 }],
      gridColumnSizes: [
        { type: "FIXED", value: 40 },
        { type: "FLEX", value: 1 },
      ],
      gridItemsPositioning: "MANUAL",
      gridAutoTracks: "ROWS",
      layoutSizingHorizontal: "FIXED",
      layoutSizingVertical: "FIXED",
    },
    children: [
      {
        index: 0,
        rowAnchor: 0,
        columnAnchor: 0,
        rowSpan: 1,
        columnSpan: 2,
        layoutSizingHorizontal: "FILL",
        gridChildHorizontalAlign: "CENTER",
      },
      {
        index: 1,
        rowAnchor: 1,
        columnAnchor: 1,
        layoutSizingVertical: "FILL",
        gridChildVerticalAlign: "MAX",
      },
    ],
    width: 320,
    height: 240,
    depth: 2,
  });

  if (tree.layoutMode !== "GRID") {
    throw new Error(`grid mode was not applied: ${tree.layoutMode}`);
  }
  if (tree.gridRowCount !== 2 || tree.gridColumnCount !== 2) {
    throw new Error(`grid counts missing from readback: ${JSON.stringify(tree)}`);
  }
  if (frame.gridRowGap !== 6 || frame.gridColumnGap !== 10) {
    throw new Error("grid gaps were not applied");
  }
  if (frame.gridRowSizes[1].type !== "FLEX" || frame.gridColumnSizes[1].type !== "FLEX") {
    throw new Error("grid track sizes were not applied");
  }
  if (frame.children[0].gridColumnSpan !== 2
      || frame.children[0].gridChildHorizontalAlign !== "CENTER") {
    throw new Error("grid child span/alignment was not applied");
  }
  if (frame.children[1].gridRowAnchorIndex !== 1
      || frame.children[1].gridColumnAnchorIndex !== 1) {
    throw new Error("grid child explicit position was not applied");
  }
  if (gridDimensionWrites.join(",") !== "column,row") {
    throw new Error(
      `grid dimensions must be written column-first: ${gridDimensionWrites.join(",")}`,
    );
  }
  gridDimensionWrites.length = 0;
  await context.setLayoutFlow({
    nodeId: frame.id,
    layout: {
      mode: "GRID",
      gridRowCount: 2,
      gridColumnCount: 2,
      gridRowSizes: [{ type: "FIXED", value: 30 }, { type: "FLEX", value: 1 }],
      gridColumnSizes: [
        { type: "FIXED", value: 40 },
        { type: "FLEX", value: 1 },
      ],
    },
    children: [],
    depth: 0,
  });
  if (gridDimensionWrites.length !== 0) {
    throw new Error(
      `unchanged grid counts must not be rewritten: ${gridDimensionWrites.join(",")}`,
    );
  }
  gridDimensionWrites.length = 0;
  const childOverrideTree = await context.setGridChildOverrides({
    nodeId: frame.id,
    children: [{ index: 1, gridChildHorizontalAlign: "MAX" }],
    depth: 1,
  });
  if (frame.children[1].gridChildHorizontalAlign !== "MAX") {
    throw new Error("grid child override was not applied");
  }
  if (gridDimensionWrites.length !== 0) {
    throw new Error("grid child overrides must not rewrite grid dimensions");
  }
  if (childOverrideTree.layoutMode !== "GRID") {
    throw new Error("grid child override readback lost grid mode");
  }

  console.log("grid and wrap layout completed");
}

run().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
