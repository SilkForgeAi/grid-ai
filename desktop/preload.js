// The only bridge between the web UI and the desktop shell. Exposes a small,
// fixed API; main.js checks which page is calling before doing anything.
"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("gridDesktop", {
  platform: process.platform,
  pickFolder: () => ipcRenderer.invoke("pick-folder"),
  openPath: (p) => ipcRenderer.invoke("open-path", String(p)),
  showInFolder: (p) => ipcRenderer.invoke("show-in-folder", String(p)),
  onMenu: (cb) => ipcRenderer.on("menu", (_e, cmd) => cb(String(cmd))),
  keys: {
    list: () => ipcRenderer.invoke("keys:list"),
    set: (name, value) => ipcRenderer.invoke("keys:set", String(name), String(value)),
    clear: (name) => ipcRenderer.invoke("keys:clear", String(name)),
  },
  particles: {
    open: () => ipcRenderer.invoke("particles:open"),
    close: (opts) => ipcRenderer.invoke("particles:close", { back: !!(opts && opts.back) }),
    onEvent: (cb) => ipcRenderer.on("particles", (_e, what) => cb(String(what))),
  },
  setup: {
    info: () => ipcRenderer.invoke("setup:info"),
    choose: () => ipcRenderer.invoke("setup:choose"),
    retry: () => ipcRenderer.invoke("setup:retry"),
    hasBundle: () => ipcRenderer.invoke("setup:has-bundle"),
    openPrivacy: () => ipcRenderer.invoke("setup:open-privacy"),
    reinstall: () => ipcRenderer.invoke("setup:reinstall"),
    onInstall: (cb) => ipcRenderer.on("install", (_e, msg) => cb({ text: String(msg?.text ?? ""), step: Number(msg?.step ?? 0) })),
  },
});
