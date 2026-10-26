const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage() {},
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

const rateLimit = context.classifyFigmaError(
  new Error("Figma rate limit exceeded")
);
const takeover = context.classifyFigmaError(
  new Error("plugin takeover: connection replaced")
);
const deleted = context.classifyFigmaError(
  new Error("NODE_NOT_FOUND: 12:34")
);
const unknown = context.classifyFigmaError(
  new Error("unexpected operation failure")
);

if (rateLimit.category !== "rate-limited" || !rateLimit.retryable) {
  throw new Error(`rate limit was not classified: ${JSON.stringify(rateLimit)}`);
}
if (takeover.category !== "plugin-takeover" || !takeover.noResend) {
  throw new Error(`takeover was not fail-closed: ${JSON.stringify(takeover)}`);
}
if (deleted.category !== "user-modification" || !deleted.noResend) {
  throw new Error(
    `concurrent deletion was not classified: ${JSON.stringify(deleted)}`
  );
}
if (unknown.category !== "unknown" || !unknown.noResend) {
  throw new Error(`unknown was not fail-closed: ${JSON.stringify(unknown)}`);
}

console.log("plugin error classification completed");
