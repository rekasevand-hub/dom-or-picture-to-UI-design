const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..", "..");
const htmlPath = path.join(repoRoot, "figma_bridge", "ui.html");
const html = fs.readFileSync(htmlPath, "utf8");
const match = html.match(/<script>([\s\S]*?)<\/script>/);
if (!match) throw new Error("ui.html inline script missing");
const script = match[1];

function element() {
  return {
    value: "",
    textContent: "",
    disabled: false,
    handlers: {},
    addEventListener(name, handler) {
      this.handlers[name] = handler;
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
const posted = [];
const windows = [];
let timerCount = 0;

class FakeWebSocket {
  static OPEN = 1;

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }

  send(message) {
    this.sent.push(JSON.parse(message));
  }

  close() {
    this.readyState = 3;
  }
}
FakeWebSocket.instances = [];

const context = vm.createContext({
  document: {
    getElementById(id) {
      if (!elements[id]) throw new Error(`unknown element: ${id}`);
      return elements[id];
    },
  },
  window: {
    addEventListener(name, handler) {
      windows.push({ name, handler });
    },
  },
  parent: {
    postMessage(message) {
      posted.push(message);
    },
  },
  WebSocket: FakeWebSocket,
  setTimeout() {
    timerCount += 1;
    return timerCount;
  },
  clearTimeout() {},
  console,
});

vm.runInContext(script, context, { filename: htmlPath });
const windowHandler = windows.find((entry) => entry.name === "message").handler;
windowHandler({
  data: {
    pluginMessage: {
      type: "plugin-config",
      config: {
        bridgeUrl: "ws://localhost:8765",
        pluginToken: "old-token",
      },
    },
  },
});

const ws = FakeWebSocket.instances[0];
if (!ws || ws.url !== "ws://localhost:8765/plugin") {
  throw new Error("plugin WebSocket was not created");
}
ws.onopen();
if (ws.sent[0].type !== "auth" || ws.sent[0].token !== "old-token") {
  throw new Error("first-frame auth missing");
}

const timersBeforeClose = timerCount;
ws.onclose({ code: 4004, reason: "plugin token rotated or revoked" });
if (!/revok/i.test(elements.status.textContent)) {
  throw new Error(`revocation status missing: ${elements.status.textContent}`);
}
if (!/token/i.test(elements.error.textContent)) {
  throw new Error(`token recovery guidance missing: ${elements.error.textContent}`);
}
if (timerCount !== timersBeforeClose) {
  throw new Error("revoked token scheduled an automatic reconnect");
}

console.log("plugin UI revocation handling completed");
