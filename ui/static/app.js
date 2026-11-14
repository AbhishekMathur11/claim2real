// claim2real UI: problem -> requirements (editable) -> search -> verification + build vs buy -> outreach.
import { mountThinkingOrb } from "./orb.js";
import { componentIcon, icon } from "./icons.js";

const $ = (id) => document.getElementById(id);
const POLL_MS = 2000;

const state = {
  bundle: null, // saved/edited spec {hardware, software, checklists}
  dirty: false,
  generating: false,
  saving: false,
  specRev: 0, // bumps on every save; a run remembers the rev it started from
  run: null, // latest run status from the backend
  runRev: null,
  limit: Number(localStorage.getItem("c2r.limit") || 6),
  sender: {
    name: localStorage.getItem("c2r.name") || "",
    company: localStorage.getItem("c2r.company") || "",
  },
  tab: "briefing",
  reqVersion: 0, // bumps on structural edits / save / generate (typing does not re-render)
};
const senderInit = { ...state.sender };
let pollTimer = null;
let stopOrb = null;

// ---------------------------------------------------------------- utils

const esc = (v) =>
  String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

const UNIT_SUFFIX = /_(nm|kg|v|w|rpm|mm_s|mm|n|a|hz|deg|c|h|tops|gb|usd)$/;
const label = (f) => (f === "budget_usd" ? "budget" : String(f).replace(UNIT_SUFFIX, "").replaceAll("_", " "));
const OP = { ">=": "≥", "<=": "≤", "==": "=", has: "has" };
const fmtNum = (v) => (typeof v === "number" ? String(Number(v.toFixed(3))) : esc(v));
const money = (v) => (v == null ? null : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const host = (u) => {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
};
const initials = (name) =>
  String(name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : res.statusText);
  }
  return data;
}

function showError(msg) {
  $("error").hidden = !msg;
  $("error").textContent = msg || "";
  if (msg) $("step-problem").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Replace a panel's HTML only when it changed; keep expanded <details data-key> open across updates.
function setHTML(el, html) {
  if (el._html === html) return false;
  const open = new Set([...el.querySelectorAll("details[open][data-key]")].map((d) => d.dataset.key));
  el.innerHTML = html;
  el._html = html;
  el.querySelectorAll("details[data-key]").forEach((d) => {
    if (open.has(d.dataset.key)) d.open = true;
  });
  return true;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2200);
}

const pill = (stateName, text) => {
  const ico = { running: "loader", done: "check", error: "x", skipped: "help", pending: "clock", waiting: "clock" }[stateName] || "clock";
  return `<span class="pill pill-${stateName}">${icon(ico, 12, stateName === "running" ? "spin" : "")}${esc(text || stateName)}</span>`;
};

// ---------------------------------------------------------------- stepper

const STEPS = [
  { id: "step-problem", label: "Problem", ico: "file-text" },
  { id: "step-requirements", label: "Requirements", ico: "list" },
  { id: "step-search", label: "Search", ico: "search" },
  { id: "step-verify", label: "Verify", ico: "shield" },
  { id: "step-outreach", label: "Outreach", ico: "send" },
];

function stepStatus() {
  const r = state.run;
  const has = !!(state.bundle && (state.bundle.checklists || []).length);
  const st = (k) => (r && r.steps ? r.steps[k].state : "pending");
  return [
    has ? "done" : state.generating ? "active" : "active",
    !has ? "locked" : r ? "done" : "active",
    !r ? (has ? "next" : "locked") : st("search") === "done" ? "done" : "active",
    !r || st("search") !== "done" ? "locked" : st("verify") === "done" ? "done" : r.phase === "search_done" ? "next" : "active",
    !r || st("verify") !== "done" ? "locked" : st("outreach") === "done" ? "done" : "active",
  ];
}

function renderStepper() {
  const s = stepStatus();
  $("stepper").innerHTML = STEPS.map(
    (step, i) => `<button class="step step-${s[i]}" data-target="${step.id}" ${s[i] === "locked" ? "disabled" : ""}>
      <span class="step-dot">${s[i] === "done" ? icon("check", 13) : icon(step.ico, 13)}</span>
      <span class="step-label">${step.label}</span>
    </button>${i < STEPS.length - 1 ? '<span class="step-line"></span>' : ""}`
  ).join("");
}

$("stepper").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-target]");
  if (b && !b.disabled) $(b.dataset.target).scrollIntoView({ behavior: "smooth", block: "start" });
});

// ---------------------------------------------------------------- step 1: problem

function renderProblem() {
  const btn = $("generate-btn");
  btn.innerHTML = state.generating ? `${icon("loader", 15, "spin")} Generating` : `${icon("sparkles", 15)} Generate requirements`;
  btn.disabled = state.generating;
  $("problem-input").readOnly = state.generating;
  $("think").hidden = !state.generating;
  if (state.generating && !stopOrb) stopOrb = mountThinkingOrb($("orb"));
  if (!state.generating && stopOrb) {
    stopOrb();
    stopOrb = null;
  }
}

async function generate(problem) {
  showError("");
  state.generating = true;
  renderAll();
  try {
    state.bundle = await api("/api/generate", { method: "POST", body: JSON.stringify({ problem }) });
    state.dirty = false;
    state.specRev += 1;
    state.reqVersion += 1;
    stopPolling();
    state.run = null;
    toast("Requirements generated");
  } catch (err) {
    showError(err.message);
  } finally {
    state.generating = false;
    renderAll();
    if (state.bundle) $("step-requirements").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

$("problem-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const p = $("problem-input").value.trim();
  if (p && !state.generating) generate(p);
});
$("problem-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("problem-form").requestSubmit();
});

// ---------------------------------------------------------------- step 2: requirements (editable)

function constraintRows(list, ci, kind) {
  return (list || [])
    .map((r, ri) => {
      const numeric = r.unit != null;
      return `<div class="req-row">
        <span class="req-field">${esc(label(r.field))}${kind === "nice_to_have" ? '<span class="tag-nice">nice</span>' : ""}</span>
        <span class="req-op">${esc(OP[r.operator] || r.operator)}</span>
        <input class="req-val" type="${numeric ? "number" : "text"}" ${numeric ? 'step="any"' : ""}
          value="${esc(r.value)}" data-ci="${ci}" data-list="${kind}" data-ri="${ri}" data-numeric="${numeric}" />
        <span class="req-unit">${esc(r.unit || "")}</span>
        <button class="icon-btn" title="Remove" data-act="del-row" data-ci="${ci}" data-list="${kind}" data-ri="${ri}"
          ${kind === "must_have" && list.length <= 1 ? "disabled" : ""}>${icon("trash", 14)}</button>
      </div>`;
    })
    .join("");
}

function hardwareCard(c, ci, total) {
  return `<article class="req-card">
    <div class="req-card-head">
      <span class="req-ico">${icon(componentIcon(c.component_type), 18)}</span>
      <div class="req-title">
        <h4>${esc(c.component_type)}</h4>
        <div class="terms">${(c.search_terms || []).slice(0, 4).map((t) => `<span class="chip ghost-chip">${esc(t)}</span>`).join("")}</div>
      </div>
      <button class="icon-btn" title="Remove component" data-act="del-comp" data-ci="${ci}" ${total <= 1 ? "disabled" : ""}>${icon("trash", 14)}</button>
    </div>
    <div class="req-meta">
      <label>Qty<input type="number" min="1" step="1" value="${c.quantity ?? 1}" data-meta="${ci}:quantity" /></label>
      <label>Budget / unit<span class="input-prefix">$<input type="number" step="1" value="${c.budget_usd ?? ""}" data-meta="${ci}:budget_usd" /></span></label>
      <label>Lead time<span class="input-suffix"><input type="number" step="1" value="${c.max_lead_time_days ?? ""}" data-meta="${ci}:max_lead_time_days" />days</span></label>
    </div>
    <div class="req-rows">
      ${constraintRows(c.must_have, ci, "must_have")}
      ${constraintRows(c.nice_to_have, ci, "nice_to_have")}
    </div>
  </article>`;
}

function renderRequirements(force = false) {
  const el = $("step-requirements");
  const b = state.bundle;
  el.hidden = !b || !(b.checklists || []).length;
  if (el.hidden) return;
  const key = `${state.reqVersion}|${state.saving}|${state.run ? state.runRev !== state.specRev : ""}|${isRunning()}|${state.limit}`;
  if (!force && el._key === key) return;
  el._key = key;
  const sw = b.software || [];
  const stale = state.run && state.runRev !== state.specRev;
  el._html = null;
  el.innerHTML = `
    <div class="panel-head">
      <span class="step-no">02</span>
      <div>
        <h2>Requirements</h2>
        <p class="sub">Edit any value, then save. Search uses the saved requirements.</p>
      </div>
      <div class="head-actions">
        <span class="save-state ${state.dirty ? "unsaved" : ""}">${state.dirty ? `${icon("edit", 13)} Unsaved changes` : `${icon("check", 13)} Saved`}</span>
        <button class="btn ghost" id="save-btn" ${state.dirty && !state.saving ? "" : "disabled"}>${icon("save", 14)} Save</button>
      </div>
    </div>
    <div class="split">
      <div class="col">
        <div class="col-head">${icon("cpu", 16)}<h3>Hardware</h3><span class="count">${b.checklists.length}</span></div>
        ${b.checklists.map((c, i) => hardwareCard(c, i, b.checklists.length)).join("")}
      </div>
      <div class="col">
        <div class="col-head">${icon("code", 16)}<h3>Software</h3><span class="count">${sw.length}</span></div>
        <article class="req-card">
          <div class="sw-list">
            ${sw
              .map(
                (s, i) => `<div class="sw-row">
                  <span class="sw-ico">${icon("code", 14)}</span>
                  <input type="text" value="${esc(s)}" data-sw="${i}" />
                  <button class="icon-btn" title="Remove" data-act="del-sw" data-i="${i}">${icon("trash", 14)}</button>
                </div>`
              )
              .join("") || '<p class="muted small">No software requirements. Add one below.</p>'}
          </div>
          <form class="sw-add" id="sw-add">
            <input type="text" id="sw-new" placeholder="Add a software requirement, e.g. SLAM / localization" />
            <button class="btn ghost" type="submit">${icon("plus", 14)} Add</button>
          </form>
        </article>
      </div>
    </div>
    <div class="action-bar">
      ${stale ? `<span class="note warn">${icon("alert", 14)} Requirements changed since the last search. Start search again to use them.</span>` : `<span class="note">${icon("search", 14)} Searches every hardware and software requirement in one Telem session.</span>`}
      <label class="inline-select">Candidates per hardware requirement
        <select id="limit-select">${[4, 6, 8, 10].map((n) => `<option ${n === state.limit ? "selected" : ""}>${n}</option>`).join("")}</select>
      </label>
      <button class="btn primary" id="search-btn" ${isRunning() ? "disabled" : ""}>${icon("search", 15)} Start search</button>
    </div>`;
}

function markDirty() {
  state.dirty = true;
  const s = document.querySelector(".save-state");
  if (s) {
    s.classList.add("unsaved");
    s.innerHTML = `${icon("edit", 13)} Unsaved changes`;
  }
  const btn = $("save-btn");
  if (btn) btn.disabled = false;
}

$("step-requirements").addEventListener("input", (e) => {
  const el = e.target;
  if (!(el instanceof HTMLInputElement) || !state.bundle) return;
  if (el.dataset.list) {
    const row = state.bundle.checklists[+el.dataset.ci][el.dataset.list][+el.dataset.ri];
    row.value = el.dataset.numeric === "true" ? (el.value === "" ? "" : Number(el.value)) : el.value;
    markDirty();
  } else if (el.dataset.meta) {
    const [ci, key] = el.dataset.meta.split(":");
    const c = state.bundle.checklists[+ci];
    c[key] = el.value === "" ? (key === "quantity" ? 1 : null) : Number(el.value);
    markDirty();
  } else if (el.dataset.sw != null) {
    state.bundle.software[+el.dataset.sw] = el.value;
    markDirty();
  }
});

$("step-requirements").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  const bundle = state.bundle;
  if (b.id === "save-btn") return void save();
  if (b.id === "search-btn") return void startSearch();
  const act = b.dataset.act;
  if (act === "del-row") bundle.checklists[+b.dataset.ci][b.dataset.list].splice(+b.dataset.ri, 1);
  else if (act === "del-comp") {
    const [gone] = bundle.checklists.splice(+b.dataset.ci, 1);
    bundle.hardware = (bundle.hardware || []).filter((h) => h !== gone.component_type);
  } else if (act === "del-sw") bundle.software.splice(+b.dataset.i, 1);
  else return;
  state.dirty = true;
  state.reqVersion += 1;
  renderRequirements(true);
});

$("step-requirements").addEventListener("submit", (e) => {
  if (e.target.id !== "sw-add") return;
  e.preventDefault();
  const v = $("sw-new").value.trim();
  if (!v) return;
  state.bundle.software = [...(state.bundle.software || []), v];
  state.dirty = true;
  state.reqVersion += 1;
  renderRequirements(true);
  $("sw-new")?.focus();
});

$("step-requirements").addEventListener("change", (e) => {
  if (e.target.id === "limit-select") {
    state.limit = Number(e.target.value);
    localStorage.setItem("c2r.limit", String(state.limit));
  }
});

async function save() {
  if (!state.bundle) return false;
  state.saving = true;
  showError("");
  try {
    state.bundle.software = (state.bundle.software || []).map((s) => String(s).trim()).filter(Boolean);
    state.bundle = await api("/api/spec", { method: "POST", body: JSON.stringify(state.bundle) });
    state.dirty = false;
    state.specRev += 1;
    state.reqVersion += 1;
    toast("Requirements saved");
    return true;
  } catch (err) {
    showError(`Could not save: ${err.message}`);
    return false;
  } finally {
    state.saving = false;
    renderAll();
  }
}

// ---------------------------------------------------------------- run control + polling

const isRunning = () => state.run && state.run.state === "running";

async function startSearch() {
  if (state.dirty && !(await save())) return;
  try {
    state.run = await api("/api/run", { method: "POST", body: JSON.stringify({ limit: state.limit }) });
    state.runRev = state.specRev;
    renderAll();
    $("step-search").scrollIntoView({ behavior: "smooth", block: "start" });
    poll();
  } catch (err) {
    showError(err.message);
  }
}

async function startVerify() {
  const name = $("sender-name").value.trim();
  const company = $("sender-company").value.trim();
  state.sender = { name, company };
  localStorage.setItem("c2r.name", name);
  localStorage.setItem("c2r.company", company);
  try {
    state.run = await api(`/api/run/${state.run.id}/verify`, { method: "POST", body: JSON.stringify(state.sender) });
    renderAll();
    $("step-verify").scrollIntoView({ behavior: "smooth", block: "start" });
    poll();
  } catch (err) {
    showError(err.message);
  }
}

function stopPolling() {
  clearTimeout(pollTimer);
  pollTimer = null;
}

async function poll() {
  stopPolling();
  if (!state.run) return;
  try {
    const prevPhase = state.run.phase;
    state.run = await api(`/api/run/${state.run.id}`);
    renderAll();
    if (prevPhase !== state.run.phase) {
      if (state.run.phase === "search_done") toast("Search complete");
      if (state.run.phase === "outreach") {
        toast("Verification complete · drafting outreach");
        $("step-verify").scrollIntoView({ behavior: "smooth", block: "start" });
      }
      if (state.run.phase === "done") toast("Report and outreach ready");
    }
  } catch {
    /* transient: keep polling */
  }
  if (state.run && state.run.state === "running") pollTimer = setTimeout(poll, POLL_MS);
}

// ---------------------------------------------------------------- step 3: search results

function hwSearchBlock(h) {
  const cands = h.candidates || [];
  return `<article class="res-block">
    <div class="res-head">
      <span class="req-ico">${icon(componentIcon(h.name), 16)}</span>
      <h4>${esc(h.name)}</h4>
      ${pill(h.search, h.search === "done" ? `${cands.length} found` : h.search)}
    </div>
    ${h.search === "running" ? '<div class="skeleton"></div><div class="skeleton short"></div>' : ""}
    <ul class="cand-list">${cands
      .map(
        (c) => `<li>
          <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a>
          <span class="muted"> · ${esc(c.vendor)}</span>
          <div class="cand-meta">${String(c.found_by_provider || "")
            .split(",")
            .filter(Boolean)
            .map((p) => `<span class="prov">${esc(p.trim())}</span>`)
            .join("")}</div>
          ${c.reason ? `<p class="muted small">${esc(c.reason)}</p>` : ""}
        </li>`
      )
      .join("")}</ul>
  </article>`;
}

function swSearchBlock(s) {
  const cands = s.candidates || [];
  return `<article class="res-block">
    <div class="res-head">
      <span class="req-ico">${icon("code", 16)}</span>
      <h4>${esc(s.name)}</h4>
      ${pill(s.search, s.search === "done" ? `${cands.length} found` : s.search)}
    </div>
    ${s.search === "running" ? '<div class="skeleton"></div><div class="skeleton short"></div>' : ""}
    <ul class="cand-list">${cands
      .map(
        (c) => `<li>
          <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a>
          <span class="muted"> · ${esc(c.provider)}</span> <span class="kind kind-${esc((c.kind || "").replace(/\s/g, "-"))}">${esc(c.kind)}</span>
          ${c.reason ? `<p class="muted small">${esc(c.reason)}</p>` : ""}
        </li>`
      )
      .join("")}</ul>
  </article>`;
}

function renderSearch() {
  const el = $("step-search");
  const r = state.run;
  el.hidden = !r;
  if (!r) return;
  const searching = r.steps.search.state !== "done";
  const canVerify = r.phase === "search_done";
  setHTML(el, `
    <div class="panel-head">
      <span class="step-no">03</span>
      <div>
        <h2>Search</h2>
        <p class="sub">Candidates per requirement from Telem search${r.trace ? ` · session <code>${esc(r.trace.session_id || "")}</code>` : ""}.</p>
      </div>
      <div class="head-actions">${pill(r.steps.search.state === "done" ? "done" : r.state === "error" ? "error" : "running",
        r.steps.search.seconds != null ? `${r.steps.search.seconds}s` : "searching")}</div>
    </div>
    ${r.error && r.phase === "search" ? `<p class="error">${esc(r.error)}</p>` : ""}
    <div class="split">
      <div class="col">
        <div class="col-head">${icon("cpu", 16)}<h3>Hardware</h3><span class="count">${r.hardware.length}</span></div>
        ${r.hardware.map(hwSearchBlock).join("")}
      </div>
      <div class="col">
        <div class="col-head">${icon("code", 16)}<h3>Software</h3><span class="count">${r.software.length}</span></div>
        ${r.software.map(swSearchBlock).join("") || '<p class="muted small">No software requirements.</p>'}
      </div>
    </div>
    ${
      r.steps.verify.state === "pending"
        ? `<div class="action-bar">
        <span class="note">${icon("mail", 14)} Outreach emails will be signed with:</span>
        <input id="sender-name" class="text-in" placeholder="Your name" value="${esc(senderInit.name)}" />
        <input id="sender-company" class="text-in" placeholder="Your company" value="${esc(senderInit.company)}" />
        <button class="btn primary" id="verify-btn" ${canVerify ? "" : "disabled"}>${icon("shield", 15)} ${searching ? "Searching…" : "Start verification"}</button>
      </div>`
        : ""
    }`);
}

$("step-search").addEventListener("click", (e) => {
  const b = e.target.closest("#verify-btn");
  if (b && !b.disabled) startVerify();
});

// ---------------------------------------------------------------- step 4: verification + build vs buy

function buildBuyCard(bb) {
  if (!bb) return `<div class="bb bb-pending">${icon("loader", 14, "spin")} Build vs Buy pending</div>`;
  const ico = { buy: "cart", build: "hammer", hybrid: "merge" }[bb.decision] || "help";
  return `<div class="bb bb-${bb.decision}">
    <div class="bb-head">
      <span class="bb-badge">${icon(ico, 15)} ${esc(bb.decision.toUpperCase())}</span>
      <span class="muted small">confidence ${esc(bb.confidence)}${bb.source === "rules" ? " · rule-based" : ""}</span>
    </div>
    <p class="bb-headline">${esc(bb.headline)}</p>
    <ul class="bb-list">${(bb.reasons || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    ${(bb.risks || []).length ? `<ul class="bb-list risks">${bb.risks.map((x) => `<li>${icon("alert", 12)} ${esc(x)}</li>`).join("")}</ul>` : ""}
    ${bb.next_step ? `<p class="bb-next">${icon("arrow", 13)} ${esc(bb.next_step)}</p>` : ""}
  </div>`;
}

function verdictRows(vs) {
  return (vs || [])
    .map(
      (v) => `<details class="claim" data-key="claim|${esc(v.label)}|${esc(v.value)}|${esc(v.quote || "")}">
      <summary>
        <span class="verdict v-${v.verdict}">${icon({ verified: "check", contradicted: "x", unverified: "help" }[v.verdict], 11)}${v.verdict}</span>
        <span class="claim-field">${esc(v.label)}</span>
        <span class="claim-val">${fmtNum(v.value)}${v.unit ? " " + esc(v.unit) : ""}${v.independent_value ? ` <span class="muted">· independent: ${esc(v.independent_value)}</span>` : ""}</span>
        ${icon("chevron", 13, "chev")}
      </summary>
      <div class="claim-body">
        ${v.quote ? `<p class="quote">Vendor page: “${esc(v.quote)}”</p>` : ""}
        ${
          (v.evidence || []).length
            ? `${v.evidence[0].note ? `<p>${esc(v.evidence[0].note)}</p>` : ""}${v.evidence
                .map((e) => `<a class="src" href="${esc(e.url)}" target="_blank" rel="noopener">${icon("external", 11)} ${esc(e.domain)} <span class="engine">${esc(String(e.engine).replaceAll("telem:", "telem·").replaceAll("+", " + "))}</span></a>`)
                .join("")}`
            : '<p class="muted">No independent evidence found.</p>'
        }
      </div>
    </details>`
    )
    .join("");
}

function hwResultCard(k, i) {
  const facts = [
    k.business_type && k.business_type !== "unknown" ? k.business_type : null,
    k.founded_year ? `founded ${k.founded_year}` : null,
    k.domain_age_years != null ? `domain ${k.domain_age_years}y` : null,
    k.release_year ? `released ${k.release_year}` : null,
    k.deployment_level && k.deployment_level !== "no evidence" ? k.deployment_level : null,
  ].filter(Boolean);
  return `<article class="result ${k.final ? "final" : ""}">
    <div class="result-head">
      <span class="rank">${i + 1}</span>
      <div class="result-title">
        <a href="${esc(k.url)}" target="_blank" rel="noopener">${esc(k.name)} ${icon("external", 12)}</a>
        <span class="muted small">${esc(k.vendor)}${money(k.price_usd) ? " · " + money(k.price_usd) : ""}${k.availability ? " · " + esc(k.availability) : ""}</span>
      </div>
      <div class="result-score">
        <span class="score">${k.score != null ? Number(k.score).toFixed(2) : "—"}</span>
        <span class="risk risk-${esc(k.risk)}">${icon("shield", 11)} risk ${esc(k.risk)}</span>
      </div>
    </div>
    ${k.final && i === 0 ? `<div class="top-pick">${icon("flag", 12)} Top pick</div>` : ""}
    <div class="chips">${Object.entries(k.fit || {})
      .map(([f, v]) => `<span class="chip fit-${v}">${icon({ meets: "check", fails: "x", unknown: "help" }[v], 11)}${esc(label(f))}</span>`)
      .join("")}</div>
    <div class="claims">${verdictRows(k.verdicts)}</div>
    ${facts.length ? `<p class="facts">${icon("building", 12)} ${facts.map(esc).join(" · ")}</p>` : ""}
    ${k.recommendation ? `<p class="rec">${esc(k.recommendation)}</p>` : ""}
  </article>`;
}

function swResultCard(k, i) {
  const facts = [
    ["scale", k.license],
    ["dollar", k.cost_model],
    ["branch", k.maintenance],
    ["activity", k.maturity],
  ].filter(([, v]) => v && v !== "unknown");
  return `<article class="result final">
    <div class="result-head">
      <span class="rank">${i + 1}</span>
      <div class="result-title">
        <a href="${esc(k.url)}" target="_blank" rel="noopener">${esc(k.name)} ${icon("external", 12)}</a>
        <span class="muted small">${esc(k.vendor)} · <span class="kind kind-${esc((k.kind || "").replace(/\s/g, "-"))}">${esc(k.kind)}</span></span>
      </div>
      <div class="result-score">
        <span class="valid valid-${esc((k.validation || "").replace(/\s/g, "-"))}">${icon("shield", 11)} ${esc(k.validation)}</span>
        <span class="muted small">fit ${esc(k.fit)}</span>
      </div>
    </div>
    ${i === 0 ? `<div class="top-pick">${icon("flag", 12)} Top pick</div>` : ""}
    <div class="chips">${facts.map(([ic, v]) => `<span class="chip">${icon(ic, 11)}${esc(v)}</span>`).join("")}${k.integration ? `<span class="chip">${icon("merge", 11)}${esc(k.integration)}</span>` : ""}</div>
    <p class="rec">${esc(k.reason)}</p>
    <div class="srcs">${(k.sources || []).map((s) => `<a class="src" href="${esc(s.url)}" target="_blank" rel="noopener">${icon("external", 11)} ${esc(s.domain)} <span class="engine">${esc(String(s.engine).replaceAll("telem:", "telem·").replaceAll("+", " + "))}</span></a>`).join("")}</div>
  </article>`;
}

function eliminatedList(rows) {
  if (!rows || !rows.length) return "";
  return `<details class="elim" data-key="elim|${esc(rows[0].name)}|${rows.length}">
    <summary>${icon("x", 13)} ${rows.length} eliminated ${icon("chevron", 13, "chev")}</summary>
    <ul>${rows
      .map(
        (e) => `<li><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.name)}</a> <span class="muted small">· ${esc(e.vendor || "")}</span>
          <ul class="reasons">${(e.reasons || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></li>`
      )
      .join("")}</ul>
  </details>`;
}

function verifyBlock(entry, kind) {
  const done = Array.isArray(entry.kept);
  const status =
    kind === "hardware"
      ? entry.verifier === "done"
        ? pill("done", "verified")
        : entry.catalog === "running"
          ? pill("running", "reading pages")
          : entry.verifier === "running"
            ? pill("running", "verifying claims")
            : pill(entry.verifier === "error" || entry.catalog === "error" ? "error" : entry.verifier, entry.verifier)
      : entry.verify === "done"
        ? pill("done", "validated")
        : pill(entry.verify, entry.verify === "running" ? "validating" : entry.verify);
  const finals = done ? (kind === "hardware" ? entry.kept.filter((k) => k.final) : entry.kept) : [];
  const extra = done && kind === "hardware" ? entry.kept.filter((k) => !k.final) : [];
  return `<article class="res-block verify">
    <div class="res-head">
      <span class="req-ico">${icon(kind === "hardware" ? componentIcon(entry.name) : "code", 16)}</span>
      <h4>${esc(entry.name)}</h4>
      ${status}
    </div>
    ${kind === "hardware" && entry.constraints?.length ? `<div class="chips">${entry.constraints.map((c) => `<span class="chip ghost-chip">${esc(c)}</span>`).join("")}${entry.budget_usd ? `<span class="chip ghost-chip">≤ ${money(entry.budget_usd)}/unit</span>` : ""}</div>` : ""}
    ${done ? buildBuyCard(entry.buildbuy) : '<div class="skeleton"></div><div class="skeleton short"></div>'}
    ${
      done
        ? `<h5 class="list-title">${icon("check", 13)} Final list <span class="muted">(${finals.length})</span></h5>
           ${finals.map(kind === "hardware" ? hwResultCard : swResultCard).join("") || `<p class="empty">${icon("alert", 14)} No option passed validation for this requirement.</p>`}
           ${extra.length ? `<details class="elim also" data-key="also|${esc(entry.name)}"><summary>${icon("list", 13)} ${extra.length} more passed ${icon("chevron", 13, "chev")}</summary>${extra.map((k, i) => hwResultCard(k, i + finals.length)).join("")}</details>` : ""}
           ${eliminatedList(entry.eliminated)}`
        : ""
    }
  </article>`;
}

function traceHtml(t) {
  if (!t) return "";
  const stages = Object.entries(t.by_stage || {});
  return `<details class="trace" data-key="trace">
    <summary>${icon("activity", 14)} Telem trace · ${t.telem_calls} provider runs · ${t.tavily_calls} Tavily calls · ${Object.keys(t.providers).length} providers ${icon("chevron", 13, "chev")}</summary>
    <p class="muted small">One session for the whole run: <code>${esc(t.session_id)}</code>${t.errors ? ` · ${t.errors} errors` : ""}</p>
    <div class="chips">${Object.entries(t.providers).map(([p, n]) => `<span class="chip">${esc(p)} <b>${n}</b></span>`).join("")}</div>
    <table class="trace-table"><thead><tr><th>Stage</th><th>Search runs</th><th>Fetches</th><th>Tavily</th><th>Provider time</th></tr></thead>
      <tbody>${stages.map(([s, v]) => `<tr><td>${esc(s)}</td><td>${v.search}</td><td>${v.fetch}</td><td>${v.tavily}</td><td>${(v.latency_ms / 1000).toFixed(1)}s</td></tr>`).join("")}</tbody></table>
  </details>`;
}

function renderVerify() {
  const el = $("step-verify");
  const r = state.run;
  el.hidden = !r || r.steps.verify.state === "pending";
  if (el.hidden) return;
  const hwDone = r.hardware.filter((h) => Array.isArray(h.kept));
  const kept = hwDone.reduce((n, h) => n + h.kept.filter((k) => k.final).length, 0);
  const elim = hwDone.reduce((n, h) => n + h.eliminated.length, 0);
  setHTML(el, `
    <div class="panel-head">
      <span class="step-no">04</span>
      <div>
        <h2>Verification &amp; Build vs Buy</h2>
        <p class="sub">Each candidate's claims are checked against independent sources; failures are eliminated with reasons.${hwDone.length ? ` Hardware so far: ${kept} shortlisted, ${elim} eliminated.` : ""}</p>
      </div>
      <div class="head-actions">${pill(r.steps.verify.state, r.steps.verify.seconds != null ? `${r.steps.verify.seconds}s` : "running")}</div>
    </div>
    ${r.error && r.phase !== "search" ? `<p class="error">${esc(r.error)}</p>` : ""}
    <div class="split">
      <div class="col">
        <div class="col-head">${icon("cpu", 16)}<h3>Hardware</h3><span class="count">${r.hardware.length}</span></div>
        ${r.hardware.map((h) => verifyBlock(h, "hardware")).join("")}
      </div>
      <div class="col">
        <div class="col-head">${icon("code", 16)}<h3>Software</h3><span class="count">${r.software.length}</span></div>
        ${r.software.map((s) => verifyBlock(s, "software")).join("") || '<p class="muted small">No software requirements.</p>'}
      </div>
    </div>
    ${traceHtml(r.trace)}`);
}

// ---------------------------------------------------------------- step 5: report + outreach

function markdown(md) {
  if (window.marked && window.DOMPurify) return window.DOMPurify.sanitize(window.marked.parse(md || ""));
  return `<pre class="md-fallback">${esc(md)}</pre>`;
}

function personCard(p, company) {
  return `<article class="person">
    <div class="avatar">${esc(initials(p.name))}</div>
    <div class="person-body">
      <div class="person-name">${esc(p.name)}</div>
      <div class="muted small">${esc(p.title)}${p.title ? " · " : ""}${esc(company.company)}</div>
      ${p.why_reach_out ? `<p class="small">${esc(p.why_reach_out)}</p>` : ""}
      <div class="person-links">
        ${p.linkedin ? `<a class="icon-link" href="${esc(p.linkedin)}" target="_blank" rel="noopener" title="LinkedIn">${icon("linkedin", 14)}</a>` : ""}
        ${p.email ? `<a class="icon-link" href="mailto:${esc(p.email)}" title="${esc(p.email)}">${icon("mail", 14)}</a>` : ""}
        ${p.source_url ? `<a class="icon-link" href="${esc(p.source_url)}" target="_blank" rel="noopener" title="Source">${icon("external", 14)}</a>` : ""}
      </div>
    </div>
  </article>`;
}

function emailCard(m, company, ci, mi) {
  const person = (company.people || []).find((p) => p.name === m.to_name);
  const mailto = person && person.email ? `mailto:${encodeURIComponent(person.email)}?subject=${encodeURIComponent(m.subject)}&body=${encodeURIComponent(m.body)}` : null;
  return `<article class="email">
    <div class="email-head">
      <div>
        <div class="small muted">To</div>
        <div><b>${esc(m.to_name)}</b> <span class="muted small">${esc(m.to_title)} · ${esc(company.company)}</span></div>
      </div>
      <div class="email-actions">
        ${mailto ? `<a class="btn ghost sm" href="${mailto}">${icon("mail", 13)} Open in mail</a>` : ""}
        <button class="btn ghost sm" data-copy="${ci}:${mi}">${icon("copy", 13)} Copy</button>
      </div>
    </div>
    <div class="email-subject">${esc(m.subject)}</div>
    <textarea class="email-body" rows="7" data-body="${ci}:${mi}">${esc(m.body)}</textarea>
  </article>`;
}

function renderOutreach() {
  const el = $("step-outreach");
  const r = state.run;
  el.hidden = !r || !["outreach", "done"].includes(r.phase) && r.steps.outreach.state === "pending";
  if (el.hidden) return;
  const o = r.outreach;
  const running = r.steps.outreach.state !== "done";
  const companies = (o && o.companies) || [];
  const people = companies.flatMap((c) => (c.people || []).map((p) => [p, c]));
  const emails = companies.flatMap((c, ci) => (c.emails || []).map((m, mi) => [m, c, ci, mi]));
  const tabs = [
    ["briefing", "file-text", "Briefing"],
    ["people", "users", `People (${people.length})`],
    ["emails", "mail", `Email drafts (${emails.length})`],
  ];
  setHTML(el, `
    <div class="panel-head">
      <span class="step-no">05</span>
      <div>
        <h2>Report &amp; outreach</h2>
        <p class="sub">Buyer briefing from the verified results, the people to contact at each manufacturer and seller, and ready-to-send drafts.</p>
      </div>
      <div class="head-actions">${pill(r.steps.outreach.state, running ? "drafting" : `${r.steps.outreach.seconds}s`)}
        ${!running ? `<a class="btn ghost sm" href="/api/run/${r.id}/download/report.md">${icon("download", 13)} Report</a><a class="btn ghost sm" href="/api/run/${r.id}/download/outreach.md">${icon("download", 13)} Outreach</a>` : ""}
      </div>
    </div>
    ${
      running
        ? `<div class="drafting">${icon("loader", 18, "spin")}<div><b>Writing the briefing and finding contacts</b><p class="muted small">Claude summarises the verified shortlist; Tavily finds leadership and sales contacts at each company; drafts are written per person.</p></div></div>`
        : !o || !o.ok
          ? `<p class="error">${icon("alert", 14)} The final agent did not produce output. See the run log.</p>`
          : `<div class="tabs">${tabs.map(([k, ic, t]) => `<button class="tab ${state.tab === k ? "on" : ""}" data-tab="${k}">${icon(ic, 14)} ${t}</button>`).join("")}</div>
        <div class="tab-body">
          ${state.tab === "briefing" ? `<div class="md">${markdown(o.report)}</div>` : ""}
          ${
            state.tab === "people"
              ? companies
                  .map(
                    (c) => `<div class="company">
                <div class="company-head">${icon("building", 15)}<b>${esc(c.company)}</b>
                  ${c.role ? `<span class="role role-${esc(c.role)}">${esc(c.role)}</span>` : ""}
                  ${c.risk ? `<span class="risk risk-${esc(c.risk)}">risk ${esc(c.risk)}</span>` : ""}
                  ${c.domain ? `<span class="muted small">${esc(host(c.domain))}</span>` : ""}</div>
                <div class="people">${(c.people || []).map((p) => personCard(p, c)).join("") || '<p class="muted small">No sourced contacts found.</p>'}</div>
              </div>`
                  )
                  .join("")
              : ""
          }
          ${state.tab === "emails" ? emails.map(([m, c, ci, mi]) => emailCard(m, c, ci, mi)).join("") || '<p class="muted small">No drafts (no contacts were found).</p>' : ""}
        </div>`
    }`);
}

$("step-outreach").addEventListener("click", async (e) => {
  const tab = e.target.closest("[data-tab]");
  if (tab) {
    state.tab = tab.dataset.tab;
    renderOutreach();
    return;
  }
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    const [ci, mi] = copy.dataset.copy.split(":").map(Number);
    const m = state.run.outreach.companies[ci].emails[mi];
    const body = document.querySelector(`[data-body="${ci}:${mi}"]`)?.value ?? m.body;
    await navigator.clipboard.writeText(`Subject: ${m.subject}\n\n${body}`);
    toast("Email copied");
  }
});

// ---------------------------------------------------------------- log + render all

function renderLog() {
  const r = state.run;
  $("run-log").hidden = !r;
  if (r) $("run-log").querySelector("pre").textContent = (r.log || []).join("\n");
}

function renderAll() {
  renderStepper();
  renderProblem();
  renderRequirements();
  renderSearch();
  renderVerify();
  renderOutreach();
  renderLog();
}

// ---------------------------------------------------------------- boot: restore saved spec + latest run

(async function boot() {
  renderAll();
  try {
    const spec = await api("/api/spec");
    if (spec && (spec.checklists || []).length) {
      state.bundle = spec;
      $("problem-input").value = spec.checklists[0].problem_statement || "";
    }
  } catch {
    /* no saved spec */
  }
  try {
    const run = await api("/api/run/latest");
    const problem = state.bundle?.checklists?.[0]?.problem_statement;
    if (run && run.problem === problem) {
      state.run = run;
      state.runRev = state.specRev;
      if (run.state === "running") poll();
    }
  } catch {
    /* no run yet */
  }
  renderAll();
})();
