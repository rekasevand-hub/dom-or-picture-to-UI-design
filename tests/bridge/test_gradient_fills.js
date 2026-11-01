const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

let created = null;
const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
  currentPage: {
    appendChild() {},
  },
  getNodeById() {
    return null;
  },
  createRectangle() {
    created = {
      fills: [],
      resize() {},
    };
    return created;
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

async function main() {
  await context.createRectangle({
    x: 0,
    y: 0,
    width: 200,
    height: 80,
    fillColor: "#1b315e",
    gradient: {
      type: "linear",
      angle: 270,
      detailedStops: [
        { color: "#1b315e", offset: 0 },
        { color: "#115291", offset: 0.52 },
        { color: "#143e74", offset: 0.87 },
      ],
    },
  });
  const paint = created.fills[0];
  if (!paint || paint.type !== "GRADIENT_LINEAR") {
    throw new Error(`expected GRADIENT_LINEAR, got ${JSON.stringify(paint)}`);
  }
  if (!paint.gradientStops || paint.gradientStops.length !== 3) {
    throw new Error(`gradient stops missing: ${JSON.stringify(paint)}`);
  }
  if (Math.abs(paint.gradientStops[1].position - 0.52) > 0.001) {
    throw new Error(`gradient stop position mismatch: ${JSON.stringify(paint)}`);
  }

  await context.createRectangle({
    x: 0,
    y: 0,
    width: 200,
    height: 80,
    fillColor: "transparent",
    gradient: {
      type: "linear",
      angle: 180,
      detailedStops: [
        { color: "rgba(0, 0, 0, 0)", offset: 0.35 },
        { color: "rgba(0, 0, 0, 0.55)", offset: 1 },
      ],
    },
  });
  const alphaPaint = created.fills[0];
  if (alphaPaint.gradientStops[0].color.a !== 0) {
    throw new Error(`transparent stop lost its alpha: ${JSON.stringify(alphaPaint)}`);
  }
  if (Math.abs(alphaPaint.gradientStops[1].color.a - 0.55) > 0.001) {
    throw new Error(`semi-transparent stop alpha mismatch: ${JSON.stringify(alphaPaint)}`);
  }
  console.log("gradient fills materialized");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
