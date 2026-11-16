/* Wall screen: plays a screen's cameras over WebRTC, rotates pages, outlines cameras with open alerts,
   follows changes made in the console every few seconds, and reports to the Wall Agent.

   Keeps running when the server is busy or restarting: the last layout is kept in the browser and the
   page itself is kept by a service worker (sw.js), so after a reload or a wall PC restart during an
   outage the wall comes up with its last cameras. Cameras keep playing while only the API is down
   (they come from the stream gateway); if the gateway is down too they show "reconnecting" and come
   back by themselves. A note in the corner says since when the platform has been unreachable. */
"use strict";
const q = new URLSearchParams(location.search);
const SID = q.get("s"), KEY = q.get("k");
const grid = document.getElementById("grid"), msg = document.getElementById("msg");
const players = new Map();      // path -> { tile, player, state }
let screen = null, pageIx = 0, rotateTimer = null, lastLayoutSig = "", offlineSince = null, loading = false;
const CACHE_KEY = `hss-wall:${SID}:${KEY}`;
const LOAD_TIMEOUT_MS = 8000;

function show(text) { msg.textContent = text; msg.hidden = !text; }
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }
function saved() { try { return JSON.parse(localStorage.getItem(CACHE_KEY) || "null"); } catch (_) { return null; } }
function save(s) { try { localStorage.setItem(CACHE_KEY, JSON.stringify(s)); } catch (_) { /* storage full or blocked */ } }
function forget() { try { localStorage.removeItem(CACHE_KEY); } catch (_) { /* ignore */ } }
const hhmm = d => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function apply(next) {
  const sig = JSON.stringify([next.tiles, next.dwell_s, next.labels, next.pages.map(p => p.map(t => t.path))]);
  const first = !screen;
  screen = next;
  document.getElementById("title").textContent = screen.name;
  if (first || sig !== lastLayoutSig) {
    lastLayoutSig = sig;
    if (pageIx >= screen.pages.length) pageIx = 0;
    drawPage();
    scheduleRotation();
  } else {
    markAlerts();
  }
}

function setOffline(on) {
  const note = document.getElementById("offline");
  if (on) {
    if (!offlineSince) {
      offlineSince = new Date();
      // Alert outlines can't be kept up to date while the platform is unreachable: clear them rather than show old ones.
      if (screen) { for (const page of screen.pages) for (const t of page) t.alert = null; markAlerts(); }
    }
    note.textContent = `Platform unreachable since ${hhmm(offlineSince)}: showing the last layout`;
    note.hidden = false;
  } else if (offlineSince) {
    offlineSince = null;
    note.hidden = true;
    for (const p of players.values()) p.player && p.player.nudge();     // reconnect now, not after the back-off
  }
}

async function load() {
  if (!SID || !KEY) { show("This wall link is incomplete. Assign a screen to this TV in the console (Video walls)."); return; }
  if (loading) return;                       // a slow server: don't stack up requests
  loading = true;
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), LOAD_TIMEOUT_MS);
  try {
    const r = await fetch(`/api/wall/screens/${encodeURIComponent(SID)}/play?k=${encodeURIComponent(KEY)}`, { cache: "no-store", signal: ctl.signal });
    if (r.status === 404) {
      forget();
      show("This screen was deleted or its link changed. The Wall Agent picks up the new link within a minute.");
      return;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const next = await r.json();
    if (!next || !Array.isArray(next.pages)) throw new Error("unexpected answer");
    show("");
    setOffline(false);
    save(next);
    apply(next);
  } catch (e) {
    // Busy, restarting or unreachable: keep what is on screen; on a fresh start use the last saved layout.
    if (!screen) {
      const last = saved();
      if (last) { show(""); apply(last); }
    }
    if (screen) setOffline(true);
    else show("Can't reach the platform. Retrying…");
  } finally {
    clearTimeout(timer);
    loading = false;
  }
}

function scheduleRotation() {
  clearInterval(rotateTimer);
  if (screen.pages.length > 1) rotateTimer = setInterval(() => { pageIx = (pageIx + 1) % screen.pages.length; drawPage(); }, screen.dwell_s * 1000);
}

function drawPage() {
  const page = screen.pages[pageIx] || [];
  grid.style.gridTemplateColumns = `repeat(${screen.cols}, minmax(0, 1fr))`;
  grid.style.gridTemplateRows = `repeat(${screen.rows}, minmax(0, 1fr))`;
  const keep = new Set(page.map(t => t.path));
  for (const [path, p] of players) if (!keep.has(path)) { p.player && p.player.close(); players.delete(path); }
  const tiles = [];
  for (const t of page) {
    let p = players.get(t.path);
    if (!p) {
      const tile = el("div", "tile"), video = el("video"), state = el("div", "state", "connecting"), name = el("div", "name");
      video.muted = true; video.autoplay = true; video.playsInline = true;
      tile.append(video, state, name);
      p = { tile, state: "connecting", stateEl: state, nameEl: name };
      if (t.configured) {
        p.player = new LivePlayer(video, t.path, (s, info) => {
          p.state = s; tile.classList.toggle("playing", s === "playing");
          const down = /fetch|NetworkError|gateway 50[234]|abort/i.test(info || "");   // the server or gateway is restarting
          state.textContent = s === "error" ? `${t.label}\n${down ? "waiting for the video server" : info}` : s === "frozen" ? "reconnecting" : s === "playing" ? "" : s;
        }, { headers: { "X-HSS-Wall": `${SID}:${KEY}` } });
      } else { state.textContent = `${t.label}\nnot in the stream gateway`; p.state = "error"; }
      players.set(t.path, p);
    }
    p.nameEl.textContent = screen.labels ? t.label : "";
    tiles.push(p.tile);
  }
  for (let i = page.length; i < screen.tiles; i++) tiles.push(el("div", "tile empty"));
  grid.replaceChildren(...tiles);
  document.getElementById("page").textContent = screen.pages.length > 1 ? `${pageIx + 1}/${screen.pages.length}` : "";
  markAlerts();
}

function markAlerts() {
  const page = screen.pages[pageIx] || [];
  const byPath = Object.fromEntries(screen.pages.flat().map(t => [t.path, t.alert]));
  for (const t of page) {
    const p = players.get(t.path);
    if (!p) continue;
    const a = byPath[t.path];
    p.tile.classList.toggle("alert-warning", a === "warning");
    p.tile.classList.toggle("alert-critical", a === "critical");
    let b = p.tile.querySelector(".badge");
    if (a && !b) { b = el("div", "badge", "ALERT"); p.tile.append(b); }
    if (!a && b) b.remove();
  }
}

function clock() { document.getElementById("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

// Heartbeat to the Wall Agent on this PC (only a loopback address is accepted), so it can restart a stuck browser.
const AGENT = q.get("wall_agent") || "";
if (/^http:\/\/127\.0\.0\.1:\d{2,5}$/.test(AGENT)) {
  const monitor = encodeURIComponent(q.get("monitor") || "0");
  setInterval(() => {
    const states = [...players.values()].map(p => p.state);
    fetch(`${AGENT}/heartbeat?monitor=${monitor}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, targetAddressSpace: "loopback",
      body: JSON.stringify({ page: "wall", screen: screen ? screen.name : "", tiles: states.length,
        playing: states.filter(s => s === "playing").length, frozen_now: states.filter(s => s === "frozen").length,
        page_ix: pageIx, pages: screen ? screen.pages.length : 0, platform_offline: !!offlineSince }),
    }).catch(() => { /* agent not running */ });
  }, 5000);
}

document.addEventListener("keydown", e => {
  if (e.key === "f" || e.key === "F") document.documentElement.requestFullscreen && document.documentElement.requestFullscreen().catch(() => {});
  if (e.key === "ArrowRight" && screen && screen.pages.length > 1) { pageIx = (pageIx + 1) % screen.pages.length; drawPage(); scheduleRotation(); }
  if (e.key === "ArrowLeft" && screen && screen.pages.length > 1) { pageIx = (pageIx - 1 + screen.pages.length) % screen.pages.length; drawPage(); scheduleRotation(); }
});
// Keep this page and its scripts on the wall PC, so it opens even while the server is restarting.
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/wall/sw.js", { scope: "/wall/" }).catch(() => { /* needs a trusted certificate */ });
load(); clock();
setInterval(load, 10000); setInterval(clock, 15000);
