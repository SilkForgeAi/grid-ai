"use strict";
const params = new URLSearchParams(location.search);
document.getElementById("reason").textContent = params.get("reason") || "";
const api = window.gridDesktop && window.gridDesktop.setup;
document.getElementById("retry").addEventListener("click", () => api && api.retry());
if (params.get("privacy") === "1") {
  document.getElementById("privacy").hidden = false;
  document.getElementById("manual").hidden = true;
  document.getElementById("open-privacy").addEventListener("click", () => api && api.openPrivacy && api.openPrivacy());
  document.getElementById("retry2").addEventListener("click", () => api && api.retry());
}
document.getElementById("choose").addEventListener("click", () => api && api.choose());
if (api) api.info().then((info) => { if (info && info.log) document.getElementById("log").textContent = info.log; });
if (api && api.hasBundle) api.hasBundle().then((has) => {
  if (!has || params.get("privacy") === "1") return;
  document.getElementById("bundled").hidden = false;
  document.getElementById("reinstall").addEventListener("click", () => api.reinstall());
});
