"use strict";
const test = require("node:test");
const assert = require("node:assert");
process.env.HSS_WA_TOKEN = "t";
const { normaliseNumber, server, setState } = require("./server");

test("normaliseNumber keeps full international numbers only", () => {
  assert.equal(normaliseNumber("+234 801 234 5678"), "2348012345678");
  assert.equal(normaliseNumber("0801 234 5678"), null);
  assert.equal(normaliseNumber("abc"), null);
});

test("API needs the token and refuses to send before WhatsApp is linked", async () => {
  await new Promise((r) => server.listen(0, r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.equal((await fetch(`${base}/health`)).status, 200);
    assert.equal((await fetch(`${base}/status`)).status, 401);
    setState("qr");
    const r = await fetch(`${base}/send`, { method: "POST", headers: { Authorization: "Bearer t" },
      body: JSON.stringify({ to: "+2348012345678", text: "hi" }) });
    assert.equal(r.status, 503);
    assert.equal((await r.json()).status, "qr");
  } finally {
    server.close();
  }
});

test("watchdog re-injects, restarts, then gives up when ready never comes", () => {
  const { makeWatchdog } = require("./server");
  let now = 0, id = 0;
  const pending = new Map();
  const timers = {
    setTimeout: (fn, ms) => { pending.set(++id, { fn, at: now + ms }); return id; },
    clearTimeout: (t) => pending.delete(t),
  };
  const advance = (ms) => {
    now += ms;
    for (const [t, { fn, at }] of [...pending].sort((a, b) => a[1].at - b[1].at)) {
      if (at <= now && pending.has(t)) { pending.delete(t); fn(); }
    }
  };
  const calls = [];
  const w = makeWatchdog({ reinjectAfterMs: 60, restartAfterMs: 180, maxRestarts: 2, timers,
    reinject: () => calls.push("reinject"), restart: (n) => calls.push(`restart ${n}`),
    giveUp: (n) => calls.push(`give up after ${n}`) });

  w.authenticated(); w.authenticated();          // the event often fires twice: one timer set only
  advance(60); advance(120);
  assert.deepEqual(calls, ["reinject", "restart 1"]);
  w.authenticated(); advance(180);
  w.authenticated(); advance(180);
  assert.deepEqual(calls, ["reinject", "restart 1", "reinject", "restart 2", "reinject", "give up after 2"]);

  w.ready();                                      // a later success resets the count
  assert.equal(w.restarts, 0);
  w.authenticated(); w.ready(); advance(500);
  assert.equal(calls[calls.length - 1], "give up after 2", "no action once ready");
});
