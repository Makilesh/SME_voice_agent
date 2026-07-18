// Electron main process — the "invisible" overlay window.
//
// Invisibility: win.setContentProtection(true) → on Windows 10 2004+ this calls
// SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE), which removes the window from
// ALL capture paths (screen share, recording, screenshots) at the DWM level.
//
// The window is frameless, transparent, always-on-top, and can toggle
// click-through so it never steals focus from the actual meeting.

const { app, BrowserWindow, globalShortcut, ipcMain } = require("electron");
const path = require("path");
const { spawn } = require("child_process");

let win = null;
let backend = null;
let clickThrough = false;

// Set to false if you start the Python backend yourself (uvicorn backend.main:app).
const SPAWN_BACKEND = process.env.SPAWN_BACKEND !== "0";
const PYTHON = process.env.PYTHON || "python";
const PROJECT_ROOT = path.resolve(__dirname, "..");

function startBackend() {
  if (!SPAWN_BACKEND) return;
  backend = spawn(PYTHON, ["-m", "uvicorn", "backend.main:app",
    "--host", "127.0.0.1", "--port", "8000"], {
    cwd: PROJECT_ROOT,
    env: { ...process.env },
  });
  backend.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  backend.stderr.on("data", (d) => process.stderr.write(`[backend] ${d}`));
  backend.on("exit", (code) => console.log(`[backend] exited ${code}`));
}

function createWindow() {
  win = new BrowserWindow({
    width: 420,
    height: 640,
    x: 40,
    y: 60,
    frame: false,
    transparent: true,
    resizable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // The key stealth call — invisible to screen share / capture.
  win.setContentProtection(true);
  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  win.loadFile(path.join(__dirname, "renderer", "index.html"));

  // Re-assert content protection after any show (known Electron quirk on hide/show).
  win.on("show", () => win.setContentProtection(true));
}

function toggleClickThrough() {
  clickThrough = !clickThrough;
  // forward:true still lets us receive mouse-move for hover, but clicks pass through.
  win.setIgnoreMouseEvents(clickThrough, { forward: true });
  win.webContents.send("ui", { type: "clickThrough", value: clickThrough });
}

function registerShortcuts() {
  // Show / hide the overlay.
  globalShortcut.register("CommandOrControl+Shift+Space", () => {
    if (win.isVisible()) win.hide();
    else { win.show(); win.setContentProtection(true); }
  });
  // Toggle click-through (interact vs pass-through).
  globalShortcut.register("CommandOrControl+Shift+X", toggleClickThrough);
  // Force a copilot suggestion on the latest question.
  globalShortcut.register("CommandOrControl+Shift+A", () =>
    win.webContents.send("ui", { type: "forceCopilot" }));
  // Focus the ask box.
  globalShortcut.register("CommandOrControl+Shift+K", () => {
    if (!win.isVisible()) { win.show(); win.setContentProtection(true); }
    win.focus();
    win.webContents.send("ui", { type: "focusAsk" });
  });
  // Nudge opacity.
  globalShortcut.register("CommandOrControl+Shift+Up", () =>
    win.webContents.send("ui", { type: "opacity", delta: 0.1 }));
  globalShortcut.register("CommandOrControl+Shift+Down", () =>
    win.webContents.send("ui", { type: "opacity", delta: -0.1 }));
}

ipcMain.handle("get-config", () => ({ backendUrl: "ws://127.0.0.1:8000/ws/control" }));

app.whenReady().then(() => {
  startBackend();
  createWindow();
  registerShortcuts();
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
  if (backend) backend.kill();
});

app.on("window-all-closed", () => app.quit());
