const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const uiPath = path.join(repoRoot, "figma_bridge", "ui.html");
const html = fs.readFileSync(uiPath, "utf8");
const match = html.match(/<script>([\s\S]*?)<\/script>/);
if (!match) throw new Error("plugin UI script was not found");

function element() {
  return {
    value: "",
    disabled: false,
    textContent: "",
    listeners: {},
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    },
  };
}

const elements = {
  "bridge-url": element(),
  "plugin-token": element(),
  "save-connect": element(),
  status: element(),
  error: element(),
};
elements["bridge-url"].value = "ws://localhost:8765";

const parentMessages = [];
const sockets = [];
class FakeWebSocket {
  static OPEN = 1;

  constructor(url) {
    this.url = url;
    this.sent = [];
    this.closeCode = null;
    this.readyState = FakeWebSocket.OPEN;
    sockets.push(this);
  }

  send(payload) {
    this.sent.push(JSON.parse(payload));
  }

  close() {
    this.closeCode = 1000;
  }
}

const windowListeners = {};
const context = vm.createContext({
  document: {
    getElementById(id) {
      if (!elements[id]) throw new Error(`unknown element: ${id}`);
      return elements[id];
    },
  },
  parent: {
    postMessage(message) {
      parentMessages.push(message);
    },
  },
  window: {
    addEventListener(name, callback) {
      windowListeners[name] = callback;
    },
  },
  WebSocket: FakeWebSocket,
  setTimeout,
  clearTimeout,
  JSON,
  String,
  Error,
});

vm.runInContext(match[1], context, { filename: uiPath });

const configRequest = parentMessages.find(
  (message) => message.pluginMessage?.type === "plugin-config-request",
);
if (!configRequest) throw new Error("UI did not request plugin configuration");

windowListeners.message({
  data: {
    pluginMessage: {
      type: "plugin-config",
      config: { bridgeUrl: "ws://localhost:8765", pluginToken: "" },
    },
  },
});
if (sockets.length !== 1) throw new Error("UI did not create a WebSocket");
sockets[0].onopen();

windowListeners.message({
  data: {
    pluginMessage: {
      type: "response",
      requestId: "request-123",
      result: { ok: true },
    },
  },
});

const responseForwarded = sockets[0].sent.some(
  (message) =>
    message.type === "response" &&
    message.requestId === "request-123" &&
    message.result?.ok === true,
);
if (!responseForwarded) {
  throw new Error(
    `plugin response was not forwarded to the bridge: ${JSON.stringify(sockets[0].sent)}`,
  );
}

console.log("plugin UI response forwarding completed");
