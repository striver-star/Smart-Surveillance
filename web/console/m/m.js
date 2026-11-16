/* HSS phone app for guards and supervisors: SOS, check-ins, alerts and the logbook. No framework. */
"use strict";
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v; else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(9)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}
// replaceChildren and append print null as the text "null": skip empty placeholders, as h() does.
const _rc = Element.prototype.replaceChildren, _ap = Element.prototype.append;
Element.prototype.replaceChildren = function (...k) { return _rc.apply(this, k.flat(9).filter(x => x !== null && x !== undefined && x !== false)); };
Element.prototype.append = function (...k) { return _ap.apply(this, k.flat(9).filter(x => x !== null && x !== undefined && x !== false)); };
const app = document.getElementById("app"), tabs = document.getElementById("tabs");
const S = { me: null, tab: "home", alerts: [], timer: null, player: null };
async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, { method: opts.method || "GET", credentials: "same-origin",
    headers: { "X-HSS": "1", ...(opts.body ? { "Content-Type": "application/json" } : {}) }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  let d = null; try { d = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) { const e = new Error(d && (typeof d.detail === "string" ? d.detail : Array.isArray(d.detail) ? d.detail.map(x => x.msg).join("; ") : "") || `Error ${r.status}`); e.status = r.status; throw e; }
  return d;
}
const t = d => new Date(d).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const label = s => s === "sos" ? "SOS" : (s || "").replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const position = (timeout = 20000) => new Promise((ok, no) => {
  if (!navigator.geolocation) return no(new Error("This phone or browser gives no location."));
  navigator.geolocation.getCurrentPosition(p => ok({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }),
    e => no(new Error(e.code === 1 ? "Location is blocked: allow location for this app in the phone's settings." : "No GPS fix yet; step outside and try again.")),
    { enableHighAccuracy: true, timeout, maximumAge: 0 });
});
function stopTimers() { clearInterval(S.timer); S.timer = null; if (S.player) { S.player.close(); S.player = null; } }

/* ---------- sign in ---------- */
function login(msg) {
  stopTimers(); tabs.hidden = true;
  const u = h("input", { autocomplete: "username", autocapitalize: "none", id: "u" }), p = h("input", { type: "password", autocomplete: "current-password", id: "p" });
  const code = h("input", { inputmode: "numeric", autocomplete: "one-time-code", id: "c", placeholder: "only if asked" });
  const err = h("div", { class: "err", hidden: !msg }, msg || "");
  const go = async () => {
    err.hidden = true;
    try { await api("/auth/login", { method: "POST", body: { username: u.value.trim(), password: p.value, code: code.value.trim() || null } }); boot(); }
    catch (e) { err.textContent = e.message; err.hidden = false; }
  };
  app.replaceChildren(h("h1", {}, "HSS Guard"), h("p", { class: "muted" }, "Sign in with the account the control room gave you."),
    h("div", { class: "card" }, err, h("div", { class: "field" }, h("label", { for: "u" }, "Username"), u), h("div", { class: "field" }, h("label", { for: "p" }, "Password"), p),
      h("div", { class: "field" }, h("label", { for: "c" }, "Two-factor code"), code), h("button", { class: "btn primary wide", onclick: go }, "Sign in")));
  p.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
}
function newPassword() {
  const cur = h("input", { type: "password", id: "cur" }), nw = h("input", { type: "password", id: "nw", autocomplete: "new-password" });
  const err = h("div", { class: "err", hidden: true });
  app.replaceChildren(h("h1", {}, "Choose your password"), h("div", { class: "card" }, err,
    h("div", { class: "field" }, h("label", { for: "cur" }, "Temporary password"), cur), h("div", { class: "field" }, h("label", { for: "nw" }, "New password (12 or more characters)"), nw),
    h("button", { class: "btn primary wide", onclick: async () => { try { await api("/auth/password", { method: "POST", body: { current: cur.value, new: nw.value } }); boot(); } catch (e) { err.textContent = e.message; err.hidden = false; } } }, "Save")));
}

/* ---------- tabs ---------- */
function drawTabs() {
  const items = [["home", "Home"], ...(S.me.supervisor ? [["alerts", "Alerts"]] : []), ["log", "Log"], ["me", "Me"]];
  tabs.hidden = false;
  tabs.replaceChildren(...items.map(([k, l]) => h("button", { class: S.tab === k ? "on" : null, onclick: () => show(k) }, l,
    k === "alerts" && S.alerts.filter(a => a.status === "open").length ? h("span", { class: "count" }, S.alerts.filter(a => a.status === "open").length) : null)));
}
function show(tab) { S.tab = tab; stopTimers(); drawTabs(); ({ home, alerts: alertsView, log, me: meView })[tab](); }

/* ---------- home: SOS and check-in ---------- */
async function home(flash) {
  const me = S.me = await api("/mobile/me");
  const msg = h("div", {}, flash || null);
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", "0 0 100 100");
  const circ = document.createElementNS(NS, "circle"); circ.setAttribute("cx", 50); circ.setAttribute("cy", 50); circ.setAttribute("r", 47);
  circ.setAttribute("stroke-dasharray", "295.3"); circ.setAttribute("stroke-dashoffset", "295.3"); svg.append(circ);
  let holdT = null, startAt = 0, raf = null;
  const sosBtn = h("button", { class: "sos", "aria-label": "SOS: hold for 2 seconds" }, svg, h("span", {}, "SOS", h("small", {}, "hold 2 seconds")));
  const reset = () => { clearTimeout(holdT); cancelAnimationFrame(raf); circ.setAttribute("stroke-dashoffset", "295.3"); };
  const anim = () => { const f = Math.min(1, (Date.now() - startAt) / 2000); circ.setAttribute("stroke-dashoffset", String(295.3 * (1 - f))); if (f < 1) raf = requestAnimationFrame(anim); };
  const fire = async () => {
    reset(); if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
    msg.replaceChildren(h("div", { class: "info" }, "Sending SOS…"));
    let pos = null; try { pos = await position(8000); } catch (_) { /* send without */ }
    try {
      const r = await api("/mobile/sos", { method: "POST", body: pos ? { lat: pos.lat, lon: pos.lon, accuracy: pos.accuracy } : {} });
      msg.replaceChildren(h("div", { class: "okmsg" }, h("strong", {}, `SOS sent at ${t(r.at)}. `), r.located ? "The control room has your location." : "Your location could not be read: tell the control room where you are."));
    } catch (e) { msg.replaceChildren(h("div", { class: "err" }, `SOS not sent: ${e.message}. Call the control room.`)); }
  };
  sosBtn.addEventListener("pointerdown", e => { e.preventDefault(); sosBtn.setPointerCapture && sosBtn.setPointerCapture(e.pointerId); startAt = Date.now(); anim(); holdT = setTimeout(fire, 2000); });
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) sosBtn.addEventListener(ev, reset);
  const checkBtn = h("button", { class: "btn primary wide", onclick: async () => {
    checkBtn.disabled = true; msg.replaceChildren(h("div", { class: "info" }, "Getting your position…"));
    try {
      const pos = await position();
      const r = await api("/mobile/checkin", { method: "POST", body: pos });
      const note = h("div", { class: r.ok ? "okmsg" : "info" }, r.message, h("div", { class: "small muted" }, `GPS accuracy about ${Math.round(pos.accuracy)} m`));
      msg.replaceChildren(note);
      if (r.ok) { if (navigator.vibrate) navigator.vibrate(80); home(note); }
    } catch (e) { msg.replaceChildren(h("div", { class: "err" }, e.message)); }
    finally { checkBtn.disabled = false; }
  } }, "Check in here");
  app.replaceChildren(h("h1", {}, `Hello, ${me.name}`), h("p", { class: "muted small", style: "margin:0" }, new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })),
    msg, h("div", { class: "card", style: "text-align:center" }, sosBtn, h("p", { class: "small muted" }, "Hold the button for 2 seconds. The control room gets a critical alert with your location.")),
    h("div", { class: "card" }, h("h2", {}, "Patrol"), checkBtn,
      h("div", { style: "margin-top:12px" }, me.check_ins.length ? me.check_ins.map(c => h("div", { class: "entry" }, h("strong", {}, c.checkpoint), h("span", { class: "muted small" }, ` · ${t(c.at)}`)))
        : h("p", { class: "muted small", style: "margin:0" }, "No check-ins in the last 12 hours."))));
}

/* ---------- alerts (supervisors) ---------- */
async function loadAlerts() { try { S.alerts = (await api("/alerts?status=active&limit=50")).alerts; } catch (_) { /* keep last */ } }
async function alertsView() {
  await loadAlerts(); drawTabs();
  const draw = () => app.replaceChildren(h("h1", {}, "Alerts"),
    S.alerts.length ? h("div", { class: "list" }, S.alerts.map(a => h("button", { class: "alert", onclick: () => alertDetail(a.id) },
      h("span", { class: `stripe ${a.severity}` }), a.snapshot_url ? h("img", { src: a.snapshot_url, alt: "", loading: "lazy" }) : h("div", { class: "noimg" }),
      h("div", {}, h("div", { class: "t" }, label(a.type)), h("div", { class: "s" }, `${a.camera_name || a.camera_id} · ${t(a.occurred_at)}`),
        h("span", { class: `badge ${a.status === "open" ? "bad" : ""}` }, a.status === "open" ? "not acknowledged" : `with ${a.assigned_to || a.acknowledged_by}`)))))
      : h("div", { class: "card muted" }, "No open alerts."));
  draw();
  S.timer = setInterval(async () => { await loadAlerts(); if (S.tab === "alerts") { draw(); drawTabs(); } }, 15000);
}
async function alertDetail(id) {
  stopTimers();
  const a = await api(`/alerts/${id}`);
  const note = h("textarea", { placeholder: "What you saw or did" });
  const reason = h("select", {}, [["real_incident", "Real incident"], ["false_alarm", "False alarm"], ["test", "Test"], ["duplicate", "Duplicate"], ["other", "Other"]].map(([v, l]) => h("option", { value: v }, l)));
  const err = h("div", { class: "err", hidden: true });
  const act = async body => { try { await api(`/alerts/${id}/action`, { method: "POST", body }); alertDetail(id); } catch (e) { err.textContent = e.message; err.hidden = false; } };
  const liveBox = h("div", {});
  app.replaceChildren(h("button", { class: "btn", onclick: () => show("alerts") }, "‹ Alerts"),
    h("h1", {}, label(a.type)), h("p", { class: "muted", style: "margin:0" }, `${a.camera_name || a.camera_id}${a.zone ? ` · ${a.zone}` : ""} · ${new Date(a.occurred_at).toLocaleString()}`),
    a.snapshot_url ? h("img", { class: "snap", src: a.snapshot_url, alt: "Snapshot" }) : null, liveBox,
    h("div", { class: "row" },
      a.status === "open" ? h("button", { class: "btn primary", onclick: () => act({ action: "acknowledge", text: note.value }) }, "Acknowledge") : null,
      h("button", { class: "btn", onclick: () => {
        if (S.player) { S.player.close(); S.player = null; liveBox.replaceChildren(); return; }
        const v = h("video", { class: "snap", muted: true, autoplay: true, playsinline: true }); v.muted = true;
        const st = h("div", { class: "small muted" }, "connecting");
        liveBox.replaceChildren(v, st);
        S.player = new LivePlayer(v, a.camera_id, (s, info) => { st.textContent = s === "playing" ? "live" : s === "error" ? info : s; });
      } }, "Live")),
    err, h("div", { class: "card" }, h("div", { class: "field" }, h("label", {}, "Note"), note),
      h("button", { class: "btn wide", onclick: () => note.value.trim() ? act({ action: "comment", text: note.value }) : null }, "Add note")),
    a.status !== "closed" ? h("div", { class: "card" }, h("div", { class: "field" }, h("label", {}, "Close as"), reason),
      h("button", { class: "btn wide", onclick: () => act({ action: "close", reason: reason.value, text: note.value }) }, "Close alert")) : null,
    h("div", { class: "card" }, h("h2", {}, "Timeline"), (a.timeline || []).slice().reverse().map(x => h("div", { class: "entry small" },
      h("strong", {}, label(x.kind)), x.username ? ` · ${x.username}` : "", h("span", { class: "muted" }, ` · ${t(x.at)}`), x.text ? h("div", { class: "muted" }, x.text) : null))));
}

/* ---------- logbook ---------- */
async function log() {
  const cat = h("select", {}, [["patrol", "Patrol"], ["incident", "Incident"], ["visitor", "Visitor"], ["maintenance", "Maintenance"], ["other", "Other"]].map(([v, l]) => h("option", { value: v }, l)));
  const text = h("textarea", { placeholder: "What happened, where, who, what you did" });
  const list = h("div", {}); const err = h("div", { class: "err", hidden: true });
  const load = async () => {
    const d = await api("/logbook");
    list.replaceChildren(...(d.entries.length ? d.entries.slice(0, 40).map(e => h("div", { class: "entry" }, h("span", { class: "badge" }, label(e.category)), " ",
      h("span", { class: "muted small" }, `${e.name} · ${t(e.at)}`), h("div", { style: "white-space:pre-wrap" }, e.text))) : [h("p", { class: "muted small" }, "Nothing logged this shift yet.")]));
  };
  app.replaceChildren(h("h1", {}, "Logbook"), err, h("div", { class: "card" }, h("div", { class: "field" }, h("label", {}, "Type"), cat), h("div", { class: "field" }, h("label", {}, "Entry"), text),
    h("button", { class: "btn primary wide", onclick: async () => {
      if (!text.value.trim()) return;
      try { await api("/logbook", { method: "POST", body: { category: cat.value, text: text.value } }); text.value = ""; err.hidden = true; load(); } catch (e) { err.textContent = e.message; err.hidden = false; }
    } }, "Add to log")), h("div", { class: "card" }, h("h2", {}, "This shift"), list));
  load();
}

/* ---------- me ---------- */
function meView() {
  app.replaceChildren(h("h1", {}, S.me.name), h("p", { class: "muted" }, `Signed in as ${S.me.username} (${S.me.role})`),
    h("div", { class: "card small" }, h("h2", {}, "Install on this phone"),
      h("p", { style: "margin:0 0 6px" }, "iPhone: Share › Add to Home Screen. Android: menu › Install app (or Add to Home screen)."),
      h("p", { class: "muted", style: "margin:0" }, "For continuous tracking on patrol, also run the Traccar Client app as the control room set it up.")),
    h("button", { class: "btn danger wide", onclick: async () => { try { await api("/auth/logout", { method: "POST", body: {} }); } catch (_) { /* ignore */ } login("Signed out."); } }, "Sign out"));
}

/* ---------- start ---------- */
async function boot() {
  let user;
  try { user = await api("/auth/me"); } catch (e) { return login(); }
  if (user.must_change_password) return newPassword();
  try { S.me = await api("/mobile/me"); } catch (e) { return login(e.status === 403 ? "This account can't use the phone app." : e.message); }
  lockBanner(S.me.lockdown);
  if (!S.lockPoll) S.lockPoll = setInterval(async () => { try { lockBanner((await api("/lockdown")).lockdown); } catch (_) { /* signed out or offline */ } }, 20000);
  show("home");
}

/* ---------- lockdown banner, on every tab ---------- */
function lockBanner(l) {
  let bar = document.getElementById("lockdown");
  if (!l) { if (bar) bar.remove(); return; }
  if (!bar) { bar = h("div", { id: "lockdown", class: "lockdown", role: "alert" }); document.body.prepend(bar); if (navigator.vibrate) navigator.vibrate([300, 150, 300]); }
  bar.replaceChildren(h("strong", {}, "LOCKDOWN"), ` since ${t(l.since)} · ${l.reason}`);
}
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/m/sw.js", { scope: "/m/" }).catch(() => { /* works without it */ });
boot();
