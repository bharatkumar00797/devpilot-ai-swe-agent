"use strict";

// DevPilot dashboard: plain JS, no build step. All server data is rendered with
// textContent (never innerHTML) so issue text, diffs and tool output cannot inject markup.

const $ = (id) => document.getElementById(id);
const POLL_MS = 800;
const state = { config: null, runId: null, cursor: 0, timer: null };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function apiKey() {
  return sessionStorage.getItem("devpilot.apiKey") || "";
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const key = apiKey();
  if (key) headers["X-API-Key"] = key;
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    let detail = body.detail || response.statusText;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    throw new Error(`${response.status}: ${detail}`);
  }
  return body;
}

function showError(message) {
  const box = $("form-error");
  box.textContent = message || "";
  box.classList.toggle("hidden", !message);
}

// ------------------------------------------------------------------ config
async function loadConfig() {
  const cfg = await api("/api/config");
  state.config = cfg;
  const labels = { "api-key": "API key required", dev: "dev mode", "public-demo": "public demo" };
  $("mode").textContent = labels[cfg.access_mode] || cfg.access_mode;
  $("version").textContent = `v${cfg.version}`;
  $("issue-max").textContent = cfg.max_issue_chars;
  $("issue").maxLength = cfg.max_issue_chars;
  $("max-steps").max = cfg.max_steps_cap;
  $("max-steps").value = cfg.default_max_steps;
  $("key-field").classList.toggle("hidden", !cfg.auth_required);
  $("api-key").value = apiKey();

  const repo = $("repo-select");
  repo.replaceChildren();
  for (const demo of cfg.demos) {
    const option = el("option", "", `Demo · ${demo.name}`);
    option.value = demo.repo;
    repo.append(option);
  }
  if (cfg.allow_paths) {
    const option = el("option", "", "Allowed path on server…");
    option.value = "__path__";
    repo.append(option);
  }
  const provider = $("provider");
  provider.replaceChildren();
  for (const name of cfg.providers) {
    const option = el("option", "", name === "mock" ? "mock (offline)" : name);
    option.value = name;
    option.selected = name === cfg.default_provider;
    provider.append(option);
  }
  onRepoChange();
}

function onRepoChange() {
  const value = $("repo-select").value;
  $("repo-path").classList.toggle("hidden", value !== "__path__");
  const demo = (state.config?.demos || []).find((d) => d.repo === value);
  if (demo && demo.issue) $("issue").value = demo.issue;
  updateCount();
}

function updateCount() {
  $("issue-count").textContent = $("issue").value.length;
}

// -------------------------------------------------------------------- runs
async function startRun(event) {
  event.preventDefault();
  showError("");
  const selected = $("repo-select").value;
  const repo = selected === "__path__" ? $("repo-path").value.trim() : selected;
  const payload = {
    repo,
    issue: $("issue").value,
    provider: $("provider").value,
    max_steps: Number($("max-steps").value) || undefined,
  };
  const button = $("start");
  button.disabled = true;
  try {
    const run = await api("/api/runs", { method: "POST", body: JSON.stringify(payload) });
    selectRun(run.id);
    refreshHistory();
  } catch (err) {
    showError(err.message);
  } finally {
    button.disabled = false;
  }
}

function selectRun(id) {
  clearTimeout(state.timer);
  window.history.replaceState(null, "", `#run=${encodeURIComponent(id)}`);
  state.runId = id;
  state.cursor = 0;
  $("trace").replaceChildren();
  $("diff").replaceChildren(el("span", "muted", "No diff yet."));
  $("summary").replaceChildren(el("span", "muted", "The PR description appears when the run finishes."));
  $("run-facts").classList.remove("hidden");
  poll();
}

async function poll() {
  const id = state.runId;
  if (!id) return;
  try {
    const trace = await api(`/api/runs/${id}/trace?since=${state.cursor}`);
    if (id !== state.runId) return;
    trace.steps.forEach(appendStep);
    state.cursor = trace.next_cursor;
    setStatus(trace.status);
    $("fact-steps").textContent = state.cursor;
    if (trace.done) {
      await renderDetail(id);
      refreshHistory();
      return;
    }
  } catch (err) {
    setStatus("error");
    showError(err.message);
    return;
  }
  state.timer = setTimeout(poll, POLL_MS);
}

function setStatus(status) {
  const badge = $("run-status");
  badge.textContent = status.replace("_", " ");
  badge.className = `badge ${status}`;
}

function formatArgs(args) {
  return Object.entries(args || {})
    .map(([k, v]) => `${k}=${JSON.stringify(v).slice(0, 60)}`)
    .join(", ");
}

function appendStep(step) {
  const item = el("li", "step");
  const details = el("details");
  const summary = el("summary");
  summary.append(
    el("span", "idx", String(step.index)),
    el("span", "tool", step.tool),
    el("span", "args", formatArgs(step.args)),
    el("span", step.ok ? "ok" : "err", step.ok ? "ok" : "error"),
  );
  details.append(summary);
  if (step.observation) details.append(el("pre", "", step.observation));
  item.append(details);
  if (step.thought) item.append(el("div", "thought", step.thought));
  $("trace").append(item);
}

async function renderDetail(id) {
  const run = await api(`/api/runs/${id}`);
  $("run-title").textContent = run.title || "Run";
  setStatus(run.status);
  const tests = $("fact-tests");
  tests.textContent = run.tests_passed === null ? "not run" : run.tests_passed ? "passing" : "failing";
  tests.className = run.tests_passed === null ? "" : run.tests_passed ? "pass" : "fail";
  $("fact-steps").textContent = run.step_count;
  $("fact-files").textContent = run.changed_files.join(", ") || "none";
  $("fact-model").textContent = run.model || run.provider;
  renderDiff(run.diff);
  const summary = $("summary");
  summary.textContent = run.error ? `Run error: ${run.error}` : run.pr_summary || run.summary;
  if (!state.cursor && run.step_count === 0) {
    $("trace").replaceChildren(el("li", "muted", run.error || "No steps recorded."));
  }
}

function renderDiff(diff) {
  const box = $("diff");
  box.replaceChildren();
  if (!diff) {
    box.append(el("span", "muted", "No changes were made."));
    return;
  }
  for (const line of diff.replace(/\n$/, "").split("\n")) {
    let cls = "line";
    if (line.startsWith("+++") || line.startsWith("---")) cls += " file";
    else if (line.startsWith("@@")) cls += " hunk";
    else if (line.startsWith("+")) cls += " add";
    else if (line.startsWith("-")) cls += " del";
    box.append(el("span", cls, line || " "));
  }
}

async function refreshHistory() {
  const list = $("history");
  try {
    const { runs } = await api("/api/runs?limit=10");
    list.replaceChildren();
    if (!runs.length) {
      list.append(el("li", "muted", "No runs yet."));
      return;
    }
    for (const run of runs) {
      const item = el("li");
      const button = el("button");
      button.type = "button";
      button.append(el("span", "title", run.title || run.id), el("span", `badge ${run.status}`, run.status.replace("_", " ")));
      button.addEventListener("click", () => {
        $("run-title").textContent = run.title || "Run";
        selectRun(run.id);
      });
      item.append(button);
      list.append(item);
    }
  } catch {
    /* history is best-effort (e.g. API key not entered yet) */
  }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== `tab-${name}`));
}

// -------------------------------------------------------------------- init
document.addEventListener("DOMContentLoaded", async () => {
  $("run-form").addEventListener("submit", (e) => {
    $("run-title").textContent = $("issue").value.trim().split("\n")[0].replace(/^#+\s*/, "").slice(0, 80) || "Run";
    startRun(e);
  });
  $("repo-select").addEventListener("change", onRepoChange);
  $("issue").addEventListener("input", updateCount);
  $("api-key").addEventListener("change", (e) => {
    sessionStorage.setItem("devpilot.apiKey", e.target.value.trim());
    refreshHistory();
  });
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  try {
    await loadConfig();
    refreshHistory();
    const linked = new URLSearchParams(location.hash.slice(1)).get("run");
    if (linked && /^[a-f0-9]{32}$/.test(linked)) selectRun(linked);
  } catch (err) {
    $("mode").textContent = "offline";
    showError(`Cannot reach the API: ${err.message}`);
  }
});
