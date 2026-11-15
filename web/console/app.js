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
// Element.replaceChildren prints null as the text "null"; skip empty placeholders like h() does.
const _replace = Element.prototype.replaceChildren;
Element.prototype.replaceChildren = function (...kids) { return _replace.apply(this, kids.flat(9).filter(k => k !== null && k !== undefined && k !== false)); };
const _append = Element.prototype.append;
Element.prototype.append = function (...kids) { return _append.apply(this, kids.flat(9).filter(k => k !== null && k !== undefined && k !== false)); };
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
  let box = document.getElementById("toasts");
  if (!box) { box = h("div", { id: "toasts", class: "toasts", "aria-live": "polite" }); document.body.append(box); }
  const t = h("div", { class: "toast", role: "status" }, msg);
  box.append(t); setTimeout(() => t.remove(), 3500);
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
  vault: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="15" rx="2"/><circle cx="12" cy="12.5" r="3"/><path d="M12 9.5V8M7 20v1M17 20v1"/></svg>',
  setup: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>',
  audit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>',
  legal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l9.5 17H2.5z"/><path d="M12 10v4M12 17.5h.01"/></svg>',
  sound: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16.5 8.5a5 5 0 010 7M19 6a8.5 8.5 0 010 12"/></svg>',
  mute: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M17 9l5 6M22 9l-5 6"/></svg>',
  menu: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  logout: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/></svg>',
};
const icon = name => h("span", { html: I[name], style: "display:contents" });

/* ---------------- state and routing ---------------- */
const state = { user: null, branding: { site_name: "Security Console", accent: "#2563eb", has_logo: false }, cleanup: [] };
const PAGES = [
  { group: "Monitor" },
  { id: "overview", title: "Overview", icon: "overview", roles: ["admin", "cso", "operator", "management"], view: viewOverview },
  { id: "alerts", title: "Alerts", icon: "alert", roles: ["admin", "cso", "operator"], view: viewAlerts },
  { id: "live", title: "Live view", icon: "live", roles: ["admin", "cso", "operator"], view: viewLive },
  { id: "events", title: "Events", icon: "events", roles: ["admin", "cso", "operator"], view: viewEvents },
  { id: "evidence", title: "Evidence vault", icon: "vault", roles: ["admin", "cso"], view: viewEvidence },
  { id: "map", title: "Site map", icon: "map", roles: ["admin", "cso", "operator"], view: viewMap },
  { group: "Manage" },
  { id: "devices", title: "Devices", icon: "devices", roles: ["admin", "cso", "operator", "management"], view: viewDevices },
  { id: "event-setup", title: "Event setup", icon: "setup", roles: ["admin", "cso", "operator"], view: viewEventSetup },
  { id: "face-plate", title: "Face & plate", icon: "legal", roles: ["admin", "cso", "management"], view: viewFacePlate },
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
  stopAlertStream();
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
      icon(p.icon), p.title, p.preview ? h("span", { class: "tag" }, "preview") : null,
      p.id === "alerts" ? h("span", { class: "count", id: "alert-count", hidden: !state.openAlerts }, state.openAlerts || "") : null));
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
        h("div", { class: "spacer" }), statusPills, alertsAllowed() ? soundButton() : null, clock),
      content));
  nav.addEventListener("click", () => shell.classList.remove("open"));
  loadStatusPills(statusPills);
  startAlertStream();
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
  if (alertsAllowed()) await refreshAlertCount();
  const o = await api("/overview");
  const canEvents = ["admin", "cso", "operator"].includes(state.user.role);
  const [events, devices] = await Promise.all([canEvents ? api("/events?limit=8") : [], api("/devices")]);
  const d = o.devices, pct = d.cameras ? Math.round(100 * d.online / d.cameras) : 0;
  const ev = o.events_24h;
  c.replaceChildren(
    h("div", { class: "grid kpis" },
      alertsAllowed() ? kpi("Open alerts", h("a", { href: "#/alerts", style: `color:${state.openAlerts ? "var(--bad)" : "var(--ok)"};text-decoration:none` }, state.openAlerts ?? "—"),
        state.openAlerts ? "Waiting for acknowledgement" : "Nothing waiting") : null,
      kpi("Cameras online", d.cameras ? h("span", {}, d.online, h("small", {}, ` / ${d.cameras}`)) : "—",
        d.live_checked_at ? `${d.nvrs} NVRs · checked ${ago(d.live_checked_at)}${d.unreachable.length ? ` · ${d.unreachable.join(", ")} not answering` : ""}`
          : d.probed_at ? `${d.nvrs} NVRs · probed ${ago(d.probed_at)}` : "No device data yet", d.cameras ? pct : null),
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
const label = s => (s || "").replace(/_/g, " ").replace(/^./, c => c.toUpperCase()).replace(/\bnvr\b/gi, "NVR");
function attentionList(dev) {
  const items = [];
  for (const n of dev.nvrs) {
    if (n.reachable === false) items.push(["bad", `${n.name}: not answering`, `Last checked ${ago(n.live_checked_at)}`]);
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
        h("button", { class: "btn primary", onclick: () => { scrim.remove(); location.hash = "#/alerts"; } }, "Go to alerts"),
        h("button", { class: "btn", onclick: () => { scrim.remove(); location.hash = "#/live"; } }, "Go to live view")),
      h("p", { class: "faint", style: "font-size:12px;margin:0" }, "Events that match an alert rule become alerts; acknowledge and close them on the Alerts page. Video clips come with Phase 3 part B.")));
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
  const labelOf = Object.fromEntries(paths.map(p => [p.path, p.label && p.label !== p.path ? p.label : ""]));
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
        video, h("span", { class: "label" }, h("span", { class: "dot" }), labelOf[path] || path), st);
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
    paths.filter(p => !filter || `${p.path} ${p.label}`.toLowerCase().includes(filter)).forEach(p => (groups[p.nvr] ||= []).push(p));
    camList.replaceChildren(...Object.entries(groups).map(([nvr, ps]) => h("div", {},
      h("h3", { style: "margin:10px 8px 4px" }, nvr.toUpperCase()),
      ps.map(p => h("button", { class: chosen.includes(p.path) ? "on" : null, onclick: () => {
        chosen = chosen.includes(p.path) ? chosen.filter(x => x !== p.path) : [...chosen, p.path].slice(-16);
        drawCams(filter); drawTiles();
      } }, h("span", { class: `dot ${chosen.includes(p.path) ? "ok" : ""}` }), labelOf[p.path] ? h("span", { title: p.path }, labelOf[p.path]) : p.path)))));
    if (!paths.length) camList.append(h("div", { class: "empty" }, "No cameras yet. An administrator adds NVRs on the Devices page."));
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
const TIER_NAMES = { E: "Camera AI", N: "NVR AI", S: "Server AI" };
async function viewDevices(c) {
  const dev = await api("/devices");
  const role = state.user.role, isAdmin = role === "admin", canTier = isAdmin || role === "cso";
  const want = new URLSearchParams(location.hash.split("?")[1] || "").get("nvr");
  let q = "";
  const box = h("div", { class: "grid" });
  const tierBadge = ch => h("span", { class: `badge ${ch.tier === "E" ? "ok" : ch.tier === "N" ? "info" : ch.tier === "S" ? "warn" : ""}`,
    title: (TIER_NAMES[ch.tier] || "Not classified") + (ch.tier_override ? ` · set by ${ch.tier_override.by}${ch.tier_override.note ? `: ${ch.tier_override.note}` : ""}` : "") }, ch.tier || "?", ch.tier_override ? " ✎" : "");
  const draw = () => box.replaceChildren(...dev.nvrs.map(n => {
    const chans = n.channels.filter(ch => !q || `${ch.name} ${ch.ip} ${ch.model} ${ch.class} ${ch.camera_id}`.toLowerCase().includes(q));
    if (q && !chans.length) return "";
    const reg = n.registered;
    return h("section", { class: "card", id: `nvr-${n.address}` },
      h("div", { class: "head" }, h("h2", {}, n.name), h("span", { class: "muted mono" }, n.address), h("span", { class: "badge mono", title: "Short name: the start of this NVR's camera ids" }, n.alias),
        n.model ? h("span", { class: "badge" }, n.model) : null, n.firmware ? h("span", { class: "badge" }, n.firmware) : null,
        reg && reg.segment ? h("span", { class: "badge", title: "Network segment" }, reg.segment) : null,
        n.disk_problem ? h("span", { class: "badge bad" }, "drive fault") : null,
        reg && !reg.enabled ? h("span", { class: "badge" }, "paused") : null,
        n.reachable === false ? h("span", { class: "badge bad" }, "not answering") : n.live_checked_at ? h("span", { class: "badge ok", title: `Checked ${fmtTime(n.live_checked_at)}` }, "live") : null,
        h("div", { class: "spacer" }),
        h("span", { class: "muted" }, `${n.online}/${n.total} online`),
        isAdmin ? h("button", { class: "btn small", onclick: () => nvrForm(reg ? n : { address: n.address, name: n.name, alias: n.alias }, !!reg) }, reg ? "Edit" : "Add to console") : null),
      reg && reg.test_ok === false ? h("div", { class: "note" }, `Last connection test ${ago(reg.tested_at)} failed: ${reg.test_detail}`) : null,
      !n.channels.length ? h("div", { class: "empty" }, "No channels known yet. Use Edit and save to test the connection again.") :
      h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Ch", "Camera", "IP", "Status", "Model", "Class", "AI tier", "Stream", "Clock"].map(t => h("th", {}, t)))),
        h("tbody", {}, chans.map(ch => h("tr", {},
          h("td", { class: "muted" }, ch.channel), h("td", {}, h("div", { style: "font-weight:600" }, ch.name), h("div", { class: "faint mono" }, ch.camera_id)), h("td", { class: "mono" }, ch.ip),
          h("td", {}, ch.online ? h("span", { class: "badge ok" }, "online") : ch.online === false ? h("span", { class: "badge bad" }, "offline") : h("span", { class: "badge" }, "unknown")),
          h("td", {}, ch.model || h("span", { class: "faint" }, "—"), ch.firmware ? h("div", { class: "faint mono" }, ch.firmware) : null),
          h("td", {}, ch.class || "—"),
          h("td", {}, canTier ? h("button", { class: "linkish", title: "Change the AI tier", onclick: () => tierForm(ch) }, tierBadge(ch)) : tierBadge(ch)),
          h("td", { class: "muted", style: "font-size:12.5px" }, ch.stream || "—"),
          h("td", {}, ch.clock_drift_s === null || ch.clock_drift_s === undefined ? "—" : Math.abs(ch.clock_drift_s) > 30 ? h("span", { class: "badge warn" }, driftText(ch.clock_drift_s)) : h("span", { class: "badge ok" }, "OK"))))))));
  }));
  c.append(h("div", { class: "toolbar" },
    h("input", { class: "input", type: "search", placeholder: "Find a camera, IP, model or class", oninput: e => { q = e.target.value.toLowerCase(); draw(); } }),
    h("div", { style: "flex:1" }),
    h("span", { class: "muted" }, dev.live_checked_at ? `Live status, checked ${ago(dev.live_checked_at)}; models and classes from the camera survey`
      : dev.probed_at ? `From the probe of ${fmtTime(dev.probed_at)}${dev.cameras_surveyed_at ? ` and the camera survey of ${fmtTime(dev.cameras_surveyed_at)}` : ""}` : "No device data on the server yet"),
    isAdmin ? h("button", { class: "btn primary", onclick: () => nvrForm({}, false) }, "Add NVR") : null),
    dev.live_checked_at ? null : h("div", { class: "note" }, "Showing the latest probe files. Start the edge service (docs/edge.md) for live status checked every minute."),
    dev.nvrs.length ? box : h("div", { class: "empty" }, isAdmin ? "No NVRs yet. Use Add NVR to connect the first one." : "No NVRs have been added yet."));
  draw();
  if (want) setTimeout(() => { const el = document.getElementById(`nvr-${want}`); if (el) el.scrollIntoView({ behavior: "smooth" }); }, 50);
}

function nvrForm(n, editing) {
  const reg = n.registered || {};
  const inp = (id, value, attrs = {}) => h("input", { class: "input", id, value: value ?? "", autocomplete: "off", ...attrs });
  const f = {
    address: inp("nvr-address", n.address, { placeholder: "e.g. 10.1.3.4" }),
    name: inp("nvr-name", editing ? n.name : (n.name && n.name !== n.address ? n.name : ""), { placeholder: "Taken from the NVR if empty" }),
    alias: inp("nvr-alias", editing ? n.alias : "", { placeholder: n.alias || "e.g. nvr4", disabled: editing }),
    username: inp("nvr-user", reg.username, { placeholder: "A dedicated NVR user, not admin" }),
    password: inp("nvr-pass", "", { type: "password", autocomplete: "new-password", placeholder: editing ? "Leave empty to keep the stored password" : "" }),
    rtsp: inp("nvr-rtsp", reg.rtsp_port || 554, { type: "number", min: 1, max: 65535 }),
    segment: inp("nvr-seg", reg.segment, { placeholder: "e.g. CCTV VLAN 30, Block B" }),
    https: h("input", { type: "checkbox", id: "nvr-https", checked: reg.scheme === "https" }),
    enabled: h("input", { type: "checkbox", id: "nvr-enabled", checked: editing ? reg.enabled : true }),
    live: h("input", { type: "checkbox", id: "nvr-live", checked: editing ? reg.live_view : true }),
  };
  const err = h("div", { class: "error", hidden: true });
  const anyway = h("label", { class: "check", hidden: true }, h("input", { type: "checkbox", id: "nvr-anyway" }), "Save anyway (the NVR is offline or not reachable from the server yet)");
  const field = (label, el, hint) => h("div", { class: "field" }, h("label", { for: el.id }, label), el, hint ? h("div", { class: "faint", style: "font-size:12px" }, hint) : null);
  const check = (el, text) => h("label", { class: "check" }, el, text);
  const body = h("div", {}, err,
    h("p", { class: "muted", style: "margin:0 0 14px" }, "The server tests the login before saving. The password is stored encrypted and is never shown again."),
    field("NVR address", f.address, "IP address, with :port only if its web port isn't 80"),
    h("div", { class: "field-row" }, field("Name", f.name), field("Short name", f.alias, editing ? "Fixed once added" : "Starts each camera id")),
    h("div", { class: "field-row" }, field("NVR user", f.username), field("Password", f.password)),
    h("div", { class: "field-row" }, field("RTSP port", f.rtsp), field("Network segment", f.segment)),
    h("div", { class: "field", style: "gap:8px" }, check(f.enabled, "Watch this NVR for events, health and clips"), check(f.live, "Add its cameras to live view"),
      check(f.https, "Use HTTPS to reach the NVR")),
    anyway);
  modal(editing ? `Edit ${n.name}` : "Add an NVR", body, close => {
    const buttons = [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel")];
    if (editing) buttons.unshift(h("button", { class: "btn danger", style: "margin-right:auto", onclick: () => {
      if (!confirm(`Remove ${n.name} from the console? Its live view paths are removed and the edge service stops watching it. Past events and alerts stay.`)) return;
      api(`/nvrs/${reg.id}`, { method: "DELETE" }).then(() => { close.remove(); toast(`${n.name} removed`); render(); }).catch(ex => { err.textContent = ex.message; err.hidden = false; });
    } }, "Remove"));
    const save = h("button", { class: "btn primary", onclick: async () => {
      save.disabled = true; save.textContent = "Testing the connection…"; err.hidden = true;
      const payload = { address: f.address.value.trim(), name: f.name.value.trim(), alias: editing ? "" : f.alias.value.trim(), username: f.username.value.trim(),
        password: f.password.value, rtsp_port: Number(f.rtsp.value) || 554, segment: f.segment.value.trim(), scheme: f.https.checked ? "https" : "http",
        enabled: f.enabled.checked, live_view: f.live.checked, save_anyway: anyway.querySelector("input").checked };
      try {
        const r = await api(editing ? `/nvrs/${reg.id}` : "/nvrs", { method: editing ? "PUT" : "POST", body: payload });
        close.remove(); toast(r.test_ok ? `${r.name || r.address}: ${r.test_detail}` : `${r.address} saved without a working connection`); render();
      } catch (ex) {
        err.textContent = ex.message; err.hidden = false;
        if (ex.status === 422 && ex.message.startsWith("Connection test failed")) anyway.hidden = false;
      } finally { save.disabled = false; save.textContent = editing ? "Test and save" : "Test and add"; }
    } }, editing ? "Test and save" : "Test and add");
    return [...buttons, save];
  });
}

function tierForm(ch) {
  const sel = h("select", { class: "input", id: "tier-sel" },
    h("option", { value: "", selected: !ch.tier_override }, `Automatic (${ch.tier_auto && ch.tier_auto !== "?" ? `${ch.tier_auto}, ${TIER_NAMES[ch.tier_auto]}` : "not classified yet"})`),
    Object.entries(TIER_NAMES).map(([k, v]) => h("option", { value: k, selected: ch.tier_override && ch.tier === k }, `${k}: ${v}`)));
  const note = h("input", { class: "input", id: "tier-note", value: ch.tier_override ? ch.tier_override.note : "", placeholder: "Why, e.g. AcuSense licence missing on this camera" });
  const err = h("div", { class: "error", hidden: true });
  modal(`AI tier for ${ch.name}`, h("div", {}, err,
    h("p", { class: "muted", style: "margin:0 0 14px" }, "E: the camera's own AI detects people and vehicles. N: the NVR's AI does. S: the server's AI watches the video. The camera survey sets this automatically; override it when you know better."),
    h("div", { class: "field" }, h("label", { for: "tier-sel" }, "Tier"), sel), h("div", { class: "field" }, h("label", { for: "tier-note" }, "Note"), note)),
    close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
      h("button", { class: "btn primary", onclick: async () => {
        try { await api(`/cameras/${ch.camera_id}/tier`, { method: "PUT", body: { tier: sel.value || null, note: note.value.trim() } }); close.remove(); toast("Tier saved"); render(); }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "Save")]);
}
const driftText = s => { const a = Math.abs(s); return a > 86400 * 365 ? "clock never set" : a > 3600 ? `${Math.round(a / 3600)} h off` : `${Math.round(a / 60)} min off`; };

/* ---------------- evidence vault ---------------- */
function sealForm(alertId, after) {
  const reason = h("input", { class: "input", id: "seal-reason", placeholder: "e.g. Theft at the fence, reported to police" });
  const ref = h("input", { class: "input", id: "seal-ref", placeholder: "Police or insurance reference, if any" });
  const err = h("div", { class: "error", hidden: true });
  modal("Seal evidence in the vault", h("div", {}, err,
    h("p", { class: "muted", style: "margin:0 0 12px" }, "Saves the snapshot, clip, event and alert history as one package that can't be changed, with its SHA-256 recorded. Every later download is logged. Alerts closed as a real incident are sealed automatically."),
    h("div", { class: "field" }, h("label", { for: "seal-reason" }, "Reason"), reason), h("div", { class: "field" }, h("label", { for: "seal-ref" }, "Case reference"), ref)),
    close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"), h("button", { class: "btn primary", onclick: async e => {
      e.target.disabled = true;
      try { const r = await api(`/alerts/${alertId}/seal`, { method: "POST", body: { reason: reason.value.trim(), case_ref: ref.value.trim() } }); close.remove(); toast(`Sealed · SHA-256 ${r.sha256.slice(0, 12)}…`); after && after(); }
      catch (ex) { err.textContent = ex.message; err.hidden = false; e.target.disabled = false; }
    } }, "Seal")]);
}

async function viewEvidence(c) {
  const v = await api("/evidence");
  const isAdmin = state.user.role === "admin";
  const kb = n => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
  c.append(v.chain_ok ? h("div", { class: "note" }, `Custody log checked: ${v.chain_detail}. Packages are kept ${v.keep_days} days after sealing unless on legal hold.`)
    : h("div", { class: "error" }, h("strong", {}, "Custody log check failed: "), v.chain_detail, ". Someone changed or removed log entries. Keep the server as it is and tell the administrator."));
  c.append(card("Sealed evidence", h("span", { class: "muted", style: "font-size:12.5px" }, `${v.items.length} package${v.items.length === 1 ? "" : "s"}`),
    v.items.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Sealed", "Evidence", "Case ref", "Contents", "SHA-256", "Kept until", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, v.items.map(e => h("tr", {},
        h("td", { style: "white-space:nowrap" }, fmtTime(e.sealed_at), h("div", { class: "faint" }, e.sealed_by)),
        h("td", {}, h("div", { style: "font-weight:600" }, e.title), e.reason ? h("div", { class: "faint" }, e.reason) : null),
        h("td", {}, e.case_ref || "—"),
        h("td", { class: "muted", style: "font-size:12.5px" }, e.files.join(", "), h("div", { class: "faint" }, kb(e.size_bytes))),
        h("td", { class: "mono", style: "font-size:12px" }, e.sha256.slice(0, 16), "…"),
        h("td", {}, e.legal_hold ? h("span", { class: "badge warn", title: e.hold_reason }, "legal hold") : e.retain_until),
        h("td", { style: "text-align:right;white-space:nowrap" },
          h("a", { class: "btn small", href: `/api/evidence/${e.id}/download`, download: "" }, "Download"), " ",
          h("button", { class: "btn small", onclick: () => evidenceDrawer(e.id, isAdmin) }, "Details"))))))) :
      h("div", { class: "empty" }, "Nothing sealed yet. Open an alert and choose Seal evidence, or close it as a real incident.")));
}

async function evidenceDrawer(eid, isAdmin) {
  const e = await api(`/evidence/${eid}`);
  const err = h("div", { class: "error", hidden: true });
  const reason = h("input", { class: "input", id: "ev-reason", placeholder: "Reason (required for hold and retention changes)" });
  const until = h("input", { class: "input", id: "ev-until", type: "date", value: e.retain_until });
  const result = h("div", {});
  const run = async (fn, okMsg) => { err.hidden = true; try { await fn(); toast(okMsg); m.remove(); evidenceDrawer(eid, isAdmin); } catch (ex) { err.textContent = ex.message; err.hidden = false; } };
  const m = modal(e.title, h("div", { class: "grid", style: "gap:12px" }, err,
    h("div", { class: "kv" },
      h("div", {}, "Sealed"), h("div", {}, `${fmtTime(e.sealed_at)} by ${e.sealed_by}`),
      h("div", {}, "Case ref"), h("div", {}, e.case_ref || "—"),
      h("div", {}, "SHA-256"), h("div", { class: "mono", style: "font-size:11.5px;word-break:break-all" }, e.sha256),
      h("div", {}, "Contents"), h("div", {}, e.files.join(", ")),
      h("div", {}, "Kept until"), h("div", {}, e.legal_hold ? `legal hold: ${e.hold_reason}` : e.retain_until)),
    result,
    h("h3", { style: "margin:4px 0 0" }, "Custody log"),
    h("div", { class: "list", style: "max-height:180px;overflow:auto" }, e.custody.map(x => h("div", { class: "item" },
      h("span", { class: `dot ${x.action === "verify_failed" ? "bad" : x.action === "sealed" ? "ok" : ""}` }),
      h("div", { class: "grow", style: "min-width:0" }, h("div", { style: "font-weight:550" }, `${x.action.replace("_", " ")} · ${x.username} · `, h("span", { class: "faint", style: "font-weight:400;font-size:12px" }, fmtTime(x.at))),
        x.detail ? h("div", { class: "faint", style: "font-size:12px;white-space:normal;overflow-wrap:anywhere" }, x.detail) : null)))),
    h("div", { class: "field" }, h("label", { for: "ev-reason" }, "Reason"), reason),
    isAdmin ? h("div", { class: "field" }, h("label", { for: "ev-until" }, "Keep until"), until) : null),
    close => [
      h("button", { class: "btn", onclick: async () => {
        try { const r = await api(`/evidence/${eid}/verify`, { method: "POST", body: {} });
          result.replaceChildren(h("div", { class: r.file_ok && r.chain_ok ? "note" : "error" }, r.file_ok ? "File matches its SHA-256. " : "File does NOT match its SHA-256. ", r.chain_detail));
        } catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "Verify"),
      h("button", { class: "btn", onclick: () => reason.value.trim().length < 3 ? (err.textContent = "Write a reason first.", err.hidden = false)
        : run(() => api(`/evidence/${eid}/hold`, { method: "PUT", body: { hold: !e.legal_hold, reason: reason.value.trim() } }), e.legal_hold ? "Legal hold removed" : "On legal hold") }, e.legal_hold ? "Remove hold" : "Legal hold"),
      isAdmin ? h("button", { class: "btn", onclick: () => reason.value.trim().length < 3 ? (err.textContent = "Write a reason first.", err.hidden = false)
        : run(() => api(`/evidence/${eid}/retention`, { method: "PUT", body: { retain_until: until.value, reason: reason.value.trim() } }), "Kept-until date changed") }, "Save date") : null,
      h("button", { class: "btn primary", onclick: () => close.remove() }, "Done")]);
}

/* ---------------- event setup and walk test ---------------- */
async function viewEventSetup(c) {
  const canCheck = ["admin", "cso"].includes(state.user.role);
  const data = canCheck ? await api("/event-setup") : { nvrs: [] };
  // Walk test
  let since = null, timer = null;
  const status = h("span", { class: "muted" }, "Walk past cameras with line crossing or intrusion set up; each one is ticked when its event arrives.");
  const results = h("div", { class: "list" });
  const allCams = Object.fromEntries(data.nvrs.flatMap(n => n.cameras.map(x => [x.camera_id, x.name])));
  const startBtn = h("button", { class: "btn primary" }, "Start walk test");
  const poll = async () => {
    try {
      const rows = await api(`/event-setup/walk?since=${encodeURIComponent(since.toISOString())}`);
      const secs = Math.round((Date.now() - since) / 1000);
      status.textContent = `Running for ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")} · ${rows.length} camera${rows.length === 1 ? "" : "s"} reported`;
      results.replaceChildren(...rows.map(r => h("div", { class: "item" }, h("span", { class: `dot ${r.alert_id ? "ok" : "warn"}` }),
        h("div", { class: "grow" }, h("div", { style: "font-weight:600" }, allCams[r.camera_id] || r.camera_id, h("span", { class: "faint mono" }, ` ${r.camera_id}`)),
          h("div", { class: "faint", style: "font-size:12.5px" }, `${label(r.type)}${r.object ? `, ${r.object}` : ""} · ${r.count} event${r.count > 1 ? "s" : ""} · `,
            r.alert_id ? `raised a ${r.alert_severity} alert` : "no alert (no rule matched, or a repeat inside the cool-down)")),
        h("span", { class: "faint", style: "font-size:12px" }, `${Math.max(0, Math.round((new Date(r.received_at) - new Date(r.occurred_at)) / 100) / 10)} s delay · ${fmtTime(r.received_at)}`))));
    } catch (ex) { status.textContent = ex.message; }
  };
  startBtn.addEventListener("click", () => {
    if (timer) { clearInterval(timer); timer = null; startBtn.textContent = "Start walk test"; return; }
    since = new Date(); results.replaceChildren(); startBtn.textContent = "Stop";
    poll(); timer = setInterval(poll, 3000);
  });
  state.cleanup.push(() => timer && clearInterval(timer));
  c.append(card("Walk test", startBtn, status, results));
  if (!canCheck) return;

  for (const n of data.nvrs) {
    const notSent = n.cameras.filter(x => x.not_sent.length).length;
    c.append(h("section", { class: "card" },
      h("div", { class: "head" }, h("h2", {}, n.nvr), h("span", { class: "badge mono" }, n.alias),
        n.checked_at ? h("span", { class: "muted", style: "font-size:12.5px" }, `event settings read ${ago(n.checked_at)}`) : null,
        notSent ? h("span", { class: "badge warn" }, `${notSent} camera${notSent > 1 ? "s" : ""} not sending some events`) : null,
        h("div", { class: "spacer" }),
        n.registered_id ? h("button", { class: "btn small", onclick: async e => {
          e.target.disabled = true; e.target.textContent = "Reading…";
          try { const r = await api(`/event-setup/${n.registered_id}/check`, { method: "POST", body: {} }); toast(`${r.triggers} event settings read`); render(); }
          catch (ex) { toast(ex.message); e.target.disabled = false; e.target.textContent = "Check event settings"; }
        } }, "Check event settings") : h("span", { class: "faint", style: "font-size:12.5px" }, "Add this NVR in Devices to check its settings")),
      n.device_events.length ? h("div", { class: "toolbar", style: "margin-bottom:8px" }, h("span", { class: "muted" }, "NVR exceptions:"),
        n.device_events.map(d => h("span", { class: `badge ${d.center ? "ok" : "warn"}`, title: d.center ? "Sent to HSS" : "Notify Surveillance Center is not ticked" }, d.name))) : null,
      h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Ch", "Camera", "Sent to HSS", "Set up but not sent", "Events, 7 days", "Last event"].map(t => h("th", {}, t)))),
        h("tbody", {}, n.cameras.map(x => h("tr", {},
          h("td", { class: "muted" }, x.channel),
          h("td", {}, h("div", { style: "font-weight:600" }, x.name), h("div", { class: "faint mono" }, x.camera_id)),
          h("td", {}, x.sent.length ? x.sent.map(t => h("span", { class: "badge ok", style: "margin:1px" }, t)) : h("span", { class: "faint" }, n.checked_at ? "none" : "not checked")),
          h("td", {}, x.not_sent.length ? x.not_sent.map(t => h("span", { class: "badge warn", style: "margin:1px", title: "Tick Notify Surveillance Center for this event on the NVR" }, t)) : "—"),
          h("td", {}, x.events_7d ? h("span", { title: Object.entries(x.types_7d).map(([k, v]) => `${label(k)}: ${v}`).join("\n") }, x.events_7d) : h("span", { class: x.sent.length ? "badge warn" : "faint" }, x.sent.length ? "none yet" : "0")),
          h("td", { class: "muted" }, x.last_event ? ago(x.last_event) : "—"))))))));
  }
  if (!data.nvrs.length) c.append(h("div", { class: "empty" }, "No NVRs yet. Add them in Devices."));
}

/* ---------------- face & plate: legal review gate ---------------- */
// A small renderer for the review's Markdown (headings, paragraphs, lists, tables, bold). Text only, no HTML from data.
function inlineMd(text) {
  return text.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map(p => p.startsWith("**") ? h("strong", {}, p.slice(2, -2)) : p);
}
function renderMd(md) {
  const out = [], lines = md.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (!l.trim()) continue;
    let m;
    if ((m = l.match(/^(#{1,3})\s+(.*)/))) { out.push(h(`h${m[1].length + 1}`, {}, inlineMd(m[2]))); continue; }
    if (l.startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith("|")) { if (!/^\|[-|\s]+\|$/.test(lines[i])) rows.push(lines[i].split("|").slice(1, -1).map(c => c.trim())); i++; }
      i--;
      out.push(h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, rows[0].map(c => h("th", {}, inlineMd(c))))),
        h("tbody", {}, rows.slice(1).map(r => h("tr", {}, r.map(c => h("td", {}, inlineMd(c)))))))));
      continue;
    }
    if ((m = l.match(/^(\d+\.|-)\s+/))) {
      const ordered = m[1] !== "-", items = [];
      while (i < lines.length && lines[i].match(ordered ? /^\d+\.\s+/ : /^-\s+/)) { items.push(lines[i].replace(/^(\d+\.|-)\s+/, "")); i++; }
      i--;
      out.push(h(ordered ? "ol" : "ul", {}, items.map(t => h("li", {}, inlineMd(t)))));
      continue;
    }
    const para = [l];
    while (i + 1 < lines.length && lines[i + 1].trim() && !/^(#|\||-\s|\d+\.\s)/.test(lines[i + 1])) para.push(lines[++i]);
    out.push(h("p", {}, inlineMd(para.join(" "))));
  }
  return out;
}

async function viewFacePlate(c) {
  const doc = await api("/legal/face-plate");
  const st = doc.status, isAdmin = state.user.role === "admin";
  const unlocked = st.face || st.plate;
  const cur = doc.history.find(x => !x.revoked_at);
  c.append(h("section", { class: `card legal-status ${unlocked ? "open" : "locked"}` },
    h("div", { class: "head" }, h("h2", {}, unlocked ? "Recognition unlocked" : "Face and plate recognition are locked"), h("div", { class: "spacer" }),
      h("span", { class: `badge ${st.face ? "ok" : "bad"}` }, `Face ${st.face ? "unlocked" : "locked"}`), " ",
      h("span", { class: `badge ${st.plate ? "ok" : "bad"}` }, `Plate ${st.plate ? "unlocked" : "locked"}`)),
    unlocked && cur ? h("div", { class: "kv" },
      h("div", {}, "Accepted by"), h("div", {}, `${cur.full_name}, ${cur.position} (${cur.username}) on ${fmtTime(cur.accepted_at)}`),
      h("div", {}, "Legal opinion"), h("div", {}, `${cur.reviewer_name}, ${cur.reviewer_firm} · ref ${cur.opinion_ref} of ${cur.opinion_date}`),
      h("div", {}, "DPIA"), h("div", {}, cur.dpia_ref),
      h("div", {}, "Valid until"), h("div", {}, fmtTime(st.expires_at)))
      : h("p", { class: "muted", style: "margin:0" }, st.locked_reason,
        " Until an administrator reads the review below and accepts its conditions, face and plate events are dropped and the recognition trial won't run. Stage 1 (camera suitability) needs no unlock."),
    unlocked && ["admin", "cso"].includes(state.user.role) ? h("div", { class: "toolbar", style: "margin-top:12px" }, h("button", { class: "btn danger", onclick: () => {
      const reason = h("input", { class: "input", id: "revoke-reason", placeholder: "e.g. Legal opinion withdrawn; complaint under review" });
      const err = h("div", { class: "error", hidden: true });
      modal("Withdraw and lock", h("div", {}, err, h("p", { class: "muted", style: "margin:0 0 12px" }, "Face and plate recognition stop at once. Unlocking again needs a new acceptance."),
        h("div", { class: "field" }, h("label", { for: "revoke-reason" }, "Reason"), reason)),
        close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"), h("button", { class: "btn primary", onclick: async () => {
          try { await api("/legal/face-plate/revoke", { method: "POST", body: { reason: reason.value.trim() } }); close.remove(); toast("Locked"); render(); }
          catch (ex) { err.textContent = ex.message; err.hidden = false; }
        } }, "Withdraw and lock")]);
    } }, "Withdraw and lock")) : null));

  // The document, with reading progress.
  const progress = h("span", {});
  const bar = h("span", { style: "width:0%" });
  const reader = h("article", { class: "legal-doc", tabindex: "0", "aria-label": doc.title }, renderMd(doc.text.replace(/^# .*\n/, "")));
  let readToEnd = false;
  const form = isAdmin ? acceptForm() : null;
  const onScroll = () => {
    const pct = Math.min(100, Math.round(100 * (reader.scrollTop + reader.clientHeight) / reader.scrollHeight));
    bar.style.width = `${pct}%`; progress.textContent = readToEnd || pct >= 99 ? "Read to the end" : `${pct}% read`;
    if (pct >= 99 && !readToEnd) { readToEnd = true; if (form) form.enable(); }
  };
  reader.addEventListener("scroll", onScroll);
  c.append(h("section", { class: "card" },
    h("div", { class: "head" }, h("h2", {}, doc.title), h("div", { class: "spacer" }), h("span", { class: "muted mono", style: "font-size:12px" }, `version ${doc.version}`)),
    h("div", { class: "legal-progress" }, h("div", { class: "bar" }, bar), progress), reader), form ? form.el : null,
    doc.history.length ? card("History", null, h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Accepted", "By", "Covers", "Legal opinion", "DPIA", "Status"].map(t => h("th", {}, t)))),
      h("tbody", {}, doc.history.map(x => h("tr", {}, h("td", {}, fmtTime(x.accepted_at)), h("td", {}, `${x.full_name} (${x.username})`),
        h("td", {}, x.scopes.join(", ")), h("td", {}, `${x.reviewer_name}, ${x.opinion_ref}`), h("td", {}, x.dpia_ref),
        h("td", {}, x.revoked_at ? h("span", { class: "badge", title: x.revoke_reason || "" }, `withdrawn ${fmtTime(x.revoked_at)} by ${x.revoked_by}`)
          : x.version !== doc.version ? h("span", { class: "badge warn" }, "older document") : new Date(x.expires_at) < new Date() ? h("span", { class: "badge warn" }, "expired")
          : h("span", { class: "badge ok" }, `in force until ${fmtTime(x.expires_at)}`)))))))) : null);
  setTimeout(onScroll, 0);

  function acceptForm() {
    let readId = null, openedAt = Date.now();
    api("/legal/face-plate/open", { method: "POST", body: {} }).then(r => { readId = r.read_id; openedAt = Date.now(); }).catch(() => {});
    const inp = (id, label, attrs = {}) => { const el = h("input", { class: "input", id, autocomplete: "off", ...attrs }); return [el, h("div", { class: "field" }, h("label", { for: id }, label), el)]; };
    const [fullName, fFull] = inp("lg-name", "Your full name");
    const [position, fPos] = inp("lg-pos", "Your position", { placeholder: "e.g. General Manager" });
    const [revName, fRev] = inp("lg-rev", "Legal practitioner who gave the opinion");
    const [revFirm, fFirm] = inp("lg-firm", "Their firm or chambers");
    const [opRef, fOp] = inp("lg-op", "Opinion reference");
    const [opDate, fOpDate] = inp("lg-opdate", "Opinion date", { type: "date" });
    const [dpia, fDpia] = inp("lg-dpia", "DPIA reference");
    const face = h("input", { type: "checkbox", id: "lg-face" }), plate = h("input", { type: "checkbox", id: "lg-plate" });
    const conds = doc.conditions.map((t, i) => h("input", { type: "checkbox", id: `lg-c${i}` }));
    const err = h("div", { class: "error", hidden: true });
    const timer = h("span", { class: "muted" });
    const btn = h("button", { class: "btn primary", disabled: true }, "Accept and unlock");
    const fs = h("fieldset", { class: "legal-accept", disabled: true },
      h("legend", {}, "Acceptance"),
      doc.two_factor_ready ? null : h("div", { class: "note" }, "Your account needs two-factor sign-in before you can accept. Turn it on under Settings, then come back."),
      h("p", { class: "muted", style: "margin-top:0" }, "Unlocks for 12 months, for this version of the review only. Recorded in the audit log."),
      h("h3", {}, "Unlock"), h("div", { class: "field", style: "gap:8px" }, h("label", { class: "check" }, plate, "Number plate recognition"), h("label", { class: "check" }, face, "Face recognition")),
      h("h3", {}, "Conditions (section 14): the site commits to each"),
      h("div", { class: "field", style: "gap:10px" }, doc.conditions.map((t, i) => h("label", { class: "check" }, conds[i], `${i + 1}. ${t}`))),
      h("h3", {}, "Records"),
      h("div", { class: "field-row" }, fFull, fPos), h("div", { class: "field-row" }, fRev, fFirm), h("div", { class: "field-row" }, fOp, fOpDate), fDpia,
      err, h("div", { class: "toolbar" }, timer, h("div", { style: "flex:1" }), btn));
    const minS = doc.min_read_s;
    const tick = setInterval(() => {
      if (!document.body.contains(fs)) return clearInterval(tick);
      const left = Math.ceil(minS - (Date.now() - openedAt) / 1000);
      timer.textContent = !fs.disabled ? (left > 0 ? `You can accept in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "") : "Read the review to the end to continue";
      btn.disabled = fs.disabled || left > 0 || !doc.two_factor_ready;
    }, 500);
    btn.addEventListener("click", async () => {
      err.hidden = true;
      const scopes = [plate.checked && "plate", face.checked && "face"].filter(Boolean);
      const missing = [!scopes.length && "choose what to unlock", conds.some(x => !x.checked) && "accept every condition",
        ![fullName, position, revName, revFirm, opRef, opDate, dpia].every(x => x.value.trim()) && "fill in every record"].filter(Boolean);
      if (missing.length) { err.textContent = `Before accepting: ${missing.join(", ")}.`; err.hidden = false; return; }
      btn.disabled = true;
      try {
        await api("/legal/face-plate/accept", { method: "POST", body: { read_id: readId || "", version: doc.version, scopes, conditions: conds.map(x => x.checked), read_to_end: readToEnd,
          full_name: fullName.value.trim(), position: position.value.trim(), reviewer_name: revName.value.trim(), reviewer_firm: revFirm.value.trim(),
          opinion_ref: opRef.value.trim(), opinion_date: opDate.value, dpia_ref: dpia.value.trim() } });
        toast(`${scopes.map(s => s === "face" ? "Face" : "Plate").join(" and ")} recognition unlocked`); render();
      } catch (ex) { err.textContent = ex.message; err.hidden = false; btn.disabled = false; }
    });
    return { el: h("section", { class: "card" }, fs), enable: () => { fs.disabled = false; } };
  }
}

/* ---------------- video walls: screens, layouts and wall PCs ---------------- */
const TILE_CHOICES = [1, 4, 6, 9, 16, 25, 32, 36, 64];
const sourceText = (sc, nvrNames) => sc.source === "all" ? "All cameras" : sc.source.startsWith("nvr:") ? (nvrNames[sc.source.slice(4)] || sc.source.slice(4)) : "Picked cameras";
async function viewWalls(c) {
  const isAdmin = state.user.role === "admin";
  const [nodes, screens, dev] = await Promise.all([api("/wall/nodes"), api("/wall/screens"), api("/devices")]);
  let paths = [];
  try { paths = await api("/live/paths"); } catch (_) { /* gateway down: the picker shows what it can */ }
  const nvrNames = Object.fromEntries(dev.nvrs.map(n => [n.alias, n.name]));
  const byUrl = Object.fromEntries(screens.map(sc => [sc.url, sc]));
  const shownOn = url => nodes.flatMap(n => n.layout.filter(l => l.path === url).map(l => `${n.id} · screen ${l.monitor + 1}`));

  c.append(h("div", { class: "toolbar" },
    h("span", { class: "muted" }, `${screens.length} screen${screens.length === 1 ? "" : "s"} · ${nodes.length} wall PC${nodes.length === 1 ? "" : "s"}`),
    h("div", { style: "flex:1" }),
    isAdmin ? h("button", { class: "btn", title: "One 32-tile screen for each NVR that doesn't have one yet", onclick: async e => {
      e.target.disabled = true;
      const have = new Set(screens.map(sc => sc.source));
      const todo = dev.nvrs.filter(n => !have.has(`nvr:${n.alias}`));
      try {
        for (const n of todo) await api("/wall/screens", { method: "POST", body: { name: n.name, source: `nvr:${n.alias}`, tiles: n.total > 16 || !n.total ? 32 : 16, dwell_s: 20, labels: true, pin_alerts: true } });
        toast(todo.length ? `${todo.length} NVR screen${todo.length > 1 ? "s" : ""} added` : "Every NVR has a screen already"); render();
      } catch (ex) { toast(ex.message); e.target.disabled = false; }
    } }, "Add a screen per NVR") : null,
    isAdmin ? h("button", { class: "btn primary", onclick: () => screenForm(null, paths, dev) }, "New screen") : null));

  c.append(card("Screens", h("span", { class: "muted", style: "font-size:12.5px" }, "A screen is what one TV shows; more cameras than tiles rotate"),
    screens.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Screen", "Cameras", "Grid", "Rotation", "Shown on", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, screens.map(sc => {
        const on = shownOn(sc.url);
        return h("tr", {},
          h("td", {}, h("div", { style: "font-weight:600" }, sc.name), h("div", { class: "faint" }, sourceText(sc, nvrNames))),
          h("td", {}, sc.camera_count),
          h("td", {}, `${sc.tiles} tiles`),
          h("td", {}, sc.pages > 1 ? `${sc.pages} pages, ${sc.dwell_s} s each` : h("span", { class: "faint" }, "fits on one page"), sc.pin_alerts ? h("div", { class: "faint" }, "alerts pinned") : null),
          h("td", {}, on.length ? on.map(o => h("div", { style: "font-size:12.5px" }, o)) : h("span", { class: "faint" }, "not assigned")),
          h("td", { style: "text-align:right;white-space:nowrap" },
            h("a", { class: "btn small", href: sc.url, target: "_blank", rel: "noopener" }, "Open"), " ",
            isAdmin ? h("button", { class: "btn small", onclick: () => screenForm(sc, paths, dev) }, "Edit") : null));
      })))) : h("div", { class: "empty" }, isAdmin ? "No screens yet. Add a screen per NVR for 32-camera NVR screens, or make your own with New screen." : "No screens yet.")));

  c.append(card("Wall PCs", h("span", { class: "muted", style: "font-size:12.5px" }, "Managed by the Wall Agent; changes reach the TVs within a minute"),
    nodes.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Wall PC", "Status", "Agent", "TVs and what they show", "CPU", "Memory", "Last heartbeat", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, nodes.map(n => {
        const monitors = Math.max((n.screens || []).length, ...n.layout.map(l => l.monitor + 1), 1);
        return h("tr", {},
          h("td", {}, h("div", { style: "font-weight:600" }, n.id), h("div", { class: "faint" }, n.hostname)),
          h("td", {}, n.online ? h("span", { class: "badge ok" }, "online") : h("span", { class: "badge bad" }, "offline")),
          h("td", { class: "mono" }, `${n.agent_version} · ${n.os}`),
          h("td", {}, Array.from({ length: monitors }, (_, m) => {
            const l = n.layout.find(x => x.monitor === m), sc = l && byUrl[l.path];
            const live = (n.screens || []).find(s => (s.monitor ? s.monitor.index : s.index) === m), pg = (live && live.page) || {};
            const stalled = live && live.running && (live.page_heartbeat_age_s === null || live.page_heartbeat_age_s > 30) && live.up_seconds > 60;
            return h("div", { style: "font-size:12.5px" }, h("strong", {}, `TV ${m + 1}: `), sc ? sc.name : l ? l.path : h("span", { class: "faint" }, "default page"),
              stalled ? h("span", { class: "badge bad", style: "margin-left:6px" }, "page stalled") : null,
              pg.tiles ? h("span", { class: pg.playing < pg.tiles ? "badge warn" : "faint", style: "margin-left:6px" }, `${pg.playing ?? "?"}/${pg.tiles} playing`) : null);
          })),
          h("td", {}, n.cpu_percent !== undefined && n.cpu_percent !== null ? `${Math.round(n.cpu_percent)}%` : "—"),
          h("td", {}, n.memory_percent !== undefined && n.memory_percent !== null ? `${Math.round(n.memory_percent)}%` : "—"),
          h("td", {}, ago(n.last_seen)),
          h("td", { style: "text-align:right" }, isAdmin ? h("button", { class: "btn small", onclick: () => assignForm(n, monitors, screens) }, "Assign screens") : null));
      })))) : h("div", { class: "empty" }, "No wall PCs have reported yet. Install the Wall Agent on each wall PC (docs/task-22-wall-agent.md).")));
}

function assignForm(n, monitors, screens) {
  const count = Math.min(16, Math.max(monitors, 1));
  const sels = Array.from({ length: Math.max(count, 3) }, (_, m) => {
    const cur = n.layout.find(x => x.monitor === m);
    return h("select", { class: "input", id: `as-${m}` }, h("option", { value: "" }, "Default page (no screen)"),
      screens.map(sc => h("option", { value: sc.url, selected: cur && cur.path === sc.url }, sc.name)),
      cur && !screens.some(sc => sc.url === cur.path) ? h("option", { value: cur.path, selected: true }, `Other: ${cur.path.slice(0, 40)}`) : null);
  });
  const err = h("div", { class: "error", hidden: true });
  modal(`Screens on ${n.id}`, h("div", {}, err,
    h("p", { class: "muted", style: "margin:0 0 12px" }, `TV numbers follow the PC's display order (Windows: Settings › Display). ${monitors} TV${monitors > 1 ? "s" : ""} reported.`),
    sels.map((sel, m) => h("div", { class: "field" }, h("label", { for: sel.id }, `TV ${m + 1}${m >= monitors ? " (not connected now)" : ""}`), sel))),
    close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
      h("button", { class: "btn primary", onclick: async () => {
        const layout = sels.map((sel, m) => ({ monitor: m, path: sel.value })).filter(l => l.path);
        try { await api(`/wall/nodes/${encodeURIComponent(n.id)}/layout`, { method: "PUT", body: layout }); close.remove(); toast("Saved. The wall PC switches within a minute."); render(); }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "Save")]);
}

function screenForm(sc, paths, dev) {
  const editing = !!sc;
  sc = sc || { name: "", source: "cameras", cameras: [], tiles: 16, dwell_s: 20, labels: true, pin_alerts: true };
  const name = h("input", { class: "input", id: "sc-name", value: sc.name, placeholder: "e.g. Perimeter, Gate area, NVR4" });
  const source = h("select", { class: "input", id: "sc-src" },
    h("option", { value: "cameras", selected: sc.source === "cameras" }, "Cameras I pick"),
    h("option", { value: "all", selected: sc.source === "all" }, "All cameras (rotation)"),
    dev.nvrs.map(n => h("option", { value: `nvr:${n.alias}`, selected: sc.source === `nvr:${n.alias}` }, `All cameras of ${n.name} (${n.total})`)));
  const tiles = h("select", { class: "input", id: "sc-tiles" }, TILE_CHOICES.map(t => h("option", { value: t, selected: t === sc.tiles }, `${t} tile${t > 1 ? "s" : ""}${t === 32 ? " (8 × 4, one NVR)" : ""}`)));
  const dwell = h("input", { class: "input", id: "sc-dwell", type: "number", min: 5, max: 600, value: sc.dwell_s });
  const labels = h("input", { type: "checkbox", id: "sc-labels", checked: sc.labels });
  const pin = h("input", { type: "checkbox", id: "sc-pin", checked: sc.pin_alerts });
  const picked = new Set(sc.cameras);
  const count = h("span", { class: "muted", style: "font-size:12.5px" });
  const find = h("input", { class: "input", type: "search", id: "sc-find", placeholder: "Find a camera" });
  const list = h("div", { class: "pick-list" });
  const drawList = () => {
    const f = find.value.toLowerCase();
    const groups = {};
    paths.filter(p => !f || `${p.path} ${p.label}`.toLowerCase().includes(f)).forEach(p => (groups[p.nvr] ||= []).push(p));
    list.replaceChildren(...Object.entries(groups).map(([nvr, ps]) => h("div", {}, h("div", { class: "faint", style: "margin:8px 0 4px;font-weight:650" }, (dev.nvrs.find(n => n.alias === nvr) || {}).name || nvr),
      ps.map(p => h("label", { class: "check" }, h("input", { type: "checkbox", checked: picked.has(p.path), onchange: e => { e.target.checked ? picked.add(p.path) : picked.delete(p.path); count.textContent = `${picked.size} picked`; } }),
        p.label !== p.path ? `${p.label} ` : p.path, p.label !== p.path ? h("span", { class: "faint mono" }, p.path) : null)))));
    if (!paths.length) list.append(h("div", { class: "empty" }, "No cameras in the stream gateway yet."));
    count.textContent = `${picked.size} picked`;
  };
  find.addEventListener("input", drawList);
  const pickBox = h("div", { class: "field" }, h("div", { style: "display:flex;justify-content:space-between" }, h("label", { for: "sc-find" }, "Cameras"), count), find, list);
  const syncSource = () => { pickBox.hidden = source.value !== "cameras"; };
  source.addEventListener("change", syncSource);
  const err = h("div", { class: "error", hidden: true });
  modal(editing ? `Edit ${sc.name}` : "New screen", h("div", {}, err,
    h("div", { class: "field" }, h("label", { for: "sc-name" }, "Name"), name),
    h("div", { class: "field" }, h("label", { for: "sc-src" }, "Shows"), source),
    h("div", { class: "field-row" }, h("div", { class: "field" }, h("label", { for: "sc-tiles" }, "Grid"), tiles),
      h("div", { class: "field" }, h("label", { for: "sc-dwell" }, "Seconds per page"), dwell, h("div", { class: "faint", style: "font-size:12px" }, "When there are more cameras than tiles"))),
    h("div", { class: "field", style: "gap:8px" }, h("label", { class: "check" }, labels, "Show camera names"),
      h("label", { class: "check" }, pin, "Keep cameras with open alerts on screen, outlined")),
    pickBox),
    close => {
      const btns = [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
        h("button", { class: "btn primary", onclick: async () => {
          const body = { name: name.value.trim(), source: source.value, cameras: source.value === "cameras" ? paths.map(p => p.path).filter(p => picked.has(p)).concat([...picked].filter(p => !paths.some(x => x.path === p))) : [],
            tiles: Number(tiles.value), dwell_s: Number(dwell.value) || 20, labels: labels.checked, pin_alerts: pin.checked };
          if (body.source === "cameras" && !body.cameras.length) { err.textContent = "Pick at least one camera."; err.hidden = false; return; }
          try { await api(editing ? `/wall/screens/${sc.id}` : "/wall/screens", { method: editing ? "PUT" : "POST", body }); close.remove(); toast(editing ? "Screen saved; TVs update within 10 seconds" : "Screen added"); render(); }
          catch (ex) { err.textContent = ex.message; err.hidden = false; }
        } }, editing ? "Save" : "Add screen")];
      if (editing) btns.unshift(
        h("button", { class: "btn danger", style: "margin-right:auto", onclick: async () => {
          if (!confirm(`Delete the screen ${sc.name}?`)) return;
          try { await api(`/wall/screens/${sc.id}`, { method: "DELETE" }); close.remove(); toast("Screen deleted"); render(); } catch (ex) { err.textContent = ex.message; err.hidden = false; }
        } }, "Delete"),
        h("button", { class: "btn", title: "Makes a new link; the old one stops working. Assigned wall PCs move to the new link.", onclick: async () => {
          try { await api(`/wall/screens/${sc.id}/new-key`, { method: "POST", body: {} }); toast("New link made"); close.remove(); render(); } catch (ex) { err.textContent = ex.message; err.hidden = false; }
        } }, "New link"));
      return btns;
    });
  drawList(); syncSource();
}

/* ---------------- notifications ---------------- */
async function viewNotify(c) {
  const st = await api("/notify/status?days=7");
  const isAdmin = state.user.role === "admin";
  const deliveries = isAdmin ? await api("/notify/deliveries?limit=30") : [];
  const wa = st.whatsapp.status;
  const totals = {};
  for (const d of st.deliveries) totals[d.status] = (totals[d.status] || 0) + d.count;
  const rc = st.recipients_check || {};
  if (rc.error) c.append(h("div", { class: "error" }, h("strong", {}, "config/recipients.json has a mistake: "), rc.error,
    rc.using_last_good ? " Messages still go to the last good list below until it's fixed." : " No recipients can be used until it's fixed."));
  if (rc.warnings && rc.warnings.length) c.append(h("div", { class: "note" }, h("strong", {}, "Check config/recipients.json: "), rc.warnings.join("; ")));
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

/* ---------------- site map: plans, cameras, zones, guards (Phase 5) ---------------- */
const SVGNS = "http://www.w3.org/2000/svg";
function sv(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(9)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}
const ZONE_KINDS = { restricted: "Restricted area", perimeter: "Perimeter", checkpoint: "Patrol checkpoint", area: "Area" };
const wedge = (x, y, bearing, fov, r) => {
  if (fov >= 359) return `M ${x - r} ${y} a ${r} ${r} 0 1 0 ${2 * r} 0 a ${r} ${r} 0 1 0 ${-2 * r} 0`;
  const a1 = (bearing - fov / 2 - 90) * Math.PI / 180, a2 = (bearing + fov / 2 - 90) * Math.PI / 180;
  return `M ${x} ${y} L ${x + r * Math.cos(a1)} ${y + r * Math.sin(a1)} A ${r} ${r} 0 ${fov > 180 ? 1 : 0} 1 ${x + r * Math.cos(a2)} ${y + r * Math.sin(a2)} Z`;
};
const parseWindows = t => t.split(",").map(x => x.trim()).filter(Boolean).map(x => x.split(/\s*(?:-|to|–)\s*/));

async function viewMap(c) {
  const canEdit = ["admin", "cso"].includes(state.user.role);
  let plans = await api("/geo/plans");
  let planId = Number(localStorage.getItem("hss.map.plan")) || (plans[0] && plans[0].id);
  if (!plans.some(p => p.id === planId)) planId = plans[0] && plans[0].id;
  let mode = "view", live = null, zoom = 1, draft = [], placing = null, simUnit = null, refDraft = [];
  let devices = null;
  const side = h("div", { class: "map-side" });
  const tip = h("div", { class: "map-tip", hidden: true });
  const svg = sv("svg", { class: "map-svg", preserveAspectRatio: "none" });
  const img = h("img", { class: "map-img", alt: "" });
  const stage = h("div", { class: "map-stage" }, img, svg);
  const scroller = h("div", { class: "map-scroll" }, stage);
  const modeBar = h("div", { class: "seg", role: "group", "aria-label": "Map mode" });
  const planBar = h("div", { class: "seg", role: "group", "aria-label": "Plan" });

  const toPlan = ev => { const r = svg.getBoundingClientRect(), p = live.plan; return [(ev.clientX - r.left) * p.width / r.width, (ev.clientY - r.top) * p.height / r.height]; };
  const setMode = m => { mode = m; draft = []; placing = null; refDraft = []; tip.hidden = m === "view"; drawModes(); drawSide(); draw(); };

  function drawModes() {
    const modes = [["view", "View"], ...(canEdit ? [["refs", "Reference points"], ["camera", "Place cameras"], ["zone", "Draw zone"], ["simulate", "Walk-through"]] : [])];
    modeBar.replaceChildren(...modes.map(([k, t]) => h("button", { class: mode === k ? "on" : null, disabled: !live, onclick: () => setMode(k) }, t)));
    tip.textContent = { refs: "Click a spot on the plan whose latitude and longitude you know (a gate, a building corner). Two spots, far apart.",
      camera: "Pick a camera on the right, then click where it is on the plan.", zone: "Click the corners of the zone in order, then Finish on the right.",
      simulate: "Pick a guard or vehicle on the right, then click on the plan to move it there, as if its phone reported from that spot." }[mode] || "";
  }
  function drawPlans() {
    planBar.replaceChildren(...plans.map(p => h("button", { class: p.id === planId ? "on" : null, onclick: () => { planId = p.id; localStorage.setItem("hss.map.plan", p.id); load(true); } }, p.name)));
  }

  function draw() {
    if (!live) return;
    const p = live.plan, W = p.width, H = p.height, k = Math.max(W, H) / 1000;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const kids = [];
    for (const z of live.zones) {
      const pts = z.points.map(q => q.join(",")).join(" ");
      const cx = z.points.reduce((a, q) => a + q[0], 0) / z.points.length, cy = z.points.reduce((a, q) => a + q[1], 0) / z.points.length;
      kids.push(sv("g", { class: `zone ${z.kind} ${z.armed_now ? "armed" : "disarmed"} ${z.enabled ? "" : "off"}`, onclick: e => { e.stopPropagation(); if (mode === "view") zonePanel(z); } },
        sv("polygon", { points: pts, "stroke-width": 2.5 * k }), sv("text", { x: cx, y: cy, "font-size": 15 * k, "text-anchor": "middle" }, z.name)));
    }
    for (const cam of live.cameras) {
      const cls = cam.alert ? `alert-${cam.alert}` : cam.online === false ? "offline" : cam.online ? "online" : "unknown";
      kids.push(sv("g", { class: `cam ${cls} ${placing && placing.camera_id === cam.camera_id ? "sel" : ""}`, onclick: e => { e.stopPropagation(); if (mode === "view") cameraPanel(cam); else if (mode === "camera") { placing = { ...cam }; drawSide(); draw(); } } },
        sv("path", { d: wedge(cam.x, cam.y, cam.bearing, cam.fov, cam.reach), class: "fov" }),
        sv("circle", { cx: cam.x, cy: cam.y, r: 8 * k, "stroke-width": 2 * k }), sv("title", {}, `${cam.name} (${cam.camera_id})`)));
    }
    if (placing && placing.x !== undefined && !live.cameras.some(x => x.camera_id === placing.camera_id && x.x === placing.x && x.y === placing.y))
      kids.push(sv("g", { class: "cam sel draft" }, sv("path", { d: wedge(placing.x, placing.y, placing.bearing, placing.fov, placing.reach), class: "fov" }), sv("circle", { cx: placing.x, cy: placing.y, r: 8 * k })));
    for (const u of live.units) {
      if (u.trail.length > 1) kids.push(sv("polyline", { class: "trail", points: u.trail.map(q => q.join(",")).join(" "), "stroke-width": 2 * k }));
      kids.push(sv("g", { class: `unit ${u.kind} ${u.offline ? "offline" : ""}`, onclick: e => { e.stopPropagation(); if (mode === "view") unitPanel(u); } },
        sv("circle", { cx: u.x, cy: u.y, r: 9 * k, "stroke-width": 2.5 * k }),
        sv("text", { x: u.x + 13 * k, y: u.y + 5 * k, "font-size": 14 * k }, u.name)));
    }
    const refs = mode === "refs" ? refDraft : (p.refs || []);
    refs.forEach((r, i) => kids.push(sv("g", { class: "ref" }, sv("circle", { cx: r.x, cy: r.y, r: 7 * k }), sv("text", { x: r.x + 10 * k, y: r.y - 8 * k, "font-size": 14 * k }, "AB"[i]))));
    if (draft.length) kids.push(sv("polyline", { class: "draft-zone", points: draft.map(q => q.join(",")).join(" "), "stroke-width": 2.5 * k }),
      ...draft.map(q => sv("circle", { class: "draft-pt", cx: q[0], cy: q[1], r: 5 * k })));
    svg.replaceChildren(...kids);
    stage.style.width = `${zoom * 100}%`;
  }

  svg.addEventListener("click", async ev => {
    if (!live || mode === "view") return;
    const [x, y] = toPlan(ev);
    if (mode === "zone") { draft.push([Math.round(x), Math.round(y)]); drawSide(); draw(); }
    else if (mode === "camera" && placing) { placing = { ...placing, x: Math.round(x), y: Math.round(y) }; drawSide(); draw(); }
    else if (mode === "refs" && refDraft.length < 2) refPointForm(Math.round(x), Math.round(y));
    else if (mode === "simulate" && simUnit) {
      try { const r = await api(`/geo/units/${simUnit}/simulate`, { method: "POST", body: { plan_id: planId, x, y } });
        toast(r.events.length ? r.events.map(e => label(e.type) + (e.alert_id ? " → alert" : "")).join(", ") : "Moved; nothing to report");
        load(); } catch (ex) { toast(ex.message); }
    }
  });

  function refPointForm(x, y) {
    const lat = h("input", { class: "input", id: "rp-lat", placeholder: "e.g. 6.524379", inputmode: "decimal" });
    const lon = h("input", { class: "input", id: "rp-lon", placeholder: "e.g. 3.379206", inputmode: "decimal" });
    const both = h("input", { class: "input", id: "rp-both", placeholder: "or paste: 6.524379, 3.379206" });
    both.addEventListener("input", () => { const m = both.value.match(/(-?\d+\.\d+)\s*[, ]\s*(-?\d+\.\d+)/); if (m) { lat.value = m[1]; lon.value = m[2]; } });
    modal(`Reference point ${"AB"[refDraft.length]}`, h("div", {},
      h("p", { class: "muted", style: "margin:0 0 12px" }, "Latitude and longitude of the spot you clicked. Stand there with a phone's map app, or right-click the spot in an online map and copy the numbers."),
      h("div", { class: "field" }, h("label", { for: "rp-both" }, "Paste both"), both),
      h("div", { class: "field-row" }, h("div", { class: "field" }, h("label", { for: "rp-lat" }, "Latitude"), lat), h("div", { class: "field" }, h("label", { for: "rp-lon" }, "Longitude"), lon))),
      close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"), h("button", { class: "btn primary", onclick: async () => {
        const la = parseFloat(lat.value), lo = parseFloat(lon.value);
        if (!isFinite(la) || !isFinite(lo)) return toast("Enter both numbers");
        refDraft.push({ x, y, lat: la, lon: lo }); close.remove(); draw(); drawSide();
        if (refDraft.length === 2) {
          try { await api(`/geo/plans/${planId}`, { method: "PUT", body: { name: live.plan.name, refs: refDraft } }); toast("Plan tied to the map"); plans = await api("/geo/plans"); setMode("view"); load(); }
          catch (ex) { toast(ex.message); refDraft = []; draw(); drawSide(); }
        }
      } }, "Set point")]);
  }

  async function drawSide() {
    if (!live) { side.replaceChildren(); return; }
    const plan = plans.find(p => p.id === planId);
    if (mode === "view") {
      const alerts = live.cameras.filter(x => x.alert), units = live.units;
      side.replaceChildren(h("h3", {}, live.plan.name),
        h("div", { class: "faint", style: "font-size:12.5px" }, plan.georeferenced ? `Tied to the map · ${plan.metres_per_px} m per pixel` : "Not tied to the map yet: set the two reference points so GPS positions and zones work."),
        h("div", { class: "legend" }, h("span", {}, h("i", { class: "lg online" }), "camera online"), h("span", {}, h("i", { class: "lg offline" }), "offline"),
          h("span", {}, h("i", { class: "lg alert" }), "open alert"), h("span", {}, h("i", { class: "lg guard" }), "guard"), h("span", {}, h("i", { class: "lg vehicle" }), "vehicle")),
        alerts.length ? h("div", {}, h("h3", {}, "Cameras with open alerts"), alerts.map(a => h("button", { class: "linkrow", onclick: () => cameraPanel(a) }, h("span", { class: `dot ${a.alert === "critical" ? "bad" : "warn"}` }), a.name))) : null,
        h("h3", {}, "On this plan"), units.length ? units.map(u => h("button", { class: "linkrow", onclick: () => unitPanel(u) },
          h("span", { class: `dot ${u.offline ? "" : "ok"}` }), u.name, h("span", { class: "faint" }, ` · ${ago(u.last_at)}`), u.on_plan ? null : h("span", { class: "badge warn", style: "margin-left:6px" }, "off the plan")))
          : h("div", { class: "faint" }, "No guards or vehicles reporting."),
        h("div", { class: "faint", style: "font-size:12.5px;margin-top:8px" }, `${live.cameras.length} camera${live.cameras.length === 1 ? "" : "s"} and ${live.zones.length} zone${live.zones.length === 1 ? "" : "s"} on this plan.`));
    } else if (mode === "refs") {
      side.replaceChildren(h("h3", {}, "Tie the plan to the map"), h("p", { class: "muted" }, `Point ${"AB"[refDraft.length] || "B"} of 2. Pick spots far apart, such as two corners of the fence.`),
        plan.georeferenced ? h("p", { class: "faint" }, "The plan already has reference points; setting new ones replaces them and moves zones and cameras on the map.") : null,
        h("button", { class: "btn", onclick: () => setMode("view") }, "Cancel"));
    } else if (mode === "camera") {
      devices = devices || await api("/devices");
      const placed = new Set(live.cameras.map(x => x.camera_id));
      const all = devices.nvrs.flatMap(n => n.channels.map(ch => ({ camera_id: ch.camera_id, name: ch.name, nvr: n.name })));
      const find = h("input", { class: "input", type: "search", placeholder: "Find a camera" });
      const list = h("div", { class: "pick-list" });
      const drawList = () => list.replaceChildren(...all.filter(x => !find.value || `${x.name} ${x.camera_id}`.toLowerCase().includes(find.value.toLowerCase()))
        .sort((a, b) => placed.has(a.camera_id) - placed.has(b.camera_id)).map(x => h("button", { class: `linkrow ${placing && placing.camera_id === x.camera_id ? "on" : ""}`, onclick: () => {
          const cur = live.cameras.find(y => y.camera_id === x.camera_id);
          placing = cur ? { ...cur } : { camera_id: x.camera_id, name: x.name, bearing: 0, fov: 90, reach: Math.round(Math.max(live.plan.width, live.plan.height) / 12) }; drawSide(); draw();
        } }, h("span", { class: `dot ${placed.has(x.camera_id) ? "ok" : ""}` }), x.name, h("span", { class: "faint mono" }, ` ${x.camera_id}`))));
      find.addEventListener("input", drawList); drawList();
      const slider = (key, lab, min, max) => h("div", { class: "field" }, h("label", {}, `${lab}: `, h("span", { class: "mono" }, Math.round(placing[key]))),
        h("input", { type: "range", min, max, value: placing[key], oninput: e => { placing[key] = Number(e.target.value); e.target.previousSibling.lastChild.textContent = e.target.value; draw(); } }));
      side.replaceChildren(h("h3", {}, "Place cameras"), find, list,
        placing ? h("div", { class: "card", style: "padding:12px;margin-top:10px" }, h("strong", {}, placing.name),
          placing.x === undefined ? h("p", { class: "muted" }, "Click its spot on the plan.") : h("div", {},
            slider("bearing", "Facing (degrees, 0 = up)", 0, 359), slider("fov", "View angle", 10, 360), slider("reach", "View length on the plan", 20, Math.max(live.plan.width, live.plan.height) / 2),
            h("div", { class: "toolbar" },
              live.cameras.some(y => y.camera_id === placing.camera_id) ? h("button", { class: "btn danger", onclick: async () => { await api(`/geo/cameras/${placing.camera_id}`, { method: "DELETE" }); placing = null; load(); } }, "Remove") : null,
              h("div", { style: "flex:1" }),
              h("button", { class: "btn primary", onclick: async () => {
                try { await api(`/geo/cameras/${placing.camera_id}`, { method: "PUT", body: { plan_id: planId, x: placing.x, y: placing.y, bearing: placing.bearing % 360, fov: placing.fov, reach: placing.reach } }); toast("Camera placed"); placing = null; load(); }
                catch (ex) { toast(ex.message); }
              } }, "Save")))) : null,
        h("button", { class: "btn", style: "margin-top:10px", onclick: () => setMode("view") }, "Done"));
    } else if (mode === "zone") {
      side.replaceChildren(h("h3", {}, "Draw a zone"), h("p", { class: "muted" }, `${draft.length} corner${draft.length === 1 ? "" : "s"}. Click the corners in order around the zone.`),
        h("div", { class: "toolbar" }, h("button", { class: "btn", disabled: !draft.length, onclick: () => { draft.pop(); drawSide(); draw(); } }, "Undo corner"),
          h("button", { class: "btn primary", disabled: draft.length < 3, onclick: () => zoneForm(null, draft) }, "Finish")),
        h("button", { class: "btn", style: "margin-top:10px", onclick: () => setMode("view") }, "Cancel"));
    } else if (mode === "simulate") {
      const units = (await api("/geo/units")).units.filter(u => u.active);
      side.replaceChildren(h("h3", {}, "Walk-through"),
        h("p", { class: "muted" }, "Test zones and alerts without a phone. Each simulated position is marked as simulated in its events."),
        plan.georeferenced ? null : h("div", { class: "error" }, "Set this plan's reference points first."),
        units.length ? units.map(u => h("button", { class: `linkrow ${simUnit === u.id ? "on" : ""}`, onclick: () => { simUnit = u.id; drawSide(); } }, h("span", { class: `dot ${simUnit === u.id ? "ok" : ""}` }), u.name, h("span", { class: "faint" }, ` · ${u.kind}`)))
          : h("div", { class: "faint" }, "Add a guard or vehicle below first."),
        simUnit ? h("button", { class: "btn danger", style: "margin-top:10px", onclick: async () => {
          const u = live.units.find(x => x.id === simUnit);
          if (!u) return toast("Click on the plan to place it first");
          try { const r = await api(`/geo/units/${simUnit}/simulate`, { method: "POST", body: { plan_id: planId, x: u.x, y: u.y, alarm: "sos" } }); toast(r.events.map(e => label(e.type)).join(", ")); load(); } catch (ex) { toast(ex.message); }
        } }, "Send SOS from here") : null,
        h("button", { class: "btn", style: "margin-top:10px", onclick: () => setMode("view") }, "Done"));
    }
  }

  function cameraPanel(cam) {
    const video = h("video", { muted: true, autoplay: true, playsinline: true, class: "map-video" });
    video.muted = true;
    const st = h("div", { class: "faint", style: "font-size:12px" }, "connecting");
    const player = new LivePlayer(video, cam.camera_id, (s, info) => { st.textContent = s === "playing" ? `live ${info || ""}` : s === "error" ? info : s; });
    state.cleanup.push(() => player.close());
    side.replaceChildren(h("button", { class: "btn small", onclick: () => { player.close(); drawSide(); } }, "‹ Back"), h("h3", {}, cam.name),
      h("div", { class: "faint mono" }, cam.camera_id), video, st,
      h("div", { class: "kv", style: "margin-top:8px" }, h("div", {}, "Status"), h("div", {}, cam.online ? "online" : cam.online === false ? "offline" : "unknown"),
        h("div", {}, "AI tier"), h("div", {}, cam.tier || "?"), cam.alert ? h("div", {}, "Alert") : null, cam.alert ? h("div", {}, h("a", { href: "#/alerts" }, `open ${cam.alert} alert`)) : null));
  }
  function unitPanel(u) {
    side.replaceChildren(h("button", { class: "btn small", onclick: () => drawSide() }, "‹ Back"), h("h3", {}, u.name),
      h("div", { class: "kv" }, h("div", {}, "Type"), h("div", {}, u.kind), h("div", {}, "Last report"), h("div", {}, `${fmtTime(u.last_at)} (${ago(u.last_at)})`),
        h("div", {}, "Battery"), h("div", {}, u.battery !== null && u.battery !== undefined ? `${Math.round(u.battery)}%` : "—"),
        h("div", {}, "In zones"), h("div", {}, live.zones.filter(z => u.zones.includes(z.id)).map(z => z.name).join(", ") || "none"),
        h("div", {}, "Status"), h("div", {}, u.offline ? "not reporting" : "reporting")));
  }
  function zonePanel(z) {
    side.replaceChildren(h("button", { class: "btn small", onclick: () => drawSide() }, "‹ Back"), h("h3", {}, z.name),
      h("div", { class: "kv" }, h("div", {}, "Kind"), h("div", {}, ZONE_KINDS[z.kind]), h("div", {}, "For"), h("div", {}, { all: "guards and vehicles", guard: "guards", vehicle: "vehicles" }[z.applies_to]),
        h("div", {}, "Alerts on"), h("div", {}, z.kind === "checkpoint" ? (z.visit_every_min ? `no visit for ${z.visit_every_min} min` : "visits only logged") : { enter: "entering", exit: "leaving", both: "entering and leaving", none: "nothing" }[z.alert_on]),
        h("div", {}, "Severity"), h("div", {}, z.severity), h("div", {}, "Armed"), h("div", {}, z.armed.length ? z.armed.map(w => w.join("–")).join(", ") : "always", z.armed_now ? " (now)" : " (not now)"),
        h("div", {}, "Cameras"), h("div", {}, z.cameras.length ? z.cameras.join(", ") : "none"),
        h("div", {}, "GPS"), h("div", {}, z.has_geo ? "active" : "plan not tied to the map")),
      canEdit ? h("div", { class: "toolbar", style: "margin-top:10px" }, h("button", { class: "btn", onclick: () => zoneForm(z, z.points) }, "Edit"),
        h("button", { class: "btn danger", onclick: async () => { if (!confirm(`Delete the zone ${z.name}?`)) return; await api(`/geo/zones/${z.id}`, { method: "DELETE" }); toast("Zone deleted"); load(); drawSide(); } }, "Delete")) : null);
  }
  async function zoneForm(z, points) {
    devices = devices || await api("/devices");
    z = z || { name: "", kind: "restricted", applies_to: "all", alert_on: "enter", severity: "warning", armed: [], cameras: [], visit_every_min: 60, enabled: true };
    const name = h("input", { class: "input", id: "z-name", value: z.name, placeholder: "e.g. Store yard" });
    const sel = (id, opts, cur) => h("select", { class: "input", id }, Object.entries(opts).map(([k, v]) => h("option", { value: k, selected: k === cur }, v)));
    const kind = sel("z-kind", ZONE_KINDS, z.kind), applies = sel("z-for", { all: "Guards and vehicles", guard: "Guards", vehicle: "Vehicles" }, z.applies_to);
    const on = sel("z-on", { enter: "Entering", exit: "Leaving", both: "Entering and leaving", none: "Nothing (show only)" }, z.alert_on);
    const sev = sel("z-sev", { info: "Info", warning: "Warning", critical: "Critical" }, z.severity);
    const armed = h("input", { class: "input", id: "z-armed", value: z.armed.map(w => w.join("-")).join(", "), placeholder: "Always, or e.g. 18:00-06:00" });
    const every = h("input", { class: "input", id: "z-every", type: "number", min: 5, max: 1440, value: z.visit_every_min || "" });
    const cams = h("select", { class: "input", id: "z-cams", multiple: true, size: 6 }, devices.nvrs.flatMap(n => n.channels.map(ch => h("option", { value: ch.camera_id, selected: z.cameras.includes(ch.camera_id) }, `${ch.name} (${ch.camera_id})`))));
    const everyBox = h("div", { class: "field" }, h("label", { for: "z-every" }, "Alert if no guard visits for (minutes)"), every);
    const alertBox = h("div", { class: "field-row" }, h("div", { class: "field" }, h("label", { for: "z-on" }, "Alert on"), on), h("div", { class: "field" }, h("label", { for: "z-sev" }, "Severity"), sev));
    const sync = () => { everyBox.hidden = kind.value !== "checkpoint"; alertBox.hidden = kind.value === "checkpoint"; };
    kind.addEventListener("change", sync); sync();
    const err = h("div", { class: "error", hidden: true });
    modal(z.id ? `Edit ${z.name}` : "New zone", h("div", {}, err,
      h("div", { class: "field" }, h("label", { for: "z-name" }, "Name"), name),
      h("div", { class: "field-row" }, h("div", { class: "field" }, h("label", { for: "z-kind" }, "Kind"), kind), h("div", { class: "field" }, h("label", { for: "z-for" }, "For"), applies)),
      alertBox, everyBox,
      h("div", { class: "field" }, h("label", { for: "z-armed" }, "Armed (local time)"), armed),
      h("div", { class: "field" }, h("label", { for: "z-cams" }, "Cameras covering it (Ctrl or Cmd to pick several)"), cams,
        h("div", { class: "faint", style: "font-size:12px" }, "Events in the zone open on the first camera, and the video wall pins it."))),
      close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"), h("button", { class: "btn primary", onclick: async () => {
        const body = { name: name.value.trim(), kind: kind.value, plan_id: planId, points, applies_to: applies.value, alert_on: on.value, severity: sev.value,
          armed: parseWindows(armed.value), cameras: [...cams.selectedOptions].map(o => o.value), visit_every_min: kind.value === "checkpoint" && every.value ? Number(every.value) : null, enabled: true };
        try { await api(z.id ? `/geo/zones/${z.id}` : "/geo/zones", { method: z.id ? "PUT" : "POST", body }); close.remove(); toast("Zone saved"); setMode("view"); load(); }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "Save zone")]);
  }

  async function load(resetZoom) {
    if (!planId) return;
    try { live = await api(`/geo/live?plan_id=${planId}`); } catch (ex) { side.replaceChildren(h("div", { class: "error" }, ex.message)); return; }
    if (resetZoom || !img.src) { img.src = `/api/geo/plans/${planId}/image`; zoom = 1; }
    drawPlans(); drawModes(); draw(); if (mode === "view" && !side.querySelector("video")) drawSide();
  }

  const addPlanBtn = canEdit ? h("button", { class: "btn", onclick: () => {
    const nm = h("input", { class: "input", id: "pl-name", placeholder: "e.g. Whole site, Admin block ground floor" });
    const file = h("input", { class: "input", id: "pl-file", type: "file", accept: "image/png,image/jpeg,image/webp" });
    const err = h("div", { class: "error", hidden: true });
    modal("Add a plan", h("div", {}, err, h("p", { class: "muted", style: "margin:0 0 12px" }, "A site drawing, a floor plan, or a satellite or drone picture of the site, as PNG, JPEG or WebP (up to 8 MB). For a PDF plan, export the page as an image first."),
      h("div", { class: "field" }, h("label", { for: "pl-name" }, "Name"), nm), h("div", { class: "field" }, h("label", { for: "pl-file" }, "Image"), file)),
      close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"), h("button", { class: "btn primary", onclick: () => {
        const f = file.files[0];
        if (!f || !nm.value.trim()) { err.textContent = "Give it a name and choose an image."; err.hidden = false; return; }
        const rd = new FileReader();
        rd.onload = async () => { try { const p = await api("/geo/plans", { method: "POST", body: { name: nm.value.trim(), image_data_url: rd.result } }); close.remove(); plans = await api("/geo/plans"); planId = p.id; localStorage.setItem("hss.map.plan", p.id); render(); } catch (ex) { err.textContent = ex.message; err.hidden = false; } };
        rd.readAsDataURL(f);
      } }, "Add plan")]);
  } }, "Add plan") : null;

  c.append(h("div", { class: "toolbar" }, planBar, h("div", { style: "flex:1" }), modeBar,
    h("div", { class: "seg", role: "group", "aria-label": "Zoom" }, h("button", { onclick: () => { zoom = Math.max(1, zoom / 1.4); draw(); }, title: "Zoom out" }, "−"), h("button", { onclick: () => { zoom = Math.min(6, zoom * 1.4); draw(); }, title: "Zoom in" }, "+")),
    addPlanBtn));
  if (!plans.length) {
    c.append(h("div", { class: "empty card" }, canEdit ? "No site plans yet. Add a plan: a site drawing, a floor plan, or a satellite picture of the site." : "No site plans yet. An administrator or the CSO adds them."));
  } else {
    c.append(tip, h("div", { class: "map-wrap" }, h("section", { class: "card map-card" }, scroller), h("aside", { class: "card" }, side)));
    await load(true);
    const t = setInterval(() => { if (!document.body.contains(svg)) return clearInterval(t); if (mode === "view" || mode === "simulate") load(); }, 5000);
    state.cleanup.push(() => clearInterval(t));
  }
  if (canEdit) c.append(await unitsCard());
}

async function unitsCard() {
  const d = await api("/geo/units");
  const host = location.hostname;
  const unitForm = (u, deviceId) => {
    u = u || { name: "", kind: "guard", device_id: deviceId || `hss-${Math.random().toString(36).slice(2, 8)}`, active: true };
    const name = h("input", { class: "input", id: "u-name", value: u.name, placeholder: "e.g. Patrol 1, Supervisor's car" });
    const kind = h("select", { class: "input", id: "u-kind" }, h("option", { value: "guard", selected: u.kind === "guard" }, "Guard (phone)"), h("option", { value: "vehicle", selected: u.kind === "vehicle" }, "Vehicle (tracker or phone)"));
    const dev = h("input", { class: "input mono", id: "u-dev", value: u.device_id });
    const active = h("input", { type: "checkbox", id: "u-active", checked: u.active });
    const err = h("div", { class: "error", hidden: true });
    modal(u.id ? `Edit ${u.name}` : "Add a guard or vehicle", h("div", {}, err,
      h("div", { class: "field" }, h("label", { for: "u-name" }, "Name"), name), h("div", { class: "field" }, h("label", { for: "u-kind" }, "Type"), kind),
      h("div", { class: "field" }, h("label", { for: "u-dev" }, "Device identifier"), dev, h("div", { class: "faint", style: "font-size:12px" }, "Type the same identifier in the Traccar Client app on the phone, or the tracker's IMEI.")),
      h("label", { class: "check" }, active, "Tracking on")),
      close => [
        u.id ? h("button", { class: "btn danger", style: "margin-right:auto", onclick: async () => { if (!confirm(`Remove ${u.name}? Its position history goes too.`)) return; await api(`/geo/units/${u.id}`, { method: "DELETE" }); close.remove(); render(); } }, "Remove") : null,
        h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
        h("button", { class: "btn primary", onclick: async () => {
          try { await api(u.id ? `/geo/units/${u.id}` : "/geo/units", { method: u.id ? "PUT" : "POST", body: { name: name.value.trim(), kind: kind.value, device_id: dev.value.trim(), active: active.checked } }); close.remove(); toast("Saved"); render(); }
          catch (ex) { err.textContent = ex.message; err.hidden = false; }
        } }, "Save")]);
  };
  return card("Guards and vehicles", h("button", { class: "btn small primary", onclick: () => unitForm(null) }, "Add"),
    h("p", { class: "muted", style: "margin-top:0" }, "Phones run the free Traccar Client app. In the app: Server URL ", h("span", { class: "mono" }, `http://${host}:5055`),
      ", Device identifier as below, Location accuracy High, Frequency 30 seconds. ", h("a", { href: "#", onclick: e => { e.preventDefault(); toast("See docs/gps.md on the server for the full phone set-up"); } }, "Set-up guide")),
    d.unknown_devices.length ? h("div", { class: "note" }, "Reporting but not added: ", d.unknown_devices.map(id => h("button", { class: "btn small", style: "margin:2px", onclick: () => unitForm(null, id) }, `Add ${id}`))) : null,
    d.units.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Name", "Type", "Device identifier", "Last report", "Battery", "Status", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, d.units.map(u => h("tr", {},
        h("td", { style: "font-weight:600" }, u.name), h("td", {}, u.kind), h("td", { class: "mono" }, u.device_id),
        h("td", {}, u.last_at ? ago(u.last_at) : "never"), h("td", {}, u.battery !== null && u.battery !== undefined ? `${Math.round(u.battery)}%` : "—"),
        h("td", {}, !u.active ? h("span", { class: "badge" }, "off") : !u.last_at ? h("span", { class: "badge" }, "waiting") : u.offline ? h("span", { class: "badge bad" }, "not reporting") : h("span", { class: "badge ok" }, "reporting")),
        h("td", { style: "text-align:right" }, h("button", { class: "btn small", onclick: () => unitForm(u) }, "Edit"))))))) :
      h("div", { class: "empty" }, "None yet. Add each guard phone, then set it up in the Traccar Client app."));
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

/* ---------------- alerts: live connection, banners, sound ---------------- */
const SEV_BADGE = { critical: "bad", warning: "warn", info: "info" };
const STATUS_BADGE = { open: "bad", acknowledged: "warn", closed: "ok" };
const CLOSE_REASONS = { real_incident: "Real incident", false_alarm: "False alarm", test: "Test", duplicate: "Duplicate", other: "Other" };
const alertsAllowed = () => state.user && ["admin", "cso", "operator"].includes(state.user.role);
const prefs = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (_) { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* private mode */ } } };

async function refreshAlertCount() {
  if (!alertsAllowed()) return;
  try {
    const r = await api("/alerts?status=open&limit=1");
    state.openAlerts = r.counts.open;
    const el = document.getElementById("alert-count");
    if (el) { el.textContent = state.openAlerts || ""; el.hidden = !state.openAlerts; }
  } catch (_) { /* next update will retry */ }
}

function startAlertStream() {
  if (!alertsAllowed() || state.sse) return;
  refreshAlertCount();
  const es = state.sse = new EventSource("/api/alerts/stream");
  es.addEventListener("alert", ev => {
    const msg = JSON.parse(ev.data);
    if (msg.kind === "new") { popAlert(msg.alert); playAlertSound(msg.alert.severity); }
    refreshAlertCount();
    window.dispatchEvent(new CustomEvent("hss-alert", { detail: msg }));
  });
  es.onerror = () => { if (es.readyState === EventSource.CLOSED) { state.sse = null; setTimeout(startAlertStream, 5000); } };
}
function stopAlertStream() { if (state.sse) { state.sse.close(); state.sse = null; } }

function popAlert(a) {
  let stack = document.getElementById("alert-stack");
  if (!stack) { stack = h("div", { id: "alert-stack", class: "alert-stack", role: "alert" }); document.body.append(stack); }
  const card = h("div", { class: `alert-pop ${a.severity}` },
    a.snapshot_url ? h("img", { src: a.snapshot_url, alt: "" }) : null,
    h("div", { class: "grow" }, h("div", { class: "title" }, `${label(a.type)}${a.object_class ? ` · ${a.object_class}` : ""}`),
      h("div", { class: "muted", style: "font-size:12.5px" }, `${a.zone || a.camera_name || a.camera_id} · ${new Date(a.occurred_at).toLocaleTimeString()}`),
      h("div", { class: "toolbar", style: "margin-top:6px" },
        h("button", { class: "btn small primary", onclick: () => { card.remove(); alertDrawer(a.id); } }, "Open"),
        h("button", { class: "btn small", onclick: () => card.remove() }, "Dismiss"))),
    h("span", { class: `badge ${SEV_BADGE[a.severity]}` }, a.severity));
  stack.prepend(card);
  while (stack.children.length > 4) stack.lastChild.remove();
  if (a.severity !== "critical") setTimeout(() => card.remove(), 15000);    // critical banners stay until handled
}

let audioCtx = null;
function soundOn() { return prefs.get("hss.sound", "on") === "on"; }
function playAlertSound(severity) {
  if (!soundOn()) return;
  try {
    audioCtx ||= new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    const beeps = severity === "critical" ? [0, 0.28, 0.56] : [0];
    for (const t0 of beeps) {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = "sine"; o.frequency.value = severity === "critical" ? 880 : 660;
      g.gain.setValueAtTime(0.0001, audioCtx.currentTime + t0);
      g.gain.exponentialRampToValueAtTime(0.25, audioCtx.currentTime + t0 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + t0 + 0.22);
      o.connect(g).connect(audioCtx.destination); o.start(audioCtx.currentTime + t0); o.stop(audioCtx.currentTime + t0 + 0.25);
    }
  } catch (_) { /* no audio on this device */ }
}
// Browsers only allow sound after the user has clicked something on the page.
document.addEventListener("click", () => { if (soundOn() && audioCtx === null) { try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (_) { /* none */ } } }, { once: true });
function soundButton() {
  const b = h("button", { class: "btn small", "aria-label": "Alert sound", title: "Alert sound on or off" });
  const draw = () => { b.innerHTML = soundOn() ? I.sound : I.mute; b.title = soundOn() ? "Alert sound is on" : "Alert sound is off"; };
  b.addEventListener("click", () => { prefs.set("hss.sound", soundOn() ? "off" : "on"); draw(); if (soundOn()) playAlertSound("warning"); });
  draw();
  return b;
}

/* ---------------- alerts page ---------------- */
async function viewAlerts(c) {
  let status = "active";
  const box = h("div", {});
  const counts = h("span", { class: "muted" });
  const load = async () => {
    const r = await api(`/alerts?status=${status}&limit=200`);
    counts.textContent = `${r.counts.open} open · ${r.counts.acknowledged} acknowledged · ${r.counts.closed} closed`;
    box.replaceChildren(r.alerts.length ? h("div", { class: "list" }, r.alerts.map(alertRow))
      : h("div", { class: "empty" }, status === "active" ? "No open alerts. New ones appear here the moment they're raised." : "No alerts here."));
  };
  const onLive = () => load();
  window.addEventListener("hss-alert", onLive);
  state.cleanup.push(() => window.removeEventListener("hss-alert", onLive));
  const ages = setInterval(() => box.querySelectorAll("[data-at]").forEach(el => { el.textContent = ago(el.dataset.at); }), 15000);
  state.cleanup.push(() => clearInterval(ages));
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Status" }, [["active", "Needs action"], ["open", "Open"], ["acknowledged", "Acknowledged"], ["closed", "Closed"], ["all", "All"]].map(([k, l]) =>
    h("button", { class: k === status ? "on" : null, onclick: e => { status = k; seg.querySelectorAll("button").forEach(x => x.classList.remove("on")); e.target.classList.add("on"); load(); } }, l)));
  c.append(h("div", { class: "toolbar" }, seg, h("div", { style: "flex:1" }), counts),
    h("section", { class: "card", style: "padding:4px 12px" }, box));
  await load();
}
function alertRow(a) {
  return h("div", { class: "item", style: "cursor:pointer", onclick: () => alertDrawer(a.id) },
    h("span", { class: `sev ${a.severity}` }),
    a.snapshot_url ? h("img", { class: "thumb", src: a.snapshot_url, alt: "", loading: "lazy" }) : h("div", { class: "thumb" }),
    h("div", { class: "grow" },
      h("div", { class: "title" }, `${label(a.type)}${a.object_class ? ` · ${a.object_class}` : ""}`),
      h("div", { class: "muted", style: "font-size:12.5px" }, `${a.zone || a.camera_name || "No zone"} · ${a.camera_id}${a.assigned_to ? ` · assigned to ${a.assigned_to}` : ""}`)),
    a.escalation_level ? h("span", { class: "badge bad", title: "Not acknowledged in time" }, `escalated ×${a.escalation_level}`) : null,
    h("span", { class: `badge ${STATUS_BADGE[a.status]}` }, a.status),
    h("span", { class: "faint", style: "font-size:12px;min-width:80px;text-align:right", "data-at": a.created_at }, ago(a.created_at)));
}

function clipBox(a, id, redraw) {
  const c = (a.clips || []).slice(-1)[0];
  if (c && c.status === "done") return h("div", {}, h("video", { class: "snapshot", src: c.url, controls: true, preload: "metadata", playsinline: true }),
    h("div", { class: "faint mono", style: "font-size:11px;margin-top:4px;word-break:break-all" }, `Clip ${new Date(c.starts_at).toLocaleTimeString()}–${new Date(c.ends_at).toLocaleTimeString()} · SHA-256 ${c.sha256}`));
  if (c && (c.status === "queued" || c.status === "working")) return h("div", { class: "note" }, `Clip from the NVR recording is being prepared (${c.status})${c.detail ? ` — last try: ${c.detail}` : ""}. It appears here when ready.`);
  const ask = h("button", { class: "btn small", onclick: async () => {
    try { await api(`/alerts/${id}/clip`, { method: "POST", body: {} }); toast("Clip requested"); redraw(await api(`/alerts/${id}`)); } catch (ex) { toast(ex.message); }
  } }, "Get clip from the NVR");
  if (c && c.status === "failed") return h("div", { class: "toolbar" }, h("span", { class: "muted" }, `No clip: ${c.detail}`), ask);
  return /^nvr\d+-ch\d+$/.test(a.camera_id) ? h("div", { class: "toolbar" }, ask) : null;
}

async function alertDrawer(id) {
  closeOverlays();
  const scrim = h("div", { class: "scrim", onclick: ev => { if (ev.target === scrim) scrim.remove(); } });
  const drawer = h("div", { class: "drawer", role: "dialog", "aria-label": "Alert" }, h("div", { class: "muted" }, "Loading…"));
  scrim.append(drawer); document.body.append(scrim);
  const canManage = ["admin", "cso"].includes(state.user.role);
  const people = await api("/alerts/assignees").catch(() => []);
  const draw = a => {
    const act = async (body, msg) => {
      try { const r = await api(`/alerts/${id}/action`, { method: "POST", body }); toast(msg); draw(r); }
      catch (ex) { toast(ex.message); }
    };
    const comment = h("textarea", { class: "input", rows: 2, placeholder: "Add a note (what you did, what you saw)", maxlength: 2000 });
    const reason = h("select", { class: "input", style: "width:auto" }, Object.entries(CLOSE_REASONS).map(([k, v]) => h("option", { value: k }, v)));
    const who = h("select", { class: "input", style: "width:auto", disabled: !canManage },
      people.map(p => h("option", { value: p.username, selected: p.username === (a.assigned_to || state.user.username) }, `${p.display_name} (${p.role})`)));
    drawer.replaceChildren(
      h("div", { class: "toolbar" }, h("span", { class: `badge ${SEV_BADGE[a.severity]}` }, a.severity), h("span", { class: `badge ${STATUS_BADGE[a.status]}` }, a.status),
        h("h2", {}, label(a.type)), h("div", { style: "flex:1" }), h("button", { class: "btn small", onclick: () => scrim.remove() }, "Close")),
      a.snapshot_url ? h("img", { class: "snapshot", src: a.snapshot_url, alt: `Snapshot from ${a.camera_id}` }) : h("div", { class: "empty card" }, "No snapshot."),
      clipBox(a, id, draw),
      h("div", { class: "kv" },
        h("div", {}, "Where"), h("div", {}, [a.zone, a.camera_name, a.camera_id].filter(Boolean).join(" · ")),
        h("div", {}, "When"), h("div", {}, fmtTime(a.occurred_at)),
        h("div", {}, "What"), h("div", {}, `${label(a.type)}${a.object_class ? `, ${a.object_class}` : ""}${a.confidence ? `, ${Math.round(a.confidence * 100)}%` : ""}`),
        h("div", {}, "Rule"), h("div", {}, a.rule),
        h("div", {}, "Assigned to"), h("div", {}, a.assigned_to || "nobody yet"),
        a.repeats ? h("div", {}, "Repeats") : null, a.repeats ? h("div", {}, `${a.repeats} more event${a.repeats > 1 ? "s" : ""} at the same place`) : null,
        a.escalation_level ? h("div", {}, "Escalated") : null, a.escalation_level ? h("div", { style: "color:var(--bad)" }, `${a.escalation_level} time${a.escalation_level > 1 ? "s" : ""}`) : null,
        a.close_reason ? h("div", {}, "Closed as") : null, a.close_reason ? h("div", {}, CLOSE_REASONS[a.close_reason]) : null),
      h("div", { class: "toolbar" },
        a.status === "open" ? h("button", { class: "btn primary", onclick: () => act({ action: "acknowledge", text: comment.value }, "Acknowledged") }, "Acknowledge") : null,
        a.status === "closed" ? h("button", { class: "btn", onclick: () => act({ action: "reopen", text: comment.value }, "Reopened") }, "Reopen") : null,
        h("a", { class: "btn", href: "#/live", onclick: () => scrim.remove() }, "Live view"),
        canManage ? h("button", { class: "btn", onclick: () => sealForm(id, async () => draw(await api(`/alerts/${id}`))) }, "Seal evidence") : null,
        canManage ? h("a", { class: "btn", href: `/api/alerts/${id}/evidence`, download: "", title: "A copy that is not kept in the vault" }, "Export copy") : null),
      h("div", { class: "field" }, h("label", {}, "Note"), comment),
      h("div", { class: "toolbar" },
        h("button", { class: "btn", onclick: () => comment.value.trim() ? act({ action: "comment", text: comment.value }, "Note added") : toast("Write a note first") }, "Add note"),
        h("span", { class: "muted" }, "Assign"), who,
        h("button", { class: "btn", onclick: () => act({ action: "assign", assignee: canManage ? who.value : state.user.username, text: comment.value }, "Assigned") }, canManage ? "Assign" : "Take it")),
      a.status !== "closed" ? h("div", { class: "toolbar" }, h("span", { class: "muted" }, "Close as"), reason,
        h("button", { class: "btn", onclick: () => act({ action: "close", reason: reason.value, text: comment.value }, "Closed") }, "Close alert")) : null,
      h("h3", {}, "Timeline"),
      h("div", { class: "list" }, (a.timeline || []).slice().reverse().map(t => h("div", { class: "item" },
        h("span", { class: `dot ${t.kind === "escalated" ? "bad" : t.kind === "closed" ? "ok" : t.kind === "acknowledged" ? "warn" : ""}` }),
        h("div", { class: "grow" }, h("div", { class: "title", style: "font-weight:550" }, `${label(t.kind)}${t.username ? ` · ${t.username}` : ""}`),
          t.text ? h("div", { class: "muted", style: "font-size:12.5px;white-space:normal" }, t.text) : null),
        h("span", { class: "faint", style: "font-size:12px" }, fmtTime(t.at))))));
  };
  try { draw(await api(`/alerts/${id}`)); } catch (ex) { drawer.replaceChildren(h("div", { class: "error" }, ex.message)); }
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
    user_changed: "Changed a user", alert_acknowledge: "Acknowledged an alert", alert_assign: "Assigned an alert", alert_comment: "Noted on an alert",
    alert_close: "Closed an alert", alert_reopen: "Reopened an alert", alert_rules_changed: "Changed alert rules", evidence_exported: "Exported evidence", "2fa_enabled": "Turned on two-factor", "2fa_disabled": "Turned off two-factor", branding_changed: "Changed branding", evidence_sealed: "Sealed evidence", evidence_downloaded: "Downloaded evidence", evidence_hold: "Changed a legal hold", evidence_verify_failed: "Evidence check FAILED", legal_accepted: "Accepted the face & plate legal review", legal_revoked: "Withdrew the face & plate legal review", screen_created: "Added a wall screen", screen_changed: "Changed a wall screen", screen_deleted: "Deleted a wall screen", screen_key_changed: "Changed a wall screen link", plan_added: "Added a site plan", plan_changed: "Changed a site plan", zone_added: "Added a zone", zone_changed: "Changed a zone", zone_deleted: "Deleted a zone", unit_added: "Added a guard or vehicle", unit_changed: "Changed a guard or vehicle", unit_deleted: "Removed a guard or vehicle", unit_simulated: "Simulated a position", nvr_added: "Added an NVR", nvr_changed: "Changed an NVR", nvr_removed: "Removed an NVR", tier_changed: "Changed a camera tier", admin_created_cli: "Admin created on the server",
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
  if (["admin", "cso"].includes(me.role)) sections.push(await rulesEditor());
  sections.push(card("Appearance", null, h("div", { class: "toolbar" }, h("span", { class: "muted" }, "Theme"),
    h("div", { class: "seg" }, ["system", "dark", "light"].map(t => h("button", { class: (localStorage.getItem("hss.theme") || "system") === t ? "on" : null, onclick: () => { setTheme(t); render(); } }, label(t)))))));
  c.append(...sections);
}
async function rulesEditor() {
  let rules = await api("/alerts/rules");
  const box = h("div", { class: "grid", style: "gap:10px" });
  const list = v => (v || []).join(", ");
  const parseList = v => v.split(",").map(x => x.trim()).filter(Boolean);
  const draw = () => box.replaceChildren(...rules.map((r, i) => {
    const f = (key, el) => { el.addEventListener("change", () => { r[key] = el.type === "checkbox" ? el.checked : el.value; }); return el; };
    const txt = (key, ph) => { const el = h("input", { class: "input", value: list(r[key]), placeholder: ph }); el.addEventListener("change", () => { r[key] = parseList(el.value); }); return el; };
    const armed = h("input", { class: "input", value: (r.armed || []).map(w => w.join("-")).join(", "), placeholder: "always, or e.g. 18:00-06:00" });
    armed.addEventListener("change", () => { r.armed = parseList(armed.value).map(w => w.split("-").map(t => t.trim())); });
    const esc = h("input", { class: "input", type: "number", min: 1, max: 1440, value: r.escalate_after_min ?? "", placeholder: "never" });
    esc.addEventListener("change", () => { r.escalate_after_min = esc.value ? Number(esc.value) : null; });
    const cool = h("input", { class: "input", type: "number", min: 0, max: 86400, value: r.cooldown_s ?? 120 });
    cool.addEventListener("change", () => { r.cooldown_s = Number(cool.value || 0); });
    const chans = ["screen", "sound", "push", "whatsapp"].map(ch => {
      const cb = h("input", { type: "checkbox", checked: (r.channels || []).includes(ch) });
      cb.addEventListener("change", () => { r.channels = cb.checked ? [...new Set([...(r.channels || []), ch])] : (r.channels || []).filter(x => x !== ch); });
      return h("label", { style: "display:flex;gap:5px;align-items:center" }, cb, label(ch));
    });
    const field = (l, el) => h("div", { class: "field", style: "margin:0" }, h("label", {}, l), el);
    return h("div", { class: "card", style: "background:var(--panel-2)" },
      h("div", { class: "toolbar", style: "margin-bottom:10px" },
        h("span", { class: "badge" }, `#${i + 1}`), f("name", h("input", { class: "input", value: r.name, style: "max-width:280px;font-weight:600" })),
        h("label", { style: "display:flex;gap:6px;align-items:center" }, f("enabled", h("input", { type: "checkbox", checked: r.enabled !== false })), "On"),
        h("div", { style: "flex:1" }),
        h("button", { class: "btn small", disabled: i === 0, onclick: () => { [rules[i - 1], rules[i]] = [rules[i], rules[i - 1]]; draw(); } }, "Up"),
        h("button", { class: "btn small danger", onclick: () => { rules.splice(i, 1); draw(); } }, "Remove")),
      h("div", { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px" },
        field("Lowest severity", f("min_severity", h("select", { class: "input" }, ["info", "warning", "critical"].map(x => h("option", { value: x, selected: x === r.min_severity }, label(x)))))),
        field("Cameras", txt("cameras", "all, or e.g. nvr4-*")), field("Zones", txt("zones", "all, or e.g. *fence*")),
        field("Event types", txt("types", "all, or e.g. intrusion")), field("Objects", txt("objects", "all, or human, vehicle")),
        field("Armed", armed),
        field("Raise to", f("raise_to", h("select", { class: "input" }, [["", "keep"], ["warning", "Warning"], ["critical", "Critical"]].map(([v, l]) => h("option", { value: v, selected: (r.raise_to || "") === v }, l))))),
        field("Escalate after (min)", esc), field("Cooldown (s)", cool)),
      h("div", { class: "toolbar", style: "margin-top:10px" }, h("span", { class: "muted" }, "Channels"), chans));
  }));
  draw();
  const err = h("div", { class: "error", hidden: true });
  return card("Alert rules", h("span", { class: "muted" }, "Checked in order; the first match decides"),
    h("p", { class: "muted", style: "margin-top:0" }, "Patterns use * as a wildcard. Armed times are local, and a window like 18:00-06:00 runs overnight. Escalation sends unacknowledged alerts to everyone subscribed to “escalation”. The cooldown folds repeat events at the same camera and zone into the open alert."),
    err, box,
    h("div", { class: "toolbar", style: "margin-top:12px" },
      h("button", { class: "btn", onclick: () => { rules.push({ name: "New rule", enabled: true, min_severity: "warning", cameras: [], zones: [], types: [], objects: [], armed: [], raise_to: null, channels: ["screen", "sound"], escalate_after_min: null, cooldown_s: 120 }); draw(); } }, "Add rule"),
      h("div", { style: "flex:1" }),
      h("button", { class: "btn primary", onclick: async () => {
        err.hidden = true;
        try { rules = await api("/alerts/rules", { method: "PUT", body: rules.map(r => ({ ...r, raise_to: r.raise_to || null })) }); toast("Alert rules saved"); draw(); }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "Save rules")));
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
            h("div", {}, "1. Scan the code with your authenticator app (Google Authenticator, Microsoft Authenticator, Authy or similar) on your phone. On this phone itself, use Open in authenticator app, or copy the key and add it in the app by hand (time-based)."),
            h("div", { class: "secret" }, s.secret.replace(/(.{4})/g, "$1 ").trim()),
            h("div", { class: "toolbar" },
              h("a", { class: "btn small", href: s.uri }, "Open in authenticator app"),
              h("button", { class: "btn small", onclick: async () => {
                try { await navigator.clipboard.writeText(s.secret); toast("Key copied"); } catch (_) { toast("Select the key and copy it"); }
              } }, "Copy key")),
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
