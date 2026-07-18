// Safe bridge between the sandboxed renderer and the main process.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("copilot", {
  getConfig: () => ipcRenderer.invoke("get-config"),
  onUi: (cb) => ipcRenderer.on("ui", (_e, payload) => cb(payload)),
});
