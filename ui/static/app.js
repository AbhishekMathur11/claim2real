import { mountThinkingOrb } from "./orb.js";

const $ = (id) => document.getElementById(id);

const state = {
  bundle: null,
  dirty: false,
  busy: false,
};

const think = $("think");
const thread = $("thread");
const form = $("chat-form");
const input = $("chat-input");
const sendBtn = $("send-btn");
const errorEl = $("error");
const orbCanvas = $("orb");

let stopOrb = null;

function formatDetail(data) {
  const detail = data && data.detail;
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  return JSON.stringify(detail);
}

function showError(msg) {
  errorEl.hidden = !msg;
  errorEl.textContent = msg || "";
}

function resize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
}

function chips(items, extra = "") {
  return (items || [])
    .map((item) => `<span class="chip ${extra}">${escapeHtml(item)}</span>`)
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function constraintRows(list, ci, name) {
  return (list || [])
    .map((row, ri) => {
      const numeric = row.unit != null;
      return `<tr>
        <td class="field">${escapeHtml(row.field)}</td>
        <td class="op">${escapeHtml(row.operator)}</td>
        <td>
          <input
            type="${numeric ? "number" : "text"}"
            ${numeric ? 'step="any"' : ""}
            value="${escapeHtml(row.value)}"
            data-ci="${ci}"
            data-list="${name}"
            data-ri="${ri}"
            data-numeric="${numeric}"
          />
        </td>
        <td class="unit">${escapeHtml(row.unit || "")}</td>
      </tr>`;
    })
    .join("");
}

function cardHtml(item, ci) {
  return `<article class="card">
    <div class="card-head">
      <h3>${escapeHtml(item.component_type)}</h3>
      <div class="meta">
        <label>Qty<input type="number" min="1" step="1" value="${item.quantity ?? 1}" data-meta="${ci}:quantity" /></label>
        <label>Budget USD<input type="number" step="1" value="${item.budget_usd ?? ""}" data-meta="${ci}:budget_usd" /></label>
        <label>Lead days<input type="number" step="1" value="${item.max_lead_time_days ?? ""}" data-meta="${ci}:max_lead_time_days" /></label>
      </div>
    </div>
    <div class="chips">${chips(item.search_terms)}${chips(item.software, "soft")}</div>
    <table>
      <tbody>
        ${constraintRows(item.must_have, ci, "must_have")}
        ${constraintRows(item.nice_to_have, ci, "nice_to_have")}
      </tbody>
    </table>
  </article>`;
}

function setOrb(on) {
  if (on) {
    think.hidden = false;
    if (!stopOrb) stopOrb = mountThinkingOrb(orbCanvas);
    return;
  }
  think.hidden = true;
  if (stopOrb) {
    stopOrb();
    stopOrb = null;
  }
}

function render() {
  const bundle = state.bundle;
  const hasSpec = bundle && (bundle.checklists || []).length;
  setOrb(state.busy);
  thread.hidden = !hasSpec || state.busy;

  if (!hasSpec || state.busy) {
    if (!state.busy) thread.innerHTML = "";
    return;
  }

  thread.innerHTML = `<section class="sheet">
    <div class="sheet-bar">
      <button id="save-btn" class="ghost" type="button" ${state.dirty ? "" : "disabled"}>Save</button>
    </div>
    <div class="inventory">
      <div class="chips">${chips(bundle.hardware)}</div>
      <div class="chips">${chips(bundle.software, "soft")}</div>
    </div>
    ${(bundle.checklists || []).map(cardHtml).join("")}
  </section>`;
  $("save-btn")?.addEventListener("click", save);
}

function markDirty() {
  state.dirty = true;
  const btn = $("save-btn");
  if (btn) btn.disabled = false;
}

function onInputChange(event) {
  const el = event.target;
  if (!(el instanceof HTMLInputElement) || !state.bundle) return;
  if (el.dataset.list) {
    const item = state.bundle.checklists[Number(el.dataset.ci)][el.dataset.list][
      Number(el.dataset.ri)
    ];
    item.value = el.dataset.numeric === "true" ? Number(el.value) : el.value;
    markDirty();
    return;
  }
  if (el.dataset.meta) {
    const [ci, key] = el.dataset.meta.split(":");
    const card = state.bundle.checklists[Number(ci)];
    const raw = el.value;
    if (raw === "") {
      card[key] = key === "quantity" ? 1 : null;
    } else {
      card[key] = Number(raw);
    }
    markDirty();
  }
}

async function generate(problem) {
  showError("");
  state.busy = true;
  state.dirty = false;
  render();
  sendBtn.disabled = true;
  input.readOnly = true;
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(formatDetail(data) || res.statusText);
    state.bundle = data;
    state.dirty = false;
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    state.busy = false;
    sendBtn.disabled = false;
    input.readOnly = false;
    render();
    input.focus();
  }
}

async function save() {
  if (!state.bundle) return;
  showError("");
  const btn = $("save-btn");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/spec", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.bundle),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(formatDetail(data) || res.statusText);
    state.bundle = data;
    state.dirty = false;
    render();
  } catch (err) {
    showError(err.message || String(err));
    if (btn) btn.disabled = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const problem = input.value.trim();
  if (!problem || state.busy) return;
  generate(problem);
});

input.addEventListener("input", resize);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

thread.addEventListener("change", onInputChange);
thread.addEventListener("input", (event) => {
  if (event.target instanceof HTMLInputElement) markDirty();
});
