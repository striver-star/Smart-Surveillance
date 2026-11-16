/* Control-room status board: a wall screen of kind "control" (see services/api/app/control.py).
   Drawn by wall.js's apply() when the screen's answer says kind: "control". Big type for a TV at a distance. */
"use strict";
const Control = (() => {
  let livePlayer = null, livePath = "", root = null;
  const NS = "http://www.w3.org/2000/svg";
  const e = (tag, cls, ...kids) => { const n = document.createElement(tag); if (cls) n.className = cls; for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) n.append(k); return n; };
  const sv = (tag, attrs, ...kids) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v); for (const k of kids) if (k) n.append(k); return n; };
  const hm = d => new Date(d).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const ago = d => { const s = Math.max(0, (Date.now() - new Date(d)) / 1000); return s < 60 ? "now" : s < 3600 ? `${Math.floor(s / 60)} min` : s < 86400 ? `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min` : `${Math.floor(s / 86400)} d`; };
  const dur = s => s === null || s === undefined ? "" : s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`;
  const label = s => (s || "").replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
  const q = (sid, key) => `?k=${encodeURIComponent(key)}`;

  function kpi(title, value, sub, tone) { return e("div", `kpi ${tone || ""}`, e("div", "k-title", title), e("div", "k-value", value), e("div", "k-sub", sub || "")); }

  function mapCard(b, sid, key) {
    const m = b.map;
    if (!m) return null;
    const p = m.plan, W = p.width, H = p.height, k = Math.max(W, H) / 1000;
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet", class: "map" });
    svg.append(sv("image", { href: `/api/wall/screens/${sid}/plan-image${q(sid, key)}`, x: 0, y: 0, width: W, height: H }));
    for (const z of m.zones) {
      if (!z.points || !z.points.length) continue;
      svg.append(sv("polygon", { class: `zone ${z.kind} ${z.armed_now ? "armed" : ""}`, points: z.points.map(pt => pt.join(",")).join(" "), "stroke-width": 3 * k }));
    }
    for (const c of m.cameras) {
      const cls = c.alert ? `alert-${c.alert}` : c.online === false ? "offline" : "online";
      svg.append(sv("circle", { class: `cam ${cls}`, cx: c.x, cy: c.y, r: (c.alert ? 14 : 9) * k, "stroke-width": 2.5 * k }));
    }
    for (const u of m.units) {
      if (!u.on_plan) continue;
      svg.append(sv("g", { class: `unit ${u.offline ? "offline" : ""}` }, sv("circle", { cx: u.x, cy: u.y, r: 11 * k, "stroke-width": 3 * k }),
        sv("text", { x: u.x + 16 * k, y: u.y + 6 * k, "font-size": 22 * k }, document.createTextNode(u.name))));
    }
    return e("section", "card map-card", e("h2", null, p.name), e("div", "map-wrap", svg),
      e("div", "legend", e("span", "lg crit", "alert"), e("span", "lg ok", "camera online"), e("span", "lg off", "offline"), e("span", "lg unit", "guard")));
  }

  function alertsCard(b, sid, key) {
    const list = b.alerts.length ? b.alerts.map(a => e("div", `al ${a.severity} ${a.status}`,
      a.has_snapshot ? (() => { const i = new Image(); i.alt = ""; i.loading = "lazy"; i.src = `/api/wall/screens/${sid}/alert-image/${a.id}${q(sid, key)}`; return i; })() : e("div", "noimg"),
      e("div", "al-text", e("div", "al-title", label(a.type), a.object_class ? ` · ${a.object_class}` : ""),
        e("div", "al-where", [a.zone, a.camera].filter(Boolean).join(" · ")),
        e("div", "al-meta", a.status === "open" ? e("b", null, `waiting ${ago(a.created_at)}`) : `acknowledged by ${a.acknowledged_by || "?"}`,
          a.escalation_level ? e("span", "esc", ` escalated ×${a.escalation_level}`) : null)),
      e("div", "al-time", hm(a.created_at)))) : [e("div", "calm", "No open alerts")];
    return e("section", "card alerts-card", e("h2", null, "Open alerts"), e("div", "al-list", list));
  }

  function liveCard(b) {
    const box = e("section", "card live-card", e("h2", null, b.live ? `Live: ${b.live.label}` : "Live"));
    const holder = e("div", "live-wrap");
    box.append(holder);
    if (!b.live || !b.live.path) {
      holder.append(e("div", "calm small", b.live ? "Camera not in the stream gateway" : "Plays the camera of the newest critical alert"));
      if (livePlayer) { livePlayer.close(); livePlayer = null; livePath = ""; }
      return box;
    }
    if (livePath !== b.live.path || !livePlayer) {
      if (livePlayer) livePlayer.close();
      const v = document.createElement("video"); v.muted = true; v.autoplay = true; v.playsInline = true;
      livePath = b.live.path;
      livePlayer = new LivePlayer(v, livePath, () => {}, { headers: { "X-HSS-Wall": `${SID}:${KEY}` } });
      livePlayer.videoEl = v;
    }
    holder.append(livePlayer.videoEl);
    livePlayer.videoEl.play().catch(() => {});        // moving a video in the page pauses it
    return box;
  }

  function sideCard(b) {
    const g = b.guards, s = b.shift;
    return e("section", "card side-card",
      e("h2", null, "Shift and patrols"),
      s ? e("div", "row-line", e("b", null, `${s.label} shift`), ` until ${hm(s.end)}`) : null,
      g && g.check_ins.length ? e("div", "sub-h", "Latest check-ins") : null,
      g ? g.check_ins.slice(0, 3).map(c => e("div", "row-line", e("span", "t", hm(c.at)), ` ${c.unit} at ${c.checkpoint}`)) : null,
      s && s.logbook.length ? e("div", "sub-h", "Logbook") : null,
      s ? s.logbook.slice(0, 3).map(l => e("div", "row-line", e("span", "t", hm(l.at)), ` ${l.by}: ${l.text}`)) : null);
  }

  function draw(b, sid, key) {
    if (!root) { root = document.getElementById("board"); }
    document.getElementById("grid").hidden = true;
    root.hidden = false;
    const c = b.counts || {}, d = b.devices, g = b.guards, s = b.shift;
    const kpis = e("div", "kpis",
      kpi("Open alerts", String(c.open ?? "–"), c.open ? `${c.critical} critical · ${c.warning} warning` : "all clear", c.critical ? "bad" : c.open ? "warn" : "ok"),
      kpi("Not acknowledged", String(c.unacknowledged ?? "–"), c.unacknowledged ? `oldest ${dur(c.oldest_unacknowledged_s)}` + (c.escalated ? ` · ${c.escalated} escalated` : "") : "", c.unacknowledged ? "bad" : "ok"),
      d ? kpi("Cameras online", `${d.online} / ${d.cameras}`, d.offline_cameras.length ? `offline: ${d.offline_cameras.slice(0, 3).join(", ")}` : "all online", d.online < d.cameras ? "warn" : "ok") : null,
      d ? kpi("NVRs", `${d.nvrs - d.nvrs_unreachable.length} / ${d.nvrs}`, d.disk_problems.length ? `drive fault: ${d.disk_problems.join(", ")}` : d.nvrs_unreachable.length ? `unreachable: ${d.nvrs_unreachable.join(", ")}` : "recording", d.disk_problems.length || d.nvrs_unreachable.length ? "bad" : "ok") : null,
      g ? kpi("Guards reporting", String(g.reporting), g.offline.length ? `no signal: ${g.offline.slice(0, 3).join(", ")}` : "", g.offline.length ? "warn" : "ok") : null,
      s ? kpi("Wall PCs", `${s.walls.online} / ${s.walls.total}`, "", s.walls.online < s.walls.total ? "warn" : "ok") : null);
    const map = mapCard(b, sid, key);
    root.replaceChildren(
      e("header", "b-head", e("div", "b-title", b.name), e("div", "b-clock", new Date().toLocaleString([], { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }))),
      kpis,
      e("div", `b-main ${map ? "" : "no-map"}`, map ? e("div", "col-left", map, sideCard(b)) : e("div", "col-left", liveCard(b), sideCard(b)),
        e("div", "col-right", map ? liveCard(b) : null, alertsCard(b, sid, key))));
  }
  function clear() {
    if (livePlayer) { livePlayer.close(); livePlayer = null; livePath = ""; }
    const r = document.getElementById("board"); if (r) r.hidden = true;
    document.getElementById("grid").hidden = false;
  }
  function nudge() { if (livePlayer) livePlayer.nudge(); }
  return { draw, clear, nudge };
})();
