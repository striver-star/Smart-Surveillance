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
