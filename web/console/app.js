/* HSS security console: login, navigation and pages. No framework, no build step, no internet needed. */
"use strict";

/* ---------------- helpers ---------------- */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;                 // only ever used with our own static icons
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(9)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = sel => document.querySelector(sel);
class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    method: opts.method || "GET", credentials: "same-origin",
    headers: { "X-HSS": "1", ...(opts.body ? { "Content-Type": "application/json" } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) {
    const msg = data && (typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? data.detail.map(d => d.msg).join("; ") : "") || `Error ${r.status}`;
    if (r.status === 401 && !path.startsWith("/auth/login")) { state.user = null; render(); }
    throw new ApiError(r.status, msg);
  }
  return data;
}
const fmtTime = t => t ? new Date(t).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
const ago = t => {
  if (!t) return "never";
  const s = (Date.now() - new Date(t)) / 1000;
  if (s < 60) return "just now"; if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`; return `${Math.round(s / 86400)} days ago`;
};
const delay = ms => { const s = ms / 1000; return s < 60 ? `${s.toFixed(1)} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`; };
const initials = u => (u.display_name || u.username || "?").split(/[\s._@-]+/).filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join("");
const ROLE_NAMES = { admin: "Administrator", cso: "Chief Security Officer", operator: "Operator", management: "Management" };
function toast(msg) {
  const t = h("div", { class: "toast", role: "status" }, msg);
  document.body.append(t); setTimeout(() => t.remove(), 3500);
}
function modal(title, body, actions) {
  const buttons = h("div", { class: "toolbar", style: "justify-content:flex-end" });
  const scrim = h("div", { class: "modal-scrim" },
    h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title }, h("h2", {}, title), body, buttons));
  scrim.addEventListener("click", e => { if (e.target === scrim) scrim.remove(); });
  buttons.append(...actions(scrim));          // the buttons get the finished dialog, so they can close it
  document.body.append(scrim);
  const first = scrim.querySelector("input, select, button"); if (first) first.focus();
  return scrim;
}

/* ---------------- icons (static, ours) ---------------- */
const I = {
  logo: '<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2"><circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="2" fill="white" stroke="none"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3" stroke-linecap="round"/></svg>',
  overview: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="9" rx="2"/><rect x="14" y="3" width="7" height="5" rx="2"/><rect x="14" y="12" width="7" height="9" rx="2"/><rect x="3" y="16" width="7" height="5" rx="2"/></svg>',
  live: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/></svg>',
  events: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 8a6 6 0 1112 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 20a2 2 0 004 0"/></svg>',
  devices: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/></svg>',
  walls: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
  map: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/></svg>',
  reports: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 3h9l4 4v14H6z"/><path d="M9 13h6M9 17h6M9 9h3"/></svg>',
  notify: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 12a8 8 0 01-11.6 7.1L4 21l1.9-5.4A8 8 0 1121 12z"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.7-3.6 3.3-5.5 6.5-5.5s5.8 1.9 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 010 7M18 14.8c1.9.7 3.1 2.4 3.5 5.2"/></svg>',
  audit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/></svg>',
  menu: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  logout: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/></svg>',
};
const icon = name => h("span", { html: I[name], style: "display:contents" });

/* ---------------- state and routing ---------------- */
const state = { user: null, branding: { site_name: "Security Console", accent: "#2563eb", has_logo: false }, cleanup: [] };
const PAGES = [
  { group: "Monitor" },
  { id: "overview", title: "Overview", icon: "overview", roles: ["admin", "cso", "operator", "management"], view: viewOverview },
  { id: "live", title: "Live view", icon: "live", roles: ["admin", "cso", "operator"], view: viewLive },
  { id: "events", title: "Events", icon: "events", roles: ["admin", "cso", "operator"], view: viewEvents },
  { id: "map", title: "Site map", icon: "map", roles: ["admin", "cso", "operator"], view: viewMap, preview: true },
  { group: "Manage" },
  { id: "devices", title: "Devices", icon: "devices", roles: ["admin", "cso", "operator", "management"], view: viewDevices },
  { id: "walls", title: "Video walls", icon: "walls", roles: ["admin", "cso"], view: viewWalls },
  { id: "reports", title: "Reports", icon: "reports", roles: ["admin", "cso", "management"], view: viewReports },
  { id: "notify", title: "WhatsApp & alerts", icon: "notify", roles: ["admin", "cso"], view: viewNotify },
  { group: "Administration", roles: ["admin"] },
  { id: "users", title: "Users", icon: "users", roles: ["admin"], view: viewUsers },
  { id: "audit", title: "Audit log", icon: "audit", roles: ["admin"], view: viewAudit },
  { id: "settings", title: "Settings", icon: "settings", roles: ["admin", "cso", "operator", "management"], view: viewSettings },
];
const allowed = p => p.view && p.roles.includes(state.user.role);
function currentPage() {
  const id = location.hash.replace(/^#\/?/, "") || "overview";
  return PAGES.find(p => p.id === id && allowed(p)) || PAGES.find(p => p.id === "overview");
}
window.addEventListener("hashchange", () => render());

function applyBranding() {
  document.documentElement.style.setProperty("--accent", state.branding.accent || "#2563eb");
  document.title = state.branding.site_name;
}
function brandBlock(sub) {
  const b = state.branding;
  return h("div", { class: "brand" },
    b.has_logo ? h("img", { src: `/api/branding/logo?v=${b.v || 0}`, alt: "" }) : h("div", { class: "mark", html: I.logo }),
    h("div", {}, h("div", { class: "name" }, b.site_name), sub ? h("div", { class: "sub" }, sub) : null));
}

async function boot() {
  try { state.branding = { ...state.branding, ...(await api("/branding")) }; } catch (_) { /* defaults */ }
  applyBranding();
  try { state.user = await api("/auth/me"); } catch (_) { state.user = null; }
  render();
}

function closeOverlays() { document.querySelectorAll(".scrim, .modal-scrim").forEach(el => el.remove()); }
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  const open = document.querySelectorAll(".scrim, .modal-scrim");
  if (open.length) open[open.length - 1].remove();
});

function render() {
  closeOverlays();
  state.cleanup.forEach(fn => { try { fn(); } catch (_) { /* ignore */ } });
  state.cleanup = [];
  const app = $("#app");
  app.replaceChildren();
  if (!state.user) return app.append(viewLogin());
  if (state.user.must_change_password) return app.append(viewForcedPassword());
  app.append(viewShell(currentPage()));
}

/* ---------------- login ---------------- */
function viewLogin() {
  let needCode = false;
  const err = h("div", { class: "error", hidden: true });
  const user = h("input", { class: "input", id: "u", autocomplete: "username", required: true, autofocus: true });
  const pass = h("input", { class: "input", id: "p", type: "password", autocomplete: "current-password", required: true });
  const code = h("input", { class: "input code-input", id: "c", inputmode: "numeric", autocomplete: "one-time-code", maxlength: 7, placeholder: "000000" });
  const codeField = h("div", { class: "field", hidden: true }, h("label", { for: "c" }, "Code from your authenticator app"), code);
  const btn = h("button", { class: "btn primary block", type: "submit" }, "Sign in");
  const form = h("form", {
    onsubmit: async e => {
      e.preventDefault(); err.hidden = true; btn.disabled = true; btn.textContent = "Signing in…";
      try {
        const res = await api("/auth/login", { method: "POST", body: { username: user.value.trim(), password: pass.value, code: needCode ? code.value : null } });
        if (res.need_code) {
          needCode = true; codeField.hidden = false; user.disabled = pass.disabled = true; code.focus();
          btn.textContent = "Verify"; btn.disabled = false; return;
        }
        state.user = res.user; render();
      } catch (ex) {
        err.textContent = ex.message; err.hidden = false; btn.disabled = false; btn.textContent = needCode ? "Verify" : "Sign in";
        if (needCode) { code.value = ""; code.focus(); } else pass.select();
      }
    },
  }, err,
    h("div", { class: "field" }, h("label", { for: "u" }, "Username"), user),
    h("div", { class: "field" }, h("label", { for: "p" }, "Password"), pass),
    codeField, btn);
  return h("div", { class: "login-wrap" },
    h("div", { class: "login" }, brandBlock("Security operations console"),
      h("h1", { style: "margin-bottom:4px" }, "Sign in"),
      h("p", { class: "muted", style: "margin:0 0 18px" }, "Use the account your administrator gave you."),
      form,
      h("div", { class: "foot" }, h("span", {}, "Forgot your password? Ask your administrator."), h("span", {}, "v0.5"))));
}

function viewForcedPassword() {
  const err = h("div", { class: "error", hidden: true });
  const cur = h("input", { class: "input", type: "password", autocomplete: "current-password" });
  const nw = h("input", { class: "input", type: "password", autocomplete: "new-password", minlength: 12 });
  const nw2 = h("input", { class: "input", type: "password", autocomplete: "new-password" });
  return h("div", { class: "login-wrap" }, h("div", { class: "login" }, brandBlock(),
    h("h1", { style: "margin-bottom:6px" }, "Choose your own password"),
    h("p", { class: "muted", style: "margin:0 0 16px" }, "You signed in with a temporary password. Choose a new one of at least 12 characters (a short sentence works well)."),
    h("form", { onsubmit: async e => {
      e.preventDefault(); err.hidden = true;
      if (nw.value !== nw2.value) { err.textContent = "The new passwords don't match."; err.hidden = false; return; }
      try {
        await api("/auth/password", { method: "POST", body: { current: cur.value, new: nw.value } });
        state.user = await api("/auth/me"); toast("Password changed"); render();
      } catch (ex) { err.textContent = ex.message; err.hidden = false; }
    } }, err,
      h("div", { class: "field" }, h("label", {}, "Temporary password"), cur),
      h("div", { class: "field" }, h("label", {}, "New password"), nw),
      h("div", { class: "field" }, h("label", {}, "New password again"), nw2),
      h("button", { class: "btn primary block", type: "submit" }, "Save and continue")),
    h("div", { class: "foot" }, h("a", { href: "#", onclick: e => { e.preventDefault(); logout(); } }, "Sign out"), h("span", {}))));
}

async function logout() {
  try { await api("/auth/logout", { method: "POST" }); } catch (_) { /* already gone */ }
  state.user = null; location.hash = ""; render();
}

/* ---------------- shell ---------------- */
function viewShell(page) {
  const u = state.user;
  const nav = h("nav", { class: "nav", "aria-label": "Main" });
  for (const p of PAGES) {
    if (p.group) { if (!p.roles || p.roles.includes(u.role)) nav.append(h("div", { class: "group" }, p.group)); continue; }
    if (!allowed(p)) continue;
    nav.append(h("a", { href: `#/${p.id}`, class: p === page ? "active" : null, "aria-current": p === page ? "page" : null },
      icon(p.icon), p.title, p.preview ? h("span", { class: "tag" }, "preview") : null));
  }
  const clock = h("span", { class: "clock" });
  const tick = () => { clock.textContent = new Date().toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
  tick(); const t = setInterval(tick, 1000); state.cleanup.push(() => clearInterval(t));
  const statusPills = h("div", { class: "toolbar" });
  const content = h("main", { class: "content", id: "content" });
  const shell = h("div", { class: "shell" },
    h("aside", { class: "side" }, brandBlock("Security console"), nav,
      h("div", { class: "me" }, h("div", { class: "avatar", "aria-hidden": "true" }, initials(u)),
        h("div", { class: "who" }, h("div", { style: "font-weight:600" }, u.display_name || u.username), h("div", { class: "muted", style: "font-size:12px" }, ROLE_NAMES[u.role])),
        h("button", { class: "btn small", title: "Sign out", "aria-label": "Sign out", onclick: logout, html: I.logout }))),
    h("div", { class: "main" },
      h("header", { class: "top" },
        h("button", { class: "btn small menu-btn", "aria-label": "Menu", html: I.menu, onclick: () => shell.classList.toggle("open") }),
        h("h1", {}, page.title), page.preview ? h("span", { class: "badge preview" }, "Preview") : null,
        h("div", { class: "spacer" }), statusPills, clock),
      content));
  nav.addEventListener("click", () => shell.classList.remove("open"));
  loadStatusPills(statusPills);
  Promise.resolve(page.view(content)).catch(e => content.replaceChildren(h("div", { class: "error" }, `Couldn't load this page: ${e.message}`)));
  return shell;
}

async function loadStatusPills(box) {
  if (!["admin", "cso"].includes(state.user.role)) return;
  try {
    const o = await api("/overview");
    const wa = o.whatsapp.status;
    box.replaceChildren(
      h("span", { class: "pill hide-sm" }, h("span", { class: `dot ${wa === "ready" ? "ok" : wa === "unknown" ? "" : "bad"}` }), `WhatsApp ${wa}`),
      h("span", { class: "pill hide-sm" }, h("span", { class: `dot ${o.walls.online ? "ok" : "warn"}` }), `Walls ${o.walls.online}/${o.walls.total}`));
  } catch (_) { /* pills are optional */ }
}

/* ---------------- overview ---------------- */
async function viewOverview(c) {
  c.append(h("div", { class: "muted" }, "Loading…"));
  const o = await api("/overview");
  const canEvents = ["admin", "cso", "operator"].includes(state.user.role);
  const [events, devices] = await Promise.all([canEvents ? api("/events?limit=8") : [], api("/devices")]);
  const d = o.devices, pct = d.cameras ? Math.round(100 * d.online / d.cameras) : 0;
  const ev = o.events_24h;
  c.replaceChildren(
    h("div", { class: "grid kpis" },
      kpi("Cameras online", d.cameras ? h("span", {}, d.online, h("small", {}, ` / ${d.cameras}`)) : "—",
        d.probed_at ? `${d.nvrs} NVRs · probed ${ago(d.probed_at)}` : "No probe data yet", d.cameras ? pct : null),
      kpi("Events, last 24 h", ev.critical + ev.warning + ev.info, h("span", {},
        h("span", { class: "badge bad" }, `${ev.critical} critical`), " ", h("span", { class: "badge warn" }, `${ev.warning} warning`))),
      kpi("Video wall PCs", h("span", {}, o.walls.online, h("small", {}, ` / ${o.walls.total} online`)), o.walls.total ? "Heartbeat every 15 s" : "No wall PCs registered"),
      kpi("WhatsApp alerts", h("span", { style: `color:${o.whatsapp.status === "ready" ? "var(--ok)" : "var(--warn)"}` }, o.whatsapp.status),
        `${o.whatsapp.sent_7d} of ${o.whatsapp.attempts_7d} messages sent this week`),
      kpi("NVR storage", d.nvr_disk_problems.length ? h("span", { style: "color:var(--bad)" }, `${d.nvr_disk_problems.length} fault`) : h("span", { style: "color:var(--ok)" }, "OK"),
        d.nvr_disk_problems.length ? d.nvr_disk_problems.join(", ") : "All drives healthy")),
    h("div", { class: "grid cols-2" },
      canEvents ? card("Latest events", h("a", { href: "#/events" }, "All events"), eventList(events)) : card("Your view", null, h("p", { class: "muted" }, "Management accounts see the overview, devices and reports.")),
      card("Needs attention", null, attentionList(devices))),
    card("NVRs", h("a", { href: "#/devices" }, "Devices"), nvrTable(devices.nvrs)));
}
function kpi(label, value, detail, barPct) {
  return h("div", { class: "card kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value),
    h("div", { class: "detail" }, detail), barPct !== null && barPct !== undefined ? h("div", { class: "bar" }, h("span", { style: `width:${barPct}%;background:${barPct > 90 ? "var(--ok)" : barPct > 75 ? "var(--warn)" : "var(--bad)"}` })) : null);
}
function card(title, extra, ...body) {
  return h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, title), h("div", { class: "spacer" }), extra), ...body);
}
function eventList(events) {
  if (!events.length) return h("div", { class: "empty" }, "No events yet. They appear here as soon as the AI workers or cameras report them.");
  return h("div", { class: "list" }, events.map(e => h("div", { class: "item clickable", style: "cursor:pointer", onclick: () => eventDrawer(e) },
    h("span", { class: `sev ${e.severity}` }),
    e.snapshot_url ? h("img", { class: "thumb", src: e.snapshot_url, alt: "", loading: "lazy" }) : h("div", { class: "thumb" }),
    h("div", { class: "grow" }, h("div", { class: "title" }, `${label(e.type)}${e.object_class ? ` · ${e.object_class}` : ""}`),
      h("div", { class: "muted", style: "font-size:12.5px" }, `${e.camera_id}${e.zone ? ` · ${e.zone}` : ""}`)),
    h("div", { class: "faint", style: "font-size:12px;text-align:right" }, ago(e.occurred_at)))));
}
const label = s => (s || "").replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
function attentionList(dev) {
  const items = [];
  for (const n of dev.nvrs) {
    if (n.disk_problem) items.push(["bad", `${n.name}: drive fault`, n.disks.filter(d => !["ok", "normal", "notexist", "idle"].includes((d.status || "").toLowerCase())).map(d => `${d.name} ${d.status}`).join(", ")]);
    const off = n.channels.filter(c => c.online === false);
    if (off.length) items.push(["warn", `${n.name}: ${off.length} camera${off.length > 1 ? "s" : ""} offline`, off.slice(0, 4).map(c => c.name).join(", ") + (off.length > 4 ? "…" : "")]);
    const drift = n.channels.filter(c => c.clock_drift_s !== null && c.clock_drift_s !== undefined && Math.abs(c.clock_drift_s) > 30);
    if (drift.length) items.push(["warn", `${n.name}: ${drift.length} camera clock${drift.length > 1 ? "s" : ""} wrong`, "Set cameras and NVRs to NTP"]);
    if (n.time_mode && n.time_mode.toLowerCase() !== "ntp") items.push(["info", `${n.name}: clock not on NTP`, `Time mode: ${n.time_mode}`]);
  }
  if (!dev.nvrs.length) return h("div", { class: "empty" }, "No probe data on the server yet (run hss-probe and hss-cameras).");
  if (!items.length) return h("div", { class: "empty" }, "Nothing needs attention.");
  return h("div", { class: "list" }, items.slice(0, 9).map(([lvl, t, d]) => h("div", { class: "item" },
    h("span", { class: `dot ${lvl}` }), h("div", { class: "grow" }, h("div", { class: "title" }, t), h("div", { class: "muted", style: "font-size:12.5px" }, d)))));
}
function nvrTable(nvrs) {
  if (!nvrs.length) return h("div", { class: "empty" }, "No NVRs yet.");
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["NVR", "Address", "Model", "Firmware", "Cameras online", "Drives", "Clock"].map(t => h("th", {}, t)))),
    h("tbody", {}, nvrs.map(n => h("tr", { class: "clickable", onclick: () => { location.hash = `#/devices?nvr=${encodeURIComponent(n.address)}`; } },
      h("td", { style: "font-weight:600" }, n.name), h("td", { class: "mono" }, n.address), h("td", {}, n.model), h("td", { class: "mono" }, n.firmware),
      h("td", {}, h("div", { style: "display:flex;align-items:center;gap:10px" }, `${n.online}/${n.total}`,
        h("div", { class: "bar", style: "width:90px;margin:0" }, h("span", { style: `width:${n.total ? 100 * n.online / n.total : 0}%;background:${n.online === n.total ? "var(--ok)" : "var(--warn)"}` })))),
      h("td", {}, n.disk_problem ? h("span", { class: "badge bad" }, "fault") : h("span", { class: "badge ok" }, "OK")),
      h("td", {}, (n.time_mode || "").toLowerCase() === "ntp" ? h("span", { class: "badge ok" }, "NTP") : h("span", { class: "badge warn" }, n.time_mode || "?")))))));
}

/* ---------------- events ---------------- */
async function viewEvents(c) {
  let sev = "all", q = "";
  const listBox = h("div", {});
  const events = await api("/events?limit=200");
  const draw = () => {
    const rows = events.filter(e => (sev === "all" || e.severity === sev) && (!q || `${e.camera_id} ${e.zone} ${e.type}`.toLowerCase().includes(q)));
    listBox.replaceChildren(rows.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["", "Snapshot", "Event", "Camera", "Zone", "Confidence", "Time", "Delay"].map(t => h("th", {}, t)))),
      h("tbody", {}, rows.map(e => h("tr", { class: "clickable", onclick: () => eventDrawer(e) },
        h("td", { style: "width:6px;padding-right:0" }, h("span", { class: `sev ${e.severity}`, style: "display:block;height:34px" })),
        h("td", {}, e.snapshot_url ? h("img", { class: "thumb", src: e.snapshot_url, alt: "", loading: "lazy" }) : h("div", { class: "thumb" })),
        h("td", {}, h("div", { style: "font-weight:600" }, label(e.type)), h("div", { class: "muted", style: "font-size:12px" }, `${e.object_class || ""} · tier ${e.tier}`)),
        h("td", {}, e.camera_id), h("td", {}, e.zone || "—"), h("td", {}, e.confidence ? `${Math.round(e.confidence * 100)}%` : "—"),
        h("td", {}, fmtTime(e.occurred_at)), h("td", { class: "muted" }, delay(e.latency_ms)))))))
      : h("div", { class: "empty" }, events.length ? "No events match." : "No events yet."));
  };
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Severity" }, ["all", "critical", "warning", "info"].map(s =>
    h("button", { class: s === sev ? "on" : null, onclick: e => { sev = s; seg.querySelectorAll("button").forEach(b => b.classList.remove("on")); e.target.classList.add("on"); draw(); } }, label(s))));
  c.append(h("div", { class: "toolbar" }, seg, h("input", { class: "input", type: "search", placeholder: "Search camera, zone or type", oninput: e => { q = e.target.value.toLowerCase(); draw(); } }),
    h("div", { style: "flex:1" }), h("span", { class: "muted" }, `${events.length} most recent`)),
    h("section", { class: "card", style: "padding:6px 8px" }, listBox));
  draw();
}
function eventDrawer(e) {
  const scrim = h("div", { class: "scrim", onclick: ev => { if (ev.target === scrim) scrim.remove(); } },
    h("div", { class: "drawer", role: "dialog", "aria-label": "Event" },
      h("div", { class: "toolbar" }, h("span", { class: `badge ${e.severity === "critical" ? "bad" : e.severity === "warning" ? "warn" : "info"}` }, e.severity),
        h("h2", {}, label(e.type)), h("div", { style: "flex:1" }), h("button", { class: "btn small", onclick: () => scrim.remove() }, "Close")),
      e.snapshot_url ? h("img", { class: "snapshot", src: e.snapshot_url, alt: `Snapshot from ${e.camera_id}` }) : h("div", { class: "empty card" }, "No snapshot for this event."),
      h("div", { class: "kv" },
        h("div", {}, "Camera"), h("div", {}, e.camera_id), h("div", {}, "Zone"), h("div", {}, e.zone || "—"),
        h("div", {}, "Object"), h("div", {}, e.object_class || "—"), h("div", {}, "Confidence"), h("div", {}, e.confidence ? `${Math.round(e.confidence * 100)}%` : "—"),
        h("div", {}, "Source"), h("div", {}, `${e.source_kind} (tier ${e.tier})${e.source_ref ? `, ${e.source_ref}` : ""}`),
        h("div", {}, "Happened"), h("div", {}, fmtTime(e.occurred_at)), h("div", {}, "Reached platform"), h("div", {}, `${delay(e.latency_ms)} later`)),
      h("div", { class: "toolbar" },
        h("button", { class: "btn primary", disabled: true, title: "Acknowledge and escalate arrive with alerts (Phase 3)" }, "Acknowledge"),
        h("button", { class: "btn", disabled: true, title: "Clips arrive with the evidence vault (Phase 3)" }, "Open clip"),
        h("button", { class: "btn", onclick: () => { scrim.remove(); location.hash = "#/live"; } }, "Go to live view")),
      h("p", { class: "faint", style: "font-size:12px;margin:0" }, "Acknowledge, escalation and clips come with the alerts phase.")));
  document.body.append(scrim);
}

/* ---------------- live view ---------------- */
async function viewLive(c) {
  let paths;
  try { paths = await api("/live/paths"); } catch (e) { paths = []; c.append(h("div", { class: "error" }, `Gateway: ${e.message}`)); }
  let layout = Number(localStorage.getItem("hss.live.layout") || 4);
  let chosen = JSON.parse(localStorage.getItem("hss.live.paths") || "null") || paths.slice(0, 16).map(p => p.path);
  chosen = chosen.filter(p => paths.some(x => x.path === p));
  const players = [];
  state.cleanup.push(() => players.forEach(p => p.close()));
  const tiles = h("div", { class: "tiles" });
  const camList = h("div", { class: "cams" });
  const drawTiles = () => {
    players.splice(0).forEach(p => p.close());
    const n = Math.sqrt(layout);
    tiles.style.gridTemplateColumns = `repeat(${n}, 1fr)`; tiles.style.gridTemplateRows = `repeat(${n}, 1fr)`;
    tiles.replaceChildren();
    for (let i = 0; i < layout; i++) {
      const path = chosen[i];
      if (!path) { tiles.append(h("div", { class: "tile empty-tile" }, "Pick a camera")); continue; }
      const video = h("video", { muted: true, autoplay: true, playsinline: true });
      video.muted = true;
      const st = h("span", { class: "state" }, "connecting");
      const tile = h("div", { class: "tile", ondblclick: () => tile.requestFullscreen && tile.requestFullscreen(), title: "Double-click for full screen" },
        video, h("span", { class: "label" }, h("span", { class: "dot" }), path), st);
      tiles.append(tile);
      players.push(new LivePlayer(video, path, (s, info) => {
        st.textContent = s === "playing" ? (info || "live") : s === "error" ? info : s;
        tile.querySelector(".dot").className = `dot ${s === "playing" ? "ok" : s === "error" ? "bad" : "warn"}`;
      }));
    }
    localStorage.setItem("hss.live.layout", layout); localStorage.setItem("hss.live.paths", JSON.stringify(chosen));
  };
  const drawCams = filter => {
    const groups = {};
    paths.filter(p => !filter || p.path.toLowerCase().includes(filter)).forEach(p => (groups[p.nvr] ||= []).push(p));
    camList.replaceChildren(...Object.entries(groups).map(([nvr, ps]) => h("div", {},
      h("h3", { style: "margin:10px 8px 4px" }, nvr.toUpperCase()),
      ps.map(p => h("button", { class: chosen.includes(p.path) ? "on" : null, onclick: () => {
        chosen = chosen.includes(p.path) ? chosen.filter(x => x !== p.path) : [...chosen, p.path].slice(-16);
        drawCams(filter); drawTiles();
      } }, h("span", { class: `dot ${chosen.includes(p.path) ? "ok" : ""}` }), p.path)))));
    if (!paths.length) camList.append(h("div", { class: "empty" }, "No cameras in the gateway yet (gateway/cameras.env)."));
  };
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Layout" }, [1, 4, 9, 16].map(n =>
    h("button", { class: n === layout ? "on" : null, onclick: e => { layout = n; seg.querySelectorAll("button").forEach(b => b.classList.remove("on")); e.target.classList.add("on"); drawTiles(); } }, `${n}`)));
  c.append(h("div", { class: "toolbar" }, h("span", { class: "muted" }, "Layout"), seg, h("div", { style: "flex:1" }),
      h("span", { class: "muted" }, "Sub-streams; double-click a tile for full screen")),
    h("div", { class: "live" },
      h("section", { class: "card", style: "padding:8px" }, h("input", { class: "input", type: "search", placeholder: "Find a camera", oninput: e => drawCams(e.target.value.toLowerCase()) }), camList),
      tiles));
  drawCams(""); drawTiles();
}

/* ---------------- devices ---------------- */
async function viewDevices(c) {
  const dev = await api("/devices");
  const want = new URLSearchParams(location.hash.split("?")[1] || "").get("nvr");
  let q = "";
  const box = h("div", { class: "grid" });
  const draw = () => box.replaceChildren(...dev.nvrs.map(n => {
    const chans = n.channels.filter(ch => !q || `${ch.name} ${ch.ip} ${ch.model} ${ch.class}`.toLowerCase().includes(q));
    if (q && !chans.length) return "";
    return h("section", { class: "card", id: `nvr-${n.address}` },
      h("div", { class: "head" }, h("h2", {}, n.name), h("span", { class: "muted mono" }, n.address),
        h("span", { class: "badge" }, n.model), h("span", { class: "badge" }, n.firmware),
        n.disk_problem ? h("span", { class: "badge bad" }, "drive fault") : null, h("div", { class: "spacer" }),
        h("span", { class: "muted" }, `${n.online}/${n.total} online`)),
      h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Ch", "Camera", "IP", "Status", "Model", "Class", "AI tier", "Stream", "Clock"].map(t => h("th", {}, t)))),
        h("tbody", {}, chans.map(ch => h("tr", {},
          h("td", { class: "muted" }, ch.channel), h("td", { style: "font-weight:600" }, ch.name), h("td", { class: "mono" }, ch.ip),
          h("td", {}, ch.online ? h("span", { class: "badge ok" }, "online") : h("span", { class: "badge bad" }, "offline")),
          h("td", {}, ch.model || h("span", { class: "faint" }, "—"), ch.firmware ? h("div", { class: "faint mono" }, ch.firmware) : null),
          h("td", {}, ch.class || "—"), h("td", {}, h("span", { class: `badge ${ch.tier === "E" ? "ok" : ch.tier === "N" ? "info" : ch.tier === "S" ? "warn" : ""}`, title: { E: "Camera AI", N: "NVR AI", S: "Server AI" }[ch.tier] || "" }, ch.tier || "?")),
          h("td", { class: "muted", style: "font-size:12.5px" }, ch.stream || "—"),
          h("td", {}, ch.clock_drift_s === null || ch.clock_drift_s === undefined ? "—" : Math.abs(ch.clock_drift_s) > 30 ? h("span", { class: "badge warn" }, driftText(ch.clock_drift_s)) : h("span", { class: "badge ok" }, "OK"))))))));
  }));
  c.append(h("div", { class: "toolbar" },
    h("input", { class: "input", type: "search", placeholder: "Find a camera, IP, model or class", oninput: e => { q = e.target.value.toLowerCase(); draw(); } }),
    h("div", { style: "flex:1" }),
    h("span", { class: "muted" }, dev.probed_at ? `From the probe of ${fmtTime(dev.probed_at)}${dev.cameras_surveyed_at ? ` and the camera survey of ${fmtTime(dev.cameras_surveyed_at)}` : ""}` : "No probe data on the server yet")),
    h("div", { class: "note" }, "This page reads the latest probe files on the server. Live device health (checked every minute) arrives in Phase 3."),
    box);
  draw();
  if (want) setTimeout(() => { const el = document.getElementById(`nvr-${want}`); if (el) el.scrollIntoView({ behavior: "smooth" }); }, 50);
}
const driftText = s => { const a = Math.abs(s); return a > 86400 * 365 ? "clock never set" : a > 3600 ? `${Math.round(a / 3600)} h off` : `${Math.round(a / 60)} min off`; };

/* ---------------- video walls ---------------- */
async function viewWalls(c) {
  const nodes = await api("/wall/nodes");
  c.append(h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, "Wall PCs"), h("div", { class: "spacer" }), h("span", { class: "muted" }, "Managed by the Wall Agent")),
    nodes.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Wall PC", "Status", "Agent", "Screens", "CPU", "Memory", "Last heartbeat", "Layout"].map(t => h("th", {}, t)))),
      h("tbody", {}, nodes.map(n => h("tr", {},
        h("td", {}, h("div", { style: "font-weight:600" }, n.id), h("div", { class: "faint" }, n.hostname)),
        h("td", {}, n.online ? h("span", { class: "badge ok" }, "online") : h("span", { class: "badge bad" }, "offline")),
        h("td", { class: "mono" }, `${n.agent_version} · ${n.os}`),
        h("td", {}, (n.screens || []).length ? (n.screens || []).map(s => h("div", { class: "muted", style: "font-size:12.5px" },
          `${s.index ?? ""} ${s.width || ""}×${s.height || ""} ${s.page_alive === false ? "· page stalled" : ""}`)) : "—"),
        h("td", {}, n.cpu_percent !== undefined && n.cpu_percent !== null ? `${Math.round(n.cpu_percent)}%` : "—"),
        h("td", {}, n.memory_percent !== undefined && n.memory_percent !== null ? `${Math.round(n.memory_percent)}%` : "—"),
        h("td", {}, ago(n.last_seen)),
        h("td", { class: "muted", style: "font-size:12.5px" }, n.layout.length ? n.layout.map(l => h("div", {}, `Screen ${l.monitor}: ${l.path}`)) : "default"))))))
      : h("div", { class: "empty" }, "No wall PCs have reported yet.")));
}

/* ---------------- notifications ---------------- */
async function viewNotify(c) {
  const st = await api("/notify/status?days=7");
  const isAdmin = state.user.role === "admin";
  const deliveries = isAdmin ? await api("/notify/deliveries?limit=30") : [];
  const wa = st.whatsapp.status;
  const totals = {};
  for (const d of st.deliveries) totals[d.status] = (totals[d.status] || 0) + d.count;
  c.append(h("div", { class: "grid kpis" },
      kpi("WhatsApp gateway", h("span", { style: `color:${wa === "ready" ? "var(--ok)" : "var(--warn)"}` }, wa), st.whatsapp.me ? `Linked number ends …${String(st.whatsapp.me).slice(-4)}` : ""),
      kpi("Sent, last 7 days", (totals.sent || 0) + (totals.delivered || 0) + (totals.read || 0), `${totals.read || 0} read · ${totals.failed || 0} failed`),
      kpi("Fallbacks", h("span", {}, st.email_configured ? "E-mail on" : "E-mail off", h("small", {}, st.push_configured ? " · push on" : " · push off")), "Used when WhatsApp fails")),
    h("div", { class: "grid cols-2" },
      card("Recipients", null, h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Name", "Role", "WhatsApp", "Receives"].map(t => h("th", {}, t)))),
        h("tbody", {}, st.recipients.map(r => h("tr", {}, h("td", { style: "font-weight:600" }, r.name), h("td", {}, r.role),
          h("td", { class: "mono" }, r.whatsapp || "—"), h("td", {}, r.subscriptions.map(s => h("span", { class: "badge", style: "margin:1px" }, s))))))))),
      card("Delivery test", null,
        h("p", { class: "muted", style: "margin-top:0" }, "Sends the one-page test report to everyone subscribed to “test”."),
        isAdmin ? h("button", { class: "btn primary", onclick: async e => {
          e.target.disabled = true;
          try { const r = await api("/notify/test", { method: "POST", body: {} }); toast(`Test sent: ${(r.attempts || []).filter(a => a.status === "sent").length} delivered`); }
          catch (ex) { toast(ex.message); } finally { e.target.disabled = false; }
        } }, "Send test report") : h("span", { class: "faint" }, "Only administrators can send tests."))),
    isAdmin ? card("Recent deliveries", null, deliveries.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Time", "Topic", "Recipient", "Channel", "To", "Status"].map(t => h("th", {}, t)))),
      h("tbody", {}, deliveries.map(d => h("tr", {}, h("td", {}, fmtTime(d.created_at)), h("td", {}, d.topic), h("td", {}, d.recipient),
        h("td", {}, d.channel, d.is_fallback ? h("span", { class: "badge warn", style: "margin-left:6px" }, "fallback") : null), h("td", { class: "mono" }, d.address || "—"),
        h("td", {}, h("span", { class: `badge ${["sent", "delivered", "read"].includes(d.status) ? "ok" : d.status === "skipped" ? "" : "bad"}`, title: d.detail || "" }, d.status)))))))
      : h("div", { class: "empty" }, "No deliveries yet.")) : null);
}

/* ---------------- map (preview) ---------------- */
function viewMap(c) {
  const m = PREVIEW.map;
  const NS = "http://www.w3.org/2000/svg";
  const s = (tag, attrs, text) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); if (text) el.textContent = text; return el; };
  const svg = s("svg", { viewBox: "0 0 800 400", role: "img", "aria-label": m.title });
  svg.append(s("rect", { x: 0, y: 0, width: 800, height: 400, fill: "var(--panel-2)" }));
  for (const z of m.zones) svg.append(s("polygon", { points: z.points, fill: z.kind === "restricted" ? "rgba(239,68,68,.10)" : "none", stroke: z.kind === "restricted" ? "#ef4444" : "#f59e0b", "stroke-width": 2, "stroke-dasharray": "8 6" }));
  for (const b of m.buildings) { svg.append(s("rect", { x: b.x, y: b.y, width: b.w, height: b.h, rx: 6, fill: "var(--panel)", stroke: "var(--line)" })); svg.append(s("text", { x: b.x + 8, y: b.y + 18, fill: "var(--muted)", "font-size": 12 }, b.name)); }
  for (const cam of m.cameras) {
    const col = { ok: "#22c55e", warn: "#f59e0b", bad: "#ef4444" }[cam.state];
    const g = s("g", {}); g.append(s("circle", { cx: cam.x, cy: cam.y, r: 7, fill: col, stroke: "#0b1220", "stroke-width": 2 }));
    g.append(s("title", {}, `${cam.name} (${cam.state})`)); svg.append(g);
  }
  for (const gd of m.guards) { svg.append(s("rect", { x: gd.x - 6, y: gd.y - 6, width: 12, height: 12, rx: 3, fill: "#38bdf8", transform: `rotate(45 ${gd.x} ${gd.y})` })); svg.append(s("text", { x: gd.x + 10, y: gd.y + 4, fill: "#38bdf8", "font-size": 11 }, gd.name)); }
  c.append(h("div", { class: "preview-banner" }, h("span", { class: "badge preview" }, "Preview"),
      "Sample site plan, not your site. Phase 5 adds your own plan or offline map, camera pins with live status, zones drawn in the platform, and guard positions from the GPS phones."),
    h("div", { class: "grid cols-2" },
      h("section", { class: "card map" }, svg),
      card("Legend", null, h("div", { class: "list" },
        h("div", { class: "item" }, h("span", { class: "dot ok" }), "Camera online"), h("div", { class: "item" }, h("span", { class: "dot warn" }), "Camera with a warning"),
        h("div", { class: "item" }, h("span", { class: "dot bad" }), "Camera offline"), h("div", { class: "item" }, h("span", { class: "dot info" }), "Guard (GPS phone)"),
        h("div", { class: "item" }, h("span", { style: "width:18px;border-top:2px dashed #f59e0b" }), "Perimeter zone, armed at night"),
        h("div", { class: "item" }, h("span", { style: "width:18px;border-top:2px dashed #ef4444" }), "Restricted area")))));
}

/* ---------------- reports ---------------- */
const KIND_NAMES = { daily: "Daily", weekly: "Weekly", monthly: "Monthly", custom: "Custom period" };
async function viewReports(c) {
  const canSend = ["admin", "cso"].includes(state.user.role);
  let q = "", kind = "";
  const listBox = h("div", {});
  const load = async () => {
    const params = new URLSearchParams({ limit: 100 }); if (kind) params.set("kind", kind); if (q) params.set("q", q);
    const rows = await api(`/reports?${params}`);
    listBox.replaceChildren(rows.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Report", "Period", "Events", "Critical", "vs previous", "Created", "Sent", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, rows.map(r => {
        const f = r.figures || {}, ch = f.change_pct;
        const delivered = (r.sent || []).filter(x => x.status === "sent").length;
        return h("tr", { class: "clickable", onclick: e => { if (!e.target.closest("a,button")) reportDrawer(r, canSend, load); } },
          h("td", {}, h("div", { style: "font-weight:600" }, r.title), h("span", { class: "badge" }, KIND_NAMES[r.kind])),
          h("td", {}, f.label || ""), h("td", {}, f.events ?? "—"),
          h("td", {}, f.critical ? h("span", { class: "badge bad" }, f.critical) : "0"),
          h("td", {}, ch === null || ch === undefined ? h("span", { class: "faint" }, "—") : h("span", { class: `badge ${ch > 0 ? "warn" : ch < 0 ? "ok" : ""}` }, `${ch > 0 ? "+" : ""}${ch}%`)),
          h("td", { class: "muted", style: "font-size:12.5px" }, fmtTime(r.created_at), h("div", { class: "faint" }, r.created_by === "schedule" ? "by schedule" : `by ${r.created_by}`)),
          h("td", {}, (r.sent || []).length ? h("span", { class: `badge ${delivered ? "ok" : "bad"}` }, delivered ? `${delivered} delivered` : "failed") : h("span", { class: "faint" }, "not sent")),
          h("td", { style: "white-space:nowrap;text-align:right" },
            h("a", { class: "btn small", href: r.files.pdf, download: "" }, "PDF"), " ",
            h("a", { class: "btn small", href: r.files.docx, download: "" }, "Word")));
      }))))
      : h("div", { class: "empty" }, q || kind ? "No reports match." : "No reports yet. Generate one above, or turn on the schedule (HSS_REPORT_TIME)."));
  };
  // generate form
  const kindSel = h("select", { class: "input", style: "width:auto" }, Object.entries(KIND_NAMES).map(([k, v]) => h("option", { value: k }, v)));
  const yesterday = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
  const on = h("input", { class: "input", type: "date", value: yesterday, style: "width:auto" });
  const start = h("input", { class: "input", type: "date", style: "width:auto" });
  const end = h("input", { class: "input", type: "date", value: yesterday, style: "width:auto" });
  const hint = h("span", { class: "muted", style: "font-size:12.5px" });
  const err = h("div", { class: "error", hidden: true });
  const dates = h("div", { class: "toolbar" });
  const drawDates = () => {
    const k = kindSel.value;
    dates.replaceChildren(...(k === "custom" ? [h("span", { class: "muted" }, "From"), start, h("span", { class: "muted" }, "to"), end] : [h("span", { class: "muted" }, k === "daily" ? "Day" : k === "weekly" ? "Any day in the week" : "Any day in the month"), on]));
    hint.textContent = { daily: "One day, midnight to midnight.", weekly: "Monday to Sunday.", monthly: "The whole calendar month, compared with the month before.", custom: "Up to 93 days." }[k];
  };
  kindSel.addEventListener("change", drawDates); drawDates();
  const gen = h("button", { class: "btn primary", onclick: async () => {
    err.hidden = true; gen.disabled = true; gen.textContent = "Generating…";
    try {
      const k = kindSel.value;
      const body = k === "custom" ? { kind: k, start: start.value, end: end.value } : { kind: k, on: on.value };
      const r = await api("/reports", { method: "POST", body });
      toast(`${r.title} ready`); await load(); reportDrawer(r, canSend, load);
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
    finally { gen.disabled = false; gen.textContent = "Generate"; }
  } }, "Generate");
  c.append(
    card("New report", h("span", { class: "muted" }, "PDF and Word, in your branding"), err,
      h("div", { class: "toolbar" }, h("span", { class: "muted" }, "Type"), kindSel, dates, gen), h("div", { style: "margin-top:8px" }, hint)),
    h("div", { class: "toolbar" },
      h("div", { class: "seg", role: "group", "aria-label": "Type" }, [["", "All"], ["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["custom", "Custom"]].map(([k, l]) =>
        h("button", { class: k === kind ? "on" : null, onclick: e => { kind = k; e.target.parentNode.querySelectorAll("button").forEach(b => b.classList.remove("on")); e.target.classList.add("on"); load(); } }, l))),
      h("input", { class: "input", type: "search", placeholder: "Search titles, periods and summaries", oninput: e => { q = e.target.value.trim(); clearTimeout(viewReports.t); viewReports.t = setTimeout(load, 300); } })),
    h("section", { class: "card", style: "padding:6px 8px" }, listBox));
  await load();
}
function reportDrawer(r, canSend, reload) {
  const f = r.figures || {};
  const sentBox = h("div", {});
  const drawSent = sent => sentBox.replaceChildren(sent.length ? h("div", { class: "list" }, sent.slice(-12).reverse().map(x => h("div", { class: "item" },
    h("span", { class: `dot ${x.status === "sent" ? "ok" : "bad"}` }), h("div", { class: "grow" }, h("div", { class: "title" }, `${x.recipient || "—"} · ${x.channel} · ${x.format}`),
      h("div", { class: "muted", style: "font-size:12px" }, `${x.status}${x.detail ? ` — ${x.detail}` : ""}`)), h("span", { class: "faint", style: "font-size:12px" }, fmtTime(x.at)))))
    : h("div", { class: "faint" }, "Not sent yet."));
  drawSent(r.sent || []);
  const withDocx = h("input", { type: "checkbox", id: "wd" });
  const scrim = h("div", { class: "scrim", onclick: ev => { if (ev.target === scrim) scrim.remove(); } },
    h("div", { class: "drawer", role: "dialog", "aria-label": r.title },
      h("div", { class: "toolbar" }, h("span", { class: "badge" }, KIND_NAMES[r.kind]), h("h2", {}, r.title), h("div", { style: "flex:1" }), h("button", { class: "btn small", onclick: () => scrim.remove() }, "Close")),
      h("div", { class: "muted" }, f.label),
      h("div", { class: "grid kpis", style: "grid-template-columns:repeat(4,1fr)" },
        [["Events", f.events], ["Critical", f.critical], ["Warnings", f.warning], ["Open items", f.open_items]].map(([l, v]) => h("div", { class: "card kpi", style: "padding:10px" }, h("div", { class: "label" }, l), h("div", { class: "value", style: "font-size:22px" }, v ?? "—")))),
      h("h3", {}, "Summary"), ...(r.summary || "").split("\n\n").map(p => h("p", { style: "margin:0" }, p)),
      h("div", { class: "toolbar" }, h("a", { class: "btn primary", href: r.files.pdf, download: "" }, "Download PDF"), h("a", { class: "btn", href: r.files.docx, download: "" }, "Download Word")),
      canSend && r.kind !== "custom" ? h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, "Send"), h("div", { class: "spacer" }), h("span", { class: "muted" }, `to everyone subscribed to ${r.kind} reports`)),
        h("div", { class: "toolbar" }, h("label", { for: "wd", class: "muted", style: "display:flex;gap:6px;align-items:center" }, withDocx, "Also send the Word file"), h("div", { style: "flex:1" }),
          h("button", { class: "btn primary", onclick: async e => {
            e.target.disabled = true; e.target.textContent = "Sending…";
            try { const res = await api(`/reports/${r.id}/send`, { method: "POST", body: { formats: withDocx.checked ? ["pdf", "docx"] : ["pdf"] } });
              const ok = res.attempts.filter(a => a.status === "sent").length; toast(`${ok} of ${res.attempts.length} delivered`);
              drawSent([...(r.sent || []), ...res.attempts]); r.sent = [...(r.sent || []), ...res.attempts]; reload(); }
            catch (ex) { toast(ex.message); } finally { e.target.disabled = false; e.target.textContent = "Send now"; }
          } }, "Send now"))) : null,
      h("h3", {}, "Deliveries"), sentBox));
  document.body.append(scrim);
}

/* ---------------- users ---------------- */
async function viewUsers(c) {
  const users = await api("/users");
  const showTemp = (title, who, temp) => modal(title,
    h("div", { class: "grid", style: "gap:10px" }, h("p", { class: "muted", style: "margin:0" }, `Give this temporary password to ${who} in person. It's shown only once; they choose their own at first sign-in.`),
      h("div", { class: "secret" }, temp)),
    close => [h("button", { class: "btn primary", onclick: () => { close.remove(); render(); } }, "Done")]);
  c.append(h("div", { class: "toolbar" }, h("span", { class: "muted" }, `${users.length} user${users.length === 1 ? "" : "s"}`), h("div", { style: "flex:1" }),
      h("button", { class: "btn primary", onclick: () => {
        const un = h("input", { class: "input", placeholder: "e.g. j.okafor", autocomplete: "off" });
        const dn = h("input", { class: "input", placeholder: "e.g. John Okafor" });
        const role = h("select", { class: "input" }, Object.entries(ROLE_NAMES).map(([k, v]) => h("option", { value: k, selected: k === "operator" }, v)));
        const err = h("div", { class: "error", hidden: true });
        modal("Add a user", h("div", {}, err, h("div", { class: "field" }, h("label", {}, "Username"), un), h("div", { class: "field" }, h("label", {}, "Full name"), dn),
          h("div", { class: "field" }, h("label", {}, "Role"), role)),
          close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
            h("button", { class: "btn primary", onclick: async () => {
              try {
                const res = await api("/users", { method: "POST", body: { username: un.value.trim(), display_name: dn.value.trim(), role: role.value } });
                close.remove(); showTemp("User added", res.user.display_name || res.user.username, res.temporary_password);
              } catch (ex) { err.textContent = ex.message; err.hidden = false; }
            } }, "Add user")]);
      } }, "Add user")),
    h("section", { class: "card", style: "padding:6px 8px" }, h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["User", "Role", "Two-factor", "Status", "Last sign-in", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, users.map(u => {
        const me = u.id === state.user.id;
        const roleSel = h("select", { class: "input", style: "width:auto;padding:6px 8px", disabled: me, onchange: async e => {
          try { await api(`/users/${u.id}`, { method: "PATCH", body: { role: e.target.value } }); toast("Role changed"); } catch (ex) { toast(ex.message); render(); }
        } }, Object.entries(ROLE_NAMES).map(([k, v]) => h("option", { value: k, selected: k === u.role }, v)));
        return h("tr", {},
          h("td", {}, h("div", { style: "display:flex;gap:10px;align-items:center" }, h("div", { class: "avatar" }, initials(u)),
            h("div", {}, h("div", { style: "font-weight:600" }, u.display_name || u.username, me ? h("span", { class: "faint" }, " (you)") : null), h("div", { class: "faint mono" }, u.username)))),
          h("td", {}, roleSel),
          h("td", {}, u.totp_enabled ? h("span", { class: "badge ok" }, "on") : h("span", { class: "badge" }, "off")),
          h("td", {}, u.disabled ? h("span", { class: "badge bad" }, "disabled") : u.locked ? h("span", { class: "badge warn" }, "locked") : u.must_change_password ? h("span", { class: "badge info" }, "new") : h("span", { class: "badge ok" }, "active")),
          h("td", { class: "muted" }, ago(u.last_login_at)),
          h("td", { style: "text-align:right;white-space:nowrap" },
            h("button", { class: "btn small", disabled: me, onclick: async () => {
              if (!confirm(`Reset the password of ${u.username}? Their two-factor setup is cleared too and they're signed out.`)) return;
              try { const r = await api(`/users/${u.id}`, { method: "PATCH", body: { reset_password: true } }); showTemp("Password reset", u.display_name || u.username, r.temporary_password); } catch (ex) { toast(ex.message); }
            } }, "Reset password"), " ",
            h("button", { class: `btn small ${u.disabled ? "" : "danger"}`, disabled: me, onclick: async () => {
              try { await api(`/users/${u.id}`, { method: "PATCH", body: { disabled: !u.disabled } }); render(); } catch (ex) { toast(ex.message); }
            } }, u.disabled ? "Enable" : "Disable")));
      }))))));
}

async function viewAudit(c) {
  const rows = await api("/audit?limit=200");
  const what = { login: "Signed in", login_failed: "Failed sign-in", logout: "Signed out", password_changed: "Changed password", user_created: "Added a user",
    user_changed: "Changed a user", "2fa_enabled": "Turned on two-factor", "2fa_disabled": "Turned off two-factor", branding_changed: "Changed branding", admin_created_cli: "Admin created on the server",
    report_generated: "Generated a report", report_downloaded: "Downloaded a report", report_sent: "Sent a report" };
  c.append(h("section", { class: "card", style: "padding:6px 8px" }, h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Time", "User", "Action", "Details", "From"].map(t => h("th", {}, t)))),
    h("tbody", {}, rows.map(r => h("tr", {}, h("td", { style: "white-space:nowrap" }, fmtTime(r.at)), h("td", { style: "font-weight:600" }, r.username || "—"),
      h("td", {}, r.action === "login_failed" ? h("span", { class: "badge warn" }, what[r.action]) : what[r.action] || r.action),
      h("td", { class: "muted", style: "font-size:12.5px" }, Object.entries(r.detail || {}).map(([k, v]) => `${k}: ${v}`).join(" · ")),
      h("td", { class: "mono" }, r.ip || "—"))))))));
}

/* ---------------- settings ---------------- */
async function viewSettings(c) {
  const me = await api("/auth/me");
  const sections = [];
  if (me.role === "admin") {
    const b = state.branding;
    const name = h("input", { class: "input", value: b.site_name, maxlength: 60 });
    const accent = h("input", { class: "input", type: "color", value: b.accent, style: "width:70px;padding:4px;height:40px" });
    const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/svg+xml,image/webp" });
    const preview = h("div", { style: "display:flex;align-items:center;gap:12px" }, brandBlock("Preview"));
    let logoData = null, removeLogo = false;
    file.addEventListener("change", () => {
      const f = file.files[0]; if (!f) return;
      if (f.size > 512 * 1024) { toast("Logo must be 512 KB or smaller."); file.value = ""; return; }
      const rd = new FileReader();
      rd.onload = () => { logoData = rd.result; removeLogo = false; preview.replaceChildren(h("div", { class: "brand" }, h("img", { src: logoData, alt: "" }), h("div", {}, h("div", { class: "name" }, name.value)))); };
      rd.readAsDataURL(f);
    });
    accent.addEventListener("input", () => document.documentElement.style.setProperty("--accent", accent.value));
    sections.push(card("Branding", h("span", { class: "muted" }, "Shown on the sign-in page, the console and reports"),
      h("div", { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(240px,1fr));align-items:end" },
        h("div", { class: "field" }, h("label", {}, "Site name"), name),
        h("div", { class: "field" }, h("label", {}, "Accent colour"), accent),
        h("div", { class: "field" }, h("label", {}, "Logo (PNG, JPEG, WebP or SVG, up to 512 KB)"), file)),
      h("div", { class: "toolbar" }, preview, h("div", { style: "flex:1" }),
        b.has_logo ? h("button", { class: "btn", onclick: () => { removeLogo = true; logoData = null; toast("Logo will be removed when you save"); } }, "Remove logo") : null,
        h("button", { class: "btn primary", onclick: async () => {
          try {
            const res = await api("/branding", { method: "PUT", body: { site_name: name.value.trim(), accent: accent.value, logo_data_url: logoData, remove_logo: removeLogo } });
            state.branding = { ...res, v: Date.now() }; applyBranding(); toast("Branding saved"); render();
          } catch (ex) { toast(ex.message); }
        } }, "Save branding"))));
  }
  const cur = h("input", { class: "input", type: "password", autocomplete: "current-password" });
  const nw = h("input", { class: "input", type: "password", autocomplete: "new-password" });
  const pwErr = h("div", { class: "error", hidden: true });
  sections.push(h("div", { class: "grid cols-2" },
    card("Password", null, pwErr, h("div", { class: "field" }, h("label", {}, "Current password"), cur), h("div", { class: "field" }, h("label", {}, "New password (12+ characters)"), nw),
      h("button", { class: "btn primary", onclick: async () => {
        pwErr.hidden = true;
        try { await api("/auth/password", { method: "POST", body: { current: cur.value, new: nw.value } }); cur.value = nw.value = ""; toast("Password changed. Other sessions were signed out."); }
        catch (ex) { pwErr.textContent = ex.message; pwErr.hidden = false; }
      } }, "Change password")),
    card("Two-factor sign-in", me.totp_enabled ? h("span", { class: "badge ok" }, "on") : h("span", { class: "badge warn" }, "off"), twoFactorBox(me))));
  sections.push(card("Appearance", null, h("div", { class: "toolbar" }, h("span", { class: "muted" }, "Theme"),
    h("div", { class: "seg" }, ["system", "dark", "light"].map(t => h("button", { class: (localStorage.getItem("hss.theme") || "system") === t ? "on" : null, onclick: () => { setTheme(t); render(); } }, label(t)))))));
  c.append(...sections);
}
function twoFactorBox(me) {
  const box = h("div", {});
  if (me.totp_enabled) {
    const pw = h("input", { class: "input", type: "password", placeholder: "Your password" });
    box.append(h("p", { class: "muted", style: "margin-top:0" }, "Signing in needs a code from your authenticator app."),
      h("div", { class: "toolbar" }, pw, h("button", { class: "btn danger", onclick: async () => {
        try { await api("/auth/2fa/disable", { method: "POST", body: { password: pw.value } }); toast("Two-factor turned off"); render(); } catch (ex) { toast(ex.message); }
      } }, "Turn off")));
    return box;
  }
  box.append(h("p", { class: "muted", style: "margin-top:0" }, "Add a second step to signing in: a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, Aegis, FreeOTP)."),
    h("button", { class: "btn primary", onclick: async () => {
      const s = await api("/auth/2fa/setup", { method: "POST", body: {} });
      const code = h("input", { class: "input code-input", inputmode: "numeric", maxlength: 7, placeholder: "000000" });
      const err = h("div", { class: "error", hidden: true });
      box.replaceChildren(
        h("div", { style: "display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start" },
          h("img", { class: "qr", src: `data:image/svg+xml;base64,${btoa(s.qr_svg)}`, alt: "QR code for your authenticator app" }),
          h("div", { style: "flex:1;min-width:200px;display:grid;gap:10px" },
            h("div", {}, "1. Scan the code with your authenticator app, or type this key:"), h("div", { class: "secret" }, s.secret.replace(/(.{4})/g, "$1 ").trim()),
            h("div", {}, "2. Enter the 6-digit code it shows:"), err, code,
            h("button", { class: "btn primary", onclick: async () => {
              try { await api("/auth/2fa/enable", { method: "POST", body: { code: code.value } }); toast("Two-factor is on"); render(); }
              catch (ex) { err.textContent = ex.message; err.hidden = false; }
            } }, "Turn on two-factor"))));
      code.focus();
    } }, "Set up two-factor"));
  return box;
}
function setTheme(t) {
  localStorage.setItem("hss.theme", t);
  if (t === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
}
setTheme(localStorage.getItem("hss.theme") || "system");

boot();
