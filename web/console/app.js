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
const fmtDate = d => d ? new Date(`${String(d).slice(0, 10)}T12:00:00`).toLocaleDateString([], { dateStyle: "medium" }) : "—";
const ago = t => {
  if (!t) return "never";
  const s = (Date.now() - new Date(t)) / 1000;
  if (s < 60) return "just now"; if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`; return `${Math.round(s / 86400)} days ago`;
};
const delay = ms => { const s = ms / 1000; return s < 60 ? `${s.toFixed(1)} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`; };
const initials = u => (u.display_name || u.username || "?").split(/[\s._@-]+/).filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join("");
const ROLE_NAMES = { admin: "Administrator", cso: "Chief Security Officer", operator: "Operator", management: "Management", guard: "Guard (phone app only)",
  viewer: "Viewer (watch and read only)", client: "Client (their cameras only)" };
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
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z"/><path d="M12 8v5M12 16h.01"/></svg>',
  start: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 3v18M5 4h11l-2 4 2 4H5"/></svg>',
  help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 015 .5c0 1.7-2.5 2-2.5 3.5M12 17h.01"/></svg>',
  planner: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 12l16-7v14L4 12z"/><circle cx="4" cy="12" r="1.5"/></svg>',
  playback: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/><path d="M3 12h2"/></svg>',
  logbook: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 3h11a2 2 0 012 2v16H6a2 2 0 01-2-2V5a2 2 0 012-2z"/><path d="M8 8h7M8 12h7M8 16h4"/></svg>',
  heat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5" fill="currentColor" fill-opacity=".35"/><rect x="3" y="14" width="7" height="7" rx="1.5" fill="currentColor" fill-opacity=".7"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>',
  noise: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20V10M9 20V4M14 20v-7M19 20v-11"/></svg>',
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
  { id: "start", title: "Getting started", icon: "start", roles: ["admin", "cso"], view: viewStart },
  { id: "alerts", title: "Alerts", icon: "alert", roles: ["admin", "cso", "operator", "viewer"], view: viewAlerts },
  { id: "live", title: "Live view", icon: "live", roles: ["admin", "cso", "operator", "viewer", "client"], view: viewLive },
  { id: "logbook", title: "Logbook", icon: "logbook", roles: ["admin", "cso", "operator", "management"], view: viewLogbook },
  { id: "playback", title: "Playback", icon: "playback", roles: ["admin", "cso", "operator", "viewer", "client"], playback: true, view: viewPlayback },
  { id: "events", title: "Events", icon: "events", roles: ["admin", "cso", "operator", "viewer"], view: viewEvents },
  { id: "evidence", title: "Evidence vault", icon: "vault", roles: ["admin", "cso"], view: viewEvidence },
  { id: "map", title: "Site map", icon: "map", roles: ["admin", "cso", "operator", "viewer"], view: viewMap },
  { group: "Manage" },
  { id: "devices", title: "Devices", icon: "devices", roles: ["admin", "cso", "operator", "management"], view: viewDevices },
  { id: "event-setup", title: "Event setup", icon: "setup", roles: ["admin", "cso", "operator"], allCameras: true, view: viewEventSetup },
  { id: "face-plate", title: "Face & plate", icon: "legal", roles: ["admin", "cso", "management"], view: viewFacePlate },
  { id: "heatmap", title: "Incident heat map", icon: "heat", roles: ["admin", "cso", "operator", "management", "viewer"], view: viewHeatmap },
  { id: "false-alarms", title: "False alarms", icon: "noise", roles: ["admin", "cso", "management"], view: viewFalseAlarms },
  { id: "planner", title: "Camera planner", icon: "planner", roles: ["admin", "cso", "management"], view: viewPlanner },
  { id: "walls", title: "Video walls", icon: "walls", roles: ["admin", "cso"], view: viewWalls },
  { id: "reports", title: "Reports", icon: "reports", roles: ["admin", "cso", "management"], view: viewReports },
  { id: "notify", title: "WhatsApp & alerts", icon: "notify", roles: ["admin", "cso"], view: viewNotify },
  { group: "Administration", roles: ["admin"] },
  { id: "users", title: "Users", icon: "users", roles: ["admin"], view: viewUsers },
  { id: "security", title: "Security", icon: "shield", roles: ["admin", "cso"], view: viewSecurity },
  { id: "audit", title: "Audit log", icon: "audit", roles: ["admin"], view: viewAudit },
  { id: "viewing", title: "Viewing log", icon: "audit", roles: ["admin", "cso"], view: viewViewing },
  { id: "help", title: "Help", icon: "help", roles: ["admin", "cso", "operator", "management", "viewer", "client"], view: viewHelp },
  { id: "settings", title: "Settings", icon: "settings", roles: ["admin", "cso", "operator", "management", "viewer", "client"], view: viewSettings },
];
// Per-camera access: a user limited to some cameras doesn't get pages that work on every camera at once,
// and Playback only when the account may watch recordings (access.py on the server enforces both).
const limitedCams = () => !["admin", "cso"].includes(state.user.role) && (state.user.cameras || []).length > 0;
const allowed = p => p.view && p.roles.includes(state.user.role) && !(p.allCameras && limitedCams()) && !(p.playback && state.user.can_playback === false);
function currentPage() {
  const id = location.hash.replace(/^#\/?/, "").split("?")[0];
  return PAGES.find(p => p.id === id && allowed(p)) || PAGES.find(p => p.id === "overview" && allowed(p)) || PAGES.find(p => allowed(p));
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
  if (state.user.role === "guard") { location.replace("/m/"); return; }       // guards use the phone app only
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
    if (p.group) {                      // a heading only when something under it is shown
      const i = PAGES.indexOf(p), next = PAGES.slice(i + 1), end = next.findIndex(x => x.group);
      if ((!p.roles || p.roles.includes(u.role)) && next.slice(0, end < 0 ? undefined : end).some(allowed)) nav.append(h("div", { class: "group" }, p.group));
      continue;
    }
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
        h("div", { class: "spacer" }), statusPills, ["admin", "cso", "operator"].includes(u.role) ? h("button", { class: "btn small lock-btn", id: "lock-btn", title: "Put the whole site in lockdown", onclick: () => startLockdown() }, "Lockdown") : null,
        alertsAllowed() ? soundButton() : null, clock),
      h("div", { id: "lockdown-bar", class: "lockdown-bar", role: "alert", hidden: true }),
      content));
  nav.addEventListener("click", () => shell.classList.remove("open"));
  loadStatusPills(statusPills);
  refreshLockdown();
  const lp = setInterval(refreshLockdown, 30000); state.cleanup.push(() => clearInterval(lp));
  startAlertStream();
  Promise.resolve(page.view(content)).catch(e => content.replaceChildren(h("div", { class: "error" }, `Couldn't load this page: ${e.message}`)));
  return shell;
}

/* ---------------- master lockdown ---------------- */
async function refreshLockdown() {
  try { drawLockdown((await api("/lockdown")).lockdown); } catch (_) { /* next poll */ }
}
function drawLockdown(l) {
  state.lockdown = l;
  const bar = document.getElementById("lockdown-bar"), btn = document.getElementById("lock-btn");
  if (btn) btn.hidden = !!l;
  if (!bar) return;
  if (!l) { bar.hidden = true; bar.replaceChildren(); return; }
  const canEnd = ["admin", "cso"].includes(state.user.role);
  bar.replaceChildren(h("strong", {}, "LOCKDOWN"),
    h("span", {}, ` since ${new Date(l.since).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${l.by} · ${l.reason}`),
    h("span", { class: "muted-on-red" }, " · every rule armed, every alert critical"),
    canEnd ? h("button", { class: "btn small", onclick: endLockdown }, "End lockdown") : null);
  bar.hidden = false;
}
function startLockdown() {
  const reason = h("textarea", { class: "input", id: "lock-reason", rows: 3, placeholder: "What is happening, for example: armed men seen at the east fence" });
  const err = h("div", { class: "error", hidden: true });
  modal("Put the site in lockdown?", h("div", {},
    h("p", { style: "margin-top:0" }, "Every alert rule is armed at once, every new alert is critical, the lockdown lights and sirens switch on, and everyone subscribed to “lockdown” is messaged. Only the CSO or an administrator can end it."),
    h("div", { class: "field" }, h("label", { for: "lock-reason" }, "Reason (sent with the messages)"), reason), err),
    sc => [h("button", { class: "btn", onclick: () => sc.remove() }, "Cancel"),
      h("button", { class: "btn danger-solid", onclick: async () => {
        if (reason.value.trim().length < 3) { err.textContent = "Say briefly what is happening."; err.hidden = false; return; }
        try { const r = await api("/lockdown", { method: "POST", body: { reason: reason.value.trim() } }); sc.remove(); drawLockdown(r.lockdown); toast("Lockdown started. Messages are going out."); }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "Start lockdown")]);
}
function endLockdown() {
  const note = h("input", { class: "input", id: "lock-note", placeholder: "Optional: how it ended, for example: police on site, all clear" });
  const err = h("div", { class: "error", hidden: true });
  modal("End the lockdown?", h("div", {},
    h("p", { style: "margin-top:0" }, "Alert rules go back to their normal times, the lockdown lights and sirens switch off, and everyone subscribed to “lockdown” is told."),
    h("div", { class: "field" }, h("label", { for: "lock-note" }, "Note"), note), err),
    sc => [h("button", { class: "btn", onclick: () => sc.remove() }, "Cancel"),
      h("button", { class: "btn primary", onclick: async () => {
        try { const r = await api("/lockdown/end", { method: "POST", body: { note: note.value.trim() } }); sc.remove(); drawLockdown(null); toast(`Lockdown ended after ${r.minutes} min.`); }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "End lockdown")]);
}
async function lockdownSettings() {
  const [cfg, outs, st] = await Promise.all([api("/lockdown/config"), api("/outputs").catch(() => []), api("/lockdown")]);
  const chosen = new Set(cfg.outputs.map(x => x.toLowerCase()));
  const boxes = outs.map(o => h("label", { class: "check" }, h("input", { type: "checkbox", value: o.name, checked: chosen.has(o.name.toLowerCase()) }), ` ${o.name}`));
  const last = st.last && st.last.ended_at ? h("p", { class: "muted", style: "margin:10px 0 0;font-size:12.5px" },
    `Last lockdown: ${fmtTime(st.last.since)} by ${st.last.by_name} (${st.last.reason}); ended ${fmtTime(st.last.ended_at)} by ${st.last.ended_by}.`,
    st.last.start_result ? ` Start: ${[...(st.last.start_result.outputs || []), st.last.start_result.messages].join("; ")}.` : "") : null;
  return card("Lockdown", null,
    h("p", { class: "muted", style: "margin-top:0" }, "The Lockdown button at the top arms every rule and makes every alert critical until the CSO ends it. Choose the outputs to switch on for the whole lockdown, and subscribe people to “lockdown” in config/recipients.json so they are messaged."),
    outs.length ? h("div", { style: "display:flex;flex-wrap:wrap;gap:6px 18px;margin-bottom:10px" }, boxes) : h("p", { class: "muted" }, "No sirens or lights added yet (Live view › Sirens and lights)."),
    outs.length ? h("button", { class: "btn", onclick: async () => {
      try { await api("/lockdown/config", { method: "PUT", body: { outputs: boxes.map(b => b.querySelector("input")).filter(i => i.checked).map(i => i.value) } }); toast("Lockdown outputs saved"); }
      catch (ex) { toast(ex.message); } } }, "Save") : null, last);
}

async function complianceSettings() {
  const cfg = await api("/reports/compliance/settings");
  const due = h("input", { class: "input", type: "date", id: "cp-dpia", value: cfg.dpia_review_due || "" });
  const signs = h("input", { class: "input", type: "date", id: "cp-signs", value: cfg.signs_checked_on || "" });
  const dpo = h("input", { class: "input", id: "cp-dpo", value: cfg.dpo_name || "", placeholder: "Name and phone or e-mail" });
  return card("Compliance", null,
    h("p", { class: "muted", style: "margin-top:0" }, "Dates the monthly compliance and privacy report checks against. Update them when the DPIA is reviewed and after each walk round the recognition signs."),
    h("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:0 12px" },
      h("div", { class: "field" }, h("label", { for: "cp-dpia" }, "DPIA review due"), due),
      h("div", { class: "field" }, h("label", { for: "cp-signs" }, "Recognition signs last checked"), signs),
      h("div", { class: "field" }, h("label", { for: "cp-dpo" }, "Data Protection Officer"), dpo)),
    h("button", { class: "btn", onclick: async () => {
      try { await api("/reports/compliance/settings", { method: "PUT", body: { dpia_review_due: due.value || null, signs_checked_on: signs.value || null, dpo_name: dpo.value } }); toast("Compliance dates saved"); }
      catch (ex) { toast(ex.message); } } }, "Save"));
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
  let setup = null, handover = null;
  if (["admin", "cso"].includes(state.user.role)) { try { setup = await api("/system/onboarding"); } catch (_) { /* older API */ } }
  if (canEvents) { try { handover = await api("/logbook/handover/pending"); } catch (_) { /* older API */ } }
  const [events, devices] = await Promise.all([canEvents ? api("/events?limit=8") : [], api("/devices")]);
  const d = o.devices, pct = d.cameras ? Math.round(100 * d.online / d.cameras) : 0;
  const ev = o.events_24h;
  c.replaceChildren(
    handover && !handover.mine ? h("a", { class: "setup-banner", href: "#/logbook" }, h("strong", {}, `Handover from ${handover.from_user} waiting`),
      h("span", { class: "muted" }, ` · ${handover.shift_label} shift · ${handover.summary.open_alerts} open alert${handover.summary.open_alerts === 1 ? "" : "s"} · take over in the Logbook`)) : null,
    setup && setup.done < setup.total ? h("a", { class: "setup-banner", href: "#/start" },
      h("strong", {}, `Setup: ${setup.done} of ${setup.total} done`), h("span", { class: "muted" }, " · next: ", (setup.steps.find(x => !x.done && !x.optional) || {}).title || ""),
      h("div", { class: "bar" }, h("span", { style: `width:${Math.round(100 * setup.done / setup.total)}%` }))) : null,
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

/* ---------------- PTZ control ---------------- */
const ptzCache = {};
async function ptzPanel(cameraId, label) {
  if (!["admin", "cso", "operator"].includes(state.user.role)) return h("div");      // viewers and clients only watch
  let info = ptzCache[cameraId];
  if (!info) {
    try { info = await api(`/ptz/${encodeURIComponent(cameraId)}`); } catch (ex) { info = { supported: false, why: ex.message }; }
    if (info.supported || info.why === undefined) ptzCache[cameraId] = info;
  }
  if (!info.supported) return h("div", { class: "faint ptz-none" }, `${label}: no PTZ`, info.why && !/added in Devices/.test(info.why) ? ` (${info.why})` : "");
  let speed = Number(localStorage.getItem("hss.ptz.speed") || 50), timer = null, moving = false;
  const msg = h("div", { class: "faint", style: "font-size:12px;min-height:16px" }, info.held_by ? `${info.held_by} is steering it` : "");
  const send = async (pan, tilt, zoom) => {
    try { await api(`/ptz/${encodeURIComponent(cameraId)}/move`, { method: "POST", body: { pan: Math.round(pan * speed), tilt: Math.round(tilt * speed), zoom: Math.round(zoom * speed) } }); msg.textContent = ""; }
    catch (ex) { msg.textContent = ex.message; end(false); }
  };
  const start = (pan, tilt, zoom) => { if (moving) return; moving = true; send(pan, tilt, zoom); timer = setInterval(() => send(pan, tilt, zoom), 500); };
  const end = (tell = true) => {
    if (!moving) return; moving = false; clearInterval(timer);
    if (tell) api(`/ptz/${encodeURIComponent(cameraId)}/stop`, { method: "POST", body: {} }).catch(() => {});
  };
  state.cleanup.push(() => end());
  const hold = (label, title, pan, tilt, zoom) => h("button", { class: "ptz-btn", title, "aria-label": title,
    onpointerdown: e => { e.preventDefault(); e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId); start(pan, tilt, zoom); },
    onpointerup: () => end(), onpointercancel: () => end(), onlostpointercapture: () => end(),
    onkeydown: e => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); start(pan, tilt, zoom); } },
    onkeyup: e => { if (e.key === " " || e.key === "Enter") end(); } }, label);
  const pad = h("div", { class: "ptz-pad" },
    hold("↖", "Up and left", -1, 1, 0), hold("↑", "Up", 0, 1, 0), hold("↗", "Up and right", 1, 1, 0),
    hold("←", "Left", -1, 0, 0), h("span", { class: "ptz-dot" }), hold("→", "Right", 1, 0, 0),
    hold("↙", "Down and left", -1, -1, 0), hold("↓", "Down", 0, -1, 0), hold("↘", "Down and right", 1, -1, 0));
  const zoom = h("div", { class: "ptz-zoom" }, hold("−", "Zoom out", 0, 0, -1), h("span", { class: "faint" }, "zoom"), hold("+", "Zoom in", 0, 0, 1));
  const sp = h("input", { type: "range", min: 10, max: 100, step: 10, value: speed, "aria-label": "Speed", oninput: e => { speed = Number(e.target.value); try { localStorage.setItem("hss.ptz.speed", speed); } catch (_) {} } });
  const presetSel = h("select", { class: "input", "aria-label": "Preset" }, info.presets.length ? info.presets.map(p => h("option", { value: p.id }, `${p.id}. ${p.name}`)) : h("option", { value: "" }, "No presets yet"));
  const goBtn = h("button", { class: "btn small", disabled: !info.presets.length, onclick: async () => {
    try { await api(`/ptz/${encodeURIComponent(cameraId)}/presets/${presetSel.value}/goto`, { method: "POST", body: {} }); msg.textContent = "Going to the preset"; } catch (ex) { msg.textContent = ex.message; }
  } }, "Go");
  const save = info.can_save_presets ? h("button", { class: "btn small", title: "Save the camera's current view as a preset", onclick: () => {
    const num = h("input", { class: "input", id: "pz-num", type: "number", min: 1, max: 300, value: (info.presets.reduce((m, p) => Math.max(m, p.id), 0) || 0) + 1 });
    const name = h("input", { class: "input", id: "pz-name", maxlength: 32, placeholder: "e.g. Fence east" });
    const err = h("div", { class: "error", hidden: true });
    modal(`Save a preset on ${label}`, h("div", {}, err, h("p", { class: "muted", style: "margin:0 0 12px" }, "Saves where the camera points now. A number already in use is replaced."),
      h("div", { class: "field-row" }, h("div", { class: "field" }, h("label", { for: "pz-num" }, "Number"), num), h("div", { class: "field" }, h("label", { for: "pz-name" }, "Name"), name))),
      close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"), h("button", { class: "btn primary", onclick: async () => {
        try { const r = await api(`/ptz/${encodeURIComponent(cameraId)}/presets/${Number(num.value)}`, { method: "PUT", body: { name: name.value.trim() || `Preset ${num.value}` } });
          info.presets = r.presets; ptzCache[cameraId] = info; close.remove(); toast("Preset saved");
          presetSel.replaceChildren(...info.presets.map(p => h("option", { value: p.id }, `${p.id}. ${p.name}`))); goBtn.disabled = !info.presets.length;
        } catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "Save")]);
  } }, "Save view") : null;
  return h("div", { class: "ptz" }, h("div", { class: "ptz-title" }, "PTZ · ", label), h("div", { class: "ptz-row" }, pad, zoom),
    h("label", { class: "ptz-speed" }, h("span", { class: "faint" }, "Speed"), sp),
    h("div", { class: "toolbar", style: "gap:6px;margin-top:6px" }, presetSel, goBtn, save), msg);
}

/* ---------------- false alarm tuning ---------------- */
async function viewFalseAlarms(c) {
  let days = Number(localStorage.getItem("hss.fa.days") || 30);
  const out = h("div", { class: "grid", style: "gap:14px" });
  const pct = r => r === null || r === undefined ? "—" : `${Math.round(r * 100)}%`;
  const dur = s => s === null || s === undefined ? "—" : s < 120 ? `${s} s` : s < 7200 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
  const playLink = x => h("a", { class: "btn small", href: `#/playback?cam=${encodeURIComponent(x.camera_id)}&t=${encodeURIComponent(new Date(new Date(x.at) - 10000).toISOString())}` }, new Date(x.at).toLocaleString([], { dateStyle: "short", timeStyle: "short" }));
  const table = (title, rows, what, empty) => card(title, null, rows.length ? h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, [what, "Alerts", "False", "Real", "False rate", "What to try", "Check recent false alarms"].map(t => h("th", {}, t)))),
    h("tbody", {}, rows.slice(0, 12).map(r => h("tr", { class: r.noisy ? "fa-noisy" : "" },
      h("td", { style: "font-weight:600" }, r.label, r.label !== r.key ? h("div", { class: "faint mono", style: "font-size:11.5px;font-weight:400" }, r.key) : null),
      h("td", {}, r.alerts), h("td", {}, r.false), h("td", {}, r.real),
      h("td", {}, r.rate === null ? h("span", { class: "faint" }, "not reviewed") : h("span", { class: `badge ${r.noisy ? "bad" : r.rate >= 0.4 ? "warn" : "ok"}` }, pct(r.rate))),
      h("td", { style: "max-width:420px;white-space:normal;font-size:12.5px" }, r.tips.length ? h("ul", { style: "margin:0;padding-left:16px" }, r.tips.map(t => h("li", {}, t))) : h("span", { class: "faint" }, r.noisy ? "" : "—")),
      h("td", { style: "white-space:nowrap" }, r.recent_false.map(x => [playLink(x), " "])))))) ) : h("div", { class: "empty" }, empty));
  const chart = hours => {
    const W = 720, H = 180, pad = 28, bw = (W - pad * 2) / 24, max = Math.max(1, ...hours.map(x => x.false + x.real + x.other));
    const ns = "http://www.w3.org/2000/svg", el = (n, a, t) => { const e = document.createElementNS(ns, n); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); if (t !== undefined) e.textContent = t; return e; };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H + 24}`, class: "fa-chart", role: "img", "aria-label": "False and real alarms by hour of day" });
    const Y = v => H - v / max * (H - 16);
    for (const g of [0.5, 1]) svg.append(el("line", { x1: pad, x2: W - pad, y1: Y(max * g), y2: Y(max * g), class: "fa-grid" }), el("text", { x: pad - 4, y: Y(max * g) + 4, class: "fa-axis", "text-anchor": "end" }, Math.round(max * g)));
    hours.forEach((x, i) => {
      let y0 = H;
      for (const [k, cls] of [["real", "fa-real"], ["false", "fa-false"], ["other", "fa-other"]]) {
        if (!x[k]) continue;
        const hgt = H - Y(x[k]);
        svg.append(el("rect", { x: pad + i * bw + 2, y: y0 - hgt, width: bw - 4, height: hgt, class: cls }, undefined));
        svg.lastChild.append(el("title", {}, `${String(i).padStart(2, "0")}:00 · ${x[k]} ${k === "real" ? "real incidents" : k === "false" ? "false alarms" : "other or open"}`));
        y0 -= hgt;
      }
      if (i % 3 === 0) svg.append(el("text", { x: pad + i * bw + bw / 2, y: H + 16, class: "fa-axis", "text-anchor": "middle" }, `${String(i).padStart(2, "0")}:00`));
    });
    svg.append(el("line", { x1: pad, x2: W - pad, y1: H, y2: H, class: "fa-base" }));
    return h("div", {}, svg, h("div", { class: "legend" }, h("span", {}, h("i", { class: "lg fa-l-false" }), "false alarm"), h("span", {}, h("i", { class: "lg fa-l-real" }), "real incident"), h("span", {}, h("i", { class: "lg fa-l-other" }), "test, duplicate, other or still open")));
  };
  const load = async () => {
    const d = await api(`/insights/false-alarms?days=${days}`);
    const k = d.kpis;
    out.replaceChildren(
      h("div", { class: "grid kpis" },
        kpi("Alerts", k.alerts, `last ${days} days, device alerts left out`),
        kpi("False alarm rate", h("span", { style: `color:${k.rate >= 0.6 ? "var(--bad)" : k.rate >= 0.4 ? "var(--warn)" : "var(--ok)"}` }, pct(k.rate)), `${k.false} false, ${k.real} real incidents`),
        kpi("Time to acknowledge", dur(k.ack_median_s), "median"),
        kpi("Not reviewed", h("span", { style: `color:${k.open_over_24h ? "var(--warn)" : "inherit"}` }, k.open), `${k.open_over_24h} open for more than a day`)),
      k.false + k.real === 0 ? h("div", { class: "note" }, "No alerts have been closed as false alarm or real incident in this period yet. The dashboard learns from how operators close alerts: ask them to always pick the right reason.") : null,
      card("By hour of day", null, chart(d.by_hour)),
      table("Rules", d.by_rule, "Rule", "No alerts in this period."),
      table("Cameras", d.by_camera, "Camera", "No alerts in this period."));
  };
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Period" }, [7, 30, 90].map(n => h("button", { class: n === days ? "on" : null, onclick: e => {
    days = n; try { localStorage.setItem("hss.fa.days", n); } catch (_) {} seg.querySelectorAll("button").forEach(b => b.classList.toggle("on", b === e.target)); load();
  } }, `${n} days`)));
  c.append(h("div", { class: "toolbar" }, h("span", { class: "muted" }, "Rules and cameras with a false alarm rate of 60% or more (and at least 5 reviewed alerts) are marked, with what to try."), h("div", { style: "flex:1" }), seg), out);
  await load();
}

/* ---------------- logbook and shift handover ---------------- */
const LOG_CATS = { patrol: "Patrol", incident: "Incident", visitor: "Visitor", maintenance: "Maintenance", other: "Other" };
function handoverSummary(s) {
  const sev = s.alerts_raised || {}, raised = (sev.critical || 0) + (sev.warning || 0) + (sev.info || 0);
  return h("div", { class: "grid", style: "gap:8px" },
    h("div", { class: "kv" },
      h("div", {}, "Alerts this shift"), h("div", {}, `${raised} raised (${sev.critical || 0} critical, ${sev.warning || 0} warning)`),
      h("div", {}, "Still open"), h("div", { style: s.open_alerts ? "color:var(--bad);font-weight:600" : "" }, `${s.open_alerts}`),
      h("div", {}, "Device problems"), h("div", {}, s.device_problems.length ? s.device_problems.map(d => `${label(d.type)} ${d.camera}`).join("; ") : "none"),
      h("div", {}, "Sirens or lights on"), h("div", { style: s.outputs_on.length ? "color:var(--bad)" : "" }, s.outputs_on.length ? s.outputs_on.join(", ") : "none"),
      h("div", {}, "Log entries"), h("div", {}, Object.entries(s.entries).map(([k, v]) => `${v} ${(LOG_CATS[k] || k).toLowerCase()}`).join(", ") || "none")),
    s.open_list.length ? h("div", { class: "list" }, s.open_list.slice(0, 6).map(a => h("a", { class: "item", href: "#/alerts", style: "text-decoration:none;color:inherit" },
      h("span", { class: `sev ${a.severity}` }), h("div", { class: "grow" }, h("div", { style: "font-weight:600" }, `${label(a.type)} · ${a.camera}`),
        h("div", { class: "faint", style: "font-size:12px" }, `${a.status}${a.assigned_to ? `, with ${a.assigned_to}` : ""} · since ${fmtTime(a.since)}`)))),
      s.open_alerts > 6 ? h("a", { href: "#/alerts", class: "faint", style: "font-size:12.5px;padding:4px 6px" }, `and ${s.open_alerts - 6} more open alerts on the Alerts page`) : null) : null);
}

async function viewLogbook(c) {
  const writer = ["admin", "cso", "operator"].includes(state.user.role);
  let sh = await api("/logbook/shift");
  const body = h("div", {});
  const head = h("div", {});
  const pend = h("div", {});
  const fmtHM = t => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const load = async () => {
    const d = await api(`/logbook?start=${encodeURIComponent(sh.start)}&end=${encodeURIComponent(sh.end)}`);
    const left = Math.max(0, Math.round((new Date(sh.end) - Date.now()) / 60000));
    head.replaceChildren(h("div", { class: "toolbar" },
      h("button", { class: "btn small", onclick: async () => { sh = await api(`/logbook/shift?at=${encodeURIComponent(new Date(new Date(sh.start) - 60000).toISOString())}`); load(); } }, "‹ Earlier shift"),
      h("div", { style: "text-align:center;flex:1" }, h("div", { style: "font-weight:650;font-size:15px" }, `${sh.label} shift`),
        h("div", { class: "muted", style: "font-size:12.5px" }, `${fmtTime(sh.start)} to ${fmtHM(sh.end)}`, sh.is_current ? ` · ${Math.floor(left / 60)} h ${left % 60} min left` : "")),
      h("button", { class: "btn small", disabled: sh.is_current, onclick: async () => { sh = await api(`/logbook/shift?at=${encodeURIComponent(new Date(new Date(sh.end).getTime() + 60000).toISOString())}`); load(); } }, "Later shift ›")));
    const items = [
      ...d.entries.map(e => ({ at: e.at, el: h("div", { class: "item log-entry" },
        h("span", { class: `badge cat-${e.category}` }, LOG_CATS[e.category]),
        h("div", { class: "grow", style: "min-width:0" }, h("div", { style: "white-space:pre-wrap" }, e.text),
          h("div", { class: "faint", style: "font-size:12px" }, `${e.name} · ${fmtHM(e.at)}`, e.edited_at ? " · corrected" : "", e.alert_id ? h("span", {}, " · ", h("a", { href: "#/alerts" }, "linked alert")) : null)),
        writer && e.username === state.user.username && Date.now() - new Date(e.at) < 15 * 60000 ? h("button", { class: "btn small", onclick: () => {
          const t = h("textarea", { class: "input", rows: 4 }, e.text);
          modal("Correct the entry", h("div", {}, h("p", { class: "muted", style: "margin:0 0 10px" }, "Entries can be corrected for 15 minutes after writing."), t),
            close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"), h("button", { class: "btn primary", onclick: async () => {
              try { await api(`/logbook/${e.id}`, { method: "PUT", body: { text: t.value } }); close.remove(); load(); } catch (ex) { toast(ex.message); }
            } }, "Save")]);
        } }, "Correct") : null) })),
      ...d.handovers.map(x => ({ at: x.from_at, el: h("div", { class: "item handover-item" },
        h("span", { class: "badge info" }, "Handover"),
        h("div", { class: "grow", style: "min-width:0" },
          h("div", { style: "font-weight:600" }, `${x.from_user} handed over the ${x.shift_label} shift at ${fmtHM(x.from_at)}`, x.to_user ? ` · ${x.to_user} took over at ${fmtHM(x.to_at)}` : " · not taken over yet"),
          x.notes ? h("div", { style: "white-space:pre-wrap;margin:4px 0" }, x.notes) : null,
          x.to_note ? h("div", { class: "muted", style: "white-space:pre-wrap" }, `${x.to_user}: ${x.to_note}`) : null,
          h("details", {}, h("summary", { class: "faint", style: "font-size:12.5px;cursor:pointer" }, "Shift summary"), handoverSummary(x.summary)))) })),
    ].sort((a, b) => new Date(b.at) - new Date(a.at));
    body.replaceChildren(items.length ? h("div", { class: "list" }, items.map(i => i.el)) : h("div", { class: "empty" }, "Nothing logged in this shift yet."));
    const p = writer ? await api("/logbook/handover/pending") : null;
    pend.replaceChildren(p && !p.mine ? h("section", { class: "card", style: "border-color:var(--accent)" },
      h("div", { class: "head" }, h("h2", {}, `${p.from_user} handed over the ${p.shift_label} shift`), h("div", { class: "spacer" }), h("span", { class: "muted" }, fmtTime(p.from_at))),
      p.notes ? h("div", { class: "note", style: "white-space:pre-wrap;margin-bottom:10px" }, h("strong", {}, "To watch: "), p.notes) : null,
      handoverSummary(p.summary),
      (() => { const note = h("input", { class: "input", placeholder: "Optional note, e.g. briefed in person" }); return h("div", { class: "toolbar", style: "margin-top:10px" }, note,
        h("button", { class: "btn primary", onclick: async () => { try { await api(`/logbook/handover/${p.id}/take`, { method: "POST", body: { note: note.value } }); toast("You have taken over the shift"); load(); } catch (ex) { toast(ex.message); } } }, "Take over")); })())
      : p && p.mine ? h("div", { class: "note" }, "You handed over this shift; it's waiting for the next operator to take over.") : null);
  };
  const form = writer ? (() => {
    const cat = h("select", { class: "input", id: "lb-cat", style: "max-width:170px" }, Object.entries(LOG_CATS).map(([k, v]) => h("option", { value: k }, v)));
    const text = h("textarea", { class: "input", id: "lb-text", rows: 3, placeholder: "What happened, where, who, what you did" });
    return h("section", { class: "card" }, h("div", { class: "field" }, h("label", { for: "lb-text" }, "New entry"), text),
      h("div", { class: "toolbar" }, cat, h("div", { style: "flex:1" }),
        h("button", { class: "btn", onclick: async () => {
          const d = await api("/logbook/handover/draft");
          const notes = h("textarea", { class: "input", rows: 4, placeholder: "What the next shift must watch: open alerts, visitors still on site, faults, instructions" });
          modal(`Hand over the ${d.shift.label} shift`, h("div", { class: "grid", style: "gap:10px" }, h("div", { class: "field", style: "margin:0" }, h("label", {}, "Things to watch"), notes),
            h("div", { class: "faint", style: "font-size:12.5px;font-weight:600" }, "Shift summary, added for you"), handoverSummary(d.summary)),
            close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"), h("button", { class: "btn primary", onclick: async () => {
              try { await api("/logbook/handover", { method: "POST", body: { notes: notes.value } }); close.remove(); toast("Handed over; the next operator takes over in the Logbook"); load(); } catch (ex) { toast(ex.message); }
            } }, "Hand over")]);
        } }, "Hand over shift"),
        h("button", { class: "btn primary", onclick: async () => {
          if (!text.value.trim()) return toast("Write the entry first");
          try { await api("/logbook", { method: "POST", body: { category: cat.value, text: text.value } }); text.value = ""; load(); } catch (ex) { toast(ex.message); }
        } }, "Add to log")));
  })() : null;
  c.append(pend, form, h("section", { class: "card" }, head, body));
  await load();
}

/* ---------------- playback of recordings ---------------- */
async function viewPlayback(c) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const dev = await api("/devices");
  const cams = dev.nvrs.filter(n => n.registered).flatMap(n => n.channels.map(ch => ({ id: ch.camera_id, name: ch.name, nvr: n.name })));
  if (!cams.length) { c.append(h("div", { class: "empty card" }, "Playback works for cameras on NVRs added in Devices. Add an NVR there first.")); return; }
  const pad = n => String(n).padStart(2, "0");
  const localDay = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const hms = d => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  let cam = params.get("cam") && cams.some(x => x.id === params.get("cam")) ? params.get("cam") : (localStorage.getItem("hss.pb.cam") || cams[0].id);
  if (!cams.some(x => x.id === cam)) cam = cams[0].id;
  let at = params.get("t") ? new Date(params.get("t")) : new Date(Date.now() - 10 * 60000);
  let day = localDay(at), tl = null, session = null, player = null, keep = null, playStart = null, playingSince = null, zoomH = 24;
  const video = h("video", { muted: true, autoplay: true, playsinline: true, class: "pb-video" }); video.muted = true;
  const state2 = h("div", { class: "pb-state" }, "Pick a time on the timeline, or press Play");
  const clock = h("div", { class: "pb-clock mono" }, "—");
  const timelineBox = h("div", { class: "pb-timeline" });
  const events = h("div", { class: "list pb-events" });
  const note = h("div", { class: "faint", style: "font-size:12.5px" });
  const pos = () => playStart ? new Date(playStart.getTime() + (playingSince ? Date.now() - playingSince : 0)) : at;
  const stop = async () => {
    clearInterval(keep); keep = null;
    if (player) { player.close(); player = null; }
    if (session) { const s = session; session = null; api(`/playback/sessions/${s}`, { method: "DELETE" }).catch(() => {}); }
    playStart = null; playingSince = null;
  };
  state.cleanup.push(stop);
  const play = async t => {
    await stop();
    at = t; playStart = t;
    state2.textContent = `Asking the NVR for ${hms(t)}…`;
    try {
      const r = await api("/playback/sessions", { method: "POST", body: { camera_id: cam, start: t.toISOString() } });
      session = r.session;
      keep = setInterval(() => session && api(`/playback/sessions/${session}/keepalive`, { method: "POST", body: {} }).catch(() => {}), 30000);
      player = new LivePlayer(video, r.path, (st, info) => {
        if (st === "playing" && !playingSince) playingSince = Date.now();
        state2.textContent = st === "playing" ? "" : st === "error" ? `No video: ${info}. The camera may not have recorded then, or the browser can't play its codec (H.265).` : st;
      });
      if (localDay(t) !== day) { day = localDay(t); loadDay(); }
    } catch (ex) { state2.textContent = ex.message; }
    drawTimeline();
  };
  const jump = s => play(new Date(pos().getTime() + s * 1000));
  // 24-hour (or zoomed) timeline: recorded spans, events, playhead.
  const drawTimeline = () => {
    const W = 1000, H = 64, dayStart = new Date(`${day}T00:00:00`).getTime();
    const centre = (localDay(pos()) === day ? pos().getTime() : dayStart + 12 * 3600e3);
    let t0 = zoomH === 24 ? dayStart : Math.max(dayStart, Math.min(dayStart + (24 - zoomH) * 3600e3, centre - zoomH * 1800e3)), t1 = t0 + zoomH * 3600e3;
    const X = t => (t - t0) / (t1 - t0) * W;
    const ns = "http://www.w3.org/2000/svg", el = (n, a) => { const e = document.createElementNS(ns, n); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "pb-svg", preserveAspectRatio: "none" });
    svg.append(el("rect", { x: 0, y: 14, width: W, height: 26, class: "pb-bg" }));
    for (const r of (tl && tl.recorded) || []) {
      const a = Math.max(t0, new Date(r.start).getTime()), b = Math.min(t1, new Date(r.end).getTime());
      if (b > a) svg.append(el("rect", { x: X(a), y: 14, width: Math.max(1, X(b) - X(a)), height: 26, class: "pb-rec" }));
    }
    for (const e of (tl && tl.events) || []) {
      const t = new Date(e.at).getTime();
      if (t >= t0 && t <= t1) svg.append(el("rect", { x: X(t) - 1, y: 8, width: 2.5, height: 38, class: `pb-ev ${e.severity}` }));
    }
    const step = zoomH === 24 ? 3 : zoomH === 6 ? 1 : 0.25;
    for (let hh = 0; hh <= 24; hh += step) {
      const t = dayStart + hh * 3600e3; if (t < t0 || t > t1) continue;
      svg.append(el("line", { x1: X(t), x2: X(t), y1: 40, y2: 46, class: "pb-tick" }));
    }
    if (localDay(pos()) === day) svg.append(el("rect", { x: X(pos().getTime()) - 1.5, y: 2, width: 3, height: 50, class: "pb-head" }));
    svg.addEventListener("click", ev => { const r = svg.getBoundingClientRect(); play(new Date(t0 + (ev.clientX - r.left) / r.width * (t1 - t0))); });
    const labels = h("div", { class: "pb-labels" });
    for (let hh = 0; hh <= 24; hh += step) {
      const t = dayStart + hh * 3600e3; if (t < t0 || t > t1) continue;
      const d = new Date(t); labels.append(h("span", { style: `left:${X(t) / W * 100}%` }, `${pad(d.getHours())}:${pad(d.getMinutes())}`));
    }
    timelineBox.replaceChildren(svg, labels);
  };
  const loadDay = async () => {
    note.textContent = "Reading the NVR's recordings…";
    try { tl = await api(`/playback/timeline?camera_id=${encodeURIComponent(cam)}&day=${day}`); }
    catch (ex) { tl = null; note.textContent = ex.message; drawTimeline(); return; }
    const hours = tl.recorded.reduce((s, r) => s + (new Date(r.end) - new Date(r.start)), 0) / 3600e3;
    note.textContent = tl.note || `${hours.toFixed(1)} h recorded on ${day}; ${tl.events.length} event${tl.events.length === 1 ? "" : "s"}. Click the timeline to play from there.`;
    events.replaceChildren(...(tl.events.length ? tl.events.slice().reverse().slice(0, 200).map(e => h("button", { class: "linkrow", onclick: () => play(new Date(new Date(e.at) - 10000)) },
      h("span", { class: `sev ${e.severity}` }), h("span", { class: "mono" }, hms(new Date(e.at))), ` ${label(e.type)}`, e.zone ? h("span", { class: "faint" }, ` · ${e.zone}`) : null,
      e.alert_id ? h("span", { class: `badge ${e.alert_status === "closed" ? "" : "warn"}`, style: "margin-left:auto;flex:none", title: `Alert ${e.alert_status}` }, "alert") : null)) : [h("div", { class: "faint", style: "padding:6px" }, "No events this day.")]));
    drawTimeline();
  };
  const camSel = h("select", { class: "input", id: "pb-cam", onchange: e => { cam = e.target.value; try { localStorage.setItem("hss.pb.cam", cam); } catch (_) {} stop(); loadDay(); } },
    cams.map(x => h("option", { value: x.id, selected: x.id === cam }, `${x.name} · ${x.nvr}`)));
  const dayIn = h("input", { class: "input", type: "date", id: "pb-day", value: day, max: localDay(new Date()), onchange: e => { day = e.target.value; loadDay(); } });
  const timeIn = h("input", { class: "input", type: "time", id: "pb-time", step: 1, value: hms(at) });
  const zoomSeg = h("div", { class: "seg", role: "group", "aria-label": "Timeline span" }, [24, 6, 1].map(z => h("button", { class: z === zoomH ? "on" : null, onclick: e => { zoomH = z; zoomSeg.querySelectorAll("button").forEach(b => b.classList.toggle("on", b === e.target)); drawTimeline(); } }, `${z} h`)));
  const btn = (t, s, title) => h("button", { class: "btn small", title, onclick: () => jump(s) }, t);
  c.append(h("div", { class: "pb" },
    h("section", { class: "card pb-side" },
      h("div", { class: "field" }, h("label", { for: "pb-cam" }, "Camera"), camSel),
      h("div", { class: "field-row" }, h("div", { class: "field" }, h("label", { for: "pb-day" }, "Day"), dayIn), h("div", { class: "field" }, h("label", { for: "pb-time" }, "Time"), timeIn)),
      h("button", { class: "btn primary", onclick: () => play(new Date(`${day}T${timeIn.value || "00:00:00"}`)) }, "Play from this time"),
      h("h3", { style: "margin:14px 0 6px;font-size:13.5px" }, "Events this day"), events),
    h("div", { class: "grid", style: "gap:12px;min-width:0" },
      h("section", { class: "card pb-main" }, h("div", { class: "pb-stage" }, video, state2),
        h("div", { class: "toolbar pb-controls" }, btn("−10 min", -600, "Back 10 minutes"), btn("−1 min", -60, "Back 1 minute"), btn("−10 s", -10, "Back 10 seconds"),
          h("button", { class: "btn small danger", onclick: () => { stop(); state2.textContent = "Stopped"; drawTimeline(); } }, "Stop"),
          btn("+10 s", 10, "Forward 10 seconds"), btn("+1 min", 60, "Forward 1 minute"), btn("+10 min", 600, "Forward 10 minutes"), h("div", { style: "flex:1" }), clock)),
      h("section", { class: "card" }, h("div", { class: "toolbar", style: "margin-bottom:6px" }, h("strong", {}, "Timeline"), h("div", { style: "flex:1" }), zoomSeg), timelineBox, note))));
  const tick = setInterval(() => { if (!document.body.contains(clock)) return clearInterval(tick); clock.textContent = playStart ? `${day === localDay(pos()) ? "" : localDay(pos()) + " "}${hms(pos())}` : "—"; if (playingSince) drawTimeline(); }, 1000);
  await loadDay();
  if (params.get("t")) play(at);
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
  let selected = null;
  const ptzBox = h("div", { class: "ptz-box" });
  const outBox = h("div", { class: "out-box" });
  const drawOutputs = async () => {
    let outs = [];
    try { outs = (await api("/outputs")).filter(o => o.enabled); } catch (_) { /* older API */ }
    outBox.replaceChildren(...(outs.length ? [h("div", { class: "ptz-title" }, "Sirens and lights"), ...outs.map(o => h("div", { class: "out-row" },
      h("span", { class: `dot ${o.on ? "bad" : ""}` }), h("span", { class: "grow" }, o.name),
      h("button", { class: `btn small ${o.on ? "" : "danger"}`, onclick: async () => {
        try { await api(`/outputs/${o.id}/switch`, { method: "POST", body: { on: !o.on } }); drawOutputs(); } catch (ex) { toast(ex.message); }
      } }, o.on ? "Off" : "On")))] : []));
  };
  drawOutputs();
  const outTimer = setInterval(() => document.body.contains(outBox) ? drawOutputs() : clearInterval(outTimer), 10000);
  state.cleanup.push(() => clearInterval(outTimer));
  const showPtz = async path => {
    ptzBox.replaceChildren(h("div", { class: "faint", style: "font-size:12.5px;padding:6px 8px" }, `${labelOf[path] || path}: checking PTZ…`));
    ptzBox.replaceChildren(await ptzPanel(path, labelOf[path] || path));
  };
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
      const tile = h("div", { class: `tile ${selected === path ? "selected" : ""}`, ondblclick: () => tile.requestFullscreen && tile.requestFullscreen(),
        onclick: () => { selected = path; tiles.querySelectorAll(".tile").forEach(t => t.classList.toggle("selected", t === tile)); showPtz(path); },
        title: "Click to select (PTZ controls on the left); double-click for full screen" },
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
      h("section", { class: "card", style: "padding:8px" }, h("input", { class: "input", type: "search", placeholder: "Find a camera", oninput: e => drawCams(e.target.value.toLowerCase()) }), camList, ptzBox, outBox),
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
        h("thead", {}, h("tr", {}, ["Ch", "Camera", "IP", "Status", "Model", "Class", "AI tier", "Stream", "Video kept", "Clock"].map(t => h("th", {}, t)))),
        h("tbody", {}, chans.map(ch => h("tr", {},
          h("td", { class: "muted" }, ch.channel), h("td", {}, h("div", { style: "font-weight:600" }, ch.name), h("div", { class: "faint mono" }, ch.camera_id)), h("td", { class: "mono" }, ch.ip),
          h("td", {}, ch.online ? h("span", { class: "badge ok" }, "online") : ch.online === false ? h("span", { class: "badge bad" }, "offline") : h("span", { class: "badge" }, "unknown")),
          h("td", {}, ch.model || h("span", { class: "faint" }, "—"), ch.firmware ? h("div", { class: "faint mono" }, ch.firmware) : null),
          h("td", {}, ch.class || "—"),
          h("td", {}, canTier ? h("button", { class: "linkish", title: "Change the AI tier", onclick: () => tierForm(ch) }, tierBadge(ch)) : tierBadge(ch)),
          h("td", { class: "muted", style: "font-size:12.5px" }, ch.stream || "—"),
          h("td", {}, ch.recorded_days === null || ch.recorded_days === undefined ? "—" : h("span", { class: `badge ${ch.recorded_days < 30 ? "warn" : "ok"}`, title: "Days of recording on the NVR" }, `${Math.floor(ch.recorded_days)} d`)),
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
  if (["admin", "cso", "operator"].includes(role)) c.append(await outputsCard(dev, isAdmin, canTier));
  if (want) setTimeout(() => { const el = document.getElementById(`nvr-${want}`); if (el) el.scrollIntoView({ behavior: "smooth" }); }, 50);
}

/* ---------------- sirens, lights and relays ---------------- */
async function outputsCard(dev, isAdmin, canTest) {
  const list = await api("/outputs");
  const regs = dev.nvrs.filter(n => n.registered);
  const body = h("div", {});
  const until = o => o.on ? (o.on_until ? `on, off at ${new Date(o.on_until * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : "on until switched off") : "off";
  const draw = items => body.replaceChildren(items.length ? h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Output", "Switched by", "Turns off after", "State", ""].map(t => h("th", {}, t)))),
    h("tbody", {}, items.map(o => h("tr", {},
      h("td", {}, h("div", { style: "font-weight:600" }, o.name, o.enabled ? null : h("span", { class: "badge", style: "margin-left:6px" }, "paused"))),
      h("td", { class: "muted" }, o.kind === "nvr_relay" ? `${o.nvr_alias} alarm output ${o.port}` : "network address"),
      h("td", {}, o.duration_s ? `${o.duration_s} s` : "stays on"),
      h("td", {}, h("span", { class: `badge ${o.on ? "bad" : ""}` }, until(o)), o.on && o.on_by ? h("div", { class: "faint", style: "font-size:12px" }, o.on_by) : null),
      h("td", { style: "text-align:right;white-space:nowrap" },
        h("button", { class: `btn small ${o.on ? "" : "danger"}`, onclick: async () => {
          try { await api(`/outputs/${o.id}/switch`, { method: "POST", body: { on: !o.on } }); toast(`${o.name} ${o.on ? "off" : "on"}`); draw(await api("/outputs")); } catch (ex) { toast(ex.message); }
        } }, o.on ? "Switch off" : "Switch on"), " ",
        canTest ? h("button", { class: "btn small", title: "On for 3 seconds", onclick: async () => {
          try { await api(`/outputs/${o.id}/test`, { method: "POST", body: {} }); toast(`${o.name}: on for 3 seconds`); } catch (ex) { toast(ex.message); }
        } }, "Test") : null, " ",
        isAdmin ? h("button", { class: "btn small", onclick: () => outputForm(o, regs) }, "Edit") : null)))))) :
    h("div", { class: "empty" }, isAdmin ? "No outputs yet. Add a siren, strobe or floodlight wired to an NVR alarm output, or a network relay." : "No outputs have been added."));
  draw(list);
  return card("Sirens, lights and relays", isAdmin ? h("button", { class: "btn small primary", onclick: () => outputForm(null, regs) }, "Add output") : null,
    h("p", { class: "muted", style: "margin-top:0" }, "Alert rules switch these on (Settings › Alert rules › Switch on). Acknowledging the alert silences them."), body);
}

function outputForm(o, regs) {
  const editing = !!o;
  o = o || { name: "", kind: "nvr_relay", nvr_alias: regs[0] ? regs[0].alias : "", port: 1, url_on: "", url_off: "", method: "GET", username: "", duration_s: 60, enabled: true };
  const inp = (id, v, a = {}) => h("input", { class: "input", id, value: v ?? "", autocomplete: "off", ...a });
  const f = { name: inp("o-name", o.name, { placeholder: "e.g. Gate siren, Fence floodlight" }),
    kind: h("select", { class: "input", id: "o-kind" }, h("option", { value: "nvr_relay", selected: o.kind === "nvr_relay" }, "NVR alarm output (wired relay)"), h("option", { value: "http", selected: o.kind === "http" }, "Network device (web address)")),
    nvr: h("select", { class: "input", id: "o-nvr" }, regs.map(n => h("option", { value: n.alias, selected: n.alias === o.nvr_alias }, `${n.name} (${n.alias})`))),
    port: inp("o-port", o.port, { type: "number", min: 1, max: 64 }),
    on: inp("o-on", o.url_on, { placeholder: "http://10.1.9.5/relay/0?turn=on" }), off: inp("o-off", o.url_off, { placeholder: "optional: http://10.1.9.5/relay/0?turn=off" }),
    method: h("select", { class: "input", id: "o-method" }, ["GET", "POST", "PUT"].map(m => h("option", { selected: m === o.method }, m))),
    user: inp("o-user", o.username), pass: inp("o-pass", "", { type: "password", autocomplete: "new-password", placeholder: editing && o.has_password ? "Leave empty to keep" : "" }),
    dur: inp("o-dur", o.duration_s, { type: "number", min: 0, max: 3600 }), enabled: h("input", { type: "checkbox", id: "o-en", checked: o.enabled }) };
  const field = (l, el, hint) => h("div", { class: "field" }, h("label", { for: el.id }, l), el, hint ? h("div", { class: "faint", style: "font-size:12px" }, hint) : null);
  const portsHint = h("div", { class: "faint", style: "font-size:12px" });
  const relayBox = h("div", {}, h("div", { class: "field-row" }, field("NVR", f.nvr), field("Alarm output number", f.port)), portsHint,
    h("button", { class: "btn small", style: "margin-bottom:12px", onclick: async () => {
      portsHint.textContent = "Reading the NVR…";
      try { const r = await api(`/outputs/nvr/${f.nvr.value}/ports`, { method: "POST", body: {} }); portsHint.textContent = r.ports.length ? `This NVR has alarm outputs ${r.ports.join(", ")}.` : "This NVR reports no alarm outputs."; }
      catch (ex) { portsHint.textContent = ex.message; }
    } }, "Read the NVR's outputs"));
  const httpBox = h("div", {}, field("Address to switch on", f.on), field("Address to switch off", f.off, "Leave empty if the device switches itself off"),
    h("div", { class: "field-row" }, field("Method", f.method), field("User (if needed)", f.user)), field("Password", f.pass));
  const sync = () => { relayBox.hidden = f.kind.value !== "nvr_relay"; httpBox.hidden = f.kind.value !== "http"; };
  f.kind.addEventListener("change", sync); sync();
  const err = h("div", { class: "error", hidden: true });
  modal(editing ? `Edit ${o.name}` : "Add an output", h("div", {}, err, field("Name", f.name, "Rules use this name"), field("Type", f.kind), relayBox, httpBox,
    field("Turns off after (seconds)", f.dur, "0 = stays on until someone switches it off or acknowledges the alert"),
    h("label", { class: "check" }, f.enabled, "In use (untick to pause it)")),
    close => [
      editing ? h("button", { class: "btn danger", style: "margin-right:auto", onclick: async () => { if (!confirm(`Delete ${o.name}?`)) return; await api(`/outputs/${o.id}`, { method: "DELETE" }); close.remove(); render(); } }, "Delete") : null,
      h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
      h("button", { class: "btn primary", onclick: async () => {
        const b = { name: f.name.value.trim(), kind: f.kind.value, nvr_alias: f.kind.value === "nvr_relay" ? f.nvr.value : null, port: f.kind.value === "nvr_relay" ? Number(f.port.value) : null,
          url_on: f.kind.value === "http" ? f.on.value.trim() : null, url_off: f.kind.value === "http" ? f.off.value.trim() || null : null, method: f.method.value,
          username: f.user.value.trim(), password: f.pass.value, duration_s: Number(f.dur.value) || 0, enabled: f.enabled.checked };
        try { await api(editing ? `/outputs/${o.id}` : "/outputs", { method: editing ? "PUT" : "POST", body: b }); close.remove(); toast("Saved"); render(); }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      } }, "Save")]);
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
      while (i < lines.length) {
        const ln = lines[i];
        if (ln.match(ordered ? /^\d+\.\s+/ : /^-\s+/)) items.push({ text: ln.replace(/^(\d+\.|-)\s+/, "").replace(/^\[ \]\s*/, "☐ ").replace(/^\[x\]\s*/i, "☑ "), sub: [] });
        else if (items.length && ln.match(/^\s{2,}(-|\d+\.)\s+/)) items[items.length - 1].sub.push(ln.replace(/^\s+(-|\d+\.)\s+/, ""));
        else break;
        i++;
      }
      i--;
      out.push(h(ordered ? "ol" : "ul", {}, items.map(t => h("li", {}, inlineMd(t.text), t.sub.length ? h("ul", {}, t.sub.map(x => h("li", {}, inlineMd(x)))) : null))));
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
  if (unlocked && ["admin", "cso"].includes(state.user.role)) c.append(await recognitionPanel(st));

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
          h("td", {}, h("div", { style: "font-weight:600" }, sc.name), h("div", { class: "faint" }, sc.kind === "control" ? "Control-room status board" : sourceText(sc, nvrNames))),
          h("td", {}, sc.kind === "control" ? "—" : sc.camera_count),
          h("td", {}, sc.kind === "control" ? "board" : `${sc.tiles} tiles`),
          h("td", {}, sc.kind === "control" ? h("span", { class: "faint" }, "refreshes every 10 s") : sc.pages > 1 ? `${sc.pages} pages, ${sc.dwell_s} s each` : h("span", { class: "faint" }, "fits on one page"), sc.pin_alerts ? h("div", { class: "faint" }, "alerts pinned") : null),
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
  sc = sc || { name: "", source: "cameras", cameras: [], tiles: 16, dwell_s: 20, labels: true, pin_alerts: true, kind: "cameras", plan_id: null };
  const name = h("input", { class: "input", id: "sc-name", value: sc.name, placeholder: "e.g. Perimeter, Gate area, NVR4" });
  const kind = h("select", { class: "input", id: "sc-kind" },
    h("option", { value: "cameras", selected: sc.kind !== "control" }, "Camera grid"),
    h("option", { value: "control", selected: sc.kind === "control" }, "Control-room status board (alerts, map, devices, guards)"));
  const plan = h("select", { class: "input", id: "sc-plan" }, h("option", { value: "" }, "No map"));
  api("/geo/plans").then(ps => plan.append(...ps.map(p => h("option", { value: p.id, selected: p.id === sc.plan_id }, p.name)))).catch(() => {});
  const planBox = h("div", { class: "field" }, h("label", { for: "sc-plan" }, "Site map on the board"), plan);
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
  const gridParts = [];
  const syncSource = () => {
    const board = kind.value === "control";
    pickBox.hidden = board || source.value !== "cameras";
    planBox.hidden = !board;
    gridParts.forEach(x => { x.hidden = board; });
  };
  source.addEventListener("change", syncSource);
  kind.addEventListener("change", syncSource);
  const err = h("div", { class: "error", hidden: true });
  modal(editing ? `Edit ${sc.name}` : "New screen", h("div", {}, err,
    h("div", { class: "field" }, h("label", { for: "sc-name" }, "Name"), name),
    h("div", { class: "field" }, h("label", { for: "sc-kind" }, "Type"), kind),
    planBox,
    ...(gridParts.push(
      h("div", { class: "field" }, h("label", { for: "sc-src" }, "Shows"), source),
      h("div", { class: "field-row" }, h("div", { class: "field" }, h("label", { for: "sc-tiles" }, "Grid"), tiles),
        h("div", { class: "field" }, h("label", { for: "sc-dwell" }, "Seconds per page"), dwell, h("div", { class: "faint", style: "font-size:12px" }, "When there are more cameras than tiles"))),
      h("div", { class: "field", style: "gap:8px" }, h("label", { class: "check" }, labels, "Show camera names"),
        h("label", { class: "check" }, pin, "Keep cameras with open alerts on screen, outlined"))), gridParts),
    pickBox),
    close => {
      const btns = [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
        h("button", { class: "btn primary", onclick: async () => {
          const body = { name: name.value.trim(), source: source.value, cameras: source.value === "cameras" ? paths.map(p => p.path).filter(p => picked.has(p)).concat([...picked].filter(p => !paths.some(x => x.path === p))) : [],
            tiles: Number(tiles.value), dwell_s: Number(dwell.value) || 20, labels: labels.checked, pin_alerts: pin.checked,
            kind: kind.value, plan_id: kind.value === "control" && plan.value ? Number(plan.value) : null };
          if (body.kind === "control") { body.source = "all"; body.cameras = []; }
          if (body.kind !== "control" && body.source === "cameras" && !body.cameras.length) { err.textContent = "Pick at least one camera."; err.hidden = false; return; }
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
    const ptzSlot = h("div", {});
    ptzPanel(cam.camera_id, cam.name).then(el => ptzSlot.replaceChildren(el));
    const video = h("video", { muted: true, autoplay: true, playsinline: true, class: "map-video" });
    video.muted = true;
    const st = h("div", { class: "faint", style: "font-size:12px" }, "connecting");
    const player = new LivePlayer(video, cam.camera_id, (s, info) => { st.textContent = s === "playing" ? `live ${info || ""}` : s === "error" ? info : s; });
    state.cleanup.push(() => player.close());
    side.replaceChildren(h("button", { class: "btn small", onclick: () => { player.close(); drawSide(); } }, "‹ Back"), h("h3", {}, cam.name),
      h("div", { class: "faint mono" }, cam.camera_id), video, st, ptzSlot,
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
const KIND_NAMES = { daily: "Daily", weekly: "Weekly", monthly: "Monthly", custom: "Custom period", compliance: "Compliance and privacy" };
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
          h("td", {}, f.label || ""),
          r.kind === "compliance" ? h("td", { colspan: 3 }, f.actions ? h("span", { class: "badge bad" }, `${f.actions} action${f.actions > 1 ? "s" : ""}`) : null, " ",
            f.attention ? h("span", { class: "badge warn" }, `${f.attention} attention`) : null, !f.actions && !f.attention ? h("span", { class: "badge ok" }, "all in order") : null) : null,
          r.kind === "compliance" ? null : h("td", {}, f.events ?? "—"),
          r.kind === "compliance" ? null : h("td", {}, f.critical ? h("span", { class: "badge bad" }, f.critical) : "0"),
          r.kind === "compliance" ? null : h("td", {}, ch === null || ch === undefined ? h("span", { class: "faint" }, "—") : h("span", { class: `badge ${ch > 0 ? "warn" : ch < 0 ? "ok" : ""}` }, `${ch > 0 ? "+" : ""}${ch}%`)),
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
    hint.textContent = { daily: "One day, midnight to midnight.", weekly: "Monday to Sunday.", monthly: "The whole calendar month, compared with the month before.", custom: "Up to 93 days.",
      compliance: "The calendar month: legal review and DPIA dates, retention, who watched video, evidence, accounts and exports. Sent on the 1st to “compliance” subscribers." }[k];
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
      h("div", { class: "seg", role: "group", "aria-label": "Type" }, [["", "All"], ["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["custom", "Custom"], ["compliance", "Compliance"]].map(([k, l]) =>
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
      r.kind === "compliance" ? h("div", { class: "list" }, (f.checks || []).map(x => h("div", { class: "item" },
        h("span", { class: `badge ${x.status === "Action" ? "bad" : x.status === "Attention" ? "warn" : "ok"}`, style: "min-width:78px;text-align:center" }, x.status),
        h("div", { class: "grow" }, h("div", { class: "title" }, x.area), h("div", { class: "muted", style: "font-size:12.5px" }, x.text))))) :
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
const alertsAllowed = () => state.user && ["admin", "cso", "operator", "viewer"].includes(state.user.role);
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
    if (msg.kind === "lockdown") { drawLockdown(msg.lockdown); if (msg.lockdown) playAlertSound("critical"); return; }
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
  const canAct = ["admin", "cso", "operator"].includes(state.user.role);         // viewers read only
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
    const recSlot = canAct && ["face_match", "plate_match"].includes(a.type) ? h("div", {}) : null;
    if (recSlot) recognitionMatch(a, async () => draw(await api(`/alerts/${id}`))).then(el => recSlot.replaceChildren(el)).catch(ex => recSlot.replaceChildren(h("div", { class: "faint" }, ex.message)));
    drawer.replaceChildren(
      h("div", { class: "toolbar" }, h("span", { class: `badge ${SEV_BADGE[a.severity]}` }, a.severity), h("span", { class: `badge ${STATUS_BADGE[a.status]}` }, a.status),
        h("h2", {}, label(a.type)), h("div", { style: "flex:1" }), h("button", { class: "btn small", onclick: () => scrim.remove() }, "Close")),
      recSlot ? recSlot : a.snapshot_url ? h("img", { class: "snapshot", src: a.snapshot_url, alt: `Snapshot from ${a.camera_id}` }) : h("div", { class: "empty card" }, "No snapshot."),
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
        canAct && a.status === "open" ? h("button", { class: "btn primary", onclick: () => act({ action: "acknowledge", text: comment.value }, "Acknowledged") }, "Acknowledge") : null,
        canAct && a.status === "closed" ? h("button", { class: "btn", onclick: () => act({ action: "reopen", text: comment.value }, "Reopened") }, "Reopen") : null,
        h("a", { class: "btn", href: "#/live", onclick: () => scrim.remove() }, "Live view"),
        h("a", { class: "btn", href: `#/playback?cam=${encodeURIComponent(a.camera_id)}&t=${encodeURIComponent(new Date(new Date(a.occurred_at) - 10000).toISOString())}`, onclick: () => scrim.remove() }, "Play recording"),
        canManage ? h("a", { class: "btn", href: `#/viewing?cam=${encodeURIComponent(a.camera_id)}&since=${encodeURIComponent(new Date(new Date(a.occurred_at) - 3600000).toISOString())}`, onclick: () => scrim.remove(), title: "Who watched this camera, live or recorded, from an hour before the alert" }, "Who watched") : null,
        canManage ? h("button", { class: "btn", onclick: () => sealForm(id, async () => draw(await api(`/alerts/${id}`))) }, "Seal evidence") : null,
        canManage ? h("a", { class: "btn", href: `/api/alerts/${id}/evidence`, download: "", title: "A copy that is not kept in the vault" }, "Export copy") : null),
      canAct ? h("div", { class: "field" }, h("label", {}, "Note"), comment) : null,
      canAct ? h("div", { class: "toolbar" },
        h("button", { class: "btn", onclick: () => comment.value.trim() ? act({ action: "comment", text: comment.value }, "Note added") : toast("Write a note first") }, "Add note"),
        h("span", { class: "muted" }, "Assign"), who,
        h("button", { class: "btn", onclick: () => act({ action: "assign", assignee: canManage ? who.value : state.user.username, text: comment.value }, "Assigned") }, canManage ? "Assign" : "Take it")) : null,
      canAct && a.status !== "closed" ? h("div", { class: "toolbar" }, h("span", { class: "muted" }, "Close as"), reason,
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
/* Camera access for one user: every camera, or a chosen list (whole NVRs or single cameras, plus patterns). */
function cameraAccess(paths, cur = [], canPlay = true) {
  const cams = [...new Map(paths.map(p => [p.path.replace(/-sub$/, ""), p])).entries()].map(([id, p]) => ({ id, label: p.label, nvr: p.nvr }));
  const byNvr = {};
  cams.forEach(x => (byNvr[x.nvr] ||= []).push(x));
  const chosen = new Set(cur);
  const mode = h("select", { class: "input", id: "ca-mode" }, h("option", { value: "all", selected: !cur.length }, "Every camera"),
    h("option", { value: "some", selected: cur.length > 0 }, "Only the cameras below"));
  const extra = h("input", { class: "input", id: "ca-extra", placeholder: "Other patterns, comma-separated (e.g. nvr9-*)",
    value: cur.filter(p => !cams.some(x => x.id === p) && !Object.keys(byNvr).some(n => p === `${n}-*`)).join(", ") });
  const play = h("input", { type: "checkbox", id: "ca-play", checked: canPlay });
  const box = h("div", { class: "pick-list", style: "max-height:260px" }, Object.entries(byNvr).map(([nvr, list]) => {
    const all = h("input", { type: "checkbox", checked: chosen.has(`${nvr}-*`) });
    const items = list.map(x => h("label", { class: "check", style: "display:flex;margin-left:18px" },
      h("input", { type: "checkbox", value: x.id, checked: chosen.has(x.id) || chosen.has(`${nvr}-*`), disabled: chosen.has(`${nvr}-*`) }),
      ` ${x.label}${x.label !== x.id ? ` ` : ""}`, x.label !== x.id ? h("span", { class: "faint mono" }, x.id) : null));
    all.addEventListener("change", () => items.forEach(l => { const i = l.querySelector("input"); i.checked = all.checked || i.checked; i.disabled = all.checked; }));
    return h("div", { style: "margin-bottom:6px" }, h("label", { class: "check", style: "display:flex;font-weight:650" }, all, ` All of ${nvr} (${list.length})`, h("span", { class: "faint mono", style: "margin-left:6px" }, `${nvr}-*`)), items);
  }));
  const sync = () => { box.hidden = extra.hidden = mode.value === "all"; };
  mode.addEventListener("change", sync); sync();
  const el = h("div", {},
    h("div", { class: "field" }, h("label", { for: "ca-mode" }, "Cameras"), mode, h("div", { class: "faint", style: "font-size:12px" }, "Administrators and the CSO always see every camera.")),
    box, h("div", { class: "field", style: "margin-top:8px" }, h("label", { for: "ca-extra" }, "Patterns (* matches anything; for example nvr4-* or nvr1-ch0?)"), extra),
    h("label", { class: "check" }, play, " Can watch recordings (Playback)"));
  const value = () => {
    if (mode.value === "all") return { cameras: [], can_playback: play.checked };
    const out = [];
    box.querySelectorAll(":scope > div").forEach(group => {
      const all = group.querySelector("label input");
      const nvrPat = group.querySelector("label .mono").textContent;
      if (all.checked) out.push(nvrPat);
      else group.querySelectorAll("label[style*='margin-left'] input:checked").forEach(i => out.push(i.value));
    });
    extra.value.split(",").map(x => x.trim()).filter(Boolean).forEach(x => out.includes(x) || out.push(x));
    return { cameras: out, can_playback: play.checked };
  };
  return { el, value };
}
const accessText = u => ["admin", "cso"].includes(u.role) ? h("span", { class: "faint" }, "all (always)")
  : (u.cameras || []).length ? h("span", { title: u.cameras.join(", ") }, `${u.cameras.length} ${u.cameras.length === 1 ? "entry" : "entries"}: ${u.cameras.slice(0, 2).join(", ")}${u.cameras.length > 2 ? "…" : ""}`)
  : h("span", { class: "faint" }, "all");

async function viewUsers(c) {
  const users = await api("/users");
  const paths = await api("/live/paths").catch(() => []);
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
        const acc = cameraAccess(paths);
        const accBox = h("div", {}, acc.el);
        const syncRole = () => { accBox.hidden = ["admin", "cso", "management", "guard"].includes(role.value); };
        role.addEventListener("change", syncRole); syncRole();
        modal("Add a user", h("div", {}, err, h("div", { class: "field" }, h("label", {}, "Username"), un), h("div", { class: "field" }, h("label", {}, "Full name"), dn),
          h("div", { class: "field" }, h("label", {}, "Role"), role), accBox),
          close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
            h("button", { class: "btn primary", onclick: async () => {
              try {
                const a = accBox.hidden ? { cameras: [], can_playback: true } : acc.value();
                const res = await api("/users", { method: "POST", body: { username: un.value.trim(), display_name: dn.value.trim(), role: role.value, ...a } });
                close.remove(); showTemp("User added", res.user.display_name || res.user.username, res.temporary_password);
              } catch (ex) { err.textContent = ex.message; err.hidden = false; }
            } }, "Add user")]);
      } }, "Add user")),
    h("section", { class: "card", style: "padding:6px 8px" }, h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["User", "Role", "Cameras", "Two-factor", "Status", "Last sign-in", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, users.map(u => {
        const me = u.id === state.user.id;
        const roleSel = h("select", { class: "input", style: "width:auto;padding:6px 8px", disabled: me, onchange: async e => {
          try { await api(`/users/${u.id}`, { method: "PATCH", body: { role: e.target.value } }); toast("Role changed"); } catch (ex) { toast(ex.message); render(); }
        } }, Object.entries(ROLE_NAMES).map(([k, v]) => h("option", { value: k, selected: k === u.role }, v)));
        return h("tr", {},
          h("td", {}, h("div", { style: "display:flex;gap:10px;align-items:center" }, h("div", { class: "avatar" }, initials(u)),
            h("div", {}, h("div", { style: "font-weight:600" }, u.display_name || u.username, me ? h("span", { class: "faint" }, " (you)") : null), h("div", { class: "faint mono" }, u.username)))),
          h("td", {}, roleSel),
          h("td", { style: "font-size:12.5px;max-width:220px" }, accessText(u), u.can_playback === false ? h("div", { class: "faint" }, "live only") : null,
            ["admin", "cso", "management", "guard"].includes(u.role) ? null : h("div", {}, h("button", { class: "btn small", style: "margin-top:4px", onclick: () => {
              const acc = cameraAccess(paths, u.cameras || [], u.can_playback !== false);
              const err = h("div", { class: "error", hidden: true });
              modal(`Cameras for ${u.display_name || u.username}`, h("div", {}, err, acc.el), close => [h("button", { class: "btn", onclick: () => close.remove() }, "Cancel"),
                h("button", { class: "btn primary", onclick: async () => {
                  try { await api(`/users/${u.id}`, { method: "PATCH", body: acc.value() }); close.remove(); toast("Camera access saved; it applies from their next action"); render(); }
                  catch (ex) { err.textContent = ex.message; err.hidden = false; }
                } }, "Save")]);
            } }, "Change"))),
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
    user_changed: "Changed a user (role, cameras or status)", alert_acknowledge: "Acknowledged an alert", alert_assign: "Assigned an alert", alert_comment: "Noted on an alert",
    alert_close: "Closed an alert", alert_reopen: "Reopened an alert", alert_rules_changed: "Changed alert rules", evidence_exported: "Exported evidence", "2fa_enabled": "Turned on two-factor", "2fa_disabled": "Turned off two-factor", branding_changed: "Changed branding", evidence_sealed: "Sealed evidence", evidence_downloaded: "Downloaded evidence", evidence_hold: "Changed a legal hold", evidence_verify_failed: "Evidence check FAILED", legal_accepted: "Accepted the face & plate legal review", legal_revoked: "Withdrew the face & plate legal review", screen_created: "Added a wall screen", screen_changed: "Changed a wall screen", screen_deleted: "Deleted a wall screen", screen_key_changed: "Changed a wall screen link", plan_added: "Added a site plan", plan_changed: "Changed a site plan", zone_added: "Added a zone", zone_changed: "Changed a zone", zone_deleted: "Deleted a zone", unit_added: "Added a guard or vehicle", unit_changed: "Changed a guard or vehicle", unit_deleted: "Removed a guard or vehicle", unit_simulated: "Simulated a position", licence_loaded: "Loaded a licence", retention_run: "Ran the retention clean-up", playback: "Played back a recording", viewing_log_exported: "Exported the viewing log", lockdown_started: "STARTED A LOCKDOWN", lockdown_ended: "Ended the lockdown", lockdown_config_changed: "Changed the lockdown outputs", compliance_settings_changed: "Changed the compliance dates", watchlist_person_added: "Added a person to a watchlist", watchlist_person_changed: "Changed a watchlist entry", watchlist_person_deleted: "Deleted a person from a watchlist", watchlist_photo_added: "Added a watchlist photo", watchlist_photo_deleted: "Deleted a watchlist photo", watchlist_photo_viewed: "Viewed a watchlist photo", watchlist_plate_added: "Added a plate to a watchlist", watchlist_plate_deleted: "Removed a plate from a watchlist", recognition_config_changed: "Changed recognition cameras or thresholds", recognition_verdict: "Gave a verdict on a match", handover_given: "Handed over a shift", handover_taken: "Took over a shift", shifts_changed: "Changed the shift times", output_added: "Added an output", output_changed: "Changed an output", output_deleted: "Deleted an output", output_switched: "Switched an output", output_tested: "Tested an output", ptz_control: "Steered a PTZ camera", ptz_preset: "Sent a PTZ camera to a preset", ptz_preset_saved: "Saved a PTZ preset", nvr_added: "Added an NVR", nvr_changed: "Changed an NVR", nvr_removed: "Removed an NVR", tier_changed: "Changed a camera tier", admin_created_cli: "Admin created on the server",
    report_generated: "Generated a report", report_downloaded: "Downloaded a report", report_sent: "Sent a report" };
  c.append(h("section", { class: "card", style: "padding:6px 8px" }, h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Time", "User", "Action", "Details", "From"].map(t => h("th", {}, t)))),
    h("tbody", {}, rows.map(r => h("tr", {}, h("td", { style: "white-space:nowrap" }, fmtTime(r.at)), h("td", { style: "font-weight:600" }, r.username || "—"),
      h("td", {}, r.action === "login_failed" ? h("span", { class: "badge warn" }, what[r.action]) : what[r.action] || r.action),
      h("td", { class: "muted", style: "font-size:12.5px" }, Object.entries(r.detail || {}).map(([k, v]) => `${k}: ${v}`).join(" · ")),
      h("td", { class: "mono" }, r.ip || "—"))))))));
}

/* ---------------- incident heat map: where and when alerts happen ---------------- */
async function viewHeatmap(c) {
  const saved = (() => { try { return JSON.parse(localStorage.getItem("hss.heat") || "{}"); } catch (_) { return {}; } })();
  const st = { days: 30, only: "all", severity: "", place: "", plan: null, ...saved, place: "" };
  let plans = [];
  try { plans = await api("/geo/plans"); } catch (_) { /* no map module */ }
  if (!plans.some(p => p.id === st.plan)) st.plan = plans[0] ? plans[0].id : null;
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const hh = n => `${String(n).padStart(2, "0")}:00`;
  const tip = h("div", { class: "hm-tip", hidden: true });
  document.body.append(tip); state.cleanup.push(() => tip.remove());
  const showTip = (ev, text) => { tip.textContent = text; tip.hidden = false; const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8); tip.style.left = `${x}px`; tip.style.top = `${ev.clientY + 14}px`; };
  const hideTip = () => { tip.hidden = true; };
  const seg = (key, opts) => h("div", { class: "seg" }, opts.map(([v, l]) => h("button", { class: String(st[key]) === String(v) ? "on" : null, onclick: () => { st[key] = v; if (key !== "place") st.place = ""; save(); load(); } }, l)));
  const save = () => { try { localStorage.setItem("hss.heat", JSON.stringify({ days: st.days, only: st.only, severity: st.severity, plan: st.plan })); } catch (_) { /* fine */ } };
  const bar = h("div", { class: "toolbar hm-filters" });
  const body = h("div", { class: "grid", style: "gap:14px" });
  c.append(bar, body);
  const shade = (n, max) => n ? `color-mix(in oklab, var(--seq-hi) ${Math.round(18 + 82 * n / max)}%, var(--seq-lo))` : null;

  function mapCard(d) {
    const p = d.plan;
    if (!p) return card("Site map", null, h("p", { class: "muted" }, plans.length ? "Pick a plan above." : "Add a site plan in Site map to see alerts by place."));
    const NS = "http://www.w3.org/2000/svg", k = Math.max(p.width, p.height) / 1000;
    const sv = (tag, attrs, ...kids) => { const n = document.createElementNS(NS, tag); for (const [a, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(a, v); kids.forEach(x => x && n.append(x)); return n; };
    const svg = sv("svg", { viewBox: `0 0 ${p.width} ${p.height}`, class: "hm-map", role: "img", "aria-label": `Alerts by place on ${p.name}` });
    svg.append(sv("image", { href: `/api/geo/plans/${p.id}/image`, x: 0, y: 0, width: p.width, height: p.height, opacity: .55 }));
    const zc = Object.fromEntries(d.zones.map(z => [z.key, z])), cc = Object.fromEntries(d.cameras.map(x => [x.key, x]));
    const zmax = Math.max(1, ...p.zones.map(z => (zc[z.name] || {}).alerts || 0));
    for (const z of p.zones) {
      const n = (zc[z.name] || {}).alerts || 0;
      const poly = sv("polygon", { class: `hm-zone ${st.place === `zone:${z.name}` ? "sel" : ""}`, points: z.points.map(q => q.join(",")).join(" "), "stroke-width": 2 * k,
        style: n ? `fill:${shade(n, zmax)};fill-opacity:.55` : null });
      poly.addEventListener("mousemove", ev => showTip(ev, `${z.name}: ${n} alert${n === 1 ? "" : "s"}`)); poly.addEventListener("mouseleave", hideTip);
      poly.addEventListener("click", () => { st.place = st.place === `zone:${z.name}` ? "" : `zone:${z.name}`; load(); });
      svg.append(poly);
    }
    const cmax = Math.max(1, ...p.cameras.map(x => (cc[x.camera_id] || {}).alerts || 0));
    const placed = p.cameras.map(x => ({ ...x, s: cc[x.camera_id] })).sort((a, b) => ((b.s || {}).alerts || 0) - ((a.s || {}).alerts || 0));
    const labelled = new Set(placed.filter(x => x.s).slice(0, 5).map(x => x.camera_id));
    for (const x of [...placed].reverse()) {
      const n = x.s ? x.s.alerts : 0;
      const r = (n ? 10 + 34 * Math.sqrt(n / cmax) : 5) * k;
      const g = sv("g", { class: `hm-cam ${st.place === `camera:${x.camera_id}` ? "sel" : ""}` },
        sv("circle", { cx: x.x, cy: x.y, r, "stroke-width": 2 * k, style: n ? `fill:${shade(n, cmax)}` : null, class: n ? null : "zero" }),
        labelled.has(x.camera_id) ? sv("text", { x: x.x, y: x.y + 5 * k, "font-size": 15 * k, "text-anchor": "middle" }, document.createTextNode(String(n))) : null);
      const name = x.s ? x.s.label : x.camera_id;
      g.addEventListener("mousemove", ev => showTip(ev, n ? `${name}: ${n} alert${n === 1 ? "" : "s"} · ${x.s.real} real · ${x.s.false} false · busiest ${hh(x.s.peak_hour)}` : `${name}: no alerts`));
      g.addEventListener("mouseleave", hideTip);
      g.addEventListener("click", () => { st.place = st.place === `camera:${x.camera_id}` ? "" : `camera:${x.camera_id}`; load(); });
      svg.append(g);
    }
    const unplaced = d.cameras.filter(x => !p.cameras.some(y => y.camera_id === x.key)).length;
    return card(`Where · ${p.name}`, null,
      h("p", { class: "muted", style: "margin:0 0 10px;font-size:12.5px" }, "Bubble size and colour = alerts at that camera; zones shaded the same way. Click one to see its hours."),
      h("div", { class: "hm-map-wrap" }, svg),
      unplaced ? h("p", { class: "faint", style: "margin:8px 0 0;font-size:12.5px" }, `${unplaced} camera${unplaced === 1 ? "" : "s"} with alerts ${unplaced === 1 ? "isn't" : "aren't"} placed on this plan; see the table below.`) : null);
  }

  function gridCard(d) {
    const max = Math.max(1, ...d.grid.flat());
    const placeName = st.place ? (st.place.startsWith("camera:") ? ((d.cameras.find(x => `camera:${x.key}` === st.place) || {}).label || st.place.slice(7)) : st.place.slice(5)) : "";
    const cells = [h("div", {}), ...Array.from({ length: 24 }, (_, i) => h("div", { class: "hm-hh" }, i % 3 === 0 ? String(i).padStart(2, "0") : ""))];
    d.grid.forEach((row, wd) => {
      cells.push(h("div", { class: "hm-day" }, DAYS[wd]));
      row.forEach((n, hr) => {
        const cell = h("div", { class: `hm-cell ${n ? "" : "zero"}`, style: n ? `background:${shade(n, max)}` : null, "aria-label": `${DAYS[wd]} ${hh(hr)}: ${n}` });
        cell.addEventListener("mousemove", ev => showTip(ev, `${DAYS[wd]} ${hh(hr)}–${hh((hr + 1) % 24)}: ${n} alert${n === 1 ? "" : "s"}`)); cell.addEventListener("mouseleave", hideTip);
        cells.push(cell);
      });
    });
    const byHour = Array.from({ length: 24 }, (_, i) => d.grid.reduce((a, r) => a + r[i], 0));
    const peak = byHour.indexOf(Math.max(...byHour));
    const night = byHour.slice(18).concat(byHour.slice(0, 6)).reduce((a, b) => a + b, 0), all = byHour.reduce((a, b) => a + b, 0);
    return card(placeName ? `When · ${placeName}` : "When · whole site", placeName ? h("button", { class: "btn small", onclick: () => { st.place = ""; load(); } }, "Whole site") : null,
      all ? h("p", { class: "hm-lead" }, `Busiest hour ${hh(peak)}–${hh((peak + 1) % 24)}; ${Math.round(100 * night / all)}% of alerts between 18:00 and 06:00.`) : h("p", { class: "muted" }, "No alerts in this period."),
      h("div", { class: "hm-grid", role: "img", "aria-label": "Alerts by day of week and hour" }, cells),
      h("div", { class: "hm-legend" }, h("span", { class: "faint" }, "fewer"), h("span", { class: "hm-ramp" }), h("span", { class: "faint" }, `more (max ${max} in an hour)`), h("span", { class: "faint", style: "margin-left:auto" }, `Times in ${d.timezone}`)),
      h("div", { class: "hm-sub" }, "All days, by hour"),
      h("div", { class: "hm-bars", role: "img", "aria-label": "Alerts by hour, all days" }, h("div", {}),
        byHour.map((n, i) => { const b = h("div", { class: "hm-bar-col" }, h("div", { class: `hm-bar ${i === peak && n ? "peak" : ""}`, style: `height:${n ? Math.max(3, 100 * n / Math.max(...byHour)) : 0}%` }));
          b.addEventListener("mousemove", ev => showTip(ev, `${hh(i)}–${hh((i + 1) % 24)}: ${n} alert${n === 1 ? "" : "s"}`)); b.addEventListener("mouseleave", hideTip); return b; })));
  }

  function tableCard(d) {
    const rows = d.cameras.slice(0, 15);
    return card("Places with the most alerts", null, rows.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Camera", "Alerts", "Critical", "Real", "False", "Busiest hour", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, rows.map(r => h("tr", { class: st.place === `camera:${r.key}` ? "sel-row" : null },
        h("td", {}, h("span", { style: "font-weight:600" }, r.label), r.label !== r.key ? h("div", { class: "faint mono", style: "font-size:11.5px" }, r.key) : null),
        h("td", {}, r.alerts), h("td", {}, r.critical || "—"), h("td", {}, r.real || "—"), h("td", {}, r.false || "—"),
        h("td", {}, r.peak_hour === null ? "—" : hh(r.peak_hour)),
        h("td", { style: "text-align:right" }, h("button", { class: "btn small", onclick: () => { st.place = `camera:${r.key}`; load(); } }, "Its hours"))))))) : h("p", { class: "muted" }, "No alerts in this period."));
  }

  async function load() {
    bar.replaceChildren(
      seg("days", [[7, "7 days"], [30, "30 days"], [90, "90 days"], [365, "1 year"]]),
      seg("only", [["all", "All alerts"], ["not_false", "Without false alarms"], ["real", "Real incidents"]]),
      seg("severity", [["", "Any severity"], ["critical", "Critical"]]),
      plans.length > 1 ? h("select", { class: "input", style: "width:auto", "aria-label": "Site plan", onchange: e => { st.plan = Number(e.target.value); save(); load(); } },
        plans.map(p => h("option", { value: p.id, selected: p.id === st.plan }, p.name))) : null);
    const q = new URLSearchParams({ days: st.days, only: st.only, severity: st.severity, place: st.place });
    if (st.plan) q.set("plan_id", st.plan);
    try {
      const d = await api(`/insights/heatmap?${q}`);
      body.replaceChildren(
        h("div", { class: "grid kpis" }, kpi("Alerts", d.total, `last ${d.days} days`), kpi("Places", d.cameras.length, "cameras with alerts"),
          kpi("Busiest place", d.cameras[0] ? d.cameras[0].label : "—", d.cameras[0] ? `${d.cameras[0].alerts} alerts` : "")),
        h("div", { class: "hm-two" }, mapCard(d), gridCard(d)), tableCard(d));
    } catch (ex) { body.replaceChildren(h("div", { class: "error" }, ex.message)); }
  }
  load();
}

/* ---------------- face and plate recognition (stage 4): watchlists, cameras, accuracy ---------------- */
async function recognitionPanel(st) {
  const tabs = [["people", "Face watchlist", st.face], ["plates", "Plate watchlist", st.plate], ["cameras", "Cameras and thresholds", true], ["accuracy", "Accuracy", true]].filter(t => t[2]);
  let tab = (() => { try { return sessionStorage.getItem("hss.rec.tab") || tabs[0][0]; } catch (_) { return tabs[0][0]; } })();
  if (!tabs.some(t => t[0] === tab)) tab = tabs[0][0];
  const body = h("div", {});
  const segs = h("div", { class: "seg" });
  const yearOn = () => { const d = new Date(); d.setMonth(d.getMonth() + 6); return d.toISOString().slice(0, 10); };
  const draw = async () => {
    segs.replaceChildren(...tabs.map(([k, l]) => h("button", { class: k === tab ? "on" : null, onclick: () => { tab = k; try { sessionStorage.setItem("hss.rec.tab", k); } catch (_) { /* fine */ } draw(); } }, l)));
    body.replaceChildren(h("div", { class: "muted" }, "Loading…"));
    try { body.replaceChildren(await ({ people: drawPeople, plates: drawPlates, cameras: drawCameras, accuracy: drawAccuracy })[tab]()); }
    catch (ex) { body.replaceChildren(h("div", { class: "error" }, ex.message)); }
  };
  const cfg = await api("/recognition/config");

  async function drawPeople() {
    const people = await api("/recognition/people");
    const listSel = h("select", { class: "input", id: "wp-list" }, Object.entries(cfg.face_lists).map(([k, v]) => h("option", { value: k }, `${v.label} (${v.severity} alert)`)));
    const nm = h("input", { class: "input", id: "wp-name", placeholder: "Full name" });
    const reason = h("input", { class: "input", id: "wp-reason", placeholder: "Why, e.g. dismissed for theft, barred from site (letter of 3 Nov 2026)" });
    const auth = h("input", { class: "input", id: "wp-auth", placeholder: "Consent form no. or legal authority reference" });
    const exp = h("input", { class: "input", type: "date", id: "wp-exp", value: yearOn() });
    const err = h("div", { class: "error", hidden: true });
    const add = h("button", { class: "btn primary", onclick: async () => {
      err.hidden = true;
      try { await api("/recognition/people", { method: "POST", body: { list: listSel.value, name: nm.value.trim(), reason: reason.value.trim(), authority_ref: auth.value.trim(), expires_at: exp.value } }); toast("Added; now add 2 to 5 photos"); draw(); }
      catch (ex) { err.textContent = ex.message; err.hidden = false; }
    } }, "Add person");
    const fileFor = p => { const inp = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", multiple: true, hidden: true });
      inp.addEventListener("change", async () => {
        for (const f of inp.files) {
          const url = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
          try { await api(`/recognition/people/${p.id}/photos`, { method: "POST", body: { image_data_url: url } }); } catch (ex) { toast(`${f.name}: ${ex.message}`); }
        }
        toast("Photos added; they're checked within a minute"); draw();
      });
      return h("span", {}, inp, h("button", { class: "btn small", onclick: () => inp.click() }, "Add photos")); };
    const faceChip = (p, f) => h("span", { class: "rec-face" },
      h("img", { src: `/api/recognition/people/${p.id}/photos/${f.id}`, alt: "", loading: "lazy" }),
      h("span", { class: `badge ${f.status === "ok" ? "ok" : f.status === "pending" ? "" : "bad"}`, title: f.problem || "" }, f.status === "ok" ? "used" : f.status === "pending" ? "checking" : "not usable"),
      h("button", { class: "btn small", title: f.problem || "Delete this photo", onclick: async () => { if (!confirm("Delete this photo?")) return; await api(`/recognition/people/${p.id}/photos/${f.id}`, { method: "DELETE" }); draw(); } }, "×"));
    return h("div", {},
      h("p", { class: "muted", style: "margin-top:0" }, "Only these people are recognised; every other face is discarded at once. Each entry needs a reason, a consent or legal authority reference and an expiry date (at most 12 months). Use 2 to 5 clear, front-facing photos of one person."),
      h("div", { class: "rec-form" }, h("div", { class: "field" }, h("label", { for: "wp-list" }, "List"), listSel), h("div", { class: "field" }, h("label", { for: "wp-name" }, "Name"), nm),
        h("div", { class: "field", style: "grid-column:span 2" }, h("label", { for: "wp-reason" }, "Reason"), reason), h("div", { class: "field" }, h("label", { for: "wp-auth" }, "Consent or authority"), auth),
        h("div", { class: "field" }, h("label", { for: "wp-exp" }, "Expires"), exp), h("div", { class: "field", style: "align-self:end" }, add)), err,
      people.length ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Person", "List", "Reason and authority", "Photos", "Expires", ""].map(t => h("th", {}, t)))),
        h("tbody", {}, people.map(p => h("tr", { class: !p.active || p.expired ? "muted" : null },
          h("td", {}, h("div", { style: "font-weight:600" }, p.name), h("div", { class: "faint", style: "font-size:12px" }, `added by ${p.added_by}, ${fmtTime(p.added_at)}`)),
          h("td", {}, h("span", { class: `badge ${p.list === "barred" ? "bad" : p.list === "watch" ? "warn" : ""}` }, (cfg.face_lists[p.list] || {}).label || p.list)),
          h("td", { style: "max-width:260px;white-space:normal;font-size:12.5px" }, p.reason, h("div", { class: "faint" }, p.authority_ref)),
          h("td", {}, h("div", { class: "rec-faces" }, p.faces.map(f => faceChip(p, f)), p.faces.filter(f => f.status !== "rejected").length < 5 ? fileFor(p) : null),
            !p.faces.some(f => f.status === "ok") ? h("div", { class: "faint", style: "font-size:12px" }, "Not matched until a photo is usable") : null),
          h("td", {}, p.expired ? h("span", { class: "badge bad" }, "expired") : !p.active ? h("span", { class: "badge" }, "paused") : fmtDate(p.expires_at)),
          h("td", { style: "text-align:right;white-space:nowrap" },
            h("button", { class: "btn small", onclick: async () => { await api(`/recognition/people/${p.id}`, { method: "PUT", body: { active: !p.active } }); draw(); } }, p.active ? "Pause" : "Resume"), " ",
            h("button", { class: "btn small danger", onclick: async () => { if (!confirm(`Delete ${p.name} and their photos and face data? This can't be undone.`)) return; await api(`/recognition/people/${p.id}`, { method: "DELETE" }); toast("Deleted"); draw(); } }, "Delete"))))))) : h("div", { class: "empty" }, "Nobody on a watchlist yet."));
  }

  async function drawPlates() {
    const rows = await api("/recognition/plates");
    const plate = h("input", { class: "input mono", id: "pl-plate", placeholder: "KJA 123 AB" });
    const listSel = h("select", { class: "input", id: "pl-list" }, Object.entries(cfg.plate_lists).map(([k, v]) => h("option", { value: k }, v.severity ? `${v.label} (${v.severity} alert)` : `${v.label} (no alert)`)));
    const nm = h("input", { class: "input", id: "pl-name", placeholder: "Owner or vehicle (optional)" });
    const reason = h("input", { class: "input", id: "pl-reason", placeholder: "Why" });
    const auth = h("input", { class: "input", id: "pl-auth", placeholder: "Authority or record reference" });
    const exp = h("input", { class: "input", type: "date", id: "pl-exp", value: yearOn() });
    const err = h("div", { class: "error", hidden: true });
    return h("div", {},
      h("p", { class: "muted", style: "margin-top:0" }, "Plates read on the recognition cameras are compared with this list only; plates not on it are discarded. Allowed plates raise nothing."),
      h("div", { class: "rec-form" }, h("div", { class: "field" }, h("label", { for: "pl-plate" }, "Plate"), plate), h("div", { class: "field" }, h("label", { for: "pl-list" }, "List"), listSel),
        h("div", { class: "field" }, h("label", { for: "pl-name" }, "Name"), nm), h("div", { class: "field" }, h("label", { for: "pl-reason" }, "Reason"), reason),
        h("div", { class: "field" }, h("label", { for: "pl-auth" }, "Authority"), auth), h("div", { class: "field" }, h("label", { for: "pl-exp" }, "Expires"), exp),
        h("div", { class: "field", style: "align-self:end" }, h("button", { class: "btn primary", onclick: async () => {
          err.hidden = true;
          try { await api("/recognition/plates", { method: "POST", body: { plate: plate.value, list: listSel.value, name: nm.value, reason: reason.value, authority_ref: auth.value, expires_at: exp.value } }); draw(); }
          catch (ex) { err.textContent = ex.message; err.hidden = false; }
        } }, "Add plate"))), err,
      rows.length ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Plate", "List", "Name", "Reason and authority", "Expires", ""].map(t => h("th", {}, t)))),
        h("tbody", {}, rows.map(r => h("tr", { class: r.expired ? "muted" : null }, h("td", { class: "mono", style: "font-weight:700" }, r.plate),
          h("td", {}, h("span", { class: `badge ${r.list === "block" ? "bad" : r.list === "watch" ? "warn" : "ok"}` }, cfg.plate_lists[r.list].label)), h("td", {}, r.name || "—"),
          h("td", { style: "font-size:12.5px" }, r.reason, h("div", { class: "faint" }, r.authority_ref)),
          h("td", {}, r.expired ? h("span", { class: "badge bad" }, "expired") : fmtDate(r.expires_at)),
          h("td", { style: "text-align:right" }, h("button", { class: "btn small danger", onclick: async () => { if (!confirm(`Remove ${r.plate}?`)) return; await api(`/recognition/plates/${r.id}`, { method: "DELETE" }); draw(); } }, "Remove"))))))) : h("div", { class: "empty" }, "No plates listed yet."));
  }

  async function drawCameras() {
    const paths = await api("/live/paths").catch(() => []);
    const cams = [...new Map(paths.map(p => [p.path.replace(/-sub$/, ""), p.label])).entries()];
    const cur = Object.fromEntries((cfg.cameras || []).map(x => [x.camera_id, x]));
    const rows = cams.map(([id, label]) => ({ id, label, face: h("input", { type: "checkbox", checked: !!(cur[id] && cur[id].face), disabled: !st.face }),
      plate: h("input", { type: "checkbox", checked: !!(cur[id] && cur[id].plate), disabled: !st.plate }),
      roi: h("input", { class: "input mono", style: "width:150px;padding:6px 8px", placeholder: "whole frame", value: cur[id] && cur[id].roi ? cur[id].roi.join(",") : "" }) }));
    const num = (id, v, step, min, max) => h("input", { class: "input", type: "number", id, value: v, step, min, max, style: "width:110px" });
    const thr = num("rc-thr", cfg.face_threshold, 0.01, 0.30, 0.80), mar = num("rc-mar", cfg.face_margin, 0.01, 0, 0.3), pc = num("rc-pc", cfg.plate_min_confidence, 0.01, 0.5, 0.99), rep = num("rc-rep", cfg.repeat_s, 10, 10, 3600);
    const w = cfg.worker || {};
    return h("div", {},
      h("p", { class: "muted", style: "margin-top:0" }, "Recognition runs only on the cameras ticked here, on their main stream. Use entrance cameras where the stage 1 suitability test showed faces of 40 pixels between the eyes or more. For plates, give the lane area as fractions x1,y1,x2,y2 (for example 0.2,0.4,0.8,0.9)."),
      h("div", { class: "note", style: "margin-bottom:10px" }, w.online ? `Recognition service running (${w.note || ""}); last report ${fmtTime(w.last_seen)}.` : "The recognition service isn't running: start it with docker compose --profile recognition up -d."),
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Camera", "Faces", "Plates", "Plate lane area", "Status"].map(t => h("th", {}, t)))),
        h("tbody", {}, rows.map(r => { const live = (w.cameras || {})[r.id];
          return h("tr", {}, h("td", {}, r.label, r.label !== r.id ? h("div", { class: "faint mono", style: "font-size:11.5px" }, r.id) : null), h("td", {}, r.face), h("td", {}, r.plate), h("td", {}, r.roi),
            h("td", { style: "font-size:12px" }, live ? `${live.connected ? "connected" : "no video"} · ${live.good_faces || 0} usable faces · ${live.face_matches || 0} face, ${live.plate_matches || 0} plate matches` : h("span", { class: "faint" }, "—"))); })))),
      h("div", { class: "rec-form", style: "margin-top:12px" },
        h("div", { class: "field" }, h("label", { for: "rc-thr" }, "Face match threshold"), thr, h("div", { class: "faint", style: "font-size:12px" }, "Higher = fewer false matches, more missed")),
        h("div", { class: "field" }, h("label", { for: "rc-mar" }, "Margin over the next person"), mar),
        h("div", { class: "field" }, h("label", { for: "rc-pc" }, "Plate read confidence"), pc),
        h("div", { class: "field" }, h("label", { for: "rc-rep" }, "Repeat a match after (s)"), rep)),
      h("button", { class: "btn primary", onclick: async () => {
        try {
          const cameras = rows.filter(r => r.face.checked || r.plate.checked).map(r => ({ camera_id: r.id, face: r.face.checked, plate: r.plate.checked,
            roi: r.roi.value.trim() ? r.roi.value.split(",").map(Number) : null }));
          Object.assign(cfg, await api("/recognition/config", { method: "PUT", body: { cameras, face_threshold: Number(thr.value), face_margin: Number(mar.value), plate_min_confidence: Number(pc.value), repeat_s: Number(rep.value) } }));
          toast("Saved; the recognition service picks it up within a minute");
        } catch (ex) { toast(ex.message); }
      } }, "Save"));
  }

  async function drawAccuracy() {
    const s = await api("/recognition/stats?days=90");
    return h("div", {},
      h("p", { class: "muted", style: "margin-top:0" }, "From operators' verdicts on matches in the last 90 days: Confirm (the same person or plate) or Not a match. Use this, with the stage 3 walk test, to set the threshold."),
      s.suggested_face_threshold ? h("div", { class: "note" }, `Suggested face threshold: ${s.suggested_face_threshold} (now ${s.face_threshold}). It removes every match operators rejected and keeps at least 90% of confirmed ones.`) : null,
      s.waiting_for_verdict ? h("p", {}, h("span", { class: "badge warn" }, `${s.waiting_for_verdict} match${s.waiting_for_verdict === 1 ? "" : "es"} waiting for a verdict`)) : null,
      s.by_camera.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Camera", "Kind", "Confirmed", "Not a match", "Right"].map(t => h("th", {}, t)))),
        h("tbody", {}, s.by_camera.map(r => h("tr", {}, h("td", {}, r.camera), h("td", {}, r.kind), h("td", {}, r.confirmed), h("td", {}, r.rejected),
          h("td", {}, r.precision === null ? "—" : h("span", { class: `badge ${r.precision >= 0.9 ? "ok" : r.precision >= 0.7 ? "warn" : "bad"}` }, `${Math.round(100 * r.precision)}%`))))))) : h("div", { class: "empty" }, "No verdicts yet."));
  }

  const el = card("Recognition", h("span", { class: "muted", style: "font-size:12.5px" }, "CSO and administrators"), h("div", { class: "toolbar", style: "margin-bottom:12px" }, segs), body);
  draw();
  return el;
}

/* A recognition match inside an alert: the enrolment photo beside the live picture, and the operator's verdict. */
async function recognitionMatch(a, onDone) {
  const m = await api(`/recognition/matches/${a.id}`);
  const canAct = ["admin", "cso", "operator"].includes(state.user.role);
  const note = h("input", { class: "input", id: "rv-note", placeholder: "Optional note" });
  const verdict = async v => {
    try { await api(`/recognition/matches/${a.id}/verdict`, { method: "POST", body: { verdict: v, note: note.value } }); toast(v === "confirmed" ? "Match confirmed" : "Marked not a match; alert closed"); onDone(); }
    catch (ex) { toast(ex.message); }
  };
  const live = a.snapshot_url ? h("img", { src: a.snapshot_url, alt: "Live picture" }) : h("div", { class: "faint" }, "no picture");
  return h("section", { class: "card rec-match" },
    h("div", { class: "head" }, h("h2", {}, m.kind === "face" ? `Face match: ${m.name}` : `Plate match: ${m.plate}`), h("div", { class: "spacer" }),
      h("span", { class: `badge ${m.list === "barred" || m.list === "block" ? "bad" : "warn"}` }, m.list_label)),
    h("p", { class: "muted", style: "margin:0 0 10px" }, m.kind === "face" ? `Score ${m.score} (margin ${m.margin}). ${m.reason}` : `Read confidence ${m.read_confidence}. ${m.name || ""}`,
      " A match is a lead, not proof: compare the pictures before acting."),
    h("div", { class: "rec-compare" },
      m.kind === "face" ? h("figure", {}, m.photos.length ? h("img", { src: m.photos[0], alt: "Enrolment photo" }) : h("div", { class: "faint" }, "photo deleted"), h("figcaption", {}, "Enrolled")) : null,
      h("figure", {}, live, h("figcaption", {}, "Camera"))),
    m.verdict ? h("p", {}, h("span", { class: `badge ${m.verdict.verdict === "confirmed" ? "ok" : ""}` }, m.verdict.verdict === "confirmed" ? "Confirmed" : "Not a match"), ` by ${m.verdict.username}, ${fmtTime(m.verdict.at)}${m.verdict.note ? ` · ${m.verdict.note}` : ""}`)
      : canAct ? h("div", { class: "toolbar" }, note, h("button", { class: "btn primary", onclick: () => verdict("confirmed") }, m.kind === "face" ? "Confirm: same person" : "Confirm: same plate"),
        h("button", { class: "btn", onclick: () => verdict("rejected") }, "Not a match")) : null);
}

/* ---------------- viewing log: who watched which camera ---------------- */
async function viewViewing(c) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const pad = n => String(n).padStart(2, "0");
  const localInput = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  let cams = [];
  try { const dev = await api("/devices"); cams = dev.nvrs.flatMap(n => (n.channels || []).map(ch => ({ id: ch.camera_id, name: ch.name || ch.camera_id }))).filter(x => x.id); } catch (_) { /* filter by id only */ }
  const camSel = h("select", { class: "input", id: "vl-cam" }, h("option", { value: "" }, "All cameras"),
    cams.map(x => h("option", { value: x.id, selected: x.id === params.get("cam") }, `${x.name} (${x.id})`)));
  if (params.get("cam") && !cams.some(x => x.id === params.get("cam"))) camSel.append(h("option", { value: params.get("cam"), selected: true }, params.get("cam")));
  const userIn = h("input", { class: "input", id: "vl-user", placeholder: "Any person", value: params.get("user") || "" });
  const kindSel = h("select", { class: "input", id: "vl-kind" }, [["", "Live and recordings"], ["live", "Live only"], ["playback", "Recordings only"]].map(([v, l]) => h("option", { value: v }, l)));
  const since0 = params.get("since") ? new Date(params.get("since")) : new Date(Date.now() - 7 * 86400000);
  const fromIn = h("input", { class: "input", type: "datetime-local", id: "vl-from", value: localInput(since0), style: "min-width:0;width:100%" });
  const toIn = h("input", { class: "input", type: "datetime-local", id: "vl-to", style: "min-width:0;width:100%", value: params.get("until") ? localInput(new Date(params.get("until"))) : "", title: "Leave empty for up to now" });
  const out = h("div");
  const query = () => {
    const q = new URLSearchParams();
    if (camSel.value) q.set("camera", camSel.value);
    if (userIn.value.trim()) q.set("user", userIn.value.trim());
    if (kindSel.value) q.set("kind", kindSel.value);
    if (fromIn.value) q.set("since", new Date(fromIn.value).toISOString());
    if (toIn.value) q.set("until", new Date(toIn.value).toISOString());
    return q.toString();
  };
  const fmtSpan = r => {
    if (r.kind !== "live") return fmtTime(r.started_at);
    const a = new Date(r.started_at), b = new Date(r.last_at);
    return b - a < 60000 ? fmtTime(a) : `${fmtTime(a)} – ${b.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  };
  const load = async () => {
    out.replaceChildren(h("div", { class: "muted" }, "Loading…"));
    try {
      const d = await api(`/viewing?${query()}`);
      out.replaceChildren(
        h("p", { class: "muted", style: "margin:4px 2px 10px" }, d.total ? `${d.total} viewing${d.total > 1 ? "s" : ""} by ${d.people} ${d.people > 1 ? "people" : "person"} of ${d.cameras} camera${d.cameras > 1 ? "s" : ""}` + (d.total > d.rows.length ? ` (showing the latest ${d.rows.length}; export for all)` : "") : "Nobody watched in this period."),
        d.rows.length ? h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, ["When", "Who", "Camera", "What", "From"].map(t => h("th", {}, t)))),
          h("tbody", {}, d.rows.map(r => h("tr", {},
            h("td", { style: "white-space:nowrap" }, fmtSpan(r)),
            h("td", {}, h("span", { style: "font-weight:600" }, r.username), h("div", { class: "faint", style: "font-size:11.5px" }, ROLE_NAMES[r.role] || r.role || "")),
            h("td", {}, r.camera, r.camera !== r.camera_id ? h("div", { class: "faint mono", style: "font-size:11.5px" }, r.camera_id) : null),
            h("td", {}, r.kind === "live" ? h("span", { class: "badge" }, "Live") : h("span", {}, h("span", { class: "badge warn" }, "Recording"), " from ", fmtTime(r.recorded_at))),
            h("td", { class: "mono" }, r.ip || "—")))))) : null);
    } catch (ex) { out.replaceChildren(h("div", { class: "err" }, ex.message)); }
  };
  c.append(card("Who watched which camera", null,
    h("p", { class: "muted", style: "margin-top:0" }, "Every live view and every recording played in the console or the phone app. Wall screens are shared displays and aren't listed. Opening the same camera again within 10 minutes extends the same line."),
    h("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:0 12px;align-items:end" },
      h("div", { class: "field", style: "grid-column:span 2" }, h("label", { for: "vl-cam" }, "Camera"), camSel),
      h("div", { class: "field" }, h("label", { for: "vl-user" }, "Person"), userIn),
      h("div", { class: "field" }, h("label", { for: "vl-kind" }, "What"), kindSel),
      h("div", { class: "field" }, h("label", { for: "vl-from" }, "From"), fromIn),
      h("div", { class: "field" }, h("label", { for: "vl-to" }, "To (empty = now)"), toIn),
      h("div", { style: "grid-column:1/-1;display:flex;gap:10px;margin-bottom:12px" },
        h("button", { class: "btn primary", onclick: load }, "Search"),
        h("button", { class: "btn", onclick: () => { location.href = `/api/viewing.csv?${query()}`; } }, "Export CSV"))),
    out));
  load();
}

/* ---------------- camera planner: will faces and plates be big enough? ---------------- */
const SENSORS = { '1/3"': 4.8, '1/2.8"': 5.12, '1/2.7"': 5.37, '1/2.5"': 5.76, '1/1.8"': 7.18, '1/1.2"': 10.67 };
const RESOLUTIONS = { "2 MP (1920 × 1080)": 1920, "4 MP (2560 × 1440)": 2560, "5 MP (2880 × 1620)": 2880, "6 MP (3200 × 1800)": 3200,
  "8 MP / 4K (3840 × 2160)": 3840, "12 MP (4000 × 3000)": 4000 };
// Pixels per metre at the target: IEC 62676-4 levels, plus what our face and plate engines need.
const DORI = [["Identify", 250], ["Recognise", 125], ["Observe", 62], ["Detect", 25]];
function planCamera(c) {
  const hfov = c.mode === "fov" ? c.hfov : 2 * Math.atan(c.sensor / (2 * c.focal)) * 180 / Math.PI;
  const k = 2 * Math.tan(hfov * Math.PI / 360);              // scene width = k × distance
  const ppm = c.px / (k * c.distance);
  const faceNeed = c.faceEye / 0.063, plateNeed = c.platePx / c.plateWidth;   // px per metre needed
  const maxAt = need => c.px / (need * k);
  const down = Math.atan(Math.max(0, c.height - c.targetH) / c.distance) * 180 / Math.PI;
  return { hfov, ppm, sceneW: k * c.distance, eyePx: ppm * 0.063, platePx: ppm * c.plateWidth, faceNeed, plateNeed,
    faceMax: maxAt(faceNeed), plateMax: maxAt(plateNeed), down, dori: DORI.map(([n, v]) => [n, v, maxAt(v)]) };
}
function viewPlanner(c) {
  const saved = (() => { try { return JSON.parse(localStorage.getItem("hss.planner") || "{}"); } catch (_) { return {}; } })();
  const st = { px: 2560, mode: "lens", focal: 4, sensor: 5.37, hfov: 90, distance: 8, height: 2.5, targetH: 1.6, faceEye: 40, platePx: 130, plateWidth: 0.30, ...saved };
  const num = (key, attrs) => { const el = h("input", { class: "input", type: "number", id: `pl-${key}`, value: st[key], step: "any", ...attrs });
    el.addEventListener("input", () => { const v = parseFloat(el.value); if (isFinite(v) && v > 0) { st[key] = v; draw(); } }); return el; };
  const sel = (key, opts) => { const el = h("select", { class: "input", id: `pl-${key}` }, Object.entries(opts).map(([l, v]) => h("option", { value: v, selected: String(v) === String(st[key]) }, l)));
    el.addEventListener("change", () => { st[key] = isNaN(Number(el.value)) ? el.value : Number(el.value); draw(); }); return el; };
  const field = (label, el, hint) => h("div", { class: "field" }, h("label", { for: el.id }, label), el, hint ? h("div", { class: "faint", style: "font-size:12px" }, hint) : null);
  const lensBox = h("div", { class: "field-row" }, field("Lens (mm)", num("focal", { min: 1 })), field("Sensor size", sel("sensor", SENSORS)));
  const fovBox = field("Horizontal view angle (degrees)", num("hfov", { min: 2, max: 179 }), "From the camera's datasheet, for the lens setting you'll use");
  const out = h("div", {});
  const pic = h("div", { class: "planner-pic" });
  const verdict = (ok, warn) => ok ? h("span", { class: "badge ok" }, "yes") : warn ? h("span", { class: "badge warn" }, "borderline") : h("span", { class: "badge bad" }, "no");
  const m = v => v >= 100 ? `${Math.round(v)} m` : `${v.toFixed(1)} m`;
  function draw() {
    try { localStorage.setItem("hss.planner", JSON.stringify(st)); } catch (_) {}
    lensBox.hidden = st.mode !== "lens"; fovBox.hidden = st.mode !== "fov";
    const r = planCamera(st);
    const faceOk = r.eyePx >= st.faceEye, faceMin = r.eyePx >= 28, plateOk = r.platePx >= st.platePx, plateMin = r.platePx >= st.platePx * 0.85;
    const level = (DORI.find(([, v]) => r.ppm >= v) || ["below Detect"])[0];
    out.replaceChildren(
      h("div", { class: "grid kpis" },
        kpi("Pixels per metre", Math.round(r.ppm), `at ${m(st.distance)}: ${level} (IEC 62676-4)`),
        kpi("Scene width there", m(r.sceneW), `view angle ${r.hfov.toFixed(0)}°`),
        kpi("Eyes apart", `${Math.round(r.eyePx)} px`, faceOk ? "big enough for face recognition" : faceMin ? "minimum only; aim for more" : `needs ${st.faceEye}`),
        kpi("Plate width", `${Math.round(r.platePx)} px`, plateOk ? "big enough for plate reading" : `needs ${st.platePx}`)),
      h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Task", "Needs", `At ${m(st.distance)}`, "Works up to", "Note"].map(t => h("th", {}, t)))),
        h("tbody", {},
          h("tr", {}, h("td", { style: "font-weight:600" }, "Face recognition"), h("td", {}, `${st.faceEye} px between eyes (${Math.round(r.faceNeed)} px/m)`),
            h("td", {}, verdict(faceOk, faceMin)), h("td", {}, m(r.faceMax)),
            h("td", { class: "muted" }, "Automatic recognition needs more than a person viewing (Identify). ",
              r.down > 15 ? `Camera looks down ${r.down.toFixed(0)}°: keep it under 15° (lower it or move it back).` : `Looks down ${r.down.toFixed(0)}°: fine.`)),
          h("tr", {}, h("td", { style: "font-weight:600" }, "Plate reading"), h("td", {}, `${st.platePx} px across a ${Math.round(st.plateWidth * 100)} cm plate (${Math.round(r.plateNeed)} px/m)`),
            h("td", {}, verdict(plateOk, plateMin)), h("td", {}, m(r.plateMax)),
            h("td", { class: "muted" }, r.sceneW > 4 ? `View is ${m(r.sceneW)} wide: one lane is about 3.5 m; narrower is better` : "View fits one lane")),
          ...r.dori.map(([n, v, d]) => h("tr", {}, h("td", {}, n), h("td", {}, `${v} px/m`), h("td", {}, verdict(r.ppm >= v)), h("td", {}, m(d)),
            h("td", { class: "muted" }, { Identify: "Tell who a person is", Recognise: "Tell if it's someone you know", Observe: "See what a person is doing; intrusion analytics", Detect: "See that someone is there" }[n])))))),
      h("p", { class: "faint", style: "font-size:12.5px" }, "Night, motion and angle reduce this further: infrared range, shutter speed (plates need 1/1000 s or faster) and lighting decide whether the pixels are usable. Confirm with the suitability tests on the real camera."));
    // Top view: the camera's cone with the range of each level.
    const W = 640, H = 260, cx = 30, cy = H / 2, maxD = Math.max(r.dori[3][2], st.distance) * 1.05, sc = (W - 60) / maxD, half = r.hfov * Math.PI / 360;
    const wedge = d => { const L = d * sc, a = Math.min(half, Math.atan((H / 2 - 10) / Math.max(L, 1))); return `M${cx},${cy} L${cx + L * Math.cos(a)},${cy - L * Math.sin(a)} L${cx + L * Math.cos(a)},${cy + L * Math.sin(a)} Z`; };
    const ns = "http://www.w3.org/2000/svg", el = (t, a, txt) => { const e = document.createElementNS(ns, t); for (const [k2, v] of Object.entries(a)) e.setAttribute(k2, v); if (txt) e.textContent = txt; return e; };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "planner-svg", role: "img", "aria-label": "Top view of the camera's coverage" });
    const bands = [["Detect", 3, "pl-detect"], ["Observe", 2, "pl-observe"], ["Recognise", 1, "pl-recognise"], ["Identify", 0, "pl-identify"]];
    for (const [, i, cls] of bands) svg.append(el("path", { d: wedge(r.dori[i][2]), class: cls }));
    const tx = cx + st.distance * sc;
    svg.append(el("line", { x1: tx, y1: 12, x2: tx, y2: H - 12, class: "pl-target" }), el("text", { x: tx + 4, y: 22, class: "pl-label" }, `target ${m(st.distance)}`));
    let lastX = -1e9;
    for (const [n, i] of [["Identify", 0], ["Recognise", 1], ["Observe", 2], ["Detect", 3]]) {
      const L = r.dori[i][2] * sc, x = cx + L;
      if (x > W - 10 || x - lastX < 90) continue;             // too close to the last label: the table has it
      const edge = L * Math.tan(Math.min(half, Math.atan((H / 2 - 10) / Math.max(L, 1))));
      svg.append(el("text", { x: x - 3, y: Math.min(H - 6, cy + edge + 14), class: "pl-label", "text-anchor": "end" }, `${n} ${m(r.dori[i][2])}`));
      lastX = x;
    }
    svg.append(el("circle", { cx, cy, r: 6, class: "pl-cam" }));
    pic.replaceChildren(svg, h("div", { class: "faint", style: "font-size:12px" }, "Seen from above. Each band is how far that level reaches; the line is your target distance."));
  }
  const mode = sel("mode", { "Lens and sensor": "lens", "View angle from the datasheet": "fov" });
  c.append(h("div", { class: "planner" },
    h("section", { class: "card" }, h("h2", { style: "margin-top:0" }, "Camera"),
      field("Resolution", sel("px", RESOLUTIONS)), field("Enter the view as", mode), lensBox, fovBox,
      h("h2", {}, "Where"),
      h("div", { class: "field-row" }, field("Distance to target (m)", num("distance", { min: 0.5 })), field("Camera height (m)", num("height", { min: 0.5 }))),
      h("h2", {}, "Targets"),
      h("div", { class: "field-row" }, field("Eyes apart needed (px)", num("faceEye", { min: 10 }), "28 minimum, 40 good"), field("Plate width needed (px)", num("platePx", { min: 50 }), "130 for our reader")),
      field("Plate width (m)", num("plateWidth", { min: 0.1, max: 1 }), "Measure a real plate on site")),
    h("div", { class: "grid", style: "gap:14px;min-width:0" }, h("section", { class: "card" }, out), h("section", { class: "card" }, pic))));
  draw();
}

/* ---------------- getting started and help (Phase 9) ---------------- */
async function viewStart(c) {
  const d = await api("/system/onboarding");
  const step = (x, i) => h("div", { class: `start-step ${x.done ? "done" : ""}` },
    h("span", { class: "start-num" }, x.done ? "✓" : i + 1),
    h("div", { class: "grow", style: "min-width:0" },
      h("div", { style: "font-weight:650" }, x.title, x.optional ? h("span", { class: "badge", style: "margin-left:8px" }, "optional") : null),
      h("div", { class: "muted", style: "font-size:13px;white-space:normal" }, x.why),
      x.detail ? h("div", { class: "faint", style: "font-size:12.5px" }, x.detail) : null),
    h("a", { class: `btn small ${x.done ? "" : "primary"}`, href: x.link }, x.done ? "View" : "Open"));
  const req = d.steps.filter(x => !x.optional), opt = d.steps.filter(x => x.optional);
  c.append(h("section", { class: "card" },
    h("div", { class: "head" }, h("h2", {}, d.done === d.total ? "Setup complete" : `${d.done} of ${d.total} steps done`), h("div", { class: "spacer" }),
      h("button", { class: "btn small", onclick: () => render() }, "Check again")),
    h("div", { class: "bar", style: "margin:0 0 14px" }, h("span", { style: `width:${Math.round(100 * d.done / d.total)}%` })),
    h("p", { class: "muted", style: "margin-top:0" }, "Each step ticks itself off when the system sees it done. Work down the list; the Help page has a guide for each role."),
    h("div", { class: "start-list" }, req.map(step))),
    card("Optional", null, h("div", { class: "start-list" }, opt.map((x, i) => step(x, req.length + i)))));
}

async function viewHelp(c) {
  const guides = await api("/help");
  let cur = new URLSearchParams(location.hash.split("?")[1] || "").get("g") || (guides.find(g => g.mine) || guides[0] || {}).id;
  const body = h("article", { class: "legal-doc", style: "max-height:none" });
  const tabs = h("div", { class: "seg", role: "group", "aria-label": "Guides" });
  const show = async id => {
    cur = id;
    tabs.replaceChildren(...guides.map(g => h("button", { class: g.id === cur ? "on" : null, onclick: () => show(g.id) }, g.title)));
    const g = await api(`/help/${id}`);
    body.replaceChildren(...renderMd(g.text));
  };
  c.append(h("div", { class: "toolbar" }, tabs), h("section", { class: "card" }, body));
  if (cur) await show(cur);
}

/* ---------------- security self-check (Phase 8) ---------------- */
async function viewSecurity(c) {
  const d = await api("/system/security");
  const STATUS = { fail: ["bad", "Needs action"], warn: ["warn", "Check"], ok: ["ok", "OK"] };
  c.append(h("div", { class: "grid kpis" },
    kpi("Needs action", h("span", { style: `color:${d.counts.fail ? "var(--bad)" : "var(--ok)"}` }, d.counts.fail), "failed checks"),
    kpi("To check", h("span", { style: `color:${d.counts.warn ? "var(--warn)" : "var(--ok)"}` }, d.counts.warn), "warnings"),
    kpi("Passing", d.counts.ok, `checked ${fmtTime(d.checked_at)}`)));
  c.append(card("Security checklist", h("button", { class: "btn small", onclick: () => render() }, "Check again"),
    h("div", { class: "list" }, d.checks.map(x => h("div", { class: "item", style: "align-items:flex-start" },
      h("span", { class: `badge ${STATUS[x.status][0]}`, style: "min-width:92px;text-align:center" }, STATUS[x.status][1]),
      h("div", { class: "grow", style: "min-width:0" }, h("div", { style: "font-weight:600" }, x.title),
        h("div", { class: "muted", style: "font-size:13px;white-space:normal" }, x.detail),
        x.status !== "ok" && x.fix ? h("div", { class: "faint", style: "font-size:12.5px;white-space:normal" }, "Fix: ", x.fix) : null))))));
  const b = d.backups, r = d.retention;
  c.append(h("div", { class: "grid cols-2" },
    card("Backups", null, h("div", { class: "kv" },
      h("div", {}, "Last backup"), h("div", {}, b.last ? `${fmtTime(b.last.at)} · ${b.last.status === "ok" ? b.last.detail : "FAILED: " + b.last.detail}` : "never"),
      h("div", {}, "Last good backup"), h("div", {}, b.last_ok ? `${fmtTime(b.last_ok.at)} (${ago(b.last_ok.at)})` : "never"),
      h("div", {}, "Restore test"), h("div", {}, b.restore_test ? `${fmtTime(b.restore_test.at)} · ${b.restore_test.status === "ok" ? "passed" : "FAILED: " + b.restore_test.detail}` : "never run")),
      h("p", { class: "faint", style: "font-size:12.5px;margin-bottom:0" }, "Backups run on the server with tools/backup/hss-backup.sh; see docs/backup.md.")),
    card("Retention", state.user.role === "admin" ? h("button", { class: "btn small", onclick: async e => {
      e.target.disabled = true;
      try { const x = await api("/system/retention/run", { method: "POST", body: {} }); toast(`${x.events} old events removed; ${x.recording_channels_checked ?? 0} cameras' recordings checked`); render(); }
      catch (ex) { toast(ex.message); e.target.disabled = false; }
    } }, "Run now") : null, h("div", { class: "kv" },
      h("div", {}, "Events kept"), h("div", {}, `${r.event_days} days (open alerts always kept)`),
      h("div", {}, "GPS positions kept"), h("div", {}, `${r.position_days} days`),
      h("div", {}, "NVR video required"), h("div", {}, `${r.recording_days} days per camera`),
      h("div", {}, "Last run"), h("div", {}, r.last_run ? `${fmtTime(r.last_run.at)}: ${r.last_run.detail}` : "not yet (runs daily)")))));
}

async function licenceCard(isAdmin) {
  const st = await api("/system/licence");
  const lic = st.licence;
  const tone = { licensed: "ok", not_set_up: "", grace: "warn", unlicensed: "bad", invalid: "bad" }[st.state];
  const file = h("input", { type: "file", id: "lic-file", accept: ".hsslicence,.json,application/json" });
  return card("Licence", h("span", { class: `badge ${tone}` }, { licensed: "licensed", not_set_up: "not set up", grace: "trial period", unlicensed: "no licence", invalid: "invalid" }[st.state]),
    h("p", { style: "margin-top:0" }, st.summary),
    lic ? h("div", { class: "kv" }, h("div", {}, "Licence"), h("div", { class: "mono" }, lic.id), h("div", {}, "Licensee"), h("div", {}, `${lic.licensee} · ${lic.site}`),
      h("div", {}, "Covers"), h("div", {}, `${lic.max_nvrs} NVRs, ${lic.max_cameras} cameras`),
      h("div", {}, "Features"), h("div", {}, lic.features.length ? lic.features.map(f => st.features_known[f] || f).join(", ") : "core only"),
      h("div", {}, "Updates and support"), h("div", {}, `until ${lic.support_until}`)) : null,
    h("div", { class: "kv", style: "margin-top:8px" }, h("div", {}, "Installation id"),
      h("div", {}, h("span", { class: "mono" }, st.installation_id), " ", h("button", { class: "btn small", onclick: async () => { try { await navigator.clipboard.writeText(st.installation_id); toast("Copied"); } catch (_) { toast("Select it and copy"); } } }, "Copy"))),
    isAdmin && st.state !== "not_set_up" ? h("div", { class: "toolbar", style: "margin-top:10px" }, file, h("button", { class: "btn primary", onclick: () => {
      const f = file.files[0]; if (!f) return toast("Choose the licence file first");
      const rd = new FileReader();
      rd.onload = async () => { try { await api("/system/licence", { method: "PUT", body: { text: rd.result } }); toast("Licence loaded"); render(); } catch (ex) { toast(ex.message); } };
      rd.readAsText(f);
    } }, "Load licence")) : null,
    h("p", { class: "faint", style: "font-size:12.5px;margin-bottom:0" }, "The licence never stops recording, live view or alerts. It limits how many NVRs and cameras can be added and turns on optional features."));
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
  if (["admin", "cso"].includes(me.role)) sections.push(await lockdownSettings());
  if (["admin", "cso"].includes(me.role)) sections.push(await complianceSettings());
  if (["admin", "cso"].includes(me.role)) {
    const sh = await api("/logbook/shift");
    const inp = h("input", { class: "input", id: "shifts-in", value: sh.shifts.map(x => `${x[0]} ${x[1]}-${x[2]}`).join(", ") });
    sections.push(card("Shifts", null, h("div", { class: "field" }, h("label", { for: "shifts-in" }, "Shift names and times (local)"), inp,
      h("div", { class: "faint", style: "font-size:12px" }, "e.g. Day 06:00-18:00, Night 18:00-06:00. Used by the Logbook and handovers.")),
      h("button", { class: "btn primary", onclick: async () => {
        const shifts = inp.value.split(",").map(x => x.trim()).filter(Boolean).map(x => { const m = x.match(/^(.+?)\s+(\d\d:\d\d)\s*-\s*(\d\d:\d\d)$/); return m ? [m[1], m[2], m[3]] : null; });
        if (shifts.some(x => !x)) return toast("Write each shift as: Name HH:MM-HH:MM");
        try { await api("/logbook/shifts", { method: "PUT", body: { shifts } }); toast("Shifts saved"); } catch (ex) { toast(ex.message); }
      } }, "Save shifts")));
  }
  if (["admin", "cso", "management"].includes(me.role)) sections.push(await licenceCard(me.role === "admin"));
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
        field("Escalate after (min)", esc), field("Cooldown (s)", cool),
        field("Turn PTZ cameras to", txt("ptz_presets", "none, or e.g. nvr4-ch05:3")),
        field("Switch on", txt("outputs", "none, or e.g. Gate siren, Fence floodlight"))),
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
