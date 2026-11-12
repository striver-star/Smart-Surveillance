// HSS WhatsApp gateway (provider A): sends messages and documents from the dedicated site number.
// Built on whatsapp-web.js (Apache 2.0), which drives WhatsApp Web in a headless Chromium.
// Linking: run `docker compose logs -f whatsapp` and scan the QR code with the dedicated phone
// (WhatsApp > Linked devices > Link a device). The session is kept in /data, so this is done once.
//
// API (internal network only, bearer token HSS_WA_TOKEN):
//   GET  /health                 {status}                     no token, for container health checks
//   GET  /status                 {status, since, me, last_error}
//   POST /send                   {to:"+234...", text, document?:{filename, mimetype, base64}} -> {id}
//   GET  /messages/<id>          {id, ack}  ack: pending | sent | delivered | read | error
//
// Ready watchdog: whatsapp-web.js sometimes logs "authenticated" but never "ready" (its helper code
// fails to load into a changed WhatsApp Web build, and the error is swallowed). The gateway logs the
// page's errors, re-runs the injection after HSS_WA_REINJECT_S (60 s), restarts the session after
// HSS_WA_RESTART_S (180 s), and after HSS_WA_MAX_RESTARTS (3) failed restarts stops in state "stuck"
// so that it doesn't hammer WhatsApp; the platform then alerts the IT Manager.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const QRCode = require("qrcode");

const PORT = Number(process.env.PORT || 3000);
const TOKEN = process.env.HSS_WA_TOKEN || "";
const MAX_BODY = 25 * 1024 * 1024; // documents up to about 18 MB after base64
const ACK = { "-1": "error", 0: "pending", 1: "sent", 2: "delivered", 3: "read", 4: "played" };

const log = (...a) => console.log(new Date().toISOString(), ...a);
const state = { status: "starting", since: new Date().toISOString(), me: null, last_error: null };
const acks = new Map(); // message id -> ack name (kept for the last 5000 messages)

function setState(status, extra = {}) {
  Object.assign(state, { status, since: new Date().toISOString() }, extra);
  log(`state: ${status}${extra.last_error ? ` (${extra.last_error})` : ""}`);
}

/** "+234 801 234 5678" -> "2348012345678"; null when it is not a full international number. */
function normaliseNumber(raw) {
  const digits = String(raw || "").replace(/[^\d]/g, "");
  return /^[1-9]\d{7,14}$/.test(digits) ? digits : null;
}

/**
 * Watches the gap between "authenticated" and "ready". Timers and actions are injected for tests.
 */
function makeWatchdog({ reinjectAfterMs, restartAfterMs, maxRestarts, reinject, restart, giveUp,
                        timers = { setTimeout, clearTimeout } }) {
  let t1 = null, t2 = null, restarts = 0;
  const clear = () => { if (t1) timers.clearTimeout(t1); if (t2) timers.clearTimeout(t2); t1 = t2 = null; };
  return {
    get restarts() { return restarts; },
    get waiting() { return t2 !== null; },
    authenticated() {
      if (t2) return;                     // already waiting (the event often fires twice)
      t1 = timers.setTimeout(() => { t1 = null; reinject(); }, reinjectAfterMs);
      t2 = timers.setTimeout(() => {
        clear();
        restarts += 1;
        if (restarts > maxRestarts) giveUp(restarts - 1); else restart(restarts);
      }, restartAfterMs);
    },
    ready() { clear(); restarts = 0; },
    stop: clear,
  };
}

const pageErrors = [];                    // last few errors from the WhatsApp Web page
function notePageError(text) {
  const line = String(text).split("\n")[0].slice(0, 300);
  if (pageErrors[pageErrors.length - 1] === line) return;
  pageErrors.push(line);
  if (pageErrors.length > 5) pageErrors.shift();
  log(`page error: ${line}`);
}

const env = (k, d) => Number(process.env[k] || d);
const watchdog = makeWatchdog({
  reinjectAfterMs: env("HSS_WA_REINJECT_S", 60) * 1000,
  restartAfterMs: env("HSS_WA_RESTART_S", 180) * 1000,
  maxRestarts: env("HSS_WA_MAX_RESTARTS", 3),
  reinject: async () => {
    log("authenticated but not ready after 60 s: re-running the WhatsApp Web injection");
    try { await client.inject(); } catch (e) { notePageError(`inject: ${(e && e.message) || e}`); }
  },
  restart: (n) => {
    setState("restarting", { last_error: `authenticated but never ready (restart ${n}); ${pageErrors.slice(-1)[0] || "no page error seen"}` });
    restart(5000);
  },
  giveUp: (n) => {
    setState("stuck", { last_error: `authenticated but never ready after ${n} restarts. Last page errors: ${pageErrors.join(" | ") || "none"}. ` +
      "Fix: update whatsapp-web.js, or re-link (see docs/task-21-whatsapp.md). Restart the container to try again." });
    try { if (client) client.destroy(); } catch { /* gone */ }
  },
});

const DATA = process.env.HSS_WA_DATA || "/data";

/**
 * Remove Chromium's profile lock files left by an earlier container. Chromium ties the lock to the
 * host name, which changes on every rebuild, and then refuses to start ("profile appears to be in
 * use by another Chromium process ... on another computer"). Only one gateway uses /data, and no
 * browser is running when this is called, so the locks are always stale here.
 */
function clearStaleLocks(dataDir = DATA) {
  const removed = [];
  let dirs = [];
  try { dirs = fs.readdirSync(dataDir).filter((d) => d.startsWith("session")).map((d) => path.join(dataDir, d)); } catch { return removed; }
  for (const dir of dirs) {
    for (const name of ["SingletonLock", "SingletonSocket", "SingletonCookie"]) {
      const f = path.join(dir, name);
      try { fs.lstatSync(f); fs.rmSync(f, { force: true }); removed.push(f); } catch { /* not there */ }
    }
  }
  if (removed.length) log(`removed stale browser lock files: ${removed.map((f) => path.basename(f)).join(", ")}`);
  return removed;
}

let client = null;
let watchedPage = null;
function watchPage(c) {
  const page = c.pupPage;
  if (!page || page === watchedPage) return;
  watchedPage = page;
  page.on("pageerror", (e) => notePageError((e && e.message) || e));
  page.on("console", (m) => { if (m.type() === "error" && watchdog.waiting) notePageError(m.text()); });
}

function makeClient() {
  const c = new Client({
    authStrategy: new LocalAuth({ dataPath: DATA }),
    puppeteer: {
      executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium",
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    },
  });
  c.on("qr", async (qr) => {
    setState("qr");
    const art = await QRCode.toString(qr, { type: "terminal", small: true });
    console.log("\nLink the dedicated phone: WhatsApp > Linked devices > Link a device, then scan:\n" + art);
  });
  c.on("authenticated", () => { log("authenticated"); watchPage(c); watchdog.authenticated(); });
  c.on("loading_screen", (pct) => log(`loading ${pct}%`));
  c.on("change_state", (st) => log(`connection: ${st}`));
  c.on("auth_failure", (m) => setState("auth_failure", { last_error: String(m) }));
  c.on("ready", () => watchdog.ready());
  c.on("ready", () => setState("ready", { me: c.info && c.info.wid ? c.info.wid.user : null, last_error: null }));
  c.on("disconnected", (reason) => {
    setState("disconnected", { last_error: String(reason) });
    restart(10000);
  });
  c.on("message_ack", (msg, ack) => {
    acks.set(msg.id._serialized, ACK[ack] || String(ack));
    if (acks.size > 5000) acks.delete(acks.keys().next().value);
  });
  return c;
}

let restarting = false;
async function restart(delayMs) {
  if (restarting || state.status === "stuck") return;   // stuck: wait for a manual container restart
  restarting = true;
  try { if (client) await client.destroy(); } catch { /* already gone */ }
  setTimeout(() => { restarting = false; start(); }, delayMs);
}

async function start() {
  clearStaleLocks();
  client = makeClient();
  try {
    await client.initialize();
  } catch (e) {
    setState("error", { last_error: String((e && e.message) || e) });
    restart(30000);
  }
}

function json(res, code, body) {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(new Error("too large")); req.destroy(); } else chunks.push(c);
    });
    req.on("end", () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}")); } catch { reject(new Error("body must be JSON")); }
    });
    req.on("error", reject);
  });
}

async function send(body) {
  if (state.status !== "ready") return [503, { error: "WhatsApp is not connected", status: state.status }];
  const number = normaliseNumber(body.to);
  if (!number) return [422, { error: "to must be a full international number, e.g. +2348012345678" }];
  if (!body.text && !body.document) return [422, { error: "text or document is required" }];
  const id = await client.getNumberId(number);
  if (!id) return [422, { error: `${body.to} is not on WhatsApp` }];
  let msg;
  if (body.document) {
    const d = body.document;
    if (!d.base64 || !d.mimetype || !d.filename) return [422, { error: "document needs filename, mimetype and base64" }];
    const media = new MessageMedia(d.mimetype, d.base64, d.filename);
    msg = await client.sendMessage(id._serialized, media, { caption: body.text || "", sendMediaAsDocument: true });
  } else {
    msg = await client.sendMessage(id._serialized, String(body.text));
  }
  const mid = msg.id._serialized;
  acks.set(mid, ACK[msg.ack] || "pending");
  log(`sent ${body.document ? "document" : "text"} to ...${number.slice(-4)}: ${mid}`);
  return [200, { id: mid }];
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://gateway");
  if (url.pathname === "/health") return json(res, 200, { status: state.status });
  if (!TOKEN || req.headers.authorization !== `Bearer ${TOKEN}`) return json(res, 401, { error: "invalid token" });
  try {
    if (req.method === "GET" && url.pathname === "/status") return json(res, 200, state);
    if (req.method === "POST" && url.pathname === "/send") {
      const [code, body] = await send(await readBody(req));
      return json(res, code, body);
    }
    const m = url.pathname.match(/^\/messages\/(.+)$/);
    if (req.method === "GET" && m) {
      const id = decodeURIComponent(m[1]);
      return acks.has(id) ? json(res, 200, { id, ack: acks.get(id) }) : json(res, 404, { error: "unknown message" });
    }
    return json(res, 404, { error: "not found" });
  } catch (e) {
    log("error:", (e && e.message) || e);
    return json(res, 500, { error: String((e && e.message) || e) });
  }
});

if (require.main === module) {
  if (!TOKEN) log("warning: HSS_WA_TOKEN is not set; every API call except /health will be refused");
  server.listen(PORT, () => log(`listening on ${PORT}`));
  start();
  for (const sig of ["SIGTERM", "SIGINT"]) {
    process.on(sig, async () => { try { if (client) await client.destroy(); } finally { process.exit(0); } });
  }
}

module.exports = { normaliseNumber, server, state, setState, makeWatchdog, clearStaleLocks };
