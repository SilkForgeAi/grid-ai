// Grid app - vanilla JS, no build step. Talks to the local Grid server (api.py).
"use strict";
import { createParticleExperience } from './particle-lab.js';
import { createBeginnerGuide } from './beginner-guide.js';
import { StreamFollower } from './scroll-follow.js';
import { createParticleBackboard } from './particle-backboard.js';

// ------------------------------------------------------------------ helpers
const $ = (sel, el = document) => el.querySelector(sel);

// Views build children with `cond ? el : null`. Native append/replaceChildren would turn
// null into the text "null", so skip empty values everywhere (like h() does).
for (const name of ["append", "prepend", "replaceChildren"]) {
  const orig = Element.prototype[name];
  Element.prototype[name] = function (...nodes) {
    return orig.apply(this, nodes.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false));
  };
}

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "style") el.setAttribute("style", v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}


// Line icons (24px grid, drawn with the current text color).
const ICONS = {
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  "file-plus": "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M12 11v6M9 14h6",
  "folder-plus": "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 10v6M9 13h6",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  refresh: "M20 11a8 8 0 0 0-14.9-4M4 4v4h4M4 13a8 8 0 0 0 14.9 4M20 20v-4h-4",
  pencil: "M15 5l4 4M4 20l1-5L16 4a2.1 2.1 0 0 1 3 3L8 18z",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
  clip: "M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l7.9-7.9",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  collapse: "M4 6h16M4 12h10M4 18h7",
  swap: "M7 4l-3 3 3 3M4 7h12M17 20l3-3-3-3M20 17H8",
  menu: "M4 6h16M4 12h16M4 18h16",
  panel: "M3 5h18v14H3zM15 5v14",
  down: "M6 9l6 6 6-6",
  plus: "M12 5v14M5 12h14",
  x: "M6 6l12 12M18 6L6 18",
  check: "M5 12.5l4.5 4.5L19 7.5",
  copy: "M9 9h10v10a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V11a2 2 0 0 1 2-2zM5 15a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2",
  send: "M12 19V5M5.5 11.5L12 5l6.5 6.5",
  stop: "M7 7h10v10H7z",
  terminal: "M4 17l5-5-5-5M12 19h8",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z",
  doc: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4",
  brain: "M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1",
  list: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01",
  image: "M4 5h16v14H4zM4 15l4.5-4.5 4 4L15 12l5 5M15.5 9.5h.01",
  cursor: "M5 3l14 7-6 2-2 6z",
  key: "M15 7a4 4 0 1 1-3.4 6.1L4 20.5V17h3v-3h3l1.6-1.6A4 4 0 0 1 15 7zM16 8h.01",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
};
function ico(name, size = 16) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", size); svg.setAttribute("height", size);
  svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round"); svg.setAttribute("aria-hidden", "true");
  svg.classList.add("ico");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICONS[name] || "");
  svg.append(path);
  return svg;
}

class ApiError extends Error {}
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

async function api(method, path, body) {
  const opts = { method, headers: { "X-Grid": "1" }, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError("Can't reach Grid - is `grid app` still running?");
  }
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) throw new ApiError(data.error || `${res.status} ${res.statusText}`);
  return data;
}
const GET = (p) => api("GET", p);
const POST = (p, b = {}) => api("POST", p, b);
const PUT = (p, b = {}) => api("PUT", p, b);
const DEL = (p) => api("DELETE", p);

function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}`, text: msg });
  const box = $("#toasts");
  box.append(t);
  while (box.children.length > 3) box.firstChild.remove();
  setTimeout(() => t.remove(), kind === "error" ? 6000 : 3200);
}

async function attempt(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(okMsg);
    return r;
  } catch (e) {
    toast(e.message || String(e), "error");
    return undefined;
  }
}

function fmtTime(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  const today = new Date();
  const same = d.toDateString() === today.toDateString();
  return same ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
              : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// Safe markdown subset: paragraphs, headings, lists, fenced code, inline code, bold, italics, links.
// Markdown for chat messages: paragraphs, headings, lists, quotes, tables, rules,
// links and code blocks (with a copy button, colored by Monaco when it's loaded).
// Text is only ever inserted as text - never as HTML.
const CODE_LANGS = { py: "python", python: "python", js: "javascript", javascript: "javascript", jsx: "javascript", mjs: "javascript",
  ts: "typescript", tsx: "typescript", typescript: "typescript", sh: "shell", bash: "shell", zsh: "shell", shell: "shell", console: "shell",
  json: "json", html: "html", xml: "xml", css: "css", scss: "scss", sql: "sql", yaml: "yaml", yml: "yaml", md: "markdown", markdown: "markdown",
  go: "go", rust: "rust", rs: "rust", java: "java", c: "c", cpp: "cpp", "c++": "cpp", cs: "csharp", rb: "ruby", ruby: "ruby", php: "php",
  swift: "swift", kotlin: "kotlin", kt: "kotlin", dockerfile: "dockerfile", toml: "ini", ini: "ini" };
function codeBlock(code, lang, live) {
  const codeEl = h("code", { text: code });
  const copy = h("button", { class: "cb-copy", title: "Copy", "aria-label": "Copy code", onclick: async () => {
    try { await navigator.clipboard.writeText(code); copy.replaceChildren(ico("check", 14), h("span", { text: "Copied" })); }
    catch (e) { toast("Couldn't copy", "error"); return; }
    setTimeout(() => copy.replaceChildren(ico("copy", 14), h("span", { text: "Copy" })), 1400);
  } }, ico("copy", 14), h("span", { text: "Copy" }));
  const id = CODE_LANGS[(lang || "").toLowerCase()];
  if (!live && id && _monaco && code.length < 40000) {
    _monaco.editor.colorize(code, id, { tabSize: 4 }).then((html) => { codeEl.innerHTML = html; codeEl.classList.add("colored"); }).catch(() => {});
  }
  return h("div", { class: "codeblock" }, h("div", { class: "cb-head" }, h("span", { class: "cb-lang", text: lang || "code" }), copy), h("pre", {}, codeEl));
}

function md(text, { live = false } = {}) {
  const root = h("div", { class: "md" });
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  let i = 0;
  const inline = (s) => {
    const frag = document.createDocumentFragment();
    const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\s][^*]*\*)|(~~[^~]+~~)|(\[[^\]]+\]\((https?:\/\/[^)\s]+)\))|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g;
    let last = 0, m;
    while ((m = re.exec(s))) {
      if (m.index > last) frag.append(s.slice(last, m.index));
      if (m[1]) frag.append(h("code", { text: m[1].slice(1, -1) }));
      else if (m[2] || m[3]) frag.append(h("strong", { text: (m[2] || m[3]).slice(2, -2) }));
      else if (m[4]) frag.append(h("em", { text: m[4].slice(1, -1) }));
      else if (m[5]) frag.append(h("del", { text: m[5].slice(2, -2) }));
      else if (m[6]) frag.append(h("a", { href: m[7], target: "_blank", rel: "noopener noreferrer", text: m[6].replace(/\]\(.*$/, "").slice(1) }));
      else if (m[8]) frag.append(h("a", { href: m[8], target: "_blank", rel: "noopener noreferrer", text: m[8] }));
      last = re.lastIndex;
    }
    if (last < s.length) frag.append(s.slice(last));
    return frag;
  };
  const isTableSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l || "");
  const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  const listRe = /^(\s*)([-*+]|\d+[.)])\s+/;
  const blockStart = /^```|^#{1,4}\s|^\s*([-*+]|\d+[.)])\s+|^\s*>|^\s*(-{3,}|\*{3,})\s*$/;
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^\s*```\s*([\w+#.-]*)/);
    if (fence) {
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
      const closed = i < lines.length;
      i++;
      root.append(codeBlock(buf.join("\n"), fence[1], live && !closed));
      continue;
    }
    const hm = line.match(/^(#{1,4})\s+(.*)$/);
    if (hm) { root.append(h(`h${Math.min(4, hm[1].length + 1)}`, {}, inline(hm[2]))); i++; continue; }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { root.append(h("hr")); i++; continue; }
    if (/^\s*>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      root.append(h("blockquote", {}, md(buf.join("\n"), { live })));
      continue;
    }
    if (line.includes("|") && isTableSep(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      root.append(h("div", { class: "md-table" }, h("table", {},
        h("thead", {}, h("tr", {}, ...head.map((c) => h("th", {}, inline(c))))),
        h("tbody", {}, ...rows.map((r) => h("tr", {}, ...head.map((_, k) => h("td", {}, inline(r[k] || "")))))))));
      continue;
    }
    if (listRe.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const start = ordered ? parseInt(line.trim(), 10) : 1;
      const list = h(ordered ? "ol" : "ul", ordered && start > 1 ? { start } : {});
      while (i < lines.length && (listRe.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && list.lastChild))) {
        if (listRe.test(lines[i])) list.append(h("li", {}, inline(lines[i].replace(listRe, ""))));
        else { list.lastChild.append(h("br"), inline(lines[i].trim())); }
        i++;
      }
      root.append(list);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !blockStart.test(lines[i]) && !(lines[i].includes("|") && isTableSep(lines[i + 1]))) para.push(lines[i++]);
    if (!para.length) { root.append(h("p", {}, inline(lines[i++]))); continue; }
    const p = h("p");
    para.forEach((l, k) => { if (k) p.append(h("br")); p.append(inline(l)); });
    root.append(p);
  }
  return root;
}

function diffView(text) {
  const box = h("div", { class: "diffview" });
  for (const line of String(text || "").split("\n")) {
    let cls = "";
    if (line.startsWith("diff --git")) cls = "file";
    else if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("index ")) continue;
    else if (line.startsWith("@@")) cls = "hunk";
    else if (line.startsWith("+")) cls = "add";
    else if (line.startsWith("-")) cls = "del";
    box.append(h("div", { class: cls, text: cls === "file" ? line.replace(/^diff --git a\/(\S+) b\/.*$/, "$1") : line || " " }));
  }
  return box;
}

// ------------------------------------------------------------------ modals
function modal({ title, body, buttons = [], wide = false, onOpen }) {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    const prevFocus = document.activeElement;
    const content = typeof body === "function" ? body() : body;
    const close = (val) => { back.remove(); document.removeEventListener("keydown", onKey); prevFocus?.focus?.(); resolve(val); };
    const footer = h("footer");
    for (const b of buttons) {
      footer.append(h("button", {
        class: `btn ${b.kind || ""}`, text: b.label,
        onclick: async () => {
          if (b.onClick) {
            const r = await b.onClick();
            if (r === false) return;
            close(r === undefined ? b.value : r);
          } else close(b.value);
        },
      }));
    }
    const box = h("div", { class: `modal ${wide ? "wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title },
      h("header", { text: title }), h("div", { class: "mbody" }, content), buttons.length ? footer : null);
    const back = h("div", { class: "modal-back", onmousedown: (e) => { if (e.target === back) close(undefined); } }, box);
    const onKey = (e) => {
      if (e.key === "Escape") close(undefined);
      if (e.key === "Enter" && !e.shiftKey && e.target.tagName === "INPUT") {
        const primary = footer.querySelector(".btn.primary");
        if (primary) { e.preventDefault(); primary.click(); }
      }
    };
    document.addEventListener("keydown", onKey);
    root.append(back);
    (box.querySelector("input, select, textarea") || box.querySelector(".btn.primary"))?.focus();
    onOpen?.(box, close);
  });
}

async function askText(title, label, value = "", okLabel = "OK") {
  const input = h("input", { type: "text", value });
  const r = await modal({
    title, body: h("label", { class: "field" }, label, input),
    buttons: [{ label: "Cancel", value: null }, { label: okLabel, kind: "primary", onClick: () => input.value.trim() || false }],
  });
  return r || null;
}

async function confirmBox(title, message, okLabel = "OK", danger = false) {
  return !!(await modal({
    title, body: h("p", { text: message }),
    buttons: [{ label: "Cancel", value: false }, { label: okLabel, kind: danger ? "danger-solid" : "primary", value: true }],
  }));
}

// ------------------------------------------------------------------ app state
const S = { projects: [], settings: {}, version: "", view: null, home: "", templates: [], running: new Set() };

const DARK_MQ = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
function applyTheme() {
  const t = S.settings.theme || "dark";
  const resolved = t === "system" ? (DARK_MQ?.matches === false ? "light" : "dark") : t;
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.setAttribute("data-accent", S.settings.accent || "teal");
  window.dispatchEvent(new Event("grid-theme"));
}
DARK_MQ?.addEventListener?.("change", () => { if ((S.settings.theme || "dark") === "system") applyTheme(); });

// Editor and terminal colors follow the theme + accent tokens.
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function hex6(c) {
  const ctx = (hex6._c ||= document.createElement("canvas").getContext("2d"));
  ctx.fillStyle = "#000"; ctx.fillStyle = c;
  const v = ctx.fillStyle;
  return v.startsWith("#") ? v.slice(1, 7) : "000000";
}

// The particle screen keeps its look, size, place and clock in localStorage, but the app runs on a
// new port (a new origin, so empty storage) every launch: mirror those keys to Grid's home folder.
const UI_PREFIX = "grid.particles.", UI_CLOCK = "grid.particles.clock";
let uiSynced = {}, uiClockSaved = 0;
function uiSnapshot() {
  const out = {};
  try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k?.startsWith(UI_PREFIX)) out[k] = localStorage.getItem(k); } } catch (e) { /* no storage */ }
  return out;
}
function saveUiState(leaving = false) {
  const now = uiSnapshot(), changed = {};
  for (const [k, v] of Object.entries(now)) if (uiSynced[k] !== v) changed[k] = v;
  // the clock ticks every second while the cloud moves: keep it now and then, and when leaving
  if (!leaving && UI_CLOCK in changed && Date.now() - uiClockSaved < 30000) delete changed[UI_CLOCK];
  if (!Object.keys(changed).length) return;
  if (UI_CLOCK in changed) uiClockSaved = Date.now();
  Object.assign(uiSynced, changed);
  if (leaving) {
    fetch("/api/ui-state", { method: "PUT", keepalive: true, credentials: "same-origin",
      headers: { "X-Grid": "1", "Content-Type": "application/json" }, body: JSON.stringify({ values: changed }) }).catch(() => {});
  } else PUT("/api/ui-state", { values: changed }).catch(() => { for (const k of Object.keys(changed)) delete uiSynced[k]; });
}
async function restoreUiState() {
  try {
    const r = await GET("/api/ui-state");
    for (const [k, v] of Object.entries(r.values || {})) if (k.startsWith(UI_PREFIX) && localStorage.getItem(k) === null) localStorage.setItem(k, v);
  } catch (e) { /* first launch, or storage is off */ }
  uiSynced = uiSnapshot(); uiClockSaved = Date.now();
  setInterval(saveUiState, 2000);
  window.addEventListener("pagehide", () => saveUiState(true));
  document.addEventListener("visibilitychange", () => { if (document.hidden) saveUiState(true); });
}

async function loadState() {
  const st = await GET("/api/state");
  S.projects = st.projects;
  S.settings = st.settings;
  S.version = st.version;
  S.executionMode = st.execution_mode;
  S.home = st.home;
  S.templates = st.templates;
  S.starters = st.starters || [];
  S.persona = st.persona;
  applyTheme();
  $("#side-foot").textContent = `Grid ${S.version}`;
  renderProjectList();
}

function renderProjectList() {
  const nav = $("#project-list");
  nav.replaceChildren();
  if (!S.projects.length) nav.append(h("div", { class: "faint", style: "padding:8px 10px;font-size:12.5px", text: "No projects yet." }));
  const current = currentProjectId();
  for (const p of S.projects) {
    nav.append(h("a", { href: `#/p/${p.id}`, class: p.id === current ? "active" : "", title: p.path },
      h("span", {}, p.name, S.running.has(p.id) ? h("span", { class: "run-dot", title: "running" }) : null),
      h("small", { text: p.exists ? p.path.replace(S.home, "~") : "folder missing" })));
  }
}

function currentProjectId() {
  const m = location.hash.match(/^#\/p\/([\w-]+)/);
  return m ? m[1] : null;
}

// ------------------------------------------------------------------ router
async function route() {
  if (S.view?.unmount) S.view.unmount();
  S.view = null;
  const main = $("#main");
  main.replaceChildren();
  const hash = location.hash || "#/";
  document.querySelectorAll(".side-nav a").forEach((a) => a.classList.toggle("active", hash.startsWith(`#/${a.dataset.nav}`)));
  renderProjectList();
  const pid = currentProjectId();
  let view;
  if (pid) {
    const p = S.projects.find((x) => x.id === pid);
    view = p ? new Workspace(p) : new HomeView();
  } else if (hash.startsWith("#/plugins")) view = new PluginsView();
  else if (hash.startsWith("#/models")) view = new ModelsView();
  else if (hash.startsWith("#/schedules")) view = new SchedulesView();
  else if (hash.startsWith("#/memory")) view = new MemoryView();
  else if (hash.startsWith("#/settings")) view = new SettingsView();
  else if (hash.startsWith("#/lab")) view = new ParticleLabView();
  else if (hash.startsWith("#/guide")) view = new BeginnerGuideView();
  else view = new HomeView();
  S.view = view;
  await view.mount(main);
}

// ------------------------------------------------------------------ project dialogs
async function newProjectDialog(starterId) {
  const starter = S.starters?.find((s) => s.id === starterId);
  const name = h("input", { type: "text", placeholder: "my-project", value: starter?.id || "" });
  const tmpl = h("select", {}, ...S.templates.map((t) => h("option", { value: t,
    text: S.starters?.find((s) => s.id === t)?.title || (t === "python" ? "Python (package + tests)" : "Empty") })));
  if (starter) tmpl.value = starter.id;
  const loc = h("input", { type: "text", value: S.settings.projects_root || "" });
  const git = h("input", { type: "checkbox", checked: true });
  const r = await modal({
    title: starter ? `Make your own ${starter.title}` : "New project",
    body: h("div", { class: "form-grid", style: "grid-template-columns:1fr" },
      h("label", { class: "field" }, "Name", name),
      h("label", { class: "field" }, "Template", tmpl),
      h("label", { class: "field" }, "Create it in", loc),
      h("label", { class: "check" }, git, "Initialize a git repository")),
    buttons: [{ label: "Cancel", value: null }, {
      label: "Create", kind: "primary",
      onClick: async () => {
        if (!name.value.trim()) { toast("Give the project a name", "error"); return false; }
        const res = await attempt(() => POST("/api/projects", { name: name.value.trim(), template: tmpl.value, location: loc.value.trim(), git_init: git.checked }));
        return res ? res.project : false;
      },
    }],
  });
  if (r) { await loadState(); location.hash = `#/p/${r.id}`; }
}

async function openFolderDialog() {
  if (window.gridDesktop?.pickFolder) {
    const path = await window.gridDesktop.pickFolder();
    if (!path) return;
    const res = await attempt(() => POST("/api/projects/open", { path }));
    if (res) { await loadState(); location.hash = `#/p/${res.project.id}`; }
    return;
  }
  let current = null;
  const pathBox = h("input", { type: "text" });
  const list = h("div", { class: "dirlist" });
  const load = async (path) => {
    const res = await attempt(() => GET(`/api/fs/browse?path=${encodeURIComponent(path || "")}`));
    if (!res) return;
    current = res.path;
    pathBox.value = res.path;
    list.replaceChildren();
    if (res.parent) list.append(h("div", { text: "..  (up)", onclick: () => load(res.parent) }));
    for (const d of res.dirs) list.append(h("div", { class: "dir-row", onclick: () => load(d.path) }, ico("folder", 15), d.name));
    if (!res.dirs.length) list.append(h("div", { class: "faint", text: "(no subfolders)" }));
  };
  pathBox.addEventListener("change", () => load(pathBox.value));
  const r = await modal({
    title: "Open a folder as a project",
    body: h("div", {}, h("label", { class: "field" }, "Folder", pathBox), h("div", { style: "height:8px" }), list),
    buttons: [{ label: "Cancel", value: null }, {
      label: "Open this folder", kind: "primary",
      onClick: async () => {
        const res = await attempt(() => POST("/api/projects/open", { path: pathBox.value || current }));
        return res ? res.project : false;
      },
    }],
    onOpen: () => load(null),
  });
  if (r) { await loadState(); location.hash = `#/p/${r.id}`; }
}

// ------------------------------------------------------------------ home
class HomeView {
  async mount(main) {
    const recent = S.projects.slice(0, 6);
    this.particles = createParticleExperience({ compact: true });
    main.append(h("div", { class: "page" }, h("div", { class: "home" },
      h("div", { class: "hero-eyebrow", text: "A LITTLE CURIOSITY GOES A LONG WAY." }),
      h("h1", { text: "Grid" }),
      h("h2", { class: "hero-title" }, "Make something.", h("br"), h("span", { text: "Make it yours." })),
      h("p", { class: "muted hero-description", text: "A game. A strange little story. Your first piece of code. Start small, try things, and understand what you build along the way." }),
      h("div", { class: "row" },
        h("button", { class: "btn primary", text: "New project", onclick: newProjectDialog }),
        h("button", { class: "btn", text: "Open a folder", onclick: openFolderDialog })),
      h("div", { class: "features" }, ...[
        ["01 / Pick a spark", "Start with working code and a small challenge."],
        ["02 / Try one change", "Ask for a hint, or work through it together."],
        ["03 / See what happens", "Run it. Read the checks. Learn from the surprises."],
        ["04 / Keep exploring", "Review changes and use checkpoints to try again."],
      ].map(([t, d]) => h("div", { class: "feature" }, h("strong", { text: t }), h("span", { text: d })))),
      h("div", { class: "home-particle-art" }, this.particles.el),
      h("a", { class: "start-here-card", href: "#/guide" }, h("span", { class: "guide-mini-mark", "aria-hidden": "true", text: "01" }),
        h("div", {}, h("strong", { text: "New here? Your first small win starts here." }), h("span", { text: "A gentle guide to projects, models, running code, and undoing mistakes." })), h("span", { "aria-hidden": "true", text: "↗" })),
      S.starters?.length ? h("section", { class: "starter-section", "aria-label": "Starter projects" },
        h("div", { class: "starter-heading" }, h("div", {}, h("span", { class: "hero-eyebrow", text: "PICK YOUR FIRST ADVENTURE" }),
          h("h2", { text: "Small projects. Big possibilities." })), h("span", { class: "muted", text: "Python · no extra libraries · yours to remix" })),
        h("div", { class: "starter-grid" }, ...S.starters.map((s, i) => h("button", {
          class: `starter-card starter-${i}`, onclick: () => newProjectDialog(s.id), "aria-label": `Start ${s.title}` },
          h("div", { class: "starter-art", "aria-hidden": "true" }, h("span", { class: "starter-glyph", text: ["?", "↗", "✦"][i] || "+" }),
            h("span", { class: "starter-orbit" }), h("span", { class: "starter-code", text: ["if curious: play()", "choose('your path')", "for pixel in idea:"][i] || "make()" })),
          h("div", { class: "starter-copy" }, h("span", { class: "starter-tag", text: s.tag }), h("h3", { text: s.title }),
            h("p", { text: s.description }), h("span", { class: "starter-concepts", text: s.concepts }),
            h("span", { class: "starter-cta", text: "Let's make it  ↗" })))))) : null,
      recent.length ? h("div", { class: "recent" }, h("h2", { text: "Recent projects" }),
        h("div", { class: "cards" }, recent.map((p) => h("a", { class: "card", href: `#/p/${p.id}` },
          h("h3", { text: p.name }), h("div", { class: "meta", text: p.path.replace(S.home, "~") }),
          h("div", { class: "meta", text: `opened ${fmtTime(p.last_opened || p.created)}` }))))) : null)));
  }
  unmount() { this.particles?.dispose(); }
}

class ParticleLabView {
  mount(main) {
    this.particles = createParticleExperience();
    main.append(h("div", { class: "page particle-page" }, h("div", { class: "lab-wrap" },
      h("header", { class: "lab-heading" }, h("div", {}, h("span", { class: "workshop-kicker", text: "THE PARTICLE LAB" }),
        h("h1", {}, "Made of dots. ", h("em", { text: "Full of possibility." }))),
        h("a", { class: "btn", href: "#/guide", text: "New to Grid? Start here ↗" })),
      this.particles.el,
      h("section", { class: "lab-lessons", "aria-label": "How to explore the Particle Lab" },
        ...[["01", "Turn it around", "Drag the cloud to explore its depth. You can also focus it and use the arrow keys."],
          ["02", "Change one thing", "Move Flow, Shape, or Glow, or pick a color. Each control changes one value in the running program."],
          ["03", "Notice the result", "Pause to inspect a fold. Shuffle sends the particles on a new path. Reset brings back the original settings."]].map(([n,t,d])=>
          h("article", {}, h("span", { class: "workshop-kicker", text:n }), h("h3", {text:t}),h("p",{text:d})))),
      h("details", { class: "lab-explanation" }, h("summary", { text: "How does a little code turn into this?" }),
        h("p", { text: "Each point has a position in three dimensions. A shader—a small program run by your graphics chip—moves those positions through a changing noise pattern. Translucent gray dots form the surface; warmer dots and a soft glow make the folds look lit from within." }),
        h("p", { text: "Flow changes how quickly time advances. Shape changes how far points move. Glow changes how brightly the color shines, and Shuffle moves the whole flow to a new place in the noise. This is a procedural particle study inspired by the reference clip, not a prerecorded video or a fluid-physics simulation." })))));
  }
  unmount() { this.particles?.dispose(); }
}
class BeginnerGuideView {
  mount(main) { main.append(createBeginnerGuide(h, { onStarter: newProjectDialog, onSetup: () => setupWizard({ force: true }) })); }
}

// ------------------------------------------------------------------ workspace
const TOOL_LABEL = { terminal: "terminal", file_editor: "edit", grep: "search", glob: "find", task_tracker: "tasks", browser: "browser",
  web_search: "web", web_fetch: "web", create_document: "document", memory: "memory", request_access: "access", view_image: "image", computer: "mac" };
// [icon, what Grid is doing while that tool is about to run]
const TOOL_META = { terminal: ["terminal", "Running a command"], file_editor: ["pencil", "Editing files"], grep: ["search", "Searching the project"],
  glob: ["search", "Looking through files"], task_tracker: ["list", "Planning the steps"], web_search: ["globe", "Searching the web"],
  web_fetch: ["globe", "Reading a page"], create_document: ["doc", "Making the document"], memory: ["brain", "Checking memory"],
  request_access: ["key", "Asking for access"], view_image: ["image", "Looking at the image"], computer: ["cursor", "Using your Mac"],
  browser: ["globe", "Using the browser"], think: ["sparkle", "Thinking it through"] };
const toolMeta = (t) => TOOL_META[t] || (String(t).startsWith("browser") ? TOOL_META.browser : ["terminal", `Using ${t}`]);
const toolLabel = (t) => TOOL_LABEL[t] || (String(t).startsWith("browser") ? "browser" : t);
function shortModel(id) { return String(id || "").replace(/^[\w-]+\//, "").replace(/^models\//, ""); }
function avatar() { return h("span", { class: "avatar", "aria-hidden": "true" }, h("img", { src: "/static/grid-mark.svg", alt: "" })); }

// Big photos and retina screenshots are resized before upload (the model sees ~1.5k px anyway).
function shrinkImage(file, maxSide = 1800) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => {
      const url = String(reader.result);
      if (file.type === "image/gif" || file.size < 600 * 1024) { resolve(url); return; }
      const img = new Image();
      img.onerror = () => resolve(url);
      img.onload = () => {
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        if (scale >= 1 && file.size < 4 * 1024 * 1024) { resolve(url); return; }
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        resolve(c.toDataURL(file.type === "image/png" ? "image/png" : "image/jpeg", 0.88));
      };
      img.src = url;
    };
    reader.readAsDataURL(file);
  });
}

function fileCard(path) {
  const name = path.split("/").pop();
  const where = path.replace(S.home, "~").split("/").slice(0, -1).join("/") || "/";
  const desk = window.gridDesktop;
  return h("div", { class: "file-card" },
    h("span", { class: `file-icon ${(name.split(".").pop() || "").toLowerCase()}`, text: ({ pdf: "PDF", docx: "DOC", xlsx: "XLS", pptx: "PPT" })[(name.split(".").pop() || "").toLowerCase()] || "FILE" }),
    h("div", { class: "grow" }, h("div", { class: "file-name", text: name }), h("div", { class: "faint", style: "font-size:12px", text: `Saved in ${where}` })),
    desk?.openPath ? h("button", { class: "btn small primary", text: "Open", onclick: () => desk.openPath(path) }) : null,
    desk?.showInFolder ? h("button", { class: "btn small", text: "Show in Finder", onclick: () => desk.showInFolder(path) }) : null,
    desk?.openPath ? null : h("a", { class: "btn small primary", href: `/api/download?path=${encodeURIComponent(path)}`, download: name, text: "Download" }));
}

class Workspace {
  constructor(project) {
    this.p = project;
    this.base = `/api/projects/${project.id}`;
    this.actions = new Map();          // action id -> {el, dot, body}
    this.asks = new Map();             // ask id -> card
    this.pendingConfidence = null;
    this.pendingApproval = null;
    this.running = false;
    this.lastSeq = 0;
    this.commands = [];
    this.status = {};
    this.expanded = new Set([""]);
    this.selectedDir = "";
    this.openFile = null;
    this.tab = "changes";
    this.terminal = [];
    this.lastOutcome = null;
    this.showHidden = false;
    this.closed = false;
  }

  // ---------------------------------------------------------------- layout
  // A project stage with focused Play, Code and Understand modes.
  // Existing editor, terminal and review state stay mounted across mode changes.
  async mount(main) {
    this.mode = "editor";
    this.root = h("div", { class: "ws mode-editor workshop", "data-workshop": "play" });
    this.editorArea = new EditorArea(this);
    this.termPanel = new TerminalPanel(this);
    // files
    this.treeEl = h("div", { class: "tree", role: "tree" });
    this.search = new SearchView(this);
    this.sideTabs = h("div", { class: "side-tabs", role: "tablist" });
    this.filesPane = h("div", { class: "side-pane" },
      h("div", { class: "pane-head" }, h("span", { class: "title", text: this.p.name, title: this.p.path }),
        h("button", { class: "icon-btn", title: "New file", "aria-label": "New file", onclick: () => this.newEntry("file") }, ico("file-plus")),
        h("button", { class: "icon-btn", title: "New folder", "aria-label": "New folder", onclick: () => this.newEntry("dir") }, ico("folder-plus")),
        h("button", { class: "icon-btn", title: "Show hidden files", "aria-label": "Show hidden files", onclick: () => { this.showHidden = !this.showHidden; this.refreshTree(); } }, ico("eye")),
        h("button", { class: "icon-btn", title: "Refresh", "aria-label": "Refresh", onclick: () => this.refreshTree() }, ico("refresh"))),
      this.treeEl);
    const files = h("section", { class: "files" }, this.sideTabs, this.filesPane, this.search.el);
    this.side = "files";
    // conversation
    this.streamEl = h("div", { class: "stream", "aria-live": "polite" });
    this.autoBtn = h("button", { class: "toggle auto", "aria-pressed": "false", title: "Autonomous mode", onclick: () => this.toggleAutonomous() }, "Autonomous");
    this.planBtn = h("button", { class: "toggle", "aria-pressed": String(!!S.settings.plan_first), title: "Plan first, then ask before executing",
      onclick: () => this.planBtn.setAttribute("aria-pressed", String(this.planBtn.getAttribute("aria-pressed") !== "true")) }, "Plan first");
    this.modelBtn = h("button", { class: "toggle model-btn", title: "Model", onclick: () => this.pickModel() }, "model");
    this.depthSel = h("select", { title: "Teaching depth", class: "depth-sel",
      onchange: () => attempt(() => POST(`${this.base}/settings`, { depth: this.depthSel.value })) },
      ...[["beginner", "Guide me"], ["intermediate", "Build together"], ["pro", "Quick explanations"], ["off", "Just build"]]
        .map(([value, text]) => h("option", { value, text })));
    this.runSpin = h("span", { class: "spinner hidden", title: "working" });
    const layoutBtn = h("button", { class: "btn small ghost", title: "Focus on the guide",
      text: "Focus guide", onclick: () => this.setWorkshopMode("understand") });
    const head = h("div", { class: "convo-head" },
      h("div", { class: "grow head-title" }, h("div", { class: "pname" }, this.mode === "editor" ? "Your guide" : this.p.name, " ", this.runSpin),
        this.mode === "chat" ? h("div", { class: "ppath", text: this.p.path.replace(S.home, "~"), title: this.p.path }) : null),
      layoutBtn,
      h("button", { class: "btn small ghost", text: "History", title: "Earlier chats in this project", onclick: () => this.showHistory() }),
      h("button", { class: "btn small ghost", text: "New chat", title: "Start a fresh conversation", onclick: () => this.newChat() }),
      this.mode === "chat" ? h("button", { class: "icon-btn", title: "Toggle files", "aria-label": "Toggle files", onclick: () => this.root.classList.toggle("no-files") }, ico("menu")) : null,
      this.mode === "chat" ? h("button", { class: "icon-btn", title: "Toggle side panel", "aria-label": "Toggle side panel", onclick: () => this.root.classList.toggle("no-inspector") }, ico("panel")) : null,
      h("button", { class: "icon-btn", title: "Remove project from Grid (keeps the folder)", text: "✕", onclick: () => this.forget() }));
    const controls = h("div", { class: "convo-controls" }, this.modelBtn, this.depthSel, this.planBtn, this.autoBtn);
    // Chat tabs: every chat in this project, oldest on the left. Click to switch, × to delete
    // (it asks once more on the same button), double-click to rename, Ctrl+Tab to cycle.
    this.chats = []; this.currentChat = null;
    this.chatTabs = h("div", { class: "chat-tabs", role: "tablist", "aria-label": "Chats" });
    this.input = h("textarea", { rows: 2, placeholder: "What are you curious about?", "aria-label": "Message Grid" });
    this.sendBtn = h("button", { class: "btn primary send-btn", title: "Send (Enter)", "aria-label": "Send", onclick: () => this.send() }, ico("send", 16), h("span", { text: "Send" }));
    this.pending = [];                       // images to send: {url, name}
    this.tray = h("div", { class: "img-tray hidden" });
    this.fileInput = h("input", { type: "file", accept: "image/png,image/jpeg,image/gif,image/webp", multiple: true, class: "hidden",
      "aria-label": "Choose images", onchange: () => { this.addImages([...this.fileInput.files]); this.fileInput.value = ""; } });
    const attachBtn = h("button", { class: "icon-btn attach-btn", title: "Add images (or paste / drop them)", "aria-label": "Add images",
      onclick: () => this.fileInput.click() }, ico("clip", 17));
    this.slashEl = h("div", { class: "slash hidden", role: "listbox" });
    const composer = h("div", { class: "composer" }, this.slashEl,
      h("div", { class: "box" }, this.tray, this.input, this.fileInput,
        h("div", { class: "bar" }, attachBtn, h("span", { class: "hint", text: this.mode === "editor" ? "Enter to send · Shift+Enter for a new line" : "Enter to send · Shift+Enter for a new line" }), this.sendBtn)));
    this.phaseEl = h("div", { class: "task-phase", role: "status", "aria-live": "polite", "data-phase": "ready" },
      h("span", { class: "phase-dot" }), h("span", { class: "phase-label", text: "Ready when you are" }), h("span", { class: "phase-detail", text: S.executionMode === "restricted" ? "Container + policy review" : "Trusted host · local guardrails" }));
    this.latestBtn = h("button", { class: "jump-latest", type: "button", text: "Latest messages ↓", hidden: true });
    const convo = h("section", { class: "convo" }, head, this.chatTabs, controls, this.phaseEl, this.streamEl, this.latestBtn, composer);
    // tool panel (bottom in editor mode, right in chat mode)
    this.insTabs = h("div", { class: "ins-tabs", role: "tablist" });
    this.insBody = h("div", { class: "ins-body" });
    this.panelTabs = this.mode === "editor"
      ? [["terminal", "Terminal"], ["log", "Agent log"], ["changes", "Changes"], ["checkpoints", "Checkpoints"]]
      : [["changes", "Changes"], ["checkpoints", "Checkpoints"], ["file", "Editor"], ["terminal", "Terminal"], ["log", "Agent log"]];
    this.tab = this.mode === "editor" ? "terminal" : "changes";
    if (this.mode === "editor") {
      const panelToggle = h("button", { class: "icon-btn", title: "Hide panel", "aria-label": "Hide panel", onclick: () => this.root.classList.toggle("panel-hidden") }, ico("down"));
      this.insTabs.append();
      const bottom = h("div", { class: "bottom-panel" }, h("div", { class: "panel-bar" }, this.insTabs, panelToggle), this.insBody);
      this.playIntro = h("div", { class: "play-intro" },
        h("div", {}, h("span", { class: "workshop-kicker", text: "THE EXPERIMENT SPACE" }),
          h("h2", { text: "Let's see what happens." }),
          h("p", { text: "Run your project below. Try a small change. Come back and try again." })),
        h("button", { class: "btn", text: "Read project guide ↗", onclick: () => this.openPath("README.md") }));
      this.backboard = createParticleBackboard(h);
      const center = h("section", { class: "center" }, this.playIntro, this.editorArea.el, bottom, this.backboard.el);
      center.addEventListener("pointerdown", e => { if (!e.target.closest(".particle-backboard")) this.backboard.dismiss({ auto: true }); }, { capture: true });
      this.root.append(files, center, convo);
    } else {
      const inspector = h("section", { class: "inspector" }, this.insTabs, this.insBody);
      this.root.append(files, convo, inspector);
    }
    this.workshopModes = h("div", { class: "workshop-modes", role: "group", "aria-label": "Workshop mode" },
      ...[["play", "01", "Play"], ["code", "02", "Code"], ["understand", "03", "Understand"]].map(([key, number, label]) =>
        h("button", { "data-mode": key, "aria-pressed": String(key === "play"), onclick: () => this.setWorkshopMode(key) },
          h("span", { text: number }), label)));
    this.filesBtn = h("button", { class: "btn small", text: "Files", "aria-expanded": "false", onclick: () => {
      const open = this.root.classList.toggle("side-open"); this.filesBtn.setAttribute("aria-expanded", String(open));
      if (open) this.setWorkshopMode("code");
    } });
    this.root.prepend(h("header", { class: "workshop-bar" },
      h("div", { class: "workshop-project" }, h("img", { class: "project-spark", "aria-hidden": "true", src: "/static/grid-mark.svg", alt: "" }),
        h("div", {}, h("span", { class: "workshop-kicker", text: "YOUR WORKSHOP" }), h("strong", { text: this.p.name }))),
      this.workshopModes, h("div", { class: "workshop-utilities" },
        h("button", { class: "btn small", text: "Particles", title: "Show the particle scene in the workspace (use − and + on it to resize, up to fullscreen)", onclick: () => this.backboard?.show() }), this.filesBtn)));
    main.append(this.root);
    this.followTail = new StreamFollower(this.streamEl, this.latestBtn);

    this.input.addEventListener("keydown", (e) => this.onKey(e));
    this.input.addEventListener("input", () => this.onComposerInput());
    this.input.addEventListener("paste", (e) => {
      const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
      if (files.length) { e.preventDefault(); this.addImages(files); }
    });
    convo.addEventListener("dragover", (e) => { if ([...(e.dataTransfer?.items || [])].some((i) => i.type.startsWith("image/"))) { e.preventDefault(); convo.classList.add("dropping"); } });
    convo.addEventListener("dragleave", (e) => { if (!convo.contains(e.relatedTarget)) convo.classList.remove("dropping"); });
    convo.addEventListener("drop", (e) => {
      const files = [...(e.dataTransfer?.files || [])].filter((f) => f.type.startsWith("image/"));
      convo.classList.remove("dropping");
      if (files.length) { e.preventDefault(); this.addImages(files); }
    });
    this.renderSide();
    this.renderTabs();
    this.welcome();
    await Promise.all([this.refreshTree(), this.loadCommands(), this.loadStatus()]);
    this.renderInspector();
    this.connect();
    this.loadChats();
    this.root.addEventListener("keydown", (e) => {
      if (e.ctrlKey && !e.metaKey && !e.altKey && e.key === "Tab") { e.preventDefault(); this.cycleChat(e.shiftKey ? -1 : 1); }
    });
    await this.editorArea.restore();
    this.setWorkshopMode(this.asks.size ? "understand" : "play");
  }

  setWorkshopMode(mode) {
    if (!["play", "code", "understand"].includes(mode)) return;
    this.workshopMode = mode;
    this.root.dataset.workshop = mode;
    this.root.classList.toggle("reviewing", mode === "code" && this.editorArea.active?.kind === "review");
    for (const button of this.workshopModes.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    }
    if (mode === "play") this.showTab("terminal");
    if (mode === "understand") this.input.focus();
    this.editorArea.layout();
    this.termPanel.fit?.fit();
  }

  unmount() {
    this.closed = true;
    try { this.ws?.close(); } catch (e) { /* ignore */ }
    clearTimeout(this.reconnectTimer);
    this.followTail?.dispose();
    this.backboard?.dispose();
    this.editorArea?.dispose();
    this.termPanel?.dispose();
  }

  // ---------------------------------------------------------------- left side: files / search
  renderSide() {
    const tab = (k, label, keys) => h("button", { class: this.side === k ? "active" : "", role: "tab", "aria-selected": String(this.side === k),
      title: `${label} (${keys})`, text: label, onclick: () => this.showSide(k) });
    this.sideTabs.replaceChildren(tab("files", "Files", "⌘⇧E"), tab("search", "Search", "⌘⇧F"));
    this.filesPane.classList.toggle("hidden", this.side !== "files");
    this.search.el.classList.toggle("hidden", this.side !== "search");
  }

  showSide(k, opts = {}) {
    this.side = k;
    this.root.classList.remove("no-files");
    this.root.classList.add("side-open");
    this.filesBtn?.setAttribute("aria-expanded", "true");
    this.setWorkshopMode("code");
    this.renderSide();
    if (k === "search") this.search.focus(opts);
  }

  // Every file in the project, for quick open. Cached until something changes on disk.
  async fileIndex() {
    if (!this._index) this._index = GET(`${this.base}/files-index`).catch((e) => { this._index = null; throw e; });
    return this._index;
  }

  openAt(path, line, col = 1, length = 0) {
    this.setWorkshopMode("code");
    this.openFile = path;
    return this.editorArea.openAt(path, line, col, length).then(() => {
      if (this.mode === "chat") this.showTab("file");
      this.refreshTree();
    });
  }

  sendTask(text) {
    this.input.value = text;
    this.autosize();
    return this.send();
  }

  addToChat(text) {
    const cur = this.input.value.trim();
    this.input.value = (cur ? cur + "\n\n" : "") + text + "\n\n";
    this.autosize();
    this.input.focus();
    this.input.setSelectionRange(this.input.value.length, this.input.value.length);
  }

  autosize() {
    this.input.style.height = "auto";
    this.input.style.height = Math.min(220, this.input.scrollHeight) + "px";
  }

  welcome() {
    const ideas = [
      ["sparkle", "Give me a hint", "Read the README and give me one hint for the first challenge. Don't change files or give away the full solution yet."],
      ["search", "Explain the code", "Explain how this project's code works in plain language. Pick one concept I can experiment with."],
      ["pencil", "Build together", "Help me make one small change to this project. Explain the idea, review the change with me, and run the relevant checks."],
      ["terminal", "Check my work", "Review my current changes and run the project's checks. Explain what the results show and what still needs checking."],
    ];
    this.streamEl.replaceChildren(h("div", { class: "welcome" },
      h("div", { class: "welcome-mark" }, h("img", { src: "/static/grid-mark.svg", alt: "" })),
      h("h2", { text: `What will you try in ${this.p.name}?` }),
      h("p", { text: "You bring the curiosity. We'll take it one small step at a time. Ask for a hint, explore the code, or build together. Choose how much explanation you want above." }),
      h("div", { class: "suggestions" }, ...ideas.map(([icon, title, prompt]) => h("button", { class: "idea", onclick: () => { this.input.value = prompt; this.input.focus(); this.autosize(); } },
        h("span", { class: "idea-ico" }, ico(icon, 15)), h("span", { class: "idea-text" }, h("strong", { text: title }),
          h("span", { text: {"Give me a hint": "A clue, so you can try it yourself.", "Explain the code": "See the idea behind the program.",
            "Build together": "One small change, with an explanation.", "Check my work": "Find out what works and what needs attention."}[title] || prompt }))))),
      S.setup && !S.setup.ready ? h("div", { class: "callout warn setup-nudge" },
        h("span", { text: `Grid can't think yet: ${S.setup.key_present ? (S.setup.endpoint_problem || "the model isn't reachable") : `no key for ${S.setup.model}`}. ` }),
        h("button", { class: "btn small primary", text: "Set up a model", onclick: () => setupWizard({ force: true }) })) : null));
    this.hasWelcome = true;
  }

  // ---------------------------------------------------------------- status & controls
  async loadStatus() {
    const st = await attempt(() => GET(`${this.base}/session`));
    if (st) this.applyStatus(st);
  }

  applyStatus(st) {
    this.status = st;
    this.autoBtn.setAttribute("aria-pressed", String(!!st.autonomous));
    this.autoBtn.textContent = st.autonomous ? `Autonomous${st.allow?.length ? " + " + st.allow.join(",") : ""}` : "Autonomous";
    if (st.depth) this.depthSel.value = st.depth;
    if (st.model) {
      this.modelBtn.replaceChildren(h("span", { class: "model-dot" }), h("span", { text: shortModel(st.model.model) }));
      this.modelBtn.title = `Model: ${st.model.model} (click to change)`;
    }
    this.setRunning(!!st.running);
    for (const a of st.pending || []) if (!this.asks.has(a.id)) this.renderAsk(a);
  }

  setPhase(phase, label, detail = "") {
    if (!this.phaseEl) return;
    this.phaseEl.dataset.phase = phase;
    this.phaseEl.querySelector(".phase-label").textContent = label;
    this.phaseEl.querySelector(".phase-detail").textContent = detail;
  }

  onComposerInput() {
    this.autosize();
    this.updateSlash();
  }

  setRunning(on) {
    this.running = on;
    if (on) this.setPhase("working", "Working on your request", "Follow the steps below");
    else if (this.phaseEl?.dataset.phase === "working") this.setPhase("ready", "Ready for your next step", S.executionMode === "restricted" ? "Container + policy review" : "Trusted host · local guardrails");
    this.runSpin.classList.toggle("hidden", !on);
    this.sendBtn.replaceChildren(ico(on ? "stop" : "send", on ? 14 : 16), h("span", { text: on ? "Stop" : "Send" }));
    this.sendBtn.className = on ? "btn danger-solid send-btn" : "btn primary send-btn";
    this.sendBtn.title = on ? "Stop after the current step" : "Send (Enter)";
    this.sendBtn.setAttribute("aria-label", on ? "Stop" : "Send");
    if (!on) this.dropLive(true);
    if (on) S.running.add(this.p.id); else S.running.delete(this.p.id);
    renderProjectList();
  }

  async toggleAutonomous() {
    if (this.status.autonomous) {
      const r = await attempt(() => POST(`${this.base}/autonomous`, { on: false }));
      if (r) { toast("Autonomous mode off - Grid will ask before risky actions."); this.loadStatus(); }
      return;
    }
    const info = await attempt(() => GET("/api/autonomy"));
    if (!info) return;
    const boxes = Object.entries(info.allowable).map(([k, desc]) => {
      const cb = h("input", { type: "checkbox", value: k });
      return { k, cb, el: h("label", { class: "check" }, cb, h("span", {}, h("code", { text: k }), " ", h("span", { class: "muted", text: desc }))) };
    });
    const confirm = h("input", { type: "text", placeholder: "type yes" });
    const ok = await modal({
      title: "Turn on autonomous mode?",
      body: h("div", {},
        h("p", { text: "Grid will stop asking before acting. Every change is still checkpointed, regressions are reverted, and a task only counts as done when Grid runs a real check and it passes." }),
        h("p", { class: "muted", text: `It checks in every ${S.settings?.step_budget ?? 25} steps without stopping, and pauses for you after ${info.max_steps ?? 300} steps on one task.`
          + (info.self_review === false ? "" : " Before \"done\", it re-reads its changes for consistency.") + " Change these in Settings." }),
        h("div", { class: "callout warn" }, h("h4", { text: "High-risk (RED) actions" }),
          h("p", { style: "margin:0 0 8px", text: "Refused unless you allow the category below:" }), ...boxes.map((b) => b.el)),
        h("div", { class: "callout bad", style: "margin-top:10px" }, h("h4", { text: "Never run unattended" }),
          h("div", { class: "muted", text: Object.values(info.hard_blocked).join(" · ") })),
        h("label", { class: "field", style: "margin-top:12px" }, "Type yes to let Grid run without asking", confirm)),
      buttons: [{ label: "Cancel", value: false }, {
        label: "Turn on", kind: "primary",
        onClick: async () => {
          if (confirm.value.trim().toLowerCase() !== "yes") { toast("Type yes to confirm", "error"); return false; }
          const allow = boxes.filter((b) => b.cb.checked).map((b) => b.k);
          return !!(await attempt(() => POST(`${this.base}/autonomous`, { on: true, allow, confirm: "yes" })));
        },
      }],
    });
    if (ok) this.loadStatus();
  }

  async pickModel() {
    const data = await attempt(() => GET("/api/models"));
    if (!data) return;
    const adhoc = h("input", { type: "text", placeholder: "or any model id, e.g. openai/gpt-5.5" });
    const list = h("div", { class: "dirlist" }, data.profiles.length ? data.profiles.map((p) =>
      h("div", { onclick: async () => { await this.setModel({ profile: p.name }); close?.(); } },
        h("strong", { text: p.name }), "  ", h("span", { class: "mono", text: p.model }), "  ",
        h("span", { class: `chip ${p.local ? "accent" : ""}`, text: p.local ? "local" : "cloud" }))) :
      h("div", { class: "faint", text: "No saved models yet - add them on the Models page." }));
    let close;
    await modal({
      title: "Model for this project",
      body: h("div", {}, h("p", { class: "muted", text: `Now: ${this.status.model?.model || data.current.model}` }), list,
        h("label", { class: "field", style: "margin-top:10px" }, "Ad-hoc model", adhoc)),
      buttons: [{ label: "Close", value: null }, {
        label: "Use ad-hoc model", kind: "primary",
        onClick: async () => adhoc.value.trim() ? (await this.setModel({ model: adhoc.value.trim() }), true) : false,
      }],
      onOpen: (_b, c) => { close = c; },
    });
  }

  async setModel(body) {
    const r = await attempt(() => POST(`${this.base}/model`, body));
    if (r) { toast(r.message); this.loadStatus(); }
  }

  async newChat() {
    if (this.running) { toast("Stop the running task first", "error"); return; }
    if (await attempt(() => POST(`${this.base}/new-chat`))) { this.actions.clear(); this.asks.clear(); this.welcome(); }
  }

  // ---------------------------------------------------------------- chat tabs
  loadChats = debounce(async () => {
    if (this.closed) return;
    let r;
    try { r = await GET(`${this.base}/chats`); } catch (e) { return; }
    this.currentChat = r.current || null;
    this.chats = (r.chats || []).slice(0, 24).sort((a, b) => (a.started || a.updated || 0) - (b.started || b.updated || 0));
    this.renderChatTabs();
  }, 150);

  renderChatTabs() {
    const tabs = this.chats.map((c) => ({ id: c.id, title: c.title || "Chat", chat: c }));
    // A chat that hasn't been saved yet (or a blank one just started with +) shows as "New chat".
    if (!this.currentChat || !tabs.some((t) => t.id === this.currentChat)) tabs.push({ id: this.currentChat, title: "New chat", fresh: true });
    const tab = (t) => {
      const current = t.id === this.currentChat;
      const del = h("button", { class: "chat-tab-x", type: "button", title: "Delete this chat", "aria-label": `Delete chat: ${t.title}`,
        onclick: (e) => { e.stopPropagation(); this.deleteChat(t, del); } }, ico("x", 12));
      // The tab itself and its × are sibling buttons: a role="tab" element hides its children
      // from screen readers, so the × can't live inside it.
      const el = h("div", { class: `chat-tab ${current ? "current" : ""} ${t.fresh ? "fresh" : ""}`,
        title: t.chat ? `${t.title}\n${fmtTime(t.chat.updated)} · ${t.chat.turns} message${t.chat.turns === 1 ? "" : "s"}` : t.title,
        onclick: () => this.switchChat(t.id),
        ondblclick: async () => {
          if (!t.chat) return;
          const name = await askText("Rename chat", "Title", t.title, "Rename");
          if (name && await attempt(() => POST(`${this.base}/chats/${t.id}/rename`, { title: name }))) this.loadChats();
        } },
        h("button", { class: "chat-tab-title", type: "button", role: "tab", "aria-selected": String(current), text: t.title,
          onkeydown: (e) => { if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); this.deleteChat(t, del); } } }),
        t.fresh && !this.chats.length ? null : del);
      return el;
    };
    const add = h("button", { class: "chat-tab-new", type: "button", title: "New chat", "aria-label": "New chat", onclick: () => this.newChat() }, ico("plus", 14));
    this.chatTabs.replaceChildren(...tabs.map(tab), add);
    this.chatTabs.querySelector(".chat-tab.current")?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }

  async switchChat(id) {
    if (!id || id === this.currentChat) return;
    if (this.running) { toast("Stop the running task first", "error"); return; }
    if (await attempt(() => POST(`${this.base}/chats/${id}/open`))) { this.actions.clear(); this.asks.clear(); this.currentChat = id; this.renderChatTabs(); }
  }

  cycleChat(step) {
    const list = this.chats.map((c) => c.id);
    if (this.currentChat && !list.includes(this.currentChat)) list.push(this.currentChat);
    if (!list.length || (list.length < 2 && this.currentChat)) return;
    let i = list.indexOf(this.currentChat);
    if (i < 0) i = step > 0 ? -1 : list.length;          // a blank new chat sits at the end
    this.switchChat(list[(i + step + list.length) % list.length]);
  }

  // × asks once more on the same button (it turns red), so a stray click never deletes a chat.
  async deleteChat(t, btn) {
    if (!btn.classList.contains("confirm")) {
      btn.classList.add("confirm"); btn.title = "Click again to delete"; btn.closest(".chat-tab")?.classList.add("deleting");
      clearTimeout(btn._undo);
      btn._undo = setTimeout(() => { btn.classList.remove("confirm"); btn.title = "Delete this chat"; btn.closest(".chat-tab")?.classList.remove("deleting"); }, 2600);
      return;
    }
    clearTimeout(btn._undo);
    if (t.id === this.currentChat) {
      if (this.running) { toast("Stop the running task first", "error"); return; }
      // Move off the open chat first: to its neighbour, or to a fresh chat if it was the only one.
      const others = this.chats.filter((c) => c.id !== t.id);
      const i = this.chats.findIndex((c) => c.id === t.id);
      const next = others[Math.min(Math.max(i, 0), others.length - 1)];
      const moved = next ? await attempt(() => POST(`${this.base}/chats/${next.id}/open`)) : await attempt(() => POST(`${this.base}/new-chat`));
      if (!moved) return;
      this.actions.clear(); this.asks.clear();
      if (!next) this.welcome();
      this.currentChat = next ? next.id : null;
    }
    if (t.fresh) { this.loadChats(); return; }
    if (await attempt(() => DEL(`${this.base}/chats/${t.id}`))) {
      this.chats = this.chats.filter((c) => c.id !== t.id);
      this.renderChatTabs();
      toast("Chat deleted");
      this.loadChats();
    }
  }

  async showHistory() {
    const r = await attempt(() => GET(`${this.base}/chats`));
    if (!r) return;
    const list = h("div", { class: "chat-list" });
    const render = (chats) => list.replaceChildren(...(chats.length ? chats.map((c) => h("div", { class: `chat-row ${c.current ? "current" : ""}` },
      h("div", { class: "grow" },
        h("div", { class: "row", style: "gap:6px" }, h("strong", { text: c.title }), c.current ? h("span", { class: "chip accent", text: "open" }) : null),
        h("div", { class: "faint", style: "font-size:12px", text: `${fmtTime(c.updated)} · ${c.turns} message${c.turns === 1 ? "" : "s"}` }),
        c.last ? h("div", { class: "muted chat-last", text: c.last }) : null),
      h("div", { class: "row", style: "gap:4px;flex-wrap:nowrap" },
        c.current ? null : h("button", { class: "btn small primary", text: "Open", onclick: async () => {
          if (this.running) { toast("Stop the running task first", "error"); return; }
          close?.();
          if (await attempt(() => POST(`${this.base}/chats/${c.id}/open`))) { this.actions.clear(); this.asks.clear(); }
        } }),
        h("button", { class: "icon-btn", title: "Rename", "aria-label": "Rename", onclick: async () => {
          const t = await askText("Rename chat", "Title", c.title, "Rename");
          if (t && await attempt(() => POST(`${this.base}/chats/${c.id}/rename`, { title: t }))) { c.title = t; render(chats); }
        } }, ico("pencil")),
        c.current ? null : h("button", { class: "icon-btn", title: "Delete from history", "aria-label": "Delete from history", onclick: async () => {
          if (await attempt(() => DEL(`${this.base}/chats/${c.id}`))) render(chats.filter((x) => x !== c));
        } }, ico("trash")))))
      : [h("div", { class: "empty", text: "No earlier chats yet. Everything you and Grid talk about shows up here." })]));
    render(r.chats);
    let close = null;
    modal({ title: "Chat history", body: h("div", {}, h("p", { class: "muted", style: "margin:0 0 8px", text: "Grid remembers every chat. Open one to pick up where you left off - or just ask Grid about it (\"what did we do about the login bug?\")." }), list),
      wide: true, buttons: [{ label: "Close", value: null }], onOpen: (_b, c) => { close = c; } });
  }

  async forget() {
    if (!(await confirmBox("Remove project from Grid?", `The folder ${this.p.path} stays on disk; Grid just stops listing it.`, "Remove", true))) return;
    if (await attempt(() => DEL(`/api/projects/${this.p.id}`))) { await loadState(); location.hash = "#/"; }
  }

  // ---------------------------------------------------------------- composer
  async loadCommands() {
    const r = await attempt(() => GET(`${this.base}/commands`));
    this.commands = r ? r.commands : [];
    if (this.input?.value.startsWith("/")) this.updateSlash();   // typed before the list arrived
  }

  updateSlash() {
    const v = this.input.value;
    if (!v.startsWith("/") || v.includes(" ") || v.includes("\n")) { this.slashEl.classList.add("hidden"); return; }
    const matches = this.commands.filter((c) => c.slash.startsWith(v)).slice(0, 12);
    this.slashEl.replaceChildren(...matches.map((c, i) => h("div", { class: i === 0 ? "active" : "", role: "option",
      onmousedown: (e) => { e.preventDefault(); this.pickSlash(c); } },
      h("code", { text: c.slash + (c.argument_hint ? " " + c.argument_hint : "") }), h("span", { class: "muted", text: c.description || "" }))));
    this.slashMatches = matches;
    this.slashEl.classList.toggle("hidden", !matches.length);
  }

  pickSlash(c) {
    this.input.value = c.slash + " ";
    this.slashEl.classList.add("hidden");
    this.input.focus();
  }

  onKey(e) {
    if (!this.slashEl.classList.contains("hidden") && (e.key === "Tab" || (e.key === "Enter" && this.slashMatches?.length))) {
      const exact = this.slashMatches.find((c) => c.slash === this.input.value.trim());
      if (!exact || e.key === "Tab") { e.preventDefault(); this.pickSlash(this.slashMatches[0]); return; }
    }
    if (e.key === "Escape") this.slashEl.classList.add("hidden");
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.send(); }
  }

  async send() {
    if (this.running) {
      await attempt(() => POST(`${this.base}/stop`));
      return;
    }
    let text = this.input.value.trim();
    const images = this.pending.map((p) => p.url);
    if (!text && !images.length) return;
    if (S.setup && !S.setup.ready) {
      await setupWizard({ force: true });
      if (!S.setup?.ready) return;      // keep the message in the box for when it's set up
    }
    let plan = this.planBtn.getAttribute("aria-pressed") === "true";
    const word = text.split(/\s+/)[0];
    if (word === "/undo") { this.input.value = ""; return this.undo(text.split(/\s+/)[1]); }
    if (word === "/verify") { this.input.value = ""; return this.verifyNow(); }
    if (word === "/new") { this.input.value = ""; return this.newChat(); }
    if (word === "/plan") { plan = true; text = text.slice(5).trim(); if (!text) return; }
    this.input.value = "";
    this.autosize();
    this.slashEl.classList.add("hidden");
    const sent = this.pending;
    this.pending = [];
    this.renderTray();
    const r = await attempt(() => POST(`${this.base}/tasks`, { text, plan, images }));
    if (!r) { this.input.value = text; this.pending = sent; this.renderTray(); }
  }

  async addImages(files) {
    for (const f of files) {
      if (this.pending.length >= 6) { toast("Up to 6 images per message", "error"); break; }
      if (!/^image\/(png|jpeg|gif|webp)$/.test(f.type)) { toast(`${f.name}: use PNG, JPEG, GIF or WebP`, "error"); continue; }
      try { this.pending.push({ url: await shrinkImage(f), name: f.name || "image" }); } catch (e) { toast(`Couldn't read ${f.name}`, "error"); }
    }
    this.renderTray();
    this.input.focus();
  }

  renderTray() {
    this.tray.classList.toggle("hidden", !this.pending.length);
    this.tray.replaceChildren(...this.pending.map((p, i) => h("div", { class: "thumb", title: p.name },
      h("img", { src: p.url, alt: p.name }),
      h("button", { class: "thumb-x", title: "Remove", "aria-label": `Remove ${p.name}`, text: "✕", onclick: () => { this.pending.splice(i, 1); this.renderTray(); } }))));
  }

  async undo(ref) {
    const r = await attempt(() => POST(`${this.base}/undo`, ref ? { ref } : {}));
    if (r) { toast(r.message); this.refreshAll(); }
  }

  async verifyNow() {
    const r = await attempt(() => POST(`${this.base}/verify`));
    if (!r) return;
    const line = this.addLine("[grid][verify] running the project's check ...");
    const res = await pollJob(r.job);
    line.remove();
    if (res?.status === "done") {
      const v = res.result;
      this.append(h("div", { class: `callout ${v.ok ? "good" : "bad"}` }, h("h4", { text: `${v.ok ? "PASS" : "FAIL"} - ${v.label}` }),
        h("details", {}, h("summary", { text: "output" }), h("pre", { class: "mono", text: v.tail }))));
    } else if (res) toast(res.error || "verify failed", "error");
  }

  // ---------------------------------------------------------------- websocket
  connect() {
    if (this.closed) return;
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${this.base}/events?since=${this.lastSeq}`;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onmessage = (m) => {
      let ev;
      try { ev = JSON.parse(m.data); } catch (e) { return; }
      if (ev.seq) { if (ev.seq <= this.lastSeq) return; this.lastSeq = ev.seq; }
      this.handle(ev);
    };
    ws.onclose = () => {
      if (this.closed) return;
      this.reconnectTimer = setTimeout(() => this.connect(), 1500);
    };
  }

  // ---------------------------------------------------------------- stream rendering
  nearBottom() {
    const s = this.streamEl;
    return this.followTail ? this.followTail.follow : s.scrollHeight - s.scrollTop - s.clientHeight < 140;
  }

  append(el) {
    if (this.hasWelcome) { this.streamEl.replaceChildren(); this.hasWelcome = false; }
    this.streamEl.append(el);
    this.followTail?.contentChanged();
    return el;
  }

  addLine(text, extra) {
    text = String(text).split(this.p.path + "/").join("");
    const m = text.match(/^\[grid\](\[[\w-]+\])?\s*(.*)$/s);
    return this.append(h("div", { class: "gline" }, h("span", { class: "tag", text: m ? (m[1] ? m[1].slice(1, -1) : "grid") : "" }), h("span", { class: "gtext", text: m ? m[2] : text }), extra || null));
  }

  handle(ev) {
    switch (ev.type) {
      case "hello": this.applyStatus(ev.status); break;
      case "status": this.setRunning(ev.running); if (!ev.running) this.loadStatus(); break;
      case "user": this.onUser(ev); break;
      case "stream": this.onStream(ev); break;
      case "say": if (/\[verify\] running/.test(ev.text)) this.setPhase("checking", "Running verification", "A passing check has a limited scope"); this.onSay(ev.text); break;
      case "action": this.onAction(ev); break;
      case "observation": this.onObservation(ev); break;
      case "rejected": this.onRejected(ev); break;
      case "agent": this.onAgent(ev); break;
      case "thought": if (ev.text) this.append(h("div", { class: "narration" }, md(ev.text))); break;
      case "note": this.onNote(ev.text); break;
      case "error": this.dropLive(true); this.append(h("div", { class: "callout bad" }, h("h4", { text: "Something went wrong" }), h("pre", { class: "mono", text: ev.text }))); break;
      case "ask": this.setPhase("approval", "Your decision is needed", "Read the action before approving"); this.renderAsk(ev); break;
      case "answered": this.setPhase("working", "Continuing", "Following your decision"); this.markAnswered(ev.id, ev.answer); break;
      case "outcome":
        this.loadChats();
        // plain conversation: no card unless something changed or was checked
        if (ev.outcome === "done" && !(ev.changed || []).length && !ev.verify) { this.lastOutcome = ev; break; }
        this.onOutcome(ev); break;
      case "files_changed": this.refreshAll(); break;
      case "cleared": this.actions.clear(); this.asks.clear(); this.live = null; this.welcome(); this.loadChats(); break;
      case "session": this.currentChat = ev.id || this.currentChat; this.loadChats(); break;
      default: break;
    }
  }

  // ---------------------------------------------------------------- live replies
  // One "live" element at the bottom while Grid works: a thinking indicator, then the
  // words as the model writes them. The finished message replaces it.
  onUser(ev) {
    this.dropLive(true);
    this.answered = false;
    const imgs = (ev.images || []).length ? h("div", { class: "msg-imgs" }, ...ev.images.map((u) => h("a", { href: u, target: "_blank", rel: "noopener" }, h("img", { src: u, alt: "attached image" })))) : null;
    this.append(h("div", { class: "turn turn-user" }, h("div", { class: "msg-user" }, ev.plan ? h("span", { class: "plan-tag", text: "Plan first" }) : null, imgs,
      h("div", { class: "utext", text: ev.text }))));
    if (!ev.replay) this.showThinking();
  }

  newLive() {
    const body = h("div", { class: "msg-body" });
    const status = h("div", { class: "live-status" });
    const meta = h("span", { class: "meta" });
    const el = h("div", { class: "turn msg-agent live" }, h("div", { class: "msg-head" }, avatar(), h("span", { class: "who", text: "Grid" }), meta), status, body);
    this.live = { el, body, status, meta, sid: null, phase: "wait", started: Date.now(), text: "", thought: "", thoughtSecs: 0 };
    this.append(el);
    clearInterval(this.liveTimer);
    this.liveTimer = setInterval(() => this.tickLive(), 1000);
    return this.live;
  }

  tickLive() {
    const L = this.live;
    if (!L) { clearInterval(this.liveTimer); return; }
    const secs = Math.round((Date.now() - L.started) / 1000);
    if (L.phase === "wait" || L.phase === "thinking" || L.phase === "tool") L.meta.textContent = secs >= 2 ? `${secs}s` : "";
  }

  showThinking() {
    if (this.live) return;
    const L = this.newLive();
    this.setLiveStatus(L, "Thinking");
  }

  setLiveStatus(L, label, icon) {
    if (!label) { L.status.replaceChildren(); L.status.classList.add("hidden"); return; }
    L.status.classList.remove("hidden");
    L.status.replaceChildren(h("span", { class: "orb" }), icon ? h("span", { class: "st-ico" }, ico(icon, 13)) : null, h("span", { class: "shimmer", text: label }));
  }

  onStream(ev) {
    if (ev.phase === "cancel") {               // a quick reply turned into real work
      if (this.live && this.live.sid === ev.sid) { this.live.el.remove(); this.live = null; this.showThinking(); }
      return;
    }
    let L = this.live;
    if (L && L.sid !== null && L.sid !== ev.sid) {
      // a new model call: what the last one said stays as narration
      if (!this.liveToNarration()) { L.el.remove(); this.live = null; }
      L = null;
    }
    if (!L) L = this.newLive();
    L.sid = ev.sid;
    if (ev.phase === "thinking") {
      L.phase = "thinking";
      L.thought = ev.text || "";
      this.setLiveStatus(L, "Thinking");
      if (!L.peek) { L.peek = h("div", { class: "think-peek" }); L.status.after(L.peek); }
      L.peek.textContent = L.thought.slice(-280);
    } else {
      if (L.peek) { L.peek.remove(); L.peek = null; }
      if ((L.phase === "thinking" || ev.thought_chars) && !L.thoughtSecs) {
        L.thoughtSecs = Math.max(1, Math.round((Date.now() - L.started) / 1000));
        L.el.querySelector(".msg-head").after(h("div", { class: "thought-for" }, ico("sparkle", 12), h("span", { text: `Thought for ${L.thoughtSecs}s` })));
      }
      if (ev.phase === "tool") {
        L.phase = "tool";
        const [icon, label] = toolMeta(ev.tool);
        this.setLiveStatus(L, label, icon);
        if (ev.text && ev.text !== L.text) { L.text = ev.text; L.body.replaceChildren(md(ev.text, { live: true })); }
      } else {
        L.phase = ev.phase;                   // text | final
        this.setLiveStatus(L, null);
        L.meta.textContent = "";
        if (ev.text !== L.text) {
          if (!ev.replay && ev.text?.length > L.text.length) this.backboard?.react(ev.text.length - L.text.length);
          L.text = ev.text || "";
          const view = md(L.text, { live: true });
          const lastBlock = view.lastElementChild;
          (lastBlock && !lastBlock.matches(".codeblock, .md-table, hr") ? lastBlock : view).append(h("span", { class: "caret" }));
          L.body.replaceChildren(view);
        }
      }
    }
    this.followTail?.contentChanged();
  }

  // The live reply was the model talking before it used a tool: keep it as narration.
  liveToNarration() {
    const L = this.live;
    if (!L) return false;
    this.live = null;
    clearInterval(this.liveTimer);
    if (!L.text.trim()) { L.el.remove(); return false; }
    L.el.replaceWith(h("div", { class: "narration" }, md(L.text)));
    return true;
  }

  // Running stopped (or failed): remove an empty indicator; keep words already written.
  dropLive(keepText) {
    const L = this.live;
    if (!L) return;
    this.live = null;
    clearInterval(this.liveTimer);
    if (keepText && L.text.trim()) { L.el.classList.remove("live"); L.status.remove(); L.body.querySelector(".caret")?.remove(); }
    else L.el.remove();
  }

  onAgent(ev) {
    const text = String(ev.text || "");
    if (!text.trim()) return;
    let L = this.live;
    if (!ev.replay && text !== L?.text) this.backboard?.react(text.length);
    this.live = null;
    clearInterval(this.liveTimer);
    let el;
    if (L) {
      el = L.el;
      el.classList.remove("live");
      L.status.remove();
      L.meta.textContent = "";
      L.body.replaceChildren(md(text));
    } else {
      el = this.append(h("div", { class: "turn msg-agent" }, h("div", { class: "msg-head" }, avatar(), h("span", { class: "who", text: "Grid" }), h("span", { class: "meta" })),
        h("div", { class: "msg-body" }, md(text))));
    }
    if (ev.final) { el.classList.add("final"); this.answered = true; }
    const copy = h("button", { class: "msg-act", title: "Copy reply", "aria-label": "Copy reply", onclick: async () => {
      try { await navigator.clipboard.writeText(text); toast("Copied"); } catch (e) { toast("Couldn't copy", "error"); }
    } }, ico("copy", 13));
    el.querySelector(".msg-head").append(h("span", { class: "msg-acts" }, copy));
    this.followTail?.contentChanged();
    if (!_monaco && /```/.test(text)) {
      const body = el.querySelector(".msg-body");
      loadMonaco().then(() => body.replaceChildren(md(text))).catch(() => {});
    }
  }

  onSay(text) {
    const t = String(text || "");
    if (t.startsWith("[grid][confidence]")) { this.pendingConfidence = t.replace("[grid][confidence]", "").trim(); return; }
    if (t.trim().startsWith("[grid] approval needed:")) { this.pendingApproval = t.trim().split("\n").slice(1).map((l) => l.trim()).join("\n"); return; }
    if (t.includes("== PLAN ==")) {
      const body = t.replace(/^[\s\S]*?=+ PLAN =+\n?/, "").replace(/\n?=+\s*$/, "");
      this.append(h("div", { class: "plan" }, h("div", { class: "label", text: "PLAN" }), md(body)));
      return;
    }
    if (/^\s*\[grid\] (outcome:|changed files|undo this task)/.test(t) || /^\s{4}\S/.test(t)) return;
    if (t.startsWith("[grid][checkpoint]")) {
      const m = t.match(/#(\d+)\s+(.*)$/);
      this.addLine(t, m ? h("button", { class: "btn small ghost", text: "restore", title: `Undo back to checkpoint #${m[1]}`, onclick: () => this.undo(m[1]) }) : null);
      this.scheduleRefresh();
      return;
    }
    if (t.startsWith("[grid][verify] PASS")) { this.append(h("div", { class: "callout good" }, h("strong", { text: "Check result: " }), t.replace("[grid][verify] PASS - ", "").replace("(proof of outcome)", ""))); return; }
    if (t.startsWith("[grid][review]")) { this.append(h("div", { class: "callout info" }, h("strong", { text: "Review: " }), t.replace("[grid][review] ", ""))); return; }
    if (t.startsWith("[grid][verify] FAIL")) { this.append(h("div", { class: "callout bad" }, h("strong", { text: "Check failed: " }), t.replace("[grid][verify] FAIL - ", ""))); return; }
    if (t.includes("[grid][regression]")) { this.append(h("div", { class: "callout warn" }, h("h4", { text: "Regression" }), t.replace("[grid][regression]", "").trim())); return; }
    if (t.startsWith("[grid][undo]")) { this.append(h("div", { class: "callout info" }, t.replace("[grid][undo]", "Undo:"))); this.scheduleRefresh(); return; }
    if (t.startsWith("[grid][autonomous] refused")) { this.append(h("div", { class: "callout bad" }, h("h4", { text: "Refused (not pre-approved)" }), t.replace("[grid][autonomous] refused: ", ""))); return; }
    if (t.startsWith("[grid] AUTONOMOUS MODE") || t.includes("AUTONOMOUS MODE")) { this.append(h("div", { class: "callout warn" }, h("pre", { class: "mono", text: t.replace(/^\[grid\]\s*/, "") }))); return; }
    if (t.startsWith("[grid][persona]")) { S.persona = { ...(S.persona || {}), effective: "teacher", minor_lock: true }; this.append(h("div", { class: "callout info", text: t.replace("[grid][persona] ", "") })); return; }
    if (t.startsWith("[grid][access]")) { this.append(h("div", { class: "callout info", text: t.replace("[grid][access] ", "") })); return; }
    if (t.startsWith("[grid] autonomous mode off")) { this.append(h("div", { class: "callout info", text: t.replace("[grid] ", "") })); return; }
    for (const line of t.split("\n")) if (line.trim()) this.addLine(line.trim());
  }

  onAction(ev) {
    const conf = this.pendingConfidence;
    this.pendingConfidence = null;
    // What the model said before using the tool stays in the chat as a short narration line.
    if (!this.liveToNarration() && ev.thought) this.append(h("div", { class: "narration" }, md(ev.thought)));
    const dot = h("span", { class: "status-dot wait" });
    const body = h("div", { class: "body" });
    if (ev.edit) {
      if (ev.edit.old_str !== undefined || ev.edit.new_str !== undefined) {
        const lines = [];
        if (ev.edit.old_str) lines.push(...String(ev.edit.old_str).split("\n").map((l) => "-" + l));
        if (ev.edit.new_str) lines.push(...String(ev.edit.new_str).split("\n").map((l) => "+" + l));
        body.append(diffView(lines.join("\n")));
      } else if (ev.edit.file_text) body.append(h("pre", { class: "out", text: ev.edit.file_text }));
    }
    const pct = conf && conf.match(/\d+%/);
    const confChip = pct ? h("span", { class: `chip conf ${/downgraded/.test(conf) ? "yellow" : ""}`, title: `Model self-estimate, not a measured probability. ${conf}`, text: pct[0] }) : null;
    const riskChip = ev.risk && ev.risk !== "LOW" ? h("span", { class: `chip ${ev.risk}`, text: ev.risk }) : null;
    let summary = ev.summary || ev.tool;
    if (ev.path) summary = summary.replace(this.p.path + "/", "");
    if (ev.tool === "file_editor") summary = summary.replace(/^file_editor\s+/, "");
    const el = h("details", { class: "act" },
      h("summary", {}, h("span", { class: "act-ico" }, ico(toolMeta(ev.tool)[0], 14)), h("span", { class: "tool", text: toolLabel(ev.tool) }),
        h("span", { class: "sum", text: summary, title: summary }), riskChip, confChip, dot),
      body);
    this.actions.set(ev.id, { el, dot, body, ev });
    this.append(el);
  }

  onObservation(ev) {
    const a = this.actions.get(ev.action_id);
    const bad = ev.is_error || (ev.exit_code !== null && ev.exit_code !== undefined && ev.exit_code !== 0 && ev.exit_code !== -1);
    if (a) {
      a.dot.className = `status-dot ${bad ? "bad" : "ok"}`;
      if (ev.text) a.body.append(h("pre", { class: "out", text: (ev.truncated ? "...\n" : "") + ev.text }));
    }
    if ((ev.images || []).length) {
      const shots = h("div", { class: "obs-imgs" }, ...ev.images.map((u) => h("a", { href: u, target: "_blank", rel: "noopener" }, h("img", { src: u, alt: "screenshot" }))));
      if (a) a.body.append(shots); else this.append(shots);
    }
    if (ev.file && !bad) this.append(fileCard(ev.file));
    if (this.running && !ev.replay && !this.answered && ev.tool !== "finish") this.showThinking();   // the model reads the result next
    if (ev.tool === "terminal") {
      this.terminal.push({ cmd: a?.ev.command || "", text: ev.text, bad });
      if (this.tab === "log") this.renderInspector();
    }
  }

  onRejected(ev) {
    const a = this.actions.get(ev.action_id);
    if (a) {
      a.el.classList.add("rejected");
      a.dot.className = "status-dot bad";
      a.body.append(h("div", { class: "callout bad", text: `Not run: ${ev.reason}` }));
    } else this.append(h("div", { class: "callout bad", text: `Not run: ${ev.reason}` }));
  }

  onNote(text) {
    const first = String(text).split("\n")[0];
    this.append(h("details", { class: "note" }, h("summary", { text: `Grid → agent: ${first.slice(0, 140)}${first.length > 140 ? "..." : ""}` }), md(text)));
  }

  renderAsk(ev) {
    if (this.asks.has(ev.id)) return;
    this.setWorkshopMode("understand");
    const ctx = this.pendingApproval;
    this.pendingApproval = null;
    const red = /\[RED\]/.test(ctx || "");
    const question = String(ev.prompt).replace(/\s*\[\w\][\s\S]*$/, "").replace(/:\s*$/, "").trim() || "Grid needs your answer";
    const reply = h("input", { type: "text", placeholder: "or type a reply / reason / guidance" });
    const access = /^(Grid wants to use |Can Grid |Grid wants to .* in )/.test(String(ev.prompt));
    const card = h("div", { class: `ask ${red ? "red" : ""} ${access ? "access" : ""}`, role: "group", "aria-label": question });
    const send = async (text) => {
      card.querySelectorAll("button, input").forEach((b) => (b.disabled = true));
      const r = await attempt(() => POST(`${this.base}/answer`, { id: ev.id, text }));
      if (!r) card.querySelectorAll("button, input").forEach((b) => (b.disabled = false));
    };
    const buttons = (ev.options || []).map((o) => h("button", {
      class: `btn small ${o.key === "y" || o.key === "r" ? (red ? "danger-solid" : "primary") : ""} ${o.key === "q" || o.key === "s" ? "ghost" : ""}`,
      text: o.label.charAt(0).toUpperCase() + o.label.slice(1), onclick: () => send(o.key),
    }));
    reply.addEventListener("keydown", (e) => { if (e.key === "Enter" && reply.value.trim()) send(reply.value.trim()); });
    const kicker = /^Grid wants to use /.test(String(ev.prompt)) ? "\u{1F512} Folder access" : /^Can Grid /.test(String(ev.prompt)) ? "\u{1F5A5} Mac control" : "\u{1F5A5} Check before acting";
    card.append(access ? h("div", { class: "ask-kicker", text: kicker }) : null,
      h("div", { class: "q", text: question }), ctx ? h("div", { class: "ctx", text: ctx }) : null,
      h("div", { class: "row" }, ...buttons), h("div", { class: "row" }, reply,
        h("button", { class: "btn small", text: "Reply", onclick: () => reply.value.trim() && send(reply.value.trim()) })));
    this.asks.set(ev.id, card);
    this.append(card);
    card.scrollIntoView({ block: "nearest" });
    // For RED actions the safe answer gets the focus, so a stray Enter can't approve it.
    ((red && buttons.find((b) => b.textContent === "No")) || buttons[0] || reply).focus();
  }

  markAnswered(id, answer) {
    const card = this.asks.get(id);
    if (!card) return;
    card.classList.add("answered");
    card.querySelectorAll("button, input").forEach((b) => (b.disabled = true));
    card.append(h("div", { class: "muted", text: `Answered: ${answer || "(nothing)"}` }));
  }

  onOutcome(ev) {
    this.lastOutcome = ev;
    this.setPhase(ev.outcome, ev.outcome === "verified" ? "Checks passed · ready to review" : ev.outcome === "blocked" ? "Request blocked by safety policy" : "Task finished", ev.outcome === "verified" ? "Review the changes" : "See the result below");
    const labels = { verified: "Checks passed", blocked: "Safety policy", done: "Done", unverified: "Not verified", planned: "Planned", paused: "Paused",
      needs_approval: "Needs your approval", stuck: "Stuck", error: "Error" };
    const files = (ev.changed || []).map((line) => {
      const [st, ...rest] = line.split("\t");
      const path = rest.join("\t");
      return h("button", { class: "btn small", title: "Open the diff", onclick: () => this.showTab("changes", path) }, h("span", { class: "chip", text: st }), " ", path);
    });
    this.append(h("div", { class: `outcome ${ev.outcome}` },
      h("div", { class: "row" }, h("span", { class: `chip ${ev.outcome}`, text: labels[ev.outcome] || ev.outcome }),
        ev.verify ? h("span", { class: "muted mono", text: ev.verify }) : null),
      ev.outcome === "blocked" ? h("p", { text: ev.message || "This request conflicts with Grid’s safety policy. Try a defensive or educational alternative." }) : null,
      ev.verify ? h("p", { class: "evidence-note", text: "This result applies to the check shown above. Review the code and any behavior it does not cover." }) : null,
      files.length ? h("div", { class: "ofiles" }, ...files) : null,
      files.length && ev.start_checkpoint !== null ? h("div", { class: "row" },
        h("button", { class: "btn small primary", text: "Review changes", onclick: () => this.reviewTask(ev) }),
        h("button", { class: "btn small danger", text: "Undo this task", onclick: async () => {
          if (await confirmBox("Undo this task?", "Restores the project to how it was before this task. You can redo it from the checkpoint list.", "Undo"))
            this.undo(String(ev.start_checkpoint));
        } })) : null));
    this.refreshAll();
  }

  scheduleRefresh = debounce(() => this.refreshAll(), 400);

  refreshAll() {
    this._index = null;
    this.search?.stale();
    this.refreshTree();
    this.editorArea?.syncFromDisk();
    if (this.tab === "changes" || this.tab === "checkpoints") this.renderInspector();
  }

  // ---------------------------------------------------------------- files
  async refreshTree() {
    if (this.closed) return;
    this._index = null;
    const build = async (rel, depth) => {
      const r = await attempt(() => GET(`${this.base}/tree?path=${encodeURIComponent(rel)}${this.showHidden ? "&hidden=1" : ""}`));
      const box = h("div", { class: depth ? "children" : "", role: depth ? "group" : null });
      if (!r) return box;
      for (const e of r.entries) {
        const isDir = e.type === "dir";
        const open = isDir && this.expanded.has(e.path);
        const node = h("div", {
          class: `node ${(this.openFile === e.path || this.selectedDir === e.path) ? "selected" : ""}`, role: "treeitem", title: e.path,
          "aria-expanded": isDir ? String(open) : null,
          onclick: () => {
            if (isDir) {
              this.selectedDir = e.path;
              if (open) this.expanded.delete(e.path); else this.expanded.add(e.path);
              this.refreshTree();
            } else { this.selectedDir = e.path.includes("/") ? e.path.slice(0, e.path.lastIndexOf("/")) : ""; this.openPath(e.path); }
          },
        },
          h("span", { class: "twisty", text: isDir ? (open ? "▾" : "▸") : "" }),
          h("span", { class: `node-ico ${isDir ? "dir" : "file"}` }, ico(isDir ? "folder" : "file", 15)),
          h("span", { class: "name", text: e.name }),
          h("span", { class: "node-actions" },
            h("button", { class: "icon-btn", title: "Rename", "aria-label": "Rename", onclick: (ev) => { ev.stopPropagation(); this.renameEntry(e); } }, ico("pencil", 14)),
            h("button", { class: "icon-btn", title: "Delete (moves to Grid's trash)", "aria-label": "Delete", onclick: (ev) => { ev.stopPropagation(); this.deleteEntry(e); } }, ico("trash", 14))));
        box.append(node);
        if (open) box.append(await build(e.path, depth + 1));
      }
      if (!depth && !r.entries.length) box.append(h("div", { class: "faint", style: "padding:6px 10px", text: "Empty folder" }));
      return box;
    };
    const tree = await build("", 0);
    this.treeEl.replaceChildren(tree);
  }

  async newEntry(kind) {
    const base = this.selectedDir ? this.selectedDir + "/" : "";
    const name = await askText(kind === "dir" ? "New folder" : "New file", `Path inside ${this.p.name}`, base, "Create");
    if (!name) return;
    const r = await attempt(() => POST(`${this.base}/files/${kind === "dir" ? "mkdir" : "new"}`, { path: name }));
    if (!r) return;
    if (kind === "dir") { this.expanded.add(name); this.selectedDir = name; }
    const parts = name.split("/");
    for (let i = 1; i < parts.length; i++) this.expanded.add(parts.slice(0, i).join("/"));
    await this.refreshTree();
    if (kind === "file") this.openPath(name);
  }

  async renameEntry(e) {
    const to = await askText("Rename", "New path", e.path, "Rename");
    if (!to || to === e.path) return;
    if (await attempt(() => POST(`${this.base}/files/rename`, { path: e.path, to }))) {
      if (this.openFile === e.path) this.openFile = to;
      this.refreshAll();
    }
  }

  async deleteEntry(e) {
    if (!(await confirmBox(`Delete ${e.name}?`, "It moves to Grid's trash (~/.grid/trash) and a checkpoint is taken first, so you can undo it.", "Delete", true))) return;
    const r = await attempt(() => POST(`${this.base}/files/delete`, { path: e.path }));
    if (r) { toast("Moved to Grid's trash"); if (this.openFile === e.path) this.openFile = null; this.refreshAll(); if (this.tab === "file") this.renderInspector(); }
  }

  openPath(path) {
    this.editorArea.open(path);
    if (this.mode === "chat") this.showTab("file");
    this.openFile = path;
    this.refreshTree();
  }

  reviewTask(ev) {
    const files = (ev.changed || []).map((line) => line.split("\t").slice(1).join("\t") || line);
    this.editorArea.openReview(String(ev.start_checkpoint), files);
    if (this.mode === "chat") this.showTab("file");
  }

  // ---------------------------------------------------------------- tool panel
  renderTabs() {
    this.insTabs.replaceChildren(...this.panelTabs.map(([k, label]) => h("button", {
      class: this.tab === k ? "active" : "", role: "tab", "aria-selected": String(this.tab === k), text: label,
      onclick: () => this.showTab(k),
    })));
  }

  showTab(k, focusPath) {
    if (this.workshopMode === "understand") this.setWorkshopMode("play");
    if (!this.panelTabs.some(([t]) => t === k)) k = k === "file" ? this.tab : "changes";
    this.tab = k;
    this.focusPath = focusPath || null;
    this.root.classList.remove("no-inspector", "panel-hidden");
    this.renderTabs();
    this.renderInspector();
  }

  async renderInspector() {
    const tab = this.tab;
    if (tab === "changes") {
      const r = await attempt(() => GET(`${this.base}/diff`));
      if (this.tab !== tab || !r) return;
      const pad = h("div", { class: "ins-pad" });
      if (!r.base) pad.append(h("div", { class: "empty", text: "No checkpoints yet. Changes show up here once Grid (or you) edits something." }));
      else {
        pad.append(h("div", { class: "row" }, h("span", { class: "muted grow", text: `Since checkpoint #${r.base.id}: ${r.base.label}` }),
          r.files.length ? h("button", { class: "btn small", text: "Review in editor", onclick: () => {
            this.editorArea.openReview(String(r.base.id), r.files.map((f) => f.split("\t").slice(1).join("\t")));
            if (this.mode === "chat") this.showTab("file");
          } }) : null));
        if (!r.files.length) pad.append(h("div", { class: "empty", text: "No changes since then." }));
        else {
          pad.append(h("div", { class: "row" }, ...r.files.map((f) => h("span", { class: "chip mono", text: f.replace("\t", " ") }))));
          const dv = diffView(r.diff);
          pad.append(dv);
          if (this.focusPath) [...dv.querySelectorAll(".file")].find((d) => d.textContent === this.focusPath)?.scrollIntoView({ block: "start" });
        }
      }
      this.insBody.replaceChildren(pad);
    } else if (tab === "checkpoints") {
      const r = await attempt(() => GET(`${this.base}/checkpoints`));
      if (this.tab !== tab || !r) return;
      if (!r.checkpoints.length) { this.insBody.replaceChildren(h("div", { class: "ins-pad" }, h("div", { class: "empty", text: "No checkpoints yet." }))); return; }
      this.insBody.replaceChildren(...r.checkpoints.map((c) => h("div", { class: `cp ${c.head ? "head" : ""}` },
        h("span", { class: "id", text: `#${c.id}` }),
        h("div", { class: "grow" }, h("div", { text: c.label.split(this.p.path + "/").join("") }),
          h("div", { class: "faint", style: "font-size:12px" }, fmtTime(c.timestamp), c.tests ? h("span", { class: `chip ${c.good ? "green" : c.good === false ? "red" : ""}`, style: "margin-left:6px", text: c.tests }) : null)),
        c.head ? h("span", { class: "chip accent", text: "current" }) :
          h("button", { class: "btn small", text: "Restore", onclick: async () => {
            if (await confirmBox(`Restore checkpoint #${c.id}?`, "The project goes back to this point. The current state is checkpointed first, so you can come back.", "Restore")) this.undo(String(c.id));
          } }))));
    } else if (tab === "terminal") {
      this.insBody.replaceChildren(this.termPanel.el);
      this.termPanel.start();
    } else if (tab === "log") {
      if (!this.terminal.length) { this.insBody.replaceChildren(h("div", { class: "ins-pad" }, h("div", { class: "empty", text: "Commands the agent runs show up here." }))); return; }
      this.insBody.replaceChildren(...this.terminal.map((t) => h("div", { class: "term-entry" },
        h("div", { class: "cmd", text: `$ ${t.cmd}` }), h("pre", { class: "mono", style: t.bad ? "color:var(--red)" : "", text: t.text }))));
      this.insBody.scrollTop = this.insBody.scrollHeight;
    } else if (tab === "file") {
      this.insBody.replaceChildren(this.editorArea.el);
      this.editorArea.layout();
    }
  }
}

// ------------------------------------------------------------------ layout preference
function getLayout() {
  try { return localStorage.getItem("grid.layout") === "chat" ? "chat" : "editor"; } catch (e) { return "editor"; }
}
function toggleLayout() {
  if (S.view instanceof Workspace) S.view.setWorkshopMode(S.view.workshopMode === "understand" ? "code" : "understand");
}

function isDark() {
  const t = document.documentElement.getAttribute("data-theme");
  if (t) return t === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

const _scripts = new Map();
function loadScript(src) {
  if (!_scripts.has(src)) {
    _scripts.set(src, new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error(`couldn't load ${src}`));
      document.head.append(s);
    }));
  }
  return _scripts.get(src);
}
function loadCss(href) {
  if (!document.querySelector(`link[href="${href}"]`)) document.head.append(h("link", { rel: "stylesheet", href }));
}

let _monaco = null;
async function loadMonaco() {
  if (_monaco) return _monaco;
  const base = "/static/vendor/monaco/vs";
  await loadScript(`${base}/loader.js`);
  window.require.config({ paths: { vs: base } });
  _monaco = await new Promise((resolve, reject) => window.require(["vs/editor/editor.main"], () => resolve(window.monaco), reject));
  const sync = () => {
    const dark = isDark();
    const bg = hex6(cssVar("--code-bg")), a1 = hex6(cssVar("--a1")), text = hex6(cssVar("--text")), faint = hex6(cssVar("--faint"));
    _monaco.editor.defineTheme("grid", { base: dark ? "vs-dark" : "vs", inherit: true,
      rules: [{ token: "comment", foreground: faint, fontStyle: "italic" }, { token: "keyword", foreground: a1 }],
      colors: { "editor.background": `#${bg}`, "editor.foreground": `#${text}`, "editorLineNumber.foreground": `#${faint}`,
        "editorLineNumber.activeForeground": `#${a1}`, "editorCursor.foreground": `#${a1}`, "editor.lineHighlightBackground": dark ? "#ffffff08" : "#0000000a",
        "editor.selectionBackground": `#${a1}40`, "editorIndentGuide.background1": dark ? "#ffffff0d" : "#0000000d",
        "editorWidget.background": dark ? "#131922" : "#ffffff", "editorGutter.background": `#${bg}`, "scrollbarSlider.background": dark ? "#ffffff14" : "#0000001a" } });
    _monaco.editor.setTheme("grid");
  };
  sync();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", sync);
  window.addEventListener("grid-theme", sync);
  return _monaco;
}

// ------------------------------------------------------------------ editor area
// Tabs of real files (Monaco editor) plus "review" tabs (Monaco diff editor)
// that show what a task changed, with keep / revert per file.
class EditorArea {
  constructor(ws) {
    this.ws = ws;
    this.tabs = [];
    this.active = null;
    this.tabBar = h("div", { class: "etabs", role: "tablist" });
    this.banner = h("div", { class: "ebanner hidden" });
    this.host = h("div", { class: "ehost" });
    this.diffWrap = h("div", { class: "review hidden" });
    this.emptyEl = h("div", { class: "eempty" },
      h("div", { class: "eempty-inner" },
        h("p", { text: "Every idea starts with a little code. Open Files to explore yours." }),
        h("div", { class: "keys" }, h("span", {}, h("kbd", { text: "⌘P" }), " go to file"), h("span", {}, h("kbd", { text: "⌘⇧F" }), " search project"),
          h("span", {}, h("kbd", { text: "⌘⇧P" }), " commands"), h("span", {}, h("kbd", { text: "⌘S" }), " save"), h("span", {}, h("kbd", { text: "⌘K" }), " edit selection with Grid"),
          h("span", {}, h("kbd", { text: "⌘L" }), " add selection to chat"), h("span", {}, h("kbd", { text: "⌘\\" }), " focus guide"))));
    this.el = h("div", { class: "editor-area" }, this.tabBar, this.banner, h("div", { class: "estack" }, this.host, this.diffWrap, this.emptyEl));
    this.render();
  }

  storageKey() { return `grid.tabs.${this.ws.p.id}`; }
  persist() {
    try {
      localStorage.setItem(this.storageKey(), JSON.stringify({ files: this.tabs.filter((t) => t.kind === "file").map((t) => t.path), active: this.active?.kind === "file" ? this.active.path : null }));
    } catch (e) { /* ignore */ }
  }
  async restore() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(this.storageKey()) || "null"); } catch (e) { /* ignore */ }
    if (!saved?.files?.length) return;
    for (const p of saved.files) await this.open(p, { quiet: true, focus: false });
    const act = this.tabs.find((t) => t.path === saved.active) || this.tabs[0];
    if (act) this.activate(act);
  }

  async ensureEditor() {
    const monaco = await loadMonaco();
    if (!this.editor) {
      this.editor = monaco.editor.create(this.host, {
        automaticLayout: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false,
        fontFamily: "'JetBrains Mono Grid', ui-monospace, Menlo, monospace", fontLigatures: true, lineHeight: 20,
        padding: { top: 10 }, smoothScrolling: true, cursorSmoothCaretAnimation: "on", roundedSelection: true,
        renderWhitespace: "selection", tabSize: 4, fixedOverflowWidgets: true, model: null,
      });
      const KM = monaco.KeyMod, KC = monaco.KeyCode;
      this.editor.addCommand(KM.CtrlCmd | KC.KeyS, () => this.save(this.active));
      this.editor.addAction({ id: "grid.edit", label: "Grid: Edit selection…", keybindings: [KM.CtrlCmd | KC.KeyK],
        contextMenuGroupId: "navigation", contextMenuOrder: 0, run: () => this.inlineEdit() });
      this.editor.addAction({ id: "grid.addToChat", label: "Grid: Add selection to chat", keybindings: [KM.CtrlCmd | KC.KeyL],
        contextMenuGroupId: "navigation", contextMenuOrder: 1, run: () => this.addSelectionToChat() });
      this.editor.addAction({ id: "grid.explain", label: "Grid: Explain this", contextMenuGroupId: "navigation", contextMenuOrder: 2,
        run: () => { const s = this.selection(); if (s) this.ws.sendTask(`Explain this code from ${s.path} (lines ${s.from}-${s.to}). Don't change any files.\n\n${s.fenced}`); } });
    }
    return monaco;
  }

  selection() {
    const t = this.active;
    if (!t || t.kind !== "file" || !this.editor) return null;
    const sel = this.editor.getSelection();
    const model = t.model;
    let range = sel;
    if (!sel || sel.isEmpty()) {
      const line = sel ? sel.startLineNumber : 1;
      range = new window.monaco.Range(line, 1, line, model.getLineMaxColumn(line));
    }
    const text = model.getValueInRange(range);
    const lang = model.getLanguageId();
    return { path: t.path, from: range.startLineNumber, to: range.endLineNumber, text,
      fenced: "```" + (lang === "plaintext" ? "" : lang) + "\n" + text + "\n```" };
  }

  addSelectionToChat() {
    const s = this.selection();
    if (s) this.ws.addToChat(`${s.path} lines ${s.from}-${s.to}:\n${s.fenced}`);
  }

  inlineEdit() {
    const s = this.selection();
    if (!s) return;
    if (this.ws.running) { toast("Grid is busy - wait for the current task or stop it", "error"); return; }
    this.closeInline();
    const input = h("input", { type: "text", placeholder: `Edit ${s.path} lines ${s.from}-${s.to}: describe the change, Enter to run` });
    const box = h("div", { class: "inline-edit" }, h("span", { class: "chip accent", text: "⌘K" }), input,
      h("button", { class: "btn small primary", text: "Edit", onclick: () => go() }), h("button", { class: "icon-btn", text: "✕", title: "Cancel", onclick: () => this.closeInline() }));
    const go = async () => {
      const what = input.value.trim();
      if (!what) return;
      if (this.active?.dirty) await this.save(this.active);
      this.closeInline();
      await this.ws.sendTask(`In ${s.path}, lines ${s.from}-${s.to}:\n${s.fenced}\n\n${what}\n\nChange only that part unless something else must change for it to work. Run the relevant tests after.`);
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); if (e.key === "Escape") this.closeInline(); });
    this.inlineBox = box;
    this.el.append(box);
    input.focus();
  }
  closeInline() { this.inlineBox?.remove(); this.inlineBox = null; }

  async open(path, { quiet = false, focus = true } = {}) {
    let tab = this.tabs.find((t) => t.kind === "file" && t.path === path);
    if (!tab) {
      const r = await (quiet ? GET(`${this.ws.base}/file?path=${encodeURIComponent(path)}`).catch(() => null) : attempt(() => GET(`${this.ws.base}/file?path=${encodeURIComponent(path)}`)));
      if (!r) return;
      if (r.binary) { if (!quiet) toast(`${path} is a binary file`, "error"); return; }
      const monaco = await this.ensureEditor();
      const uri = monaco.Uri.file(`/${this.ws.p.id}/${path}`);
      const model = monaco.editor.getModel(uri) || monaco.editor.createModel(r.text, undefined, uri);
      if (model.getValue() !== r.text) model.setValue(r.text);
      tab = { kind: "file", key: `file:${path}`, path, model, saved: model.getAlternativeVersionId(), disk: r.text, version: r.version, dirty: false, view: null, truncated: r.truncated };
      model.onDidChangeContent(() => {
        const d = model.getAlternativeVersionId() !== tab.saved;
        if (d !== tab.dirty) { tab.dirty = d; this.render(); }
      });
      this.tabs.push(tab);
    }
    if (focus) this.activate(tab);
    this.persist();
    return tab;
  }

  // Open a file and put the cursor on a line (and select a match if given).
  async openAt(path, line, col = 1, length = 0) {
    const tab = await this.open(path);
    if (!tab || this.active !== tab) return;
    this.reveal(line, col, length);
  }

  reveal(line, col = 1, length = 0) {
    if (!this.editor || this.active?.kind !== "file") return false;
    const model = this.active.model;
    const ln = Math.max(1, Math.min(model.getLineCount(), line | 0));
    const c = Math.max(1, Math.min(model.getLineMaxColumn(ln), col | 0));
    const end = Math.min(model.getLineMaxColumn(ln), c + (length | 0));
    const range = new window.monaco.Range(ln, c, ln, end);
    this.editor.setSelection(range);
    this.editor.revealRangeInCenterIfOutsideViewport(range);
    this.editor.focus();
    return true;
  }

  async openReview(ref, files) {
    const key = `review:${ref}`;
    let tab = this.tabs.find((t) => t.key === key);
    if (!tab) {
      tab = { kind: "review", key, ref, files: files.map((f) => ({ path: f, state: "pending" })), current: files[0] };
      this.tabs.push(tab);
    } else {
      for (const f of files) if (!tab.files.some((x) => x.path === f)) tab.files.push({ path: f, state: "pending" });
    }
    await this.ensureEditor();
    this.activate(tab);
  }

  activate(tab) {
    this.ws.backboard?.dismiss({ auto: true });
    this.ws.setWorkshopMode("code");
    if (this.active?.kind === "file" && this.editor) this.active.view = this.editor.saveViewState();
    this.active = tab;
    this.closeInline();
    this.render();
    if (tab.kind === "file") {
      rememberRecent(this.ws.p.id, tab.path);
      this.editor.setModel(tab.model);
      if (tab.view) this.editor.restoreViewState(tab.view);
      this.editor.focus();
    } else if (tab.kind === "review") this.renderReview(tab);
    this.persist();
  }

  async close(tab) {
    if (tab.dirty && !(await confirmBox(`Close ${tab.path}?`, "It has unsaved changes. Closing discards them.", "Discard", true))) return;
    this.tabs = this.tabs.filter((t) => t !== tab);
    if (tab.kind === "file") tab.model.dispose();
    if (this.active === tab) { this.active = null; const next = this.tabs[this.tabs.length - 1]; if (next) this.activate(next); else this.render(); }
    else this.render();
    this.persist();
  }

  async save(tab) {
    if (!tab || tab.kind !== "file") return;
    const text = tab.model.getValue();
    if (tab.conflict) { toast("Resolve the disk conflict before saving.", "error"); return; }
    const r = await attempt(() => PUT(`${this.ws.base}/file`, { path: tab.path, text, expected_version: tab.version }));
    if (!r) return;
    tab.saved = tab.model.getAlternativeVersionId();
    tab.disk = text;
    tab.version = r.version;
    tab.dirty = false;
    tab.conflict = false;
    this.render();
    this.ws.refreshTree();
  }

  // Pick up changes the agent (or anything else) made on disk.
  async syncFromDisk() {
    for (const tab of this.tabs.filter((t) => t.kind === "file")) {
      const r = await GET(`${this.ws.base}/file?path=${encodeURIComponent(tab.path)}`).catch(() => null);
      if (!r) { tab.missing = true; continue; }
      tab.missing = false;
      if (r.text === tab.disk) continue;
      if (!tab.dirty) {
        const view = this.active === tab ? this.editor.saveViewState() : null;
        tab.model.pushEditOperations([], [{ range: tab.model.getFullModelRange(), text: r.text }], () => null);
        tab.saved = tab.model.getAlternativeVersionId();
        tab.disk = r.text;
        tab.version = r.version;
        tab.dirty = false;
        if (view) this.editor.restoreViewState(view);
        tab.flash = true;
        setTimeout(() => { tab.flash = false; this.render(); }, 1500);
      } else {
        tab.conflict = true;
        tab.diskPending = r.text;
        tab.versionPending = r.version;
      }
    }
    this.render();
    if (this.active?.kind === "review") this.renderReview(this.active);
  }

  render() {
    this.tabBar.replaceChildren(...this.tabs.map((t) => {
      const label = t.kind === "file" ? t.path.split("/").pop() : "Review changes";
      return h("div", { class: `etab ${t === this.active ? "active" : ""} etab-${t.kind} ${t.flash ? "flash" : ""}`, role: "tab", title: t.path || label,
        onclick: () => this.activate(t), onauxclick: (e) => { if (e.button === 1) this.close(t); } },
        t.kind === "review" ? h("span", { class: "chip accent", text: "diff" }) : null,
        h("span", { class: "etab-name", text: label }), t.missing ? h("span", { class: "chip red", text: "deleted" }) : null,
        h("button", { class: `etab-x ${t.dirty ? "dirty" : ""}`, title: t.dirty ? "Unsaved - click to close" : "Close", text: t.dirty ? "●" : "✕",
          onclick: (e) => { e.stopPropagation(); this.close(t); } }));
    }));
    const a = this.active;
    this.ws.root?.classList.toggle("reviewing", this.ws.workshopMode === "code" && a?.kind === "review");
    this.emptyEl.classList.toggle("hidden", !!a);
    this.host.classList.toggle("hidden", !a || a.kind !== "file");
    this.diffWrap.classList.toggle("hidden", !a || a.kind !== "review");
    if (a?.kind === "file" && a.conflict) {
      this.banner.replaceChildren(h("span", { text: `${a.path} changed on disk while you had unsaved edits.` }),
        h("button", { class: "btn small", text: "Load disk version", onclick: () => { a.model.setValue(a.diskPending); a.saved = a.model.getAlternativeVersionId(); a.disk = a.diskPending; a.version = a.versionPending; a.dirty = false; a.conflict = false; this.render(); } }),
        h("button", { class: "btn small", text: "Keep mine", onclick: () => { a.version = a.versionPending; a.conflict = false; this.render(); } }));
      this.banner.classList.remove("hidden");
    } else if (a?.kind === "file" && a.truncated) {
      this.banner.replaceChildren(h("span", { text: "This file is large and was truncated - editing is disabled." }));
      this.banner.classList.remove("hidden");
      this.editor?.updateOptions({ readOnly: true });
    } else {
      this.banner.classList.add("hidden");
      this.editor?.updateOptions({ readOnly: false });
    }
  }

  async renderReview(tab) {
    const monaco = await this.ensureEditor();
    const list = h("div", { class: "review-files" },
      h("div", { class: "review-head" }, h("strong", { text: "Review changes" }), h("span", { class: "faint", text: `${tab.files.length} file${tab.files.length === 1 ? "" : "s"} · checkpoint #${tab.ref}` })),
      ...tab.files.map((f) => h("div", { class: `review-file ${f.path === tab.current ? "active" : ""} ${f.state}`, onclick: () => { tab.current = f.path; this.renderReview(tab); } },
        h("span", { class: "grow mono", text: f.path }),
        f.state === "kept" ? h("span", { class: "chip green", text: "kept" }) : f.state === "reverted" ? h("span", { class: "chip red", text: "reverted" }) : null)),
      h("div", { class: "review-actions" },
        h("button", { class: "btn small primary", text: "Keep all", onclick: () => { tab.files.forEach((f) => { if (f.state === "pending") f.state = "kept"; }); toast("Kept all changes"); this.close(tab); } }),
        h("button", { class: "btn small danger", text: "Undo all", onclick: async () => {
          if (await confirmBox("Undo all these changes?", `Restores the whole project to checkpoint #${tab.ref}. The current state is checkpointed first.`, "Undo all", true)) { await this.ws.undo(tab.ref); this.close(tab); }
        } })));
    const f = tab.files.find((x) => x.path === tab.current) || tab.files[0];
    const bar = h("div", { class: "review-bar" });
    const diffHost = h("div", { class: "review-diff" });
    this.diffWrap.replaceChildren(list, h("div", { class: "review-main" }, bar, diffHost));
    if (!f) { diffHost.append(h("div", { class: "empty", text: "Nothing to review." })); return; }
    const [before, now] = await Promise.all([
      GET(`${this.ws.base}/file-at?ref=${encodeURIComponent(tab.ref)}&path=${encodeURIComponent(f.path)}`).catch(() => ({ text: "", exists: false })),
      GET(`${this.ws.base}/file?path=${encodeURIComponent(f.path)}`).catch(() => ({ text: "", binary: false })),
    ]);
    bar.append(...[h("span", { class: "mono grow", text: f.path }),
      !before.exists ? h("span", { class: "chip green", text: "new file" }) : null,
      h("button", { class: "btn small", text: "Keep", onclick: () => { f.state = "kept"; this.nextPending(tab); } }),
      h("button", { class: "btn small danger", text: before.exists ? "Revert file" : "Delete file", onclick: async () => {
        const r = await attempt(() => POST(`${this.ws.base}/files/revert`, { path: f.path, ref: tab.ref }));
        if (r) { f.state = "reverted"; toast(`${f.path} ${r.result}`); this.ws.refreshAll(); this.nextPending(tab); }
      } }),
      h("button", { class: "btn small ghost", text: "Open", onclick: () => this.open(f.path) })].filter(Boolean));
    if (this.diffEditor) this.diffEditor.dispose();
    this.diffModels?.forEach((m) => m.dispose());
    const orig = monaco.editor.createModel(before.text || "", undefined, monaco.Uri.file(`/review-before/${this.ws.p.id}/${tab.ref}/${f.path}`));
    const mod = monaco.editor.createModel(now.text || "", undefined, monaco.Uri.file(`/review-after/${this.ws.p.id}/${tab.ref}/${f.path}`));
    this.diffModels = [orig, mod];
    this.diffEditor = monaco.editor.createDiffEditor(diffHost, { automaticLayout: true, readOnly: true, originalEditable: false,
      renderSideBySide: diffHost.clientWidth > 900, wordWrap: "on", diffWordWrap: "on", minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 13 });
    this.diffEditor.setModel({ original: orig, modified: mod });
  }

  nextPending(tab) {
    const next = tab.files.find((x) => x.state === "pending");
    if (next) tab.current = next.path;
    this.renderReview(tab);
  }

  layout() { this.editor?.layout(); this.diffEditor?.layout(); }

  dispose() {
    this.editor?.dispose();
    this.diffEditor?.dispose();
    this.diffModels?.forEach((m) => m.dispose());
    this.tabs.filter((t) => t.kind === "file").forEach((t) => t.model.dispose());
  }
}

// ------------------------------------------------------------------ search across files (⌘⇧F)
function splitPath(p) {
  const i = p.lastIndexOf("/");
  return i < 0 ? ["", p] : [p.slice(0, i), p.slice(i + 1)];
}

function highlighted(text, positions, offset = 0) {
  // text with the characters at `positions` (indexes into the full string, shifted by offset) wrapped in <b>
  if (!positions?.length) return [text];
  const set = new Set(positions.map((x) => x - offset));
  const out = [];
  let run = "", inMatch = false;
  for (let i = 0; i < text.length; i++) {
    const m = set.has(i);
    if (m !== inMatch && run) { out.push(inMatch ? h("b", { text: run }) : run); run = ""; }
    inMatch = m;
    run += text[i];
  }
  if (run) out.push(inMatch ? h("b", { text: run }) : run);
  return out;
}

class SearchView {
  constructor(ws) {
    this.ws = ws;
    this.opts = { case: false, word: false, regex: false };
    this.seq = 0;
    this.data = null;
    this.collapsed = new Set();
    this.dismissed = new Set();      // "path" or "path:line:col"
    this.showReplace = false;
    this.showGlobs = false;
    const opt = (k, label, title) => h("button", { class: "sopt", "aria-pressed": "false", title, text: label, onclick: (e) => {
      this.opts[k] = !this.opts[k]; e.currentTarget.setAttribute("aria-pressed", String(this.opts[k])); this.run(); } });
    this.q = h("input", { type: "text", placeholder: "Search", "aria-label": "Search in project", spellcheck: "false" });
    this.r = h("input", { type: "text", placeholder: "Replace", "aria-label": "Replace with", spellcheck: "false" });
    this.inc = h("input", { type: "text", placeholder: "e.g. *.py, src", "aria-label": "Files to include" });
    this.exc = h("input", { type: "text", placeholder: "e.g. tests, *.md", "aria-label": "Files to exclude" });
    this.replaceToggle = h("button", { class: "icon-btn rtoggle", title: "Toggle replace (⌘⇧H)", text: "▸", "aria-expanded": "false",
      onclick: () => this.setReplace(!this.showReplace) });
    this.replaceAllBtn = h("button", { class: "btn small", text: "Replace all", title: "Replace every match shown below", onclick: () => this.replaceAll() });
    this.replaceRow = h("div", { class: "srow hidden" }, this.r, this.replaceAllBtn);
    this.globs = h("div", { class: "sglobs hidden" },
      h("label", { class: "field" }, "files to include", this.inc), h("label", { class: "field" }, "files to exclude", this.exc));
    this.status = h("div", { class: "sstatus" });
    this.list = h("div", { class: "sresults", role: "tree" });
    this.el = h("div", { class: "side-pane search-pane hidden" },
      h("div", { class: "search-form" },
        h("div", { class: "sgrid" }, this.replaceToggle,
          h("div", { class: "grow sfields" },
            h("div", { class: "srow sq" }, this.q,
              h("span", { class: "sopts" }, opt("case", "Aa", "Match case"), opt("word", "ab", "Whole word"), opt("regex", ".*", "Regular expression"))),
            this.replaceRow)),
        h("div", { class: "row sbar" }, this.status,
          h("button", { class: "icon-btn", title: "Files to include / exclude", "aria-label": "Files to include or exclude", onclick: () => { this.showGlobs = !this.showGlobs; this.globs.classList.toggle("hidden", !this.showGlobs); } }, ico("more")),
          h("button", { class: "icon-btn", title: "Collapse all", "aria-label": "Collapse all", onclick: () => { (this.data?.results || []).forEach((f) => this.collapsed.add(f.path)); this.render(); } }, ico("collapse"))),
        this.globs),
      this.list);
    const later = debounce(() => this.run(), 250);
    this.q.addEventListener("input", later);
    this.inc.addEventListener("input", later);
    this.exc.addEventListener("input", later);
    this.r.addEventListener("input", () => this.render());
    this.q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); this.run(); } if (e.key === "Escape") this.ws.editorArea.editor?.focus(); });
    this.r.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); this.replaceAll(); }
    });
    this.renderStatus("Type to search every file in the project.");
  }

  focus({ replace = false, text } = {}) {
    if (replace) this.setReplace(true);
    const sel = text ?? this.editorSelection();
    if (sel && sel !== this.q.value) { this.q.value = sel; this.run(); }
    (replace && this.q.value ? this.r : this.q).focus();
    (replace && this.q.value ? this.r : this.q).select();
  }

  editorSelection() {
    const ed = this.ws.editorArea.editor;
    if (!ed || this.ws.editorArea.active?.kind !== "file") return null;
    const sel = ed.getSelection();
    if (!sel || sel.isEmpty() || sel.startLineNumber !== sel.endLineNumber) return null;
    return ed.getModel().getValueInRange(sel);
  }

  setReplace(on) {
    this.showReplace = on;
    this.replaceRow.classList.toggle("hidden", !on);
    this.replaceToggle.textContent = on ? "▾" : "▸";
    this.replaceToggle.setAttribute("aria-expanded", String(on));
    this.render();
  }

  query() {
    return { query: this.q.value, ...this.opts, include: this.inc.value, exclude: this.exc.value };
  }

  stale() { if (this.data && !this.busy) this.refresh(); }
  refresh = debounce(() => this.run({ keepDismissed: true }), 500);

  async run({ keepDismissed = false } = {}) {
    const seq = ++this.seq;
    if (!keepDismissed) this.dismissed.clear();
    if (!this.q.value) { this.data = null; this.list.replaceChildren(); this.renderStatus("Type to search every file in the project."); return; }
    this.renderStatus(h("span", { class: "spinner" }));
    let r;
    try { r = await POST(`${this.ws.base}/search`, this.query()); } catch (e) {
      if (seq !== this.seq) return;
      this.data = null; this.list.replaceChildren(); this.renderStatus(e.message, true); return;
    }
    if (seq !== this.seq) return;
    this.data = r;
    this.render();
  }

  visible() {
    // results minus anything dismissed: [{path, matches}]
    if (!this.data) return [];
    return this.data.results.filter((f) => !this.dismissed.has(f.path))
      .map((f) => ({ path: f.path, matches: f.matches.filter((m) => !this.dismissed.has(`${f.path}:${m.line}:${m.col}`)) }))
      .filter((f) => f.matches.length);
  }

  renderStatus(content, bad = false) {
    this.status.className = `sstatus grow ${bad ? "bad" : ""}`;
    this.status.replaceChildren(content);
  }

  replacementFor(matchText) {
    const rep = this.r.value;
    if (!this.opts.regex) return rep;
    try { return matchText.replace(new RegExp(this.q.value, this.opts.case ? "" : "i"), rep); } catch (e) { return rep; }
  }

  render() {
    if (!this.data) return;
    const files = this.visible();
    const n = files.reduce((a, f) => a + f.matches.length, 0);
    this.renderStatus(n ? `${n} result${n === 1 ? "" : "s"} in ${files.length} file${files.length === 1 ? "" : "s"}${this.data.truncated ? " (stopped early - narrow the search)" : ""}`
      : "No results.");
    this.replaceAllBtn.disabled = !n;
    const replacing = this.showReplace;
    this.list.replaceChildren(...files.map((f) => {
      const [dir, base] = splitPath(f.path);
      const open = !this.collapsed.has(f.path);
      const head = h("div", { class: "sfile", role: "treeitem", "aria-expanded": String(open), title: f.path,
        onclick: () => { if (open) this.collapsed.add(f.path); else this.collapsed.delete(f.path); this.render(); } },
        h("span", { class: "twisty", text: open ? "▾" : "▸" }),
        h("span", { class: "sname", text: base }), h("span", { class: "sdir", text: dir }),
        h("span", { class: "scount", text: String(f.matches.length) }),
        h("span", { class: "sacts" },
          replacing ? h("button", { class: "icon-btn", title: "Replace all in this file", "aria-label": "Replace all in this file", onclick: (e) => { e.stopPropagation(); this.replaceSome(f.matches.map((m) => ({ path: f.path, ...m }))); } }, ico("swap", 14)) : null,
          h("button", { class: "icon-btn", title: "Dismiss", text: "✕", onclick: (e) => { e.stopPropagation(); this.dismissed.add(f.path); this.render(); } })));
      if (!open) return head;
      return h("div", { class: "sgroup" }, head, ...f.matches.map((m) => {
        const pre = m.text.slice(0, m.start), hit = m.text.slice(m.start, m.end), post = m.text.slice(m.end);
        return h("div", { class: "smatch", role: "treeitem", title: `${f.path}:${m.line}`, onclick: () => this.ws.openAt(f.path, m.line, m.ecol, m.elength) },
          h("span", { class: "sline", text: String(m.line) }),
          h("span", { class: "stext" }, m.clipped_left ? "…" : "", pre,
            replacing ? [h("del", { text: hit }), h("ins", { text: this.replacementFor(m.match) })] : h("mark", { text: hit }), post),
          h("span", { class: "sacts" },
            replacing ? h("button", { class: "icon-btn", title: "Replace this", "aria-label": "Replace this", onclick: (e) => { e.stopPropagation(); this.replaceSome([{ path: f.path, ...m }]); } }, ico("swap", 14)) : null,
            h("button", { class: "icon-btn", title: "Dismiss", text: "✕", onclick: (e) => { e.stopPropagation(); this.dismissed.add(`${f.path}:${m.line}:${m.col}`); this.render(); } })));
      }));
    }));
  }

  async replaceAll() {
    const files = this.visible();
    const all = files.flatMap((f) => f.matches.map((m) => ({ path: f.path, ...m })));
    if (!all.length) return;
    const to = this.r.value;
    const ok = await confirmBox(`Replace ${all.length} match${all.length === 1 ? "" : "es"} in ${files.length} file${files.length === 1 ? "" : "s"}?`,
      `"${this.q.value}" becomes "${to}"${to ? "" : " (deleted)"}. Grid takes a checkpoint first, so you can undo it from Checkpoints.`, "Replace all");
    if (ok) await this.replaceSome(all);
  }

  async replaceSome(items) {
    if (this.ws.running) { toast("Grid is working - wait for it or stop it first", "error"); return; }
    const paths = new Set(items.map((i) => i.path));
    if (!(await this.saveOpenFiles(paths))) return;
    this.busy = true;
    const r = await attempt(() => POST(`${this.ws.base}/replace`, { ...this.query(), replace: this.r.value,
      only: items.map((i) => ({ path: i.path, line: i.line, col: i.col, match: i.match })) }));
    if (!r) { this.busy = false; return; }
    let msg = `Replaced ${r.replacements} in ${r.files_changed.length} file${r.files_changed.length === 1 ? "" : "s"}`;
    if (r.skipped) msg += ` - skipped ${r.skipped} that changed since the search`;
    toast(msg);
    this.ws.refreshAll();
    await this.run({ keepDismissed: true });
    this.busy = false;
  }

  async saveOpenFiles(paths) {
    const ea = this.ws.editorArea;
    const dirty = ea.tabs.filter((t) => t.kind === "file" && t.dirty && paths.has(t.path));
    if (!dirty.length) return true;
    const names = dirty.map((t) => t.path).join(", ");
    if (!(await confirmBox("Save open files first?", `${names} ${dirty.length === 1 ? "has" : "have"} unsaved changes. Grid saves them, then replaces, so nothing gets lost.`, "Save and replace"))) return false;
    for (const t of dirty) await ea.save(t);
    return !dirty.some((t) => t.dirty);
  }
}

// ------------------------------------------------------------------ quick open (⌘P) and commands (⌘⇧P)
// Fuzzy match: query letters in order, rewarding runs and word starts. Returns null or {score, pos}.
function fuzzy(query, target) {
  if (!query) return { score: 0, pos: [] };
  const t = target.toLowerCase();
  const pos = [];
  let qi = 0, score = 0, prev = -2;
  for (let i = 0; i < t.length && qi < query.length; i++) {
    if (t[i] !== query[qi]) continue;
    let s = 1;
    if (i === prev + 1) s += 5;
    const before = target[i - 1];
    if (i === 0 || "/_-. ".includes(before)) s += 8;
    else if (target[i] !== t[i] && before === before.toLowerCase()) s += 6;   // camelCase hump
    if (prev >= 0) s -= Math.min(3, (i - prev - 1) * 0.2);
    score += s; pos.push(i); prev = i; qi++;
  }
  return qi < query.length ? null : { score, pos };
}

function rankFile(query, path) {
  const q = query.toLowerCase().replace(/\s+/g, "");
  const [dir, base] = splitPath(path);
  const off = dir ? dir.length + 1 : 0;
  const b = fuzzy(q, base);
  if (b) {
    let score = b.score * 2 + 20 - path.length * 0.05;
    if (base.toLowerCase() === q) score += 60;
    else if (base.toLowerCase().startsWith(q)) score += 30;
    return { score, pos: b.pos.map((x) => x + off) };
  }
  const f = fuzzy(q, path);
  return f ? { score: f.score - path.length * 0.05, pos: f.pos } : null;
}

const PALETTE_COMMANDS = [
  ["Go to File…", "quick-open", "⌘P"], ["Search in Project", "find-in-project", "⌘⇧F"], ["Replace in Project", "replace-in-project", "⌘⇧H"],
  ["Show Files", "show-files", "⌘⇧E"], ["Go to Line…", "go-to-line", "⌃G"], ["Save", "save", "⌘S"], ["Terminal", "terminal", "⌘J"],
  ["Switch Editor / Chat Layout", "toggle-layout", "⌘\\"], ["New Chat", "new-chat", "⌘⇧L"], ["Focus Chat", "focus-chat", "⌘⇧I"],
  ["Review Changes", "review-changes", ""], ["Checkpoints", "checkpoints", ""], ["New File…", "new-file", ""], ["New Folder…", "new-folder", ""],
  ["New Project…", "new-project", "⌘⇧N"], ["Open Folder…", "open-folder", "⌘O"], ["Plugins", "plugins", ""], ["Models", "models", ""],
  ["Schedules", "schedules", ""], ["Memory", "memory", ""], ["Settings", "settings", "⌘,"], ["Set Up a Model…", "setup", ""],
];

class Palette {
  static open(prefix = "") {
    if (Palette.current) { Palette.current.set(prefix); return Palette.current; }
    return new Palette(prefix);
  }

  constructor(prefix) {
    Palette.current = this;
    this.ws = S.view instanceof Workspace ? S.view : null;
    this.sel = 0;
    this.items = [];
    this.input = h("input", { type: "text", spellcheck: "false", "aria-label": "Go to file or run a command", "aria-controls": "palette-list", "aria-autocomplete": "list" });
    this.list = h("div", { class: "plist", role: "listbox", id: "palette-list" });
    this.hint = h("div", { class: "phint" });
    this.box = h("div", { class: "palette", role: "dialog", "aria-modal": "true", "aria-label": "Quick open" }, this.input, this.list, this.hint);
    this.back = h("div", { class: "palette-back", onmousedown: (e) => { if (e.target === this.back) this.close(); } }, this.box);
    this.prevFocus = document.activeElement;
    this.input.addEventListener("input", () => { this.sel = 0; this.update(); });
    this.input.addEventListener("keydown", (e) => this.onKey(e));
    $("#modal-root").append(this.back);
    this.set(prefix);
    if (this.ws) this.ws.fileIndex().then((r) => { this.files = r.files; this.truncated = r.truncated; this.update(); }).catch((e) => { this.error = e.message; this.update(); });
  }

  set(prefix) {
    const cur = this.input.value;
    if (!(prefix === "" && cur && !cur.startsWith(">") && !cur.startsWith(":"))) this.input.value = prefix;
    this.input.focus();
    this.input.setSelectionRange(prefix.length, this.input.value.length);
    this.sel = 0;
    this.update();
  }

  close({ restore = true } = {}) {
    this.back.remove();
    Palette.current = null;
    if (restore) this.prevFocus?.focus?.();
  }

  onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); this.close(); }
    else if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "n")) { e.preventDefault(); this.move(1); }
    else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "p")) { e.preventDefault(); this.move(-1); }
    else if (e.key === "Enter") { e.preventDefault(); this.pick(this.items[this.sel]); }
  }

  move(d) {
    if (!this.items.length) return;
    this.sel = (this.sel + d + this.items.length) % this.items.length;
    this.paint();
  }

  pick(item) {
    if (!item) return;
    this.close({ restore: false });
    item.run();
  }

  recent() {
    let rec = [];
    try { rec = JSON.parse(localStorage.getItem(`grid.recent.${this.ws.p.id}`) || "[]"); } catch (e) { /* ignore */ }
    const tabs = this.ws.editorArea.tabs.filter((t) => t.kind === "file").map((t) => t.path);
    return [...new Set([...rec, ...tabs])];
  }

  update() {
    const v = this.input.value;
    let items = [];
    let hint = "";
    if (v.startsWith(">")) {
      const q = v.slice(1).trim().toLowerCase();
      items = PALETTE_COMMANDS.map(([label, cmd, keys]) => ({ label, cmd, keys, m: fuzzy(q.replace(/\s+/g, ""), label) }))
        .filter((c) => c.m && (this.ws || !WS_ONLY.has(c.cmd)))
        .sort((a, b) => b.m.score - a.m.score)
        .map((c) => ({ kind: "cmd", label: c.label, pos: c.m.pos, keys: c.keys, run: () => menuCommand(c.cmd) }));
      hint = "Run a command. Delete the > to look for files.";
    } else if (v.startsWith(":")) {
      const n = parseInt(v.slice(1), 10);
      const t = this.ws?.editorArea.active;
      if (t?.kind === "file") {
        const max = t.model.getLineCount();
        items = Number.isFinite(n) ? [{ kind: "line", label: `Go to line ${Math.min(n, max)}`, run: () => this.ws.editorArea.reveal(n, 1) }] : [];
        hint = `Type a line number between 1 and ${max}.`;
      } else hint = "Open a file first, then type a line number.";
    } else if (!this.ws) {
      hint = "Open a project to look for files - or type > for commands.";
    } else if (this.error) {
      hint = this.error;
    } else if (!this.files) {
      hint = "Indexing files…";
    } else {
      const m = v.match(/^(.*?):(\d+)(?::(\d+))?$/);
      const q = (m ? m[1] : v).trim();
      const line = m ? parseInt(m[2], 10) : 0, col = m && m[3] ? parseInt(m[3], 10) : 1;
      let ranked;
      if (!q) {
        const rec = this.recent().filter((p) => this.files.includes(p));
        const rest = this.files.filter((p) => !rec.includes(p));
        ranked = [...rec.map((p) => ({ path: p, pos: [], recent: true })), ...rest.slice(0, 200 - rec.length).map((p) => ({ path: p, pos: [] }))];
      } else {
        ranked = [];
        for (const p of this.files) { const r = rankFile(q, p); if (r) ranked.push({ path: p, ...r }); }
        ranked.sort((a, b) => b.score - a.score);
        ranked = ranked.slice(0, 60);
      }
      items = ranked.map((r) => ({ kind: "file", path: r.path, pos: r.pos, recent: r.recent,
        run: () => (line ? this.ws.openAt(r.path, line, col) : this.ws.openPath(r.path)) }));
      hint = items.length ? "↑↓ to move · Enter to open · add :42 to jump to a line · > for commands" : `No file matches "${q}".`;
      if (this.truncated) hint += " (very big project: only the first 20,000 files are listed)";
    }
    this.items = items;
    this.hint.textContent = hint;
    this.paint();
  }

  paint() {
    this.list.replaceChildren(...this.items.map((it, i) => {
      let content;
      if (it.kind === "file") {
        const [dir, base] = splitPath(it.path);
        const off = dir ? dir.length + 1 : 0;
        content = [h("span", { class: "pname" }, highlighted(base, it.pos.filter((x) => x >= off), off)),
          h("span", { class: "pdir" }, highlighted(dir, it.pos.filter((x) => x < off))), it.recent ? h("span", { class: "prec", text: "recent" }) : null];
      } else {
        content = [h("span", { class: "pname" }, highlighted(it.label, it.pos || [])), it.keys ? h("kbd", { text: it.keys }) : null];
      }
      return h("div", { class: `pitem ${i === this.sel ? "sel" : ""}`, role: "option", "aria-selected": String(i === this.sel), id: `pi-${i}`,
        onmousemove: () => { if (this.sel !== i) { this.sel = i; this.paint(); } }, onclick: () => this.pick(it) }, content);
    }));
    this.input.setAttribute("aria-activedescendant", this.items.length ? `pi-${this.sel}` : "");
    this.list.children[this.sel]?.scrollIntoView({ block: "nearest" });
  }
}
Palette.current = null;
const WS_ONLY = new Set(["quick-open", "find-in-project", "replace-in-project", "show-files", "go-to-line", "save", "terminal", "new-chat", "focus-chat", "review-changes", "checkpoints", "new-file", "new-folder"]);

function rememberRecent(pid, path) {
  try {
    const key = `grid.recent.${pid}`;
    const rec = JSON.parse(localStorage.getItem(key) || "[]").filter((p) => p !== path);
    rec.unshift(path);
    localStorage.setItem(key, JSON.stringify(rec.slice(0, 30)));
  } catch (e) { /* ignore */ }
}

// ------------------------------------------------------------------ terminal
class TerminalPanel {
  constructor(ws) {
    this.ws = ws;
    this.el = h("div", { class: "xterm-host" });
    this.started = false;
  }
  async start() {
    if (this.started) { this.fit?.fit(); this.term?.focus(); return; }
    this.started = true;
    loadCss("/static/vendor/xterm/xterm.css");
    try {
      await loadScript("/static/vendor/xterm/xterm.js");
      await loadScript("/static/vendor/xterm/addon-fit.js");
    } catch (e) { this.el.append(h("div", { class: "empty", text: e.message })); return; }
    const theme = () => {
      const bg = `#${hex6(cssVar("--code-bg"))}`, fg = `#${hex6(cssVar("--text"))}`, a1 = `#${hex6(cssVar("--a1"))}`;
      return { background: bg, foreground: fg, cursor: a1, cursorAccent: bg, selectionBackground: `${a1}44`,
        green: "#4ade80", brightGreen: "#86efac", cyan: "#22d3ee", blue: "#60a5fa", red: "#f87171", yellow: "#fbbf24", magenta: "#c084fc" };
    };
    this.term = new window.Terminal({ fontFamily: "'JetBrains Mono Grid', ui-monospace, Menlo, monospace", fontSize: 12.5, lineHeight: 1.15, cursorBlink: true, theme: theme() });
    this.onTheme = () => { this.term.options.theme = theme(); };
    window.addEventListener("grid-theme", this.onTheme);
    this.fit = new window.FitAddon.FitAddon();
    this.term.loadAddon(this.fit);
    this.term.open(this.el);
    requestAnimationFrame(() => { try { this.fit.fit(); } catch (e) { /* hidden */ } this.connect(); });
    this.ro = new ResizeObserver(() => { try { this.fit.fit(); } catch (e) { /* hidden */ } this.sendSize(); });
    this.ro.observe(this.el);
    this.term.onData((d) => { this.ws.backboard?.dismiss({ auto: true }); if (this.sock?.readyState === 1) this.sock.send(JSON.stringify({ type: "input", data: d })); });
  }
  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.sock = new WebSocket(`${proto}://${location.host}${this.ws.base}/pty?cols=${this.term.cols}&rows=${this.term.rows}`);
    this.sock.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data);
        if (ev.type === "output") this.term.write(ev.data);
        else if (ev.type === "exit") this.term.write("\r\n[shell exited - click to restart]\r\n");
      } catch (e) { /* ignore */ }
    };
    this.sock.onclose = () => {
      if (this.disposed) return;
      const restart = () => { this.el.removeEventListener("click", restart); this.term.reset(); this.connect(); };
      this.el.addEventListener("click", restart);
    };
  }
  sendSize() {
    if (this.sock?.readyState === 1 && this.term) this.sock.send(JSON.stringify({ type: "resize", cols: this.term.cols, rows: this.term.rows }));
  }
  dispose() {
    this.disposed = true;
    if (this.onTheme) window.removeEventListener("grid-theme", this.onTheme);
    this.ro?.disconnect();
    try { this.sock?.close(); } catch (e) { /* ignore */ }
    this.term?.dispose();
  }
}

async function pollJob(jid, timeoutMs = 600000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const j = await attempt(() => GET(`/api/jobs/${jid}`));
    if (!j) return null;
    if (j.status !== "running") return j;
    await new Promise((r) => setTimeout(r, 700));
  }
  return { status: "error", error: "timed out" };
}

// ------------------------------------------------------------------ plugins
function pluginContents(p) {
  const parts = [];
  if (p.skills?.length) parts.push(h("div", {}, h("strong", { text: "Skills: " }), p.skills.join(", ")));
  if (p.commands?.length) parts.push(h("div", {}, h("strong", { text: "Commands: " }), ...p.commands.map((c, i) => [i ? ", " : "", h("code", { text: c.slash })])));
  for (const [name, what] of Object.entries(p.mcp || {})) parts.push(h("div", {}, h("strong", { text: "MCP server: " }), `${name} - ${what}`));
  if (p.has_hooks) parts.push(h("div", { class: "faint", text: "Has hooks (not run by Grid yet)" }));
  if (p.agents?.length) parts.push(h("div", { class: "faint", text: `Agent definitions: ${p.agents.join(", ")} (not used yet)` }));
  return h("div", { class: "meta" }, ...parts);
}

async function installFlow(source) {
  const prev = await attempt(() => POST("/api/plugins/preview", { source }));
  if (!prev) return false;
  const p = prev.plugin;
  const scope = h("select", {}, h("option", { value: "user", text: "Every project (user)" }),
    ...S.projects.map((pr) => h("option", { value: `project:${pr.id}`, text: `Only ${pr.name}` })));
  const ok = await modal({
    title: `Install ${p.name}?`,
    body: h("div", {}, h("p", { text: p.description || "" }), pluginContents(p),
      Object.keys(p.mcp || {}).length ? h("div", { class: "callout warn", style: "margin-top:10px", text: "MCP servers run programs on your computer when the agent uses them. Their tools are treated as YELLOW (asked first, unless you're in autonomous mode)." }) : null,
      h("label", { class: "field", style: "margin-top:12px" }, "Install for", scope)),
    buttons: [{ label: "Cancel", value: false }, {
      label: "Install", kind: "primary", onClick: async () => {
        const [sc, pid] = scope.value.split(":");
        const q = pid ? `?project=${pid}` : "";
        return !!(await attempt(() => POST(`/api/plugins/install${q}`, { source, scope: sc })));
      },
    }],
  });
  if (ok) toast(`${p.name} installed - available in new chats`);
  return ok;
}

class PluginsView {
  constructor() { this.tab = "installed"; }
  async mount(main) {
    this.page = h("div", { class: "page" });
    main.append(this.page);
    await this.render();
  }
  async render() {
    const tabs = h("div", { class: "tabs" }, ...[["installed", "Installed"], ["catalog", "Catalog"], ["source", "Install from a folder or git"]]
      .map(([k, l]) => h("button", { class: this.tab === k ? "active" : "", text: l, onclick: () => { this.tab = k; this.render(); } })));
    const body = h("div");
    this.page.replaceChildren(h("h1", { text: "Plugins" }),
      h("p", { class: "lede", text: "Plugins add skills (know-how the agent pulls in), slash commands (/plugin:command) and MCP servers (external tools). Use a standard plugin folder to bring skills, commands, and tools into your workspace." }),
      tabs, body);
    if (this.tab === "installed") {
      const r = await attempt(() => GET("/api/plugins"));
      const all = r ? [...r.plugins] : [];
      for (const pr of S.projects) {
        const pp = await attempt(() => GET(`/api/plugins?project=${pr.id}`));
        for (const p of pp?.plugins || []) if (p.scope === "project") all.push({ ...p, projectName: pr.name, projectId: pr.id });
      }
      if (!all.length) { body.append(h("div", { class: "empty" }, "No plugins yet. ", h("a", { href: "#/plugins", onclick: (e) => { e.preventDefault(); this.tab = "catalog"; this.render(); }, text: "Browse the catalog" }))); return; }
      body.append(h("div", { class: "cards" }, ...all.map((p) => {
        const q = p.projectId ? `?project=${p.projectId}` : "";
        const toggle = h("button", { class: "toggle", "aria-pressed": String(p.enabled), text: p.enabled ? "On" : "Off",
          onclick: async () => { if (await attempt(() => POST(`/api/plugins/${encodeURIComponent(p.name)}/enable${q}`, { enabled: !p.enabled, scope: p.scope }))) this.render(); } });
        return h("div", { class: "card" },
          h("h3", {}, p.name, h("span", { class: "chip", text: p.version }), h("span", { class: "chip accent", text: p.projectName ? `project: ${p.projectName}` : "all projects" })),
          h("div", { class: "meta", text: p.description }), pluginContents(p),
          h("div", { class: "actions" }, toggle,
            h("button", { class: "btn small danger", text: "Remove", onclick: async () => {
              if (await confirmBox(`Remove ${p.name}?`, "Its files are deleted from Grid's plugin folder.", "Remove", true) &&
                  await attempt(() => DEL(`/api/plugins/${encodeURIComponent(p.name)}${q ? q + "&" : "?"}scope=${p.scope}`))) this.render();
            } })));
      })));
    } else if (this.tab === "catalog") {
      const r = await attempt(() => GET("/api/plugins/catalog"));
      body.append(h("div", { class: "cards" }, ...(r?.plugins || []).map((p) => h("div", { class: "card" },
        h("h3", {}, p.name, h("span", { class: "chip", text: p.version }), p.installed ? h("span", { class: "chip green", text: "installed" }) : null),
        h("div", { class: "meta", text: p.description }), pluginContents(p),
        h("div", { class: "actions" }, h("button", { class: "btn small primary", text: p.installed ? "Install again" : "Install",
          onclick: async () => { if (await installFlow(p.source)) this.render(); } }))))));
    } else {
      const src = h("input", { type: "text", placeholder: "/path/to/plugin  or  github:owner/repo  or  https://...git" });
      body.append(h("div", { class: "panel" }, h("label", { class: "field" }, "Plugin source", src),
        h("p", { class: "muted", text: "A folder with .plugin/plugin.json plus skills/, commands/ and/or .mcp.json. You'll see exactly what it contains before anything is installed." }),
        h("button", { class: "btn primary", text: "Preview & install", onclick: async () => { if (src.value.trim() && await installFlow(src.value.trim())) { this.tab = "installed"; this.render(); } } })));
    }
  }
}

// ------------------------------------------------------------------ models
class ModelsView {
  async mount(main) {
    this.page = h("div", { class: "page" });
    main.append(this.page);
    await this.render();
  }
  async render() {
    const r = await attempt(() => GET("/api/models"));
    if (!r) return;
    const rows = r.profiles.map((p) => {
      const c = p.compat;
      const testBtn = h("button", { class: "btn small", text: "Test", onclick: () => this.test(p.name, testBtn) });
      return h("tr", {},
        h("td", {}, h("strong", { text: p.name }), r.default === p.name ? h("span", { class: "chip accent", style: "margin-left:6px", text: "default" }) : null),
        h("td", {}, h("div", { class: "mono", text: p.model }), p.base_url ? h("div", { class: "faint mono", text: p.base_url }) : null),
        h("td", {}, h("span", { class: `chip ${p.local ? "accent" : ""}`, text: p.local ? "local" : "cloud" }),
          p.api_key_env ? h("div", { class: "faint mono", text: `$${p.api_key_env}` }) : null,
          p.native_tool_calling ? null : h("div", { class: "faint", text: "prompted tools" }),
          p.model.startsWith("ollama") ? h("label", { class: "check", style: "margin-top:6px;font-size:12px", title: "Lets the model reason at length before each step. Much slower on a laptop (minutes per step); a little more careful." },
            h("input", { type: "checkbox", checked: !!p.think, onchange: async (e) => {
              const on = e.target.checked;
              if (!(await attempt(() => POST(`/api/models/${encodeURIComponent(p.name)}/think`, { on }), on ? "Thinking on - slower, applies to new chats" : "Thinking off - faster, applies to new chats"))) e.target.checked = !on;
            } }), "Think before each step (slower)") : null),
        h("td", {}, c ? h("span", { class: `chip ${c.verdict}`, title: c.tested_at, text: c.verdict }) : h("span", { class: "faint", text: "untested" })),
        h("td", {}, h("div", { class: "row" }, testBtn,
          r.default === p.name ? null : h("button", { class: "btn small", text: "Make default", onclick: async () => { if (await attempt(() => POST(`/api/models/${encodeURIComponent(p.name)}/default`))) this.render(); } }),
          h("button", { class: "btn small danger", text: "Remove", onclick: async () => { if (await confirmBox(`Remove ${p.name}?`, "Only the saved profile is removed.", "Remove", true) && await attempt(() => DEL(`/api/models/${encodeURIComponent(p.name)}`))) this.render(); } }))));
    });
    const f = {
      name: h("input", { type: "text", placeholder: "work" }),
      model: h("input", { type: "text", placeholder: "provider/model-id  ·  ollama/model-name" }),
      base_url: h("input", { type: "text", placeholder: "http://localhost:11434 (local/self-hosted only)" }),
      api_key_env: h("input", { type: "text", placeholder: "ANTHROPIC_API_KEY (the variable NAME)" }),
      prompted: h("input", { type: "checkbox" }), def: h("input", { type: "checkbox" }),
    };
    this.page.replaceChildren(
      h("h1", { text: "Models" }),
      h("p", { class: "lede", text: "Bring your own model: any LiteLLM model, cloud or local. Keys stay in your environment - a profile only stores the name of the variable that holds the key." }),
      h("div", { class: "callout info" }, "Now using ", h("strong", { class: "mono", text: r.current.model }), ` (${r.current.source})`),
      h("h2", { text: "Saved models" }),
      r.profiles.length ? h("table", { class: "list" }, h("thead", {}, h("tr", {}, ...["Name", "Model", "Where", "Works with Grid?", ""].map((t) => h("th", { text: t })))), h("tbody", {}, ...rows))
        : h("div", { class: "empty", text: "No saved models. Add a provider and model to get started." }),
      this.result = h("div"),
      this.keyHints = h("div"),
      h("h2", { text: "Add a model" }),
      h("div", { class: "panel" }, h("div", { class: "form-grid" },
        h("label", { class: "field" }, "Name", f.name), h("label", { class: "field" }, "Model id", f.model),
        h("label", { class: "field" }, "Server URL", f.base_url), h("label", { class: "field" }, "Key variable", f.api_key_env)),
        h("div", { class: "row", style: "margin-top:10px" },
          h("label", { class: "check" }, f.prompted, "No native tool calling (describe tools in the prompt)"),
          h("label", { class: "check" }, f.def, "Make default"), h("span", { class: "grow" }),
          h("button", { class: "btn primary", text: "Save model", onclick: async () => {
            const ok = await attempt(() => POST("/api/models", { name: f.name.value.trim(), model: f.model.value.trim(), base_url: f.base_url.value.trim() || null,
              api_key_env: f.api_key_env.value.trim() || null, prompted_tools: f.prompted.checked, default: f.def.checked }), "Saved - run Test to check it works with Grid");
            if (ok) this.render();
          } }))));
    // A key saved in Settings doesn't pick a model by itself: point out keys no model uses yet.
    const PROVIDERS = { ANTHROPIC_API_KEY: ["anthropic", "Anthropic"], OPENAI_API_KEY: ["openai", "OpenAI"], GEMINI_API_KEY: ["gemini", "Gemini"],
      DEEPSEEK_API_KEY: ["deepseek", "DeepSeek"], OPENROUTER_API_KEY: ["openrouter", "OpenRouter"], GROQ_API_KEY: ["groq", "Groq"] };
    try {
      const saved = (await window.gridDesktop?.keys?.list?.()) || [];
      const unused = saved.map((k) => k.name).filter((n) => PROVIDERS[n] && !r.profiles.some((p) => p.api_key_env === n));
      this.keyHints.replaceChildren(...unused.map((n) => {
        const [prefix, label] = PROVIDERS[n];
        return h("div", { class: "callout info", style: "margin:14px 0 0;display:flex;align-items:center;gap:12px" },
          h("span", { class: "grow", text: `Your ${label} key is saved, but no model uses it yet. Add one below: the model id starts with ${prefix}/ (check ${label}'s site for current model names).` }),
          h("button", { class: "btn small primary", text: `Set up ${label}`, onclick: () => {
            f.name.value = f.name.value || prefix; f.model.value = `${prefix}/`; f.api_key_env.value = n; f.def.checked = true;
            f.model.focus(); f.model.setSelectionRange(f.model.value.length, f.model.value.length);
          } }));
      }));
    } catch (e) { /* not in the desktop app: keys come from the environment */ }
  }
  async test(name, btn) {
    btn.disabled = true;
    btn.replaceChildren(h("span", { class: "spinner" }), " testing");
    const r = await attempt(() => POST(`/api/models/${encodeURIComponent(name)}/test`));
    const job = r ? await pollJob(r.job) : null;
    if (job?.status === "done") {
      await this.render();
      this.result.replaceChildren(h("div", { class: `callout ${job.result.verdict === "ready" ? "good" : job.result.verdict === "usable" ? "warn" : "bad"}`, style: "margin-top:12px" },
        h("h4", { text: `${name}: ${job.result.verdict.toUpperCase()}` }), h("pre", { class: "mono", text: job.result.report })));
    } else {
      if (job) toast(job.error || "test failed", "error");
      btn.disabled = false;
      btn.textContent = "Test";
    }
  }
}

// ------------------------------------------------------------------ schedules
const CRON_PRESETS = [["@hourly", "Every hour"], ["0 9 * * *", "Every day at 9:00"], ["0 9 * * 1-5", "Weekdays at 9:00"],
  ["0 9 * * 1", "Mondays at 9:00"], ["0 2 * * *", "Every night at 2:00"], ["custom", "Custom (cron)"]];

class SchedulesView {
  async mount(main) {
    this.page = h("div", { class: "page" });
    main.append(this.page);
    await this.render();
  }
  async render() {
    const [r, models, info] = await Promise.all([attempt(() => GET("/api/schedules")), attempt(() => GET("/api/models")), attempt(() => GET("/api/autonomy"))]);
    if (!r) return;
    const projName = (path) => (S.projects.find((p) => p.path === path) || {}).name || path.replace(S.home, "~");
    const cards = r.schedules.map((s) => {
      const runBtn = h("button", { class: "btn small", text: "Run now", onclick: async () => {
        runBtn.disabled = true; runBtn.replaceChildren(h("span", { class: "spinner" }), " running");
        const j = await attempt(() => POST(`/api/schedules/${s.id}/run`));
        const res = j ? await pollJob(j.job) : null;
        if (res?.status === "done") toast(`${s.name}: ${res.result.outcome}`);
        else if (res) toast(res.error || "run failed", "error");
        this.render();
      } });
      return h("div", { class: "card" },
        h("h3", {}, s.name, h("span", { class: `chip ${s.enabled ? "green" : ""}`, text: s.enabled ? "on" : "off" }), h("span", { class: `chip ${s.mode === "autonomous" ? "yellow" : ""}`, text: s.mode })),
        h("div", { class: "meta" }, h("code", { text: s.cron_text }), ` · ${projName(s.project)}`),
        h("div", { text: s.prompt }),
        h("div", { class: "meta" }, `Next: ${s.enabled ? fmtTime(s.next_run) : "-"} · Last: ${fmtTime(s.last_run)} `,
          s.last_outcome ? h("span", { class: `chip ${s.last_outcome}`, text: s.last_outcome }) : null),
        s.allow?.length ? h("div", { class: "meta", text: `Pre-approved RED: ${s.allow.join(", ")}` }) : null,
        h("div", { class: "actions" }, runBtn,
          h("button", { class: "btn small", text: s.enabled ? "Pause" : "Resume", onclick: async () => { if (await attempt(() => POST(`/api/schedules/${s.id}/enable`, { enabled: !s.enabled }))) this.render(); } }),
          h("button", { class: "btn small", text: "Runs & logs", onclick: () => this.logs(s) }),
          h("button", { class: "btn small danger", text: "Delete", onclick: async () => { if (await confirmBox(`Delete ${s.name}?`, "The schedule and its run history are removed.", "Delete", true) && await attempt(() => DEL(`/api/schedules/${s.id}`))) this.render(); } })));
    });
    const f = {
      name: h("input", { type: "text", placeholder: "nightly-tests" }),
      project: h("select", {}, ...S.projects.map((p) => h("option", { value: p.id, text: p.name }))),
      prompt: h("textarea", { rows: 3, placeholder: "Run the test suite. If anything fails, find the cause and fix it." }),
      preset: h("select", {}, ...CRON_PRESETS.map(([v, l]) => h("option", { value: v, text: l }))),
      cron: h("input", { type: "text", placeholder: "minute hour day month weekday, e.g. 30 8 * * 1-5", class: "hidden" }),
      mode: h("select", {}, h("option", { value: "headless", text: "Unattended - refuse anything risky" }), h("option", { value: "autonomous", text: "Autonomous - run, RED only if allowed below" })),
      model: h("select", {}, h("option", { value: "", text: "Default model" }), ...(models?.profiles || []).map((p) => h("option", { value: p.name, text: p.name }))),
    };
    const allowBoxes = Object.entries(info?.allowable || {}).map(([k, d]) => { const cb = h("input", { type: "checkbox", value: k }); return { k, cb, el: h("label", { class: "check", title: d }, cb, h("code", { text: k })) }; });
    const allowRow = h("div", { class: "row hidden" }, h("span", { class: "muted", text: "Pre-approve:" }), ...allowBoxes.map((b) => b.el));
    f.preset.addEventListener("change", () => f.cron.classList.toggle("hidden", f.preset.value !== "custom"));
    f.mode.addEventListener("change", () => allowRow.classList.toggle("hidden", f.mode.value !== "autonomous"));
    this.page.replaceChildren(
      h("h1", { text: "Schedules" }),
      h("p", { class: "lede", text: "Recurring tasks that run on their own. They run while the Grid app is open (or from your system scheduler with `grid schedule run-due`). Runs missed while Grid was closed are skipped. Every run still has to pass a real check to count as verified." }),
      r.schedules.length ? h("div", { class: "cards" }, ...cards) : h("div", { class: "empty", text: "No schedules yet." }),
      h("h2", { text: "New schedule" }),
      S.projects.length ? h("div", { class: "panel" },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Name", f.name), h("label", { class: "field" }, "Project", f.project),
          h("label", { class: "field" }, "When", f.preset, f.cron), h("label", { class: "field" }, "Mode", f.mode), h("label", { class: "field" }, "Model", f.model)),
        h("label", { class: "field", style: "margin-top:12px" }, "Task", f.prompt), allowRow,
        h("div", { class: "row", style: "margin-top:12px;justify-content:flex-end" }, h("button", { class: "btn primary", text: "Create schedule", onclick: async () => {
          const cron = f.preset.value === "custom" ? f.cron.value.trim() : f.preset.value;
          const ok = await attempt(() => POST("/api/schedules", { name: f.name.value.trim(), project: f.project.value, prompt: f.prompt.value.trim(), cron,
            mode: f.mode.value, allow: f.mode.value === "autonomous" ? allowBoxes.filter((b) => b.cb.checked).map((b) => b.k) : [], model_profile: f.model.value || null }), "Schedule created");
          if (ok) this.render();
        } })))
        : h("div", { class: "empty", text: "Create or open a project first." }));
  }
  async logs(s) {
    const r = await attempt(() => GET(`/api/schedules/${s.id}/runs`));
    if (!r) return;
    const pre = h("pre", { class: "mono", style: "max-height:50vh;overflow:auto;background:var(--code-bg);padding:10px;border-radius:8px" });
    const show = async (log) => { const l = await attempt(() => GET(`/api/schedules/${s.id}/log?log=${encodeURIComponent(log || "")}`)); pre.textContent = l?.text || "(empty)"; };
    const list = h("div", { class: "dirlist" }, ...(r.runs.length ? r.runs.map((run) => h("div", { onclick: () => show(run.log) }, fmtTime(run.started), " ", h("span", { class: `chip ${run.outcome}`, text: run.outcome })))
      : [h("div", { class: "faint", text: "No runs yet." })]));
    if (r.runs.length) show(r.runs[0].log);
    await modal({ title: `${s.name} - runs`, wide: true, body: h("div", {}, list, h("div", { style: "height:10px" }), pre), buttons: [{ label: "Close", kind: "primary" }] });
  }
}

// ------------------------------------------------------------------ memory
class MemoryView {
  async mount(main) {
    this.page = h("div", { class: "page" });
    main.append(this.page);
    this.pid = currentProjectId() || S.projects[0]?.id;
    this.tab = "you";
    await this.render();
  }

  async render() {
    const tabs = h("div", { class: "tabs" }, ...[["you", "About you"], ["project", "Project notes"], ["chats", "Past chats"], ["lessons", "Lessons"]]
      .map(([k, label]) => h("button", { class: this.tab === k ? "active" : "", text: label, onclick: () => { this.tab = k; this.render(); } })));
    const projSel = S.projects.length ? h("select", { style: "width:auto", "aria-label": "Project", onchange: () => { this.pid = projSel.value; this.render(); } },
      ...S.projects.map((p) => h("option", { value: p.id, text: p.name, selected: p.id === this.pid }))) : null;
    const body = h("div");
    this.page.replaceChildren(h("h1", { text: "Memory" }),
      h("p", { class: "lede", text: "What Grid remembers between chats. It reads this at the start of every chat and searches it when you mention earlier work. Edit or delete anything - Grid never stores passwords or keys." }),
      tabs, body);
    if (this.tab === "you" || this.tab === "project") {
      if (this.tab === "project" && !this.pid) { body.append(h("div", { class: "empty", text: "No projects yet." })); return; }
      const r = await attempt(() => GET(`/api/memory/facts${this.pid ? `?project=${this.pid}` : ""}`));
      if (!r) return;
      const facts = this.tab === "you" ? r.user : r.project;
      const input = h("input", { type: "text", placeholder: this.tab === "you" ? "e.g. I'm learning Python for data analysis" : "e.g. We use pytest and black here", "aria-label": "New memory" });
      const add = async () => {
        if (!input.value.trim()) return;
        if (await attempt(() => POST("/api/memory/facts", { text: input.value.trim(), scope: this.tab === "you" ? "user" : "project", project: this.tab === "project" ? this.pid : null }), "Saved")) this.render();
      };
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      body.append(
        this.tab === "project" ? h("div", { class: "row", style: "margin-bottom:12px" }, h("span", { class: "muted", text: "Project" }), projSel) : null,
        h("div", { class: "row", style: "margin-bottom:12px;flex-wrap:nowrap" }, input, h("button", { class: "btn primary", text: "Remember", onclick: add })),
        facts.length ? h("div", { class: "fact-list" }, ...facts.slice().reverse().map((f) => {
          const text = h("span", { class: "grow", text: f.text });
          return h("div", { class: "fact" }, text,
            h("span", { class: "faint", style: "font-size:12px;white-space:nowrap", text: `${f.source === "user" ? "you added" : "Grid saved"} · ${fmtTime(f.created)}` }),
            h("button", { class: "icon-btn", title: "Edit", "aria-label": "Edit", onclick: async () => {
              const t = await askText("Edit memory", "What Grid should remember", f.text, "Save");
              if (t && await attempt(() => PUT(`/api/memory/facts/${f.id}`, { text: t }))) this.render();
            } }, ico("pencil")),
            h("button", { class: "icon-btn", title: "Forget", "aria-label": "Forget", onclick: async () => { if (await attempt(() => DEL(`/api/memory/facts/${f.id}`))) this.render(); } }, ico("trash")));
        })) : h("div", { class: "empty", text: this.tab === "you" ? "Nothing yet. Tell Grid about yourself in a chat (\"I'm new to coding and want to build websites\") or add it here." : "No notes for this project yet." }));
    } else if (this.tab === "chats") {
      const q = h("input", { type: "text", placeholder: "Search past chats (e.g. login bug)", "aria-label": "Search past chats" });
      const every = h("input", { type: "checkbox" });
      const results = h("div");
      const run = async () => {
        if (!q.value.trim()) {
          if (!this.pid) { results.replaceChildren(); return; }
          const r = await attempt(() => GET(`/api/projects/${this.pid}/chats`));
          results.replaceChildren(...(r?.chats.length ? r.chats.map((c) => h("div", { class: "fact" }, h("div", { class: "grow" }, h("strong", { text: c.title }), c.last ? h("div", { class: "muted chat-last", text: c.last }) : null),
            h("span", { class: "faint", style: "font-size:12px;white-space:nowrap", text: `${fmtTime(c.updated)} · ${c.turns}` }),
            h("button", { class: "btn small", text: "Open", onclick: () => { location.hash = `#/p/${this.pid}`; setTimeout(() => attempt(() => POST(`/api/projects/${this.pid}/chats/${c.id}/open`)), 400); } })))
            : [h("div", { class: "empty", text: "No chats yet in this project." })]));
          return;
        }
        const r = await attempt(() => GET(`/api/memory/search?q=${encodeURIComponent(q.value)}${this.pid ? `&project=${this.pid}` : ""}${every.checked ? "&everywhere=1" : ""}`));
        results.replaceChildren(...(r?.hits.length ? r.hits.map((hh) => h("div", { class: "fact" }, h("pre", { class: "hit", text: hh.text })))
          : [h("div", { class: "empty", text: "Nothing matches." })]));
      };
      q.addEventListener("input", debounce(run, 300));
      every.addEventListener("change", run);
      body.append(h("div", { class: "row", style: "margin-bottom:12px" }, projSel, q, h("label", { class: "check" }, every, "All projects")), results);
      run();
    } else {
      if (!this.pid) { body.append(h("div", { class: "empty", text: "No projects yet." })); return; }
      const r = await attempt(() => GET(`/api/projects/${this.pid}/memory`));
      const eps = r?.episodes || [];
      body.append(h("div", { class: "row", style: "margin-bottom:12px" }, h("span", { class: "muted", text: "Project" }), projSel,
        h("span", { class: "faint", text: "Mistakes Grid learned from (failed checks, regressions)." })),
      eps.length ? h("table", { class: "list" }, h("thead", {}, h("tr", {}, ...["Kind", "What happened", "Lesson", "When", ""].map((t) => h("th", { text: t })))),
        h("tbody", {}, ...eps.slice().reverse().map((e) => h("tr", {}, h("td", {}, h("span", { class: `chip ${e.kind === "regression" ? "yellow" : "red"}`, text: e.kind })),
          h("td", { text: e.error_signature }), h("td", { style: "max-width:520px" }, h("div", { text: e.lesson })), h("td", { class: "faint", text: fmtTime(e.timestamp) }),
          h("td", {}, h("button", { class: "btn small danger", text: "Forget", onclick: async () => { if (await attempt(() => DEL(`/api/projects/${this.pid}/memory/${e.index}`))) this.render(); } }))))))
        : h("div", { class: "empty", text: "No lessons for this project yet." }));
    }
  }
}

// ------------------------------------------------------------------ settings
class SettingsView {
  async mount(main) {
    const s = await attempt(() => GET("/api/settings"));
    if (!s) return;
    const f = {
      depth: h("select", {}, ...["beginner", "intermediate", "pro", "off"].map((d) => h("option", { value: d, text: d, selected: d === s.depth }))),
      step_budget: h("input", { type: "number", min: "1", value: s.step_budget }),
      confidence_threshold: h("input", { type: "number", min: "0", max: "1", step: "0.05", value: s.confidence_threshold }),
      projects_root: h("input", { type: "text", value: s.projects_root }),
      theme: h("select", {}, ...[["dark", "Midnight (dark)"], ["light", "Daylight (light)"], ["system", "Match my Mac"]].map(([t, label]) => h("option", { value: t, text: label, selected: t === s.theme }))),
      verify: h("input", { type: "checkbox", checked: s.verify }),
      plan_first: h("input", { type: "checkbox", checked: s.plan_first }),
      self_review: h("input", { type: "checkbox", checked: s.self_review !== false }),
      autonomous_max_steps: h("input", { type: "number", min: "10", max: "5000", step: "10", value: s.autonomous_max_steps ?? 300 }),
    };
    main.append(h("div", { class: "page" },
      h("h1", { text: "Settings" }),
      h("p", { class: "lede", text: "Defaults for new chats. A running chat keeps the settings it started with." }),
      h("div", { class: "panel" }, h("div", { class: "form-grid" },
        h("label", { class: "field" }, "Teaching depth", f.depth),
        h("label", { class: "field" }, "Check in every N steps", f.step_budget),
        h("label", { class: "field" }, "Ask first below this confidence", f.confidence_threshold),
        h("label", { class: "field" }, "Autonomous mode pauses after N steps", f.autonomous_max_steps),
        h("label", { class: "field" }, "New projects go in", f.projects_root),
        h("label", { class: "field" }, "Theme", f.theme)),
        h("div", { class: "field", style: "margin-top:14px" }, h("span", { text: "Accent" }), accentPicker()),
        h("div", { class: "row", style: "margin-top:12px" },
          h("label", { class: "check" }, f.verify, "Verify before accepting \"done\" (strongly recommended)"),
          h("label", { class: "check" }, f.plan_first, "Plan first by default"),
          h("label", { class: "check", title: "Before 'done', the agent re-opens what it changed and checks names, call sites, docs and leftovers agree. Adds a few steps." },
            f.self_review, "Review its own changes for consistency before \"done\"")),
        h("div", { class: "row", style: "margin-top:14px;justify-content:flex-end" }, h("button", { class: "btn primary", text: "Save", onclick: async () => {
          const res = await attempt(() => PUT("/api/settings", { depth: f.depth.value, step_budget: Number(f.step_budget.value), confidence_threshold: Number(f.confidence_threshold.value),
            projects_root: f.projects_root.value.trim(), theme: f.theme.value, verify: f.verify.checked, plan_first: f.plan_first.checked,
            self_review: f.self_review.checked, autonomous_max_steps: Number(f.autonomous_max_steps.value) }), "Settings saved");
          if (res) { S.settings = res; applyTheme(); }
        } }))),
      macAccessPanel(),
      browserPanel(),
      macControlPanel(),
      h("h2", { text: "Model" }),
      h("div", { class: "panel row" }, h("span", { class: "grow muted", text: "Pick the AI model Grid uses, add its key and check it works." }),
        h("button", { class: "btn", text: "Run model setup", onclick: () => setupWizard({ force: true }) })),
      personalityPanel(),
      window.gridDesktop?.keys ? apiKeysPanel() : null,
      h("h2", { text: "Safety" }),
      h("div", { class: "panel muted" },
        h("p", { style: "margin-top:0", text: "A high-risk (RED) action never runs without your approval - at the prompt, or pre-approved by category when you turn on autonomous mode. Root access, credentials, writes outside the project, disk and system changes can never be pre-approved." }),
        h("p", { style: "margin-bottom:0", text: "Grid only listens on this computer (127.0.0.1) and only for the browser that opened its sign-in link." }))));
  }
}

function apiKeysPanel() {
  const KNOWN = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY",
    "BRAVE_API_KEY", "TAVILY_API_KEY"];
  const box = h("div", { class: "panel" });
  const render = async () => {
    const stored = await window.gridDesktop.keys.list();
    const names = [...new Set([...KNOWN, ...stored.map((k) => k.name)])];
    const rows = names.map((name) => {
      const has = stored.some((k) => k.name === name);
      const input = h("input", { type: "password", placeholder: has ? "saved - type to replace" : "paste key", autocomplete: "off", "aria-label": name });
      return h("tr", {}, h("td", { class: "mono", text: name }), h("td", {}, h("span", { class: `chip ${has ? "green" : ""}`, text: has ? "saved" : "not set" })),
        h("td", { style: "width:45%" }, input),
        h("td", {}, h("div", { class: "row" },
          h("button", { class: "btn small primary", text: "Save", onclick: async () => {
            if (!input.value.trim()) return;
            await window.gridDesktop.keys.set(name, input.value.trim());
            toast(`${name} saved - restarting Grid's engine. Next: add a model that uses it in Models.`);
          } }),
          has ? h("button", { class: "btn small danger", text: "Remove", onclick: async () => { await window.gridDesktop.keys.clear(name); toast(`${name} removed`); } }) : null)));
    });
    const custom = h("input", { type: "text", placeholder: "OTHER_API_KEY" });
    box.replaceChildren(
      h("p", { class: "muted", style: "margin-top:0", text: "Stored encrypted with your macOS Keychain and handed only to Grid's engine. Grid restarts the engine when keys change. Web search works without a key; a Brave or Tavily key makes it steadier." }),
      h("table", { class: "list" }, h("tbody", {}, ...rows)),
      h("div", { class: "row", style: "margin-top:10px" }, custom, h("button", { class: "btn small", text: "Add another key name", onclick: async () => {
        const n = custom.value.trim().toUpperCase();
        if (!/^[A-Z_][A-Z0-9_]*$/.test(n)) { toast("Use a variable name like MY_API_KEY", "error"); return; }
        KNOWN.push(n); render();
      } })));
  };
  render();
  return h("div", {}, h("h2", { text: "API keys" }), box);
}

// ------------------------------------------------------------------ first-run setup (model + key + check)
async function loadSetup() {
  try { S.setup = await GET("/api/setup"); } catch (e) { S.setup = null; }
  return S.setup;
}

function extLink(href, text) {
  return h("a", { href, target: "_blank", rel: "noopener noreferrer", text });
}

async function setupWizard({ force = false } = {}) {
  const st = await loadSetup();
  if (!st || (!force && (st.ready || st.done))) return;
  if (document.querySelector(".setup")) return;
  const body = h("div", { class: "setup" });
  let close = null;
  const owns = (p, m) => [p.prefix, ...(p.also || [])].some((x) => String(m || "").startsWith(x));
  let picked = st.providers.find((p) => st.chosen && owns(p, st.model)) || st.providers.find((p) => p.recommended);

  const stepper = (n) => h("div", { class: "steps" }, ...["Choose a model", "Add your key", "Check it works"].map((label, i) =>
    h("span", { class: `step ${i + 1 === n ? "on" : i + 1 < n ? "done" : ""}`, text: `${i + 1}. ${label}` })));

  const finish = async () => {
    await attempt(() => POST("/api/setup/done"));
    await loadSetup();
    close?.(true);
    if (S.view instanceof Workspace && S.view.hasWelcome) S.view.welcome();
  };

  const stepChoose = () => {
    const cards = st.providers.map((p) => h("button", { class: `pcard ${p === picked ? "on" : ""}`, "aria-pressed": String(p === picked),
      onclick: () => { picked = p; stepChoose(); } },
      h("div", { class: "row" }, h("strong", { text: p.label }), p.recommended ? h("span", { class: "chip accent", text: "recommended" }) : null,
        p.local ? h("span", { class: "chip", text: "free · private" }) : null),
      h("div", { class: "muted", text: p.blurb })));
    const model = h("input", { type: "text", value: st.chosen && owns(picked, st.model) ? st.model : picked.model,
      placeholder: `${picked.prefix}<model id>`, "aria-label": "Model id", spellcheck: "false" });
    const extra = h("div", { class: "setup-extra" });
    if (picked.local) {
      extra.append(h("span", { class: "spinner" }));
      GET(`/api/setup/ollama?base_url=${encodeURIComponent(picked.base_url)}`).then((r) => {
        if (r.models.length) {
          const sel = h("select", { "aria-label": "Installed models", onchange: () => { model.value = picked.prefix + sel.value; } },
            ...r.models.map((m) => h("option", { value: m, text: m })));
          if (!model.value) model.value = picked.prefix + r.models[0];
          extra.replaceChildren(h("label", { class: "field" }, "Models installed in Ollama", sel));
        } else {
          extra.replaceChildren(h("div", { class: "callout warn" }, "Ollama isn't running on this computer (or has no models). Install it from ",
            extLink("https://ollama.com/download", "ollama.com"), ", then run ", h("code", { text: "ollama pull <model>" }), " in the terminal."));
        }
      }).catch(() => extra.replaceChildren());
    }
    const go = h("button", { class: "btn primary", text: "Continue", onclick: async () => {
      go.disabled = true;
      const r = await attempt(() => POST("/api/setup/choose", { provider: picked.id, model: model.value.trim(), base_url: picked.base_url || null }));
      go.disabled = false;
      if (!r) return;
      Object.assign(st, r);
      if (r.key_present) stepCheck(); else stepKey();
    } });
    body.replaceChildren(stepper(1),
      h("p", { class: "muted", text: "Grid needs an AI model to think with. Pick one - you can add more later in Models." }),
      h("div", { class: "pcards" }, ...cards),
      h("label", { class: "field" }, h("span", {}, "Model id ", picked.models_url ? h("span", { class: "faint" }, "· ", extLink(picked.models_url, "see the list")) : null), model),
      extra,
      h("div", { class: "row setup-foot" }, h("button", { class: "btn ghost", text: "Skip for now", onclick: finish }), h("span", { class: "grow" }), go));
    model.focus();
  };

  const stepKey = () => {
    const prov = st.providers.find((p) => p.key_env === st.key_env) || picked;
    const parts = [stepper(2)];
    if (window.gridDesktop?.keys) {
      const key = h("input", { type: "password", placeholder: "paste your key", autocomplete: "off", "aria-label": st.key_env });
      const save = h("button", { class: "btn primary", text: "Save key", onclick: async () => {
        const v = key.value.trim();
        if (!v) return;
        save.disabled = true;
        await window.gridDesktop.keys.set(st.key_env, v);
        toast("Key saved to your Keychain - restarting Grid's engine");
        // the engine restarts and this page reloads; setup continues with the check
      } });
      parts.push(h("p", { text: `Paste your ${prov.label} API key. It's stored encrypted in your macOS Keychain and only handed to Grid's engine - never written to a file.` }),
        h("label", { class: "field" }, st.key_env, key),
        prov.keys_url ? h("p", { class: "muted" }, "Don't have one? ", extLink(prov.keys_url, `Create a key at ${new URL(prov.keys_url).host}`), ".") : null,
        h("div", { class: "row setup-foot" }, h("button", { class: "btn ghost", text: "Back", onclick: stepChoose }), h("span", { class: "grow" }), save));
      body.replaceChildren(...parts.filter(Boolean));
      key.focus();
      key.addEventListener("keydown", (e) => { if (e.key === "Enter") save.click(); });
    } else {
      const cmd = `export ${st.key_env}=paste-your-key-here`;
      parts.push(h("p", { text: "Grid never writes keys to disk. In the browser version, give it the key through your shell, then restart Grid:" }),
        h("pre", { class: "mono codebox", text: `${cmd}\ngrid app` }),
        h("p", { class: "muted" }, "Put the export line in ~/.zshrc to keep it. ", prov.keys_url ? ["Get a key at ", extLink(prov.keys_url, new URL(prov.keys_url).host), "."] : null),
        h("div", { class: "row setup-foot" }, h("button", { class: "btn ghost", text: "Back", onclick: stepChoose }), h("span", { class: "grow" }),
          h("button", { class: "btn", text: "I've restarted it - check again", onclick: async () => { const r = await loadSetup(); if (r) { Object.assign(st, r); if (r.key_present) stepCheck(); else toast(`${st.key_env} still isn't set for Grid`, "error"); } } })));
      body.replaceChildren(...parts);
    }
  };

  const stepCheck = () => {
    const out = h("div");
    const run = h("button", { class: "btn primary", text: "Run the check", onclick: async () => {
      run.disabled = true;
      out.replaceChildren(h("div", { class: "row" }, h("span", { class: "spinner" }), h("span", { class: "muted", text: `Asking ${st.model} to say "ready"…` })));
      const r = await attempt(() => POST("/api/setup/check"));
      const job = r ? await pollJob(r.job, 120000) : null;
      run.disabled = false;
      if (job?.status === "done" && job.result.ok) {
        out.replaceChildren(h("div", { class: "callout good" }, h("h4", { text: "It works." }), `${st.model} answered: "${job.result.reply || "(empty)"}". You're ready to build.`));
        run.replaceWith(h("button", { class: "btn primary", text: "Start building", onclick: finish }));
      } else {
        const msg = job?.status === "done" ? job.result.error : (job?.error || "The check didn't finish.");
        out.replaceChildren(h("div", { class: "callout bad" }, h("h4", { text: "That didn't work" }), msg));
      }
    } });
    body.replaceChildren(stepper(3),
      h("p", { text: `Grid will send one tiny message to ${st.model} to make sure the key and model work (costs a fraction of a cent).` }),
      st.endpoint_problem ? h("div", { class: "callout warn", text: st.endpoint_problem }) : null,
      out,
      h("div", { class: "row setup-foot" }, h("button", { class: "btn ghost", text: "Change model", onclick: stepChoose }),
        st.key_env && !st.local ? h("button", { class: "btn ghost", text: "Change key", onclick: stepKey }) : null,
        h("span", { class: "grow" }), run));
  };

  if (!st.chosen && !st.key_present) stepChoose();
  else if (!st.key_present) stepKey();
  else stepCheck();
  return modal({ title: "Set up Grid", body, wide: true, onOpen: (_box, c) => { close = c; } });
}

// ------------------------------------------------------------------ accent colors
const ACCENTS = [["teal", "Teal glow"], ["violet", "Electric violet"], ["lime", "Terminal lime"], ["sunset", "Sunset"]];
function accentPicker() {
  const box = h("div", { class: "swatches", role: "radiogroup", "aria-label": "Accent color" });
  const render = () => box.replaceChildren(...ACCENTS.map(([k, label]) => h("button", { class: `swatch ${k}`, role: "radio", "aria-pressed": String((S.settings.accent || "teal") === k),
    "aria-checked": String((S.settings.accent || "teal") === k), onclick: async () => {
      const r = await attempt(() => PUT("/api/settings", { accent: k }));
      if (r) { S.settings = r; applyTheme(); render(); }
    } }, h("i"), label)));
  render();
  return box;
}

// ------------------------------------------------------------------ Mac control
function macControlPanel() {
  const box = h("div", { class: "panel" });
  const render = async () => {
    const r = await attempt(() => GET("/api/computer"));
    if (!r) return;
    if (!r.available) {
      box.replaceChildren(h("p", { class: "muted", style: "margin:0", text: "Mac control works when Grid runs on a Mac." }));
      return;
    }
    const perm = (key, label, which) => {
      const v = r.permissions[key];
      return h("div", { class: "fact" }, h("span", { class: `chip ${v ? "green" : v === false ? "yellow" : ""}`, text: v ? "on" : v === false ? "off" : "?" }),
        h("span", { class: "grow", text: label }),
        v ? null : h("button", { class: "btn small", text: "Open System Settings", onclick: () => attempt(() => POST("/api/computer/settings", { which })) }));
    };
    box.replaceChildren(
      h("p", { class: "muted", style: "margin-top:0", text: "Grid can use your apps like you do - look at the screen, click, type. It asks the first time for each app (once, always or no). It never touches password managers, Terminal or Grid itself, never types passwords, and always asks before sending, buying, posting or deleting." }),
      h("div", { class: "fact-list" },
        perm("screen", "Screen Recording - so Grid can see the screen", "screen"),
        perm("control", "Accessibility - so Grid can click and type", "control")),
      h("h3", { style: "font-size:13.5px;margin:14px 0 6px", text: "Apps Grid may always control" }),
      r.apps.length || r.screen_always ? h("div", { class: "fact-list" },
        r.screen_always ? h("div", { class: "fact" }, h("span", { class: "grow", text: "Seeing your screen" }),
          h("button", { class: "btn small danger", text: "Remove", onclick: async () => { if (await attempt(() => DEL(`/api/computer/apps?name=${encodeURIComponent("(your screen)")}`))) render(); } })) : null,
        ...r.apps.map((a) => h("div", { class: "fact" }, h("span", { class: "grow", text: a.name }), h("span", { class: "faint", style: "font-size:12px", text: `since ${fmtTime(a.granted)}` }),
          h("button", { class: "btn small danger", text: "Remove", onclick: async () => { if (await attempt(() => DEL(`/api/computer/apps?name=${encodeURIComponent(a.name)}`))) render(); } }))))
        : h("div", { class: "empty", text: "None yet - Grid asks when it needs an app." }));
  };
  render();
  return h("div", {}, h("h2", { text: "Mac control" }), box);
}

// ------------------------------------------------------------------ Grid's browser
function browserPanel() {
  const box = h("div", { class: "panel" });
  const render = async () => {
    const r = await attempt(() => GET("/api/browser"));
    if (!r) return;
    const visible = h("input", { type: "checkbox", checked: r.visible, onchange: async () => {
      if (await attempt(() => PUT("/api/settings", { browser_visible: visible.checked }), "Saved - applies to new chats")) S.settings.browser_visible = visible.checked;
    } });
    const install = h("button", { class: "btn", text: "Download Grid's browser (~150 MB)", onclick: async () => {
      install.disabled = true;
      install.replaceChildren(h("span", { class: "spinner" }), " downloading…");
      const j = await attempt(() => POST("/api/browser/install"));
      const res = j ? await pollJob(j.job, 900000) : null;
      if (res?.status === "done" && res.result.ok) { toast("Grid's browser is ready - new chats can use it"); render(); }
      else { toast(res?.result?.error || res?.error || "download failed", "error"); install.disabled = false; install.textContent = "Try again"; }
    } });
    box.replaceChildren(
      h("p", { class: "muted", style: "margin-top:0", text: "For sites that need clicking or forms, Grid drives its own browser: a separate profile that isn't signed in to your accounts. Screenshots of each step show in the chat." }),
      r.path ? h("div", { class: "callout good" }, "Ready - using ", h("code", { text: r.path.replace(S.home, "~") }))
        : h("div", { class: "callout warn" }, "No Chrome or Chromium found. Install Google Chrome, or let Grid download its own copy. ", r.can_install ? install : null),
      h("label", { class: "check", style: "margin-top:10px" }, visible, "Show the browser window while Grid works (otherwise it runs in the background)"));
  };
  render();
  return h("div", {}, h("h2", { text: "Grid's browser" }), box);
}

// ------------------------------------------------------------------ Mac access
function macAccessPanel() {
  const box = h("div", { class: "panel" });
  const render = async () => {
    const r = await attempt(() => GET("/api/access"));
    if (!r) return;
    const pathInput = h("input", { type: "text", placeholder: "~/Documents/notes", "aria-label": "Folder to allow" });
    const add = async (p) => { if (p && await attempt(() => POST("/api/access", { path: p }), "Folder allowed")) render(); };
    box.replaceChildren(
      h("p", { class: "muted", style: "margin-top:0", text: "Grid works inside your project. To use other folders (save a PDF to Downloads, read notes in Documents) it asks first - once, always, or no. Folders you allowed always are listed here. Key and system folders are never available, and risky actions still ask." }),
      r.folders.length ? h("div", { class: "fact-list" }, ...r.folders.map((f) => h("div", { class: "fact" },
        h("span", { class: "grow mono", text: f.pretty }), h("span", { class: "faint", style: "font-size:12px", text: `since ${fmtTime(f.granted)}` }),
        h("button", { class: "btn small danger", text: "Remove", onclick: async () => { if (await attempt(() => DEL(`/api/access?path=${encodeURIComponent(f.path)}`))) render(); } }))))
        : h("div", { class: "empty", text: "No folders allowed yet - Grid will ask when it needs one." }),
      h("div", { class: "row", style: "margin-top:10px;flex-wrap:nowrap" },
        window.gridDesktop?.pickFolder ? h("button", { class: "btn", text: "Allow a folder…", onclick: async () => add(await window.gridDesktop.pickFolder()) })
          : [pathInput, h("button", { class: "btn", text: "Allow folder", onclick: () => add(pathInput.value.trim()) })]));
  };
  render();
  return h("div", {}, h("h2", { text: "Mac access" }), box);
}

// ------------------------------------------------------------------ personality
async function ageGate() {
  if (!S.persona?.needs_age_check) return;
  const answer = await modal({
    title: "Quick question before we start",
    body: h("div", {},
      h("p", {}, "Grid has two personalities:"),
      h("ul", {}, h("li", {}, h("strong", { text: "Grid" }), " - a sarcastic, foul-mouthed senior engineer who roasts your code into shape. Adults only."),
        h("li", {}, h("strong", { text: "Teacher" }), " - same skills, clean language, endlessly patient.")),
      h("p", { style: "margin-bottom:0" }, h("strong", { text: "Are you 18 or older?" })),
      h("p", { class: "muted", style: "margin-top:4px;font-size:12.5px", text: "Grid takes your word for it and only stores the answer, not your age. You can change your personality later in Settings." })),
    // Neither answer is pre-selected: Enter must not confirm adulthood by accident.
    buttons: [{ label: "I'm under 18", value: "minor" }, { label: "I'm 18 or older", value: "adult" }],
  });
  if (!answer) return;   // no answer: teacher for now, ask again next time
  const r = await attempt(() => POST("/api/persona", { age: answer }));
  if (r) { S.persona = r; toast(answer === "adult" ? "Grid voice unlocked. Brace yourself." : "Teacher mode it is."); }
}

function personalityPanel() {
  const box = h("div", { class: "panel" });
  const render = async () => {
    const p = await attempt(() => GET("/api/persona"));
    if (!p) return;
    S.persona = p;
    const adultOk = p.age_answer === "adult" && !p.minor_lock;
    const choice = (value, title, desc) => h("label", { class: "check", style: "align-items:flex-start;margin-bottom:8px;opacity:" + (value === "grid" && !adultOk ? ".5" : "1") },
      h("input", { type: "radio", name: "persona", value, checked: p.effective === value, disabled: value === "grid" && !adultOk,
        onchange: async () => { const r = await attempt(() => POST("/api/persona", { persona: value }), "Saved - new chats use this voice"); if (r) render(); } }),
      h("span", {}, h("strong", { text: title }), h("br"), h("span", { class: "muted", text: desc })));
    const status = p.minor_lock
      ? h("div", { class: "callout info" }, "Teacher mode is locked because you said you're under 18. ",
          h("button", { class: "btn small", text: "That was a mistake - I'm 18 or older", onclick: async () => {
            if (await confirmBox("Confirm your age", "Only continue if you are 18 or older. The Grid voice swears and makes adult jokes.", "I'm 18 or older")) {
              if (await attempt(() => POST("/api/persona", { age: "adult" }))) render();
            }
          } }))
      : p.age_answer === null
        ? h("div", { class: "callout warn" }, "The Grid voice is for adults. ",
            h("button", { class: "btn small", text: "I'm 18 or older", onclick: async () => { if (await attempt(() => POST("/api/persona", { age: "adult" }))) render(); } }), " ",
            h("button", { class: "btn small", text: "I'm under 18", onclick: async () => { if (await attempt(() => POST("/api/persona", { age: "minor" }))) render(); } }))
        : null;
    box.replaceChildren(...[
      choice("grid", "Grid (18+)", "The senior engineer who roasts your code into competence. Dry, savage, swears when it lands - never at you."),
      choice("teacher", "Teacher", "Same skills and lessons, clean language, extra patient. Always on for anyone under 18."),
      status,
      h("p", { class: "muted", style: "margin-bottom:0;font-size:12.5px", text: "Code, comments and files Grid writes stay professional in both. Changes apply to new chats." })].filter(Boolean));
  };
  render();
  return h("div", {}, h("h2", { text: "Personality" }), box);
}

// ------------------------------------------------------------------ boot
function menuCommand(cmd) {
  const ws = S.view instanceof Workspace ? S.view : null;
  switch (cmd) {
    case "new-project": return newProjectDialog();
    case "open-folder": return openFolderDialog();
    case "new-chat": return ws?.newChat();
    case "toggle-layout": return toggleLayout();
    case "save": return ws?.editorArea?.save(ws.editorArea.active);
    case "settings": location.hash = "#/settings"; return;
    case "plugins": location.hash = "#/plugins"; return;
    case "models": location.hash = "#/models"; return;
    case "schedules": location.hash = "#/schedules"; return;
    case "memory": location.hash = "#/memory"; return;
    case "focus-chat": return ws?.input.focus();
    case "terminal": return ws?.showTab("terminal");
    case "quick-open": return ws ? Palette.open("") : Palette.open(">");
    case "command-palette": return Palette.open(">");
    case "go-to-line": return ws && Palette.open(":");
    case "find-in-project": return ws?.showSide("search");
    case "replace-in-project": return ws?.showSide("search", { replace: true });
    case "show-files": return ws?.showSide("files");
    case "review-changes": return ws?.showTab("changes");
    case "checkpoints": return ws?.showTab("checkpoints");
    case "new-file": return ws?.newEntry("file");
    case "new-folder": return ws?.newEntry("dir");
    case "setup": return setupWizard({ force: true });
    default: return undefined;
  }
}
window.gridMenu = menuCommand;

async function boot() {
  window.gridDesktop?.onMenu?.(menuCommand);
  document.addEventListener("keydown", (e) => {
    const mod = IS_MAC ? e.metaKey : e.ctrlKey;   // never steal Ctrl+J/P/E/H from the shell on a Mac
    if (mod && e.key === "\\") { e.preventDefault(); toggleLayout(); }
    if (mod && e.key === "j" && S.view instanceof Workspace) { e.preventDefault(); S.view.showTab("terminal"); }
  });
  // Capture phase so these win over the editor and the terminal.
  window.addEventListener("keydown", (e) => {
    const mod = IS_MAC ? e.metaKey : e.ctrlKey;
    if (!mod || e.altKey) return;
    const cmd = { KeyP: e.shiftKey ? "command-palette" : "quick-open", KeyF: e.shiftKey ? "find-in-project" : null,
      KeyH: e.shiftKey ? "replace-in-project" : null, KeyE: e.shiftKey ? "show-files" : null }[e.code];
    if (!cmd) return;
    if (document.querySelector(".modal-back")) return;   // a dialog is open
    e.preventDefault();
    e.stopPropagation();
    menuCommand(cmd);
  }, true);
  document.documentElement.classList.toggle("desktop", !!window.gridDesktop);
  $("#btn-new-project").addEventListener("click", newProjectDialog);
  $("#btn-open-folder").addEventListener("click", openFolderDialog);
  window.addEventListener("hashchange", route);
  try {
    await Promise.all([loadState(), loadSetup(), restoreUiState()]);
  } catch (e) {
    $("#main").replaceChildren(h("div", { class: "page" }, h("div", { class: "empty", text: e.message })));
    return;
  }
  await route();
  await ageGate();
  await setupWizard();
  if (S.view instanceof Workspace && S.view.hasWelcome) S.view.welcome();
}

boot();
