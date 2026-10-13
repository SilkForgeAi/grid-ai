// Grid desktop app (Electron). It starts Grid's engine (`grid app --no-browser`),
// waits for the private sign-in link it prints, and shows the app in a native
// window with real menus, a native folder picker and Keychain-encrypted API keys.
"use strict";

const { app, BrowserWindow, Menu, dialog, ipcMain, shell, safeStorage } = require("electron");
const { spawn, execFile } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { selectEngineWheel } = require("./engine-bundle.cjs");

const IS_MAC = process.platform === "darwin";
const TEST = process.env.GRID_DESKTOP_TEST === "1";
const userDir = () => app.getPath("userData");
const configPath = () => path.join(userDir(), "config.json");
const keysPath = () => path.join(userDir(), "keys.json");

let win = null;
let engine = null;          // child process
let engineUrl = null;       // http://127.0.0.1:PORT/?token=...
let engineOrigin = null;
let engineLog = [];
let quitting = false;
let shellEnvCache = null;

// ---------------------------------------------------------------- config
function readJson(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch (e) { return fallback; }
}
function writeJson(p, data) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(data, null, 2), { mode: 0o600 });
}
const config = () => readJson(configPath(), {});
const saveConfig = (patch) => writeJson(configPath(), { ...config(), ...patch });

// Also kept in ~/.grid/logs/desktop.log (sign-in tokens removed) so a stuck start can be looked at later.
const logFile = () => path.join(os.homedir(), ".grid", "logs", "desktop.log");
let logReady = false;
function log(line) {
  engineLog.push(line);
  if (engineLog.length > 3000) engineLog = engineLog.slice(-2000);
  if (TEST && !process.env.GRID_DESKTOP_LOG) return;
  try {
    const f = logFile();
    if (!logReady) {
      fs.mkdirSync(path.dirname(f), { recursive: true, mode: 0o700 });
      try { if (fs.statSync(f).size > 1024 * 1024) fs.renameSync(f, f + ".1"); } catch (e) { /* no log yet */ }
      logReady = true;
    }
    const clean = String(line).replace(/token=[\w-]+/g, "token=…").replace(/(sk-[\w-]{4})[\w-]+/g, "$1…");
    fs.appendFileSync(f, `${new Date().toISOString()} ${clean}\n`, { mode: 0o600 });
  } catch (e) { /* logging must never break Grid */ }
}

// ---------------------------------------------------------------- API keys (Keychain-encrypted)
function keysAvailable() { return TEST || safeStorage.isEncryptionAvailable(); }
function loadKeys() {
  const raw = readJson(keysPath(), {});
  const out = {};
  for (const [name, val] of Object.entries(raw)) {
    try {
      out[name] = TEST && val.startsWith("plain:") ? val.slice(6) : safeStorage.decryptString(Buffer.from(val, "base64"));
    } catch (e) { log(`[desktop] couldn't decrypt ${name}; ignoring it`); }
  }
  return out;
}
function storeKey(name, value) {
  if (!/^[A-Z_][A-Z0-9_]{0,63}$/.test(name)) throw new Error("bad key name");
  if (!keysAvailable()) throw new Error("Secure storage isn't available on this system.");
  const raw = readJson(keysPath(), {});
  raw[name] = TEST && !safeStorage.isEncryptionAvailable() ? "plain:" + value : safeStorage.encryptString(value).toString("base64");
  writeJson(keysPath(), raw);
}
function clearKey(name) {
  const raw = readJson(keysPath(), {});
  delete raw[name];
  writeJson(keysPath(), raw);
}

// ---------------------------------------------------------------- engine discovery
// Apps opened from the Dock don't get your terminal's PATH or exported keys,
// so read them from a login shell once (with a timeout).
function shellEnv() {
  if (shellEnvCache) return Promise.resolve(shellEnvCache);
  const sh = process.env.SHELL || (IS_MAC ? "/bin/zsh" : "/bin/bash");
  return new Promise((resolve) => {
    execFile(sh, ["-ilc", "env -0"], { timeout: 6000, maxBuffer: 4 * 1024 * 1024 }, (err, stdout) => {
      const env = {};
      if (!err && stdout) {
        for (const pair of stdout.split("\0")) {
          const i = pair.indexOf("=");
          if (i > 0) env[pair.slice(0, i)] = pair.slice(i + 1);
        }
      }
      const extra = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"];
      const parts = (env.PATH || process.env.PATH || "").split(":").filter(Boolean);
      for (const p of extra) if (!parts.includes(p)) parts.push(p);
      env.PATH = parts.join(":");
      shellEnvCache = env;
      resolve(env);
    });
  });
}

function isExecutable(p) {
  try { fs.accessSync(p, fs.constants.X_OK); return fs.statSync(p).isFile(); } catch (e) { return false; }
}

// macOS privacy (TCC) makes Desktop/Documents/Downloads look unreadable until the user allows it.
// Tell "blocked" apart from "missing" so Grid asks for permission instead of reinstalling.
function blockedByPrivacy(p) {
  try { fs.accessSync(p, fs.constants.X_OK); return false; } catch (e) { return e && (e.code === "EPERM" || e.code === "EACCES"); }
}
let blockedPath = null;
const PRIVACY_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders";

// ---------------------------------------------------------------- bundled engine
// A packaged Grid.app carries `uv` and Grid's wheel. On first launch (or when the
// app ships a newer wheel) it builds its own engine in ~/.grid/engine - no
// terminal, no Python install needed; uv fetches Python itself.
const engineHome = () => path.join(os.homedir(), ".grid", "engine");
const selfGrid = () => path.join(engineHome(), "bin", "grid");
const markerPath = () => path.join(engineHome(), ".grid-bundle");

function bundledEngine() {
  const dir = app.isPackaged ? path.join(process.resourcesPath, "engine") : path.join(__dirname, "engine");
  let files = [];
  try { files = fs.readdirSync(dir); } catch (e) { return null; }
  const uv = path.join(dir, "uv");
  const wheel = selectEngineWheel(files);
  if (!wheel || !isExecutable(uv)) return null;
  const wheelPath = path.join(dir, wheel);
  const hash = crypto.createHash("sha256").update(fs.readFileSync(wheelPath)).digest("hex").slice(0, 16);
  return { uv, wheel: wheelPath, id: `${wheel}#${hash}` };
}

function selfEngineCurrent(bundle) {
  if (!isExecutable(selfGrid())) return false;
  if (!bundle) return true;
  try { return fs.readFileSync(markerPath(), "utf8").trim() === bundle.id; } catch (e) { return false; }
}

function run(cmd, args, env, onLine) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { env, cwd: os.homedir(), stdio: ["ignore", "pipe", "pipe"] });
    const feed = (chunk) => chunk.toString().split(/\r?\n/).forEach((l) => l.trim() && onLine(l));
    child.stdout.on("data", feed);
    child.stderr.on("data", feed);
    child.on("error", (err) => { onLine(err.message); resolve(1); });
    child.on("exit", (code) => resolve(code ?? 1));
  });
}

let installing = null;
let installError = null;
function installEngine(bundle) {
  if (installing) return installing;
  installing = (async () => {
    const progress = (text, step) => {
      log(`[install] ${text}`);
      if (win) win.webContents.send("install", { text, step });
    };
    if (win) await win.loadFile(path.join(__dirname, "install.html"));
    const gridDir = path.join(os.homedir(), ".grid");
    const env = {
      ...process.env, ...(await shellEnv()),
      UV_PYTHON_INSTALL_DIR: path.join(gridDir, "python"), UV_CACHE_DIR: path.join(gridDir, "cache", "uv"),
      UV_NO_PROGRESS: "1", NO_COLOR: "1",
    };
    try {
      progress("Getting Python ready (first time only)…", 1);
      fs.rmSync(engineHome(), { recursive: true, force: true });
      let code = await run(bundle.uv, ["venv", "--python", "3.12", "--python-preference", "managed", engineHome()], env, (l) => progress(l, 1));
      if (code !== 0) throw new Error("couldn't set up Python - check your internet connection");
      progress("Installing Grid and its libraries (a minute or two)…", 2);
      // --find-links: prebuilt wheels shipped next to Grid's (e.g. pure-Python deps that only publish source)
      code = await run(bundle.uv, ["pip", "install", "--python", path.join(engineHome(), "bin", "python"),
        "--find-links", path.dirname(bundle.wheel), bundle.wheel], env, (l) => progress(l, 2));
      if (code !== 0 || !isExecutable(selfGrid())) throw new Error("couldn't install Grid's libraries - check your internet connection");
      fs.writeFileSync(markerPath(), bundle.id);
      progress("Done. Starting Grid…", 3);
      return selfGrid();
    } catch (e) {
      progress(`Install failed: ${e.message}`, -1);
      installError = e.message;
      showSetup(`Installing Grid's engine failed: ${e.message}`);
      return null;
    } finally {
      installing = null;
    }
  })();
  return installing;
}

async function findGrid() {
  const home = os.homedir();
  const cfg = config();
  const candidates = [
    process.env.GRID_BIN,
    cfg.gridCommand,
    path.join(home, "Desktop", "Grid AI", "grid-ai", ".venv", "bin", "grid"),   // a developer checkout wins
    path.join(home, "grid-ai", ".venv", "bin", "grid"),
  ].filter(Boolean);
  blockedPath = null;
  for (const c of candidates) {
    if (brokenEngines.has(c)) continue;
    if (isExecutable(c)) return c;
    if (!blockedPath && blockedByPrivacy(c)) blockedPath = c;
  }
  if (blockedPath) return null;          // the engine is there, macOS just won't let Grid read it yet
  const bundle = bundledEngine();
  if (bundle) return selfEngineCurrent(bundle) ? selfGrid() : installEngine(bundle);
  for (const c of [selfGrid(), path.join(home, ".grid", "venv", "bin", "grid"), path.join(home, ".local", "bin", "grid"),
    "/opt/homebrew/bin/grid", "/usr/local/bin/grid"]) if (isExecutable(c)) return c;
  const env = await shellEnv();
  for (const dir of (env.PATH || "").split(":")) {
    const p = path.join(dir, "grid");
    if (dir && isExecutable(p)) return p;
  }
  return null;
}

// ---------------------------------------------------------------- engine lifecycle
// An engine found on disk (e.g. a half-finished developer checkout) that dies before it
// starts is skipped for this run, and Grid falls back to its own bundled engine.
const brokenEngines = new Set();

async function startEngine() {
  stopEngine();
  engineUrl = null;
  installError = null;
  let grid, bundle;
  try {
    grid = await findGrid();
    bundle = bundledEngine();
  } catch (error) {
    log(`[desktop] ${error.message}`);
    showSetup(error.message);
    return;
  }
  if (!grid) {
    if (blockedPath) {
      const where = blockedPath.includes("/Desktop/") ? "Desktop" : blockedPath.includes("/Documents/") ? "Documents" : "that";
      showSetup(`macOS is blocking Grid from your ${where} folder, where Grid's engine lives. Open System Settings, then Privacy & Security, then Files & Folders, turn on ${where} Folder for Grid, and click Try again.`, { privacy: true });
    } else if (!installError) showSetup("Grid's engine wasn't found on this Mac.");
    return;
  }
  const env = { ...process.env, ...(await shellEnv()), ...loadKeys(), OPENHANDS_SUPPRESS_BANNER: "1", PYTHONUNBUFFERED: "1", GRID_DESKTOP: "1" };
  if (bundle) env.GRID_UV = bundle.uv;      // lets the engine download its browser without a terminal
  log(`[desktop] starting ${grid} app --no-browser`);
  const child = spawn(grid, ["app", "--no-browser", "--port", "0"], { env, cwd: os.homedir(), stdio: ["ignore", "pipe", "pipe"] });
  engine = child;
  let buf = "";
  const timer = setTimeout(() => {
    if (!engineUrl) showSetup("Grid's engine didn't start in time.");
  }, 120000);   // the first start after an install compiles Python files and is slow
  const onData = (chunk) => {
    const text = chunk.toString();
    buf += text;
    text.split("\n").forEach((l) => l.trim() && log(l));
    const m = buf.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);
    if (m && !engineUrl) {
      clearTimeout(timer);
      const url = m[0];
      engineOrigin = new URL(url).origin;
      waitForServer(engineOrigin).then((ok) => {
        if (engine !== child) return;
        if (!ok) { showSetup("Grid's engine printed its address but never answered."); return; }
        engineUrl = url;
        loadEngine();
      });
    }
  };
  child.stdout.on("data", onData);
  child.stderr.on("data", onData);
  child.on("exit", (code) => {
    clearTimeout(timer);
    log(`[desktop] engine exited (${code})`);
    const ours = engine === child;
    if (ours) engine = null;
    if (quitting || !ours) return;
    if (!engineUrl && grid !== selfGrid() && bundledEngine() && !brokenEngines.has(grid)) {
      brokenEngines.add(grid);
      log(`[desktop] ${grid} didn't start - using Grid's own engine instead`);
      startEngine();
      return;
    }
    showSetup(`Grid's engine stopped (exit code ${code}).`);
  });
  child.on("error", (err) => { log(`[desktop] ${err.message}`); showSetup(`Couldn't start Grid's engine: ${err.message}`); });
}

// The engine prints its link a moment before it starts listening.
async function waitForServer(origin, timeoutMs = 30000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try {
      const r = await fetch(`${origin}/static/app.css`, { method: "HEAD" });
      if (r.status < 500) return true;
    } catch (e) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 150));
  }
  return false;
}

function stopEngine() {
  const child = engine;
  engine = null;
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  setTimeout(() => { if (child.exitCode === null) child.kill("SIGKILL"); }, 3000);
}

async function restartEngine() {
  stopEngine();
  if (win) win.loadFile(path.join(__dirname, "loading.html"));
  await new Promise((r) => setTimeout(r, 600));
  startEngine();
}

// ---------------------------------------------------------------- windows
function createWindow() {
  const bounds = config().bounds || { width: 1440, height: 920 };
  win = new BrowserWindow({
    ...bounds, minWidth: 900, minHeight: 600, show: false, title: "Grid",
    backgroundColor: "#07090d",
    titleBarStyle: IS_MAC ? "hiddenInset" : "default",
    trafficLightPosition: { x: 14, y: 12 },
    icon: path.join(__dirname, "build", "icon.png"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false, spellcheck: false },
  });
  win.once("ready-to-show", () => win.show());
  win.on("close", () => { try { saveConfig({ bounds: win.getBounds() }); } catch (e) { /* ignore */ } });
  win.on("closed", () => { win = null; if (particlesWin && !particlesWin.isDestroyed()) particlesWin.close(); });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url) && !sameOrigin(url, engineOrigin)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    const ok = sameOrigin(url, engineOrigin) || url.startsWith("file://");
    if (!ok) { e.preventDefault(); if (/^https?:\/\//.test(url)) shell.openExternal(url); }
  });
  if (engineUrl) loadEngine(); else win.loadFile(path.join(__dirname, "loading.html"));
}

function loadEngine() {
  if (win && engineUrl) win.loadURL(engineUrl);
}

function showSetup(reason, { privacy = false } = {}) {
  if (!win) return;
  win.loadFile(path.join(__dirname, "setup.html"), { query: { reason, privacy: privacy ? "1" : "" } });
}

// ---------------------------------------------------------------- IPC (validated)
function sameOrigin(url, origin) {
  try { return !!origin && new URL(url).origin === origin; } catch (e) { return false; }
}
function fromEngine(event) {
  return sameOrigin(event.senderFrame?.url || "", engineOrigin);
}
function fromLocal(event) {
  return (event.senderFrame?.url || "").startsWith("file://");
}

ipcMain.handle("pick-folder", async (event) => {
  if (!fromEngine(event)) return null;
  const r = await dialog.showOpenDialog(win, { title: "Open a folder as a Grid project", properties: ["openDirectory", "createDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});
// Documents Grid made: open them in their app or reveal them in Finder. Only real
// files in your home folder, never key or app-data folders; "open" only for documents.
const NO_GO = [".ssh", ".aws", ".gnupg", ".grid", "Library"];
function safeUserFile(p, docsOnly) {
  if (typeof p !== "string" || !path.isAbsolute(p)) return null;
  let real;
  try { real = fs.realpathSync(p); } catch (e) { return null; }
  const home = fs.realpathSync(os.homedir());
  if (!real.startsWith(home + path.sep)) return null;
  const rel = path.relative(home, real).split(path.sep)[0];
  if (NO_GO.includes(rel)) return null;
  if (!fs.statSync(real).isFile()) return null;
  if (docsOnly && !/\.(pdf|docx|xlsx|pptx)$/i.test(real)) return null;
  return real;
}
ipcMain.handle("open-path", async (event, p) => {
  const f = fromEngine(event) && safeUserFile(p, true);
  if (!f) return false;
  return (await shell.openPath(f)) === "";
});
ipcMain.handle("show-in-folder", (event, p) => {
  const f = fromEngine(event) && safeUserFile(p, false);
  if (!f) return false;
  shell.showItemInFolder(f);
  return true;
});
ipcMain.handle("keys:list", (event) => (fromEngine(event) ? Object.keys(readJson(keysPath(), {})).map((name) => ({ name, set: true })) : []));
ipcMain.handle("keys:set", async (event, name, value) => {
  if (!fromEngine(event) || typeof name !== "string" || typeof value !== "string") return false;
  storeKey(name, value);
  setTimeout(restartEngine, 300);
  return true;
});
ipcMain.handle("keys:clear", async (event, name) => {
  if (!fromEngine(event) || typeof name !== "string") return false;
  clearKey(name);
  setTimeout(restartEngine, 300);
  return true;
});
ipcMain.handle("setup:info", async (event) => {
  if (!fromLocal(event)) return null;
  return { log: engineLog.slice(-80).join("\n").replace(/token=[\w-]+/g, "token=…"), configured: config().gridCommand || null, home: os.homedir() };
});
ipcMain.handle("setup:choose", async (event) => {
  if (!fromLocal(event)) return null;
  const r = await dialog.showOpenDialog(win, { title: "Choose the `grid` program (in your Grid virtualenv: .venv/bin/grid)", properties: ["openFile", "showHiddenFiles"] });
  if (r.canceled) return null;
  const p = r.filePaths[0];
  if (!isExecutable(p)) { dialog.showErrorBox("Not a program", `${p} isn't executable.`); return null; }
  saveConfig({ gridCommand: p });
  brokenEngines.clear();
  startEngine();
  return p;
});
ipcMain.handle("setup:retry", (event) => { if (fromLocal(event)) { brokenEngines.clear(); startEngine(); } });
ipcMain.handle("setup:open-privacy", (event) => { if (fromLocal(event)) shell.openExternal(PRIVACY_PANE); });
ipcMain.handle("setup:has-bundle", (event) => (fromLocal(event) ? !!bundledEngine() : false));
ipcMain.handle("setup:reinstall", async (event) => {
  if (!fromLocal(event)) return false;
  const bundle = bundledEngine();
  if (!bundle) return false;
  try { fs.rmSync(markerPath(), { force: true }); } catch (e) { /* ignore */ }
  startEngine();
  return true;
});
ipcMain.handle("setup:open-docs", (event) => { if (fromLocal(event)) shell.openExternal("https://github.com/SilkForgeAi"); });

// ---------------------------------------------------------------- menu
function send(cmd) { if (win && engineUrl) win.webContents.send("menu", cmd); }

// ---------------------------------------------------------------- the Grid particle screen, popped out
// Its own small window that floats above other apps and can go anywhere on the screen.
// It loads one page from the engine (static, no project access) and can only ask to be
// closed - optionally "back", which tells the main window to raise its in-app screen again.
let particlesWin = null;
let particlesBack = false;
function openParticles() {
  if (!engineOrigin || !win) return false;
  if (particlesWin && !particlesWin.isDestroyed()) { particlesWin.show(); particlesWin.focus(); return true; }
  const saved = config().particlesBounds;
  const bounds = saved && saved.width >= 220 && saved.height >= 160 ? saved : { width: 480, height: 340 };
  particlesBack = false;
  const pw = new BrowserWindow({
    ...bounds, minWidth: 220, minHeight: 160, show: false, title: "Grid", frame: false, hasShadow: true,
    backgroundColor: "#020205", alwaysOnTop: true, fullscreenable: true, roundedCorners: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false, spellcheck: false },
  });
  particlesWin = pw;
  pw.setAlwaysOnTop(true, "floating");
  pw.once("ready-to-show", () => pw.show());
  pw.webContents.on("did-fail-load", (_e, code, desc) => { log(`[desktop] particles: page failed (${code} ${desc})`); if (!pw.isDestroyed()) pw.show(); });
  setTimeout(() => { if (!pw.isDestroyed() && !pw.isVisible()) pw.show(); }, 1500);
  pw.on("close", () => { try { saveConfig({ particlesBounds: pw.getBounds() }); } catch (e) { /* ignore */ } });
  pw.on("closed", () => {
    if (particlesWin === pw) particlesWin = null;
    if (win && !win.isDestroyed()) win.webContents.send("particles", particlesBack ? "returned" : "closed");
    particlesBack = false;
  });
  pw.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  pw.webContents.on("will-navigate", (e, url) => { if (!sameOrigin(url, engineOrigin)) e.preventDefault(); });
  log("[desktop] particles: popped out");
  pw.loadURL(`${engineOrigin}/static/particles.html`).catch((e) => log(`[desktop] particles: load error (${e.message})`));
  return true;
}
ipcMain.handle("particles:open", (event) => {
  const ok = !!win && event.sender === win.webContents && fromEngine(event);
  if (!ok) { log(`[desktop] particles: refused pop-out from ${event.senderFrame?.url || "?"}`); return false; }
  try { return openParticles(); } catch (e) { log(`[desktop] particles: couldn't open (${e.message})`); return false; }
});
ipcMain.handle("particles:close", (event, opts) => {
  if (!fromEngine(event) || !particlesWin || particlesWin.isDestroyed()) return false;
  const fromPopup = event.sender === particlesWin.webContents;
  if (!fromPopup && !(win && event.sender === win.webContents)) return false;
  particlesBack = fromPopup ? !!(opts && opts.back) : false;   // the app closing it raises its own screen itself
  particlesWin.close();
  return true;
});

function buildMenu() {
  const template = [
    ...(IS_MAC ? [{ label: "Grid", submenu: [
      { role: "about" }, { type: "separator" },
      { label: "Settings…", accelerator: "Cmd+,", click: () => send("settings") },
      { type: "separator" }, { role: "services" }, { type: "separator" },
      { role: "hide" }, { role: "hideOthers" }, { role: "unhide" }, { type: "separator" }, { role: "quit" },
    ] }] : []),
    { label: "File", submenu: [
      { label: "New Project…", accelerator: "CmdOrCtrl+Shift+N", click: () => send("new-project") },
      { label: "Open Folder…", accelerator: "CmdOrCtrl+O", click: () => send("open-folder") },
      { type: "separator" },
      { label: "New Chat", accelerator: "CmdOrCtrl+Shift+L", click: () => send("new-chat") },
      { label: "Save", accelerator: "CmdOrCtrl+S", click: () => send("save") },
      { type: "separator" },
      IS_MAC ? { role: "close" } : { role: "quit" },
    ] },
    { role: "editMenu" },
    { label: "Go", submenu: [
      { label: "Go to File…", accelerator: "CmdOrCtrl+P", click: () => send("quick-open") },
      { label: "Command Palette…", accelerator: "CmdOrCtrl+Shift+P", click: () => send("command-palette") },
      { type: "separator" },
      { label: "Search in Project", accelerator: "CmdOrCtrl+Shift+F", click: () => send("find-in-project") },
      { label: "Replace in Project", accelerator: "CmdOrCtrl+Shift+H", click: () => send("replace-in-project") },
      { label: "Show Files", accelerator: "CmdOrCtrl+Shift+E", click: () => send("show-files") },
    ] },
    { label: "View", submenu: [
      { label: "Focus Workshop / Guide", accelerator: "CmdOrCtrl+\\", click: () => send("toggle-layout") },
      { label: "Terminal", accelerator: "CmdOrCtrl+J", click: () => send("terminal") },
      { label: "Focus Guide", accelerator: "CmdOrCtrl+Shift+I", click: () => send("focus-chat") },
      { type: "separator" },
      { label: "Plugins", click: () => send("plugins") },
      { label: "Models", click: () => send("models") },
      { label: "Schedules", click: () => send("schedules") },
      { label: "Memory", click: () => send("memory") },
      { type: "separator" },
      { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { type: "separator" },
      { role: "togglefullscreen" },
      { label: "Reload", accelerator: "CmdOrCtrl+Shift+R", click: () => loadEngine() },
      { role: "toggleDevTools" },
    ] },
    { role: "windowMenu" },
    { label: "Help", submenu: [
      { label: "Restart Grid's Engine", click: () => restartEngine() },
      { label: "Show Engine Log", click: () => {
        const w = new BrowserWindow({ width: 900, height: 600, title: "Grid engine log", webPreferences: { sandbox: true, contextIsolation: true } });
        const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
        const tokenSafe = engineLog.join("\n").replace(/token=[\w-]+/g, "token=…");
        w.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(`<pre style="font:12px Menlo,monospace;white-space:pre-wrap;padding:12px">${esc(tokenSafe)}</pre>`));
      } },
      { label: "Choose Grid Engine…", click: () => showSetup("Pick the `grid` program Grid should run.") },
    ] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------- app lifecycle
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(() => {
    app.setName("Grid");
    if (IS_MAC && app.dock) app.dock.setIcon(path.join(__dirname, "build", "icon.png"));
    buildMenu();
    createWindow();
    startEngine();
    app.on("activate", () => { if (!win) createWindow(); });
  });
  app.on("window-all-closed", () => { if (!IS_MAC) app.quit(); });
  app.on("before-quit", (e) => {
    quitting = true;
    const child = engine;
    if (child && child.exitCode === null) {
      // Don't leave the engine behind: a task can keep it busy past SIGTERM, and a leftover
      // engine keeps the project locked and the model busy. Wait for it to exit (stopEngine
      // force-kills it after 3 s), then finish quitting.
      e.preventDefault();
      child.once("exit", () => setImmediate(() => app.quit()));
      stopEngine();
    }
  });
}
