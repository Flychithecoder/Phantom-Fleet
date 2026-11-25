// Preload — exposes a tiny, typed-ish surface to the renderer.
// The renderer is still just the Next.js app; this gives it a way to detect
// that it's running inside the shell and to read/change the pinned target.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("phantomFleet", {
  isDesktop: true,
  version: process.versions.electron,
  config: () => ipcRenderer.invoke("pf:config"),
  setTarget: (url) => ipcRenderer.invoke("pf:setTarget", url),
});
