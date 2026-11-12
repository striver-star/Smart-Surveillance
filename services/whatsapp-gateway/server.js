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
"use strict";
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

let client = null;
function makeClient() {
  const c = new Client({
    authStrategy: new LocalAuth({ dataPath: process.env.HSS_WA_DATA || "/data" }),
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
  c.on("authenticated", () => log("authenticated"));
  c.on("auth_failure", (m) => setState("auth_failure", { last_error: String(m) }));
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
  if (restarting) return;
  restarting = true;
  try { if (client) await client.destroy(); } catch { /* already gone */ }
  setTimeout(() => { restarting = false; start(); }, delayMs);
}

async function start() {
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

module.exports = { normaliseNumber, server, state, setState };
