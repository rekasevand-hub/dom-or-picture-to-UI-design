const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const codePath = path.join(repoRoot, "figma_bridge", "code.js");
const code = fs.readFileSync(codePath, "utf8");

const messages = [];
const stored = {
  bridgeUrl: "wss://localhost:8765",
  pluginToken: "existing-token",
};
const figma = {
  showUI() {},
  ui: {
    onmessage: null,
    postMessage(message) {
      messages.push(message);
    },
  },
  clientStorage: {
    async getAsync() {
      return stored;
    },
    async setAsync(key, value) {
      if (key !== "figmaBridgePluginConfig") {
        throw new Error(`unexpected storage key: ${key}`);
      }
      Object.assign(stored, value);
    },
  },
};

const context = vm.createContext({
  __html__: "",
  figma,
  console,
});

vm.runInContext(code, context, { filename: codePath });

(async () => {
  await figma.ui.onmessage({ type: "plugin-config-request" });
  const loaded = messages.find((message) => message.type === "plugin-config");
  if (!loaded || loaded.config.pluginToken !== "existing-token") {
    throw new Error(`plugin config was not loaded: ${JSON.stringify(messages)}`);
  }

  await figma.ui.onmessage({
    type: "save-plugin-config",
    config: {
      bridgeUrl: "wss://127.0.0.1:9443",
      pluginToken: "new-token",
    },
  });
  if (stored.bridgeUrl !== "wss://127.0.0.1:9443") {
    throw new Error("bridge URL was not persisted");
  }
  if (stored.pluginToken !== "new-token") {
    throw new Error("plugin token was not persisted");
  }
  if (!messages.some((message) => message.type === "plugin-config-saved")) {
    throw new Error("save acknowledgement missing");
  }
  console.log("plugin token storage completed");
})().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
