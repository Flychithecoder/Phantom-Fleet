// Phantom Fleet desktop shell — Electron main process.
// Wraps the Next.js dashboard, adds a native menu, tray, window-state persistence
// and a tiny IPC bridge so the renderer can hit the local FastAPI backend without
// going through fetch's same-origin friction when we later package offline.

const { app, BrowserWindow, Menu, Tray, shell, ipcMain, nativeImage, dialog } = require("electron");
const path = require("path");
const Store = require("electron-store").default || require("electron-store");

const store = new Store({
  name: "window-state",
  defaults: {
    width: 1440,
    height: 900,
    x: undefined,
    y: undefined,
    maximized: false,
    target: process.env.PF_TARGET || "http://localhost:3016",
    backend: process.env.PF_BACKEND || "http://localhost:8000",
  },
});

let mainWindow = null;
let tray = null;
let isQuitting = false;

function buildMenu() {
  const template = [
    {
      label: "Fleet",
      submenu: [
        { label: "Reload", accelerator: "CmdOrCtrl+R", click: () => mainWindow?.reload() },
        { label: "Force reload", accelerator: "CmdOrCtrl+Shift+R", click: () => mainWindow?.webContents.reloadIgnoringCache() },
        { type: "separator" },
        {
          label: "Set target URL…",
          click: async () => {
            const result = await dialog.showMessageBox(mainWindow, {
              type: "question",
              buttons: ["localhost:3016 (dev)", "localhost:3017", "Cancel"],
              defaultId: 0,
              cancelId: 2,
              title: "Phantom Fleet target",
              message: "Point the shell at which Next.js dashboard?",
            });
            if (result.response === 2) return;
            const next = result.response === 0 ? "http://localhost:3016" : "http://localhost:3017";
            store.set("target", next);
            mainWindow?.loadURL(next);
          },
        },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "zoomIn" },
        { role: "zoomOut" },
        { role: "resetZoom" },
        { type: "separator" },
        { role: "togglefullscreen" },
        { role: "toggleDevTools" },
      ],
    },
    {
      label: "Platforms",
      submenu: [
        { label: "Instagram", click: () => mainWindow?.loadURL(`${store.get("target")}/instagram`) },
        { label: "Threads",   click: () => mainWindow?.loadURL(`${store.get("target")}/threads`) },
        { label: "Reddit",    click: () => mainWindow?.loadURL(`${store.get("target")}/reddit`) },
        { label: "Fleet",     click: () => mainWindow?.loadURL(`${store.get("target")}/fleet`) },
        { label: "Overview",  click: () => mainWindow?.loadURL(`${store.get("target")}/`) },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Open backend docs",
          click: () => shell.openExternal(`${store.get("backend")}/docs`),
        },
        {
          label: "About Phantom Fleet",
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: "info",
              title: "Phantom Fleet",
              message: "Phantom Fleet desktop",
              detail: `v${app.getVersion()}\nTarget: ${store.get("target")}\nBackend: ${store.get("backend")}\nElectron ${process.versions.electron}\nNode ${process.versions.node}`,
            });
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createTray() {
  const iconPath = path.join(__dirname, "..", "assets", "tray.png");
  let image;
  try {
    image = nativeImage.createFromPath(iconPath);
    if (image.isEmpty()) throw new Error("empty");
  } catch {
    // Fall back to a 16x16 transparent placeholder so missing assets don't crash boot.
    image = nativeImage.createEmpty();
  }
  tray = new Tray(image);
  tray.setToolTip("Phantom Fleet");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Show dashboard", click: () => { mainWindow?.show(); mainWindow?.focus(); } },
    { label: "Reload",         click: () => mainWindow?.reload() },
    { type: "separator" },
    { label: "Quit", click: () => { isQuitting = true; app.quit(); } },
  ]));
  tray.on("click", () => { mainWindow?.show(); mainWindow?.focus(); });
}

function createWindow() {
  const bounds = {
    width: store.get("width"),
    height: store.get("height"),
    x: store.get("x"),
    y: store.get("y"),
  };

  mainWindow = new BrowserWindow({
    ...bounds,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    backgroundColor: "#0a0a0a",
    title: "Phantom Fleet",
    autoHideMenuBar: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (store.get("maximized")) mainWindow.maximize();

  const target = store.get("target");
  mainWindow.loadURL(target).catch((err) => {
    console.error("[phantom-fleet] load failed:", err.message);
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());

  mainWindow.on("close", (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
      return;
    }
    const b = mainWindow.getBounds();
    store.set({ width: b.width, height: b.height, x: b.x, y: b.y, maximized: mainWindow.isMaximized() });
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.webContents.on("render-process-gone", (_e, details) => {
    console.error("[phantom-fleet] render gone:", details.reason);
  });
}

ipcMain.handle("pf:config", () => ({
  target: store.get("target"),
  backend: store.get("backend"),
  version: app.getVersion(),
  electron: process.versions.electron,
}));

ipcMain.handle("pf:setTarget", (_e, url) => {
  if (typeof url !== "string" || !/^https?:\/\//.test(url)) return false;
  store.set("target", url);
  mainWindow?.loadURL(url);
  return true;
});

app.whenReady().then(() => {
  createWindow();
  buildMenu();
  createTray();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else mainWindow?.show();
  });
});

app.on("before-quit", () => { isQuitting = true; });
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
