"use strict";
const logEl = document.getElementById("log");
const steps = [...document.querySelectorAll("#steps li")];
const api = window.gridDesktop && window.gridDesktop.setup;
if (api && api.onInstall) {
  api.onInstall(({ text, step }) => {
    logEl.textContent += text + "\n";
    if (logEl.textContent.length > 20000) logEl.textContent = logEl.textContent.slice(-15000);
    logEl.scrollTop = logEl.scrollHeight;
    if (step > 0) steps.forEach((li, i) => { li.className = i + 1 < step ? "done" : i + 1 === step ? "on" : ""; });
  });
}
