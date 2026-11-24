// node --test test.mjs — stubs `cloudflare:email`, checks the form PostHog will verify and the Mailgun API shim.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { register } from "node:module";

register(
  "data:text/javascript," +
    encodeURIComponent(`export async function resolve(s, c, n) {
      return s === "cloudflare:email" ? { url: "data:text/javascript,export class EmailMessage{constructor(f,t,r){Object.assign(this,{f,t,r})}}", shortCircuit: true } : n(s, c);
    }`)
);
const { default: worker, buildForm, stripQuotedText } = await import("./src/index.js");

const raw = new TextEncoder().encode(
  [
    "Authentication-Results: mx.cloudflare.net; spf=pass smtp.mailfrom=alice@example.com; dkim=pass header.d=example.com",
    "Authentication-Results: evil.example; spf=fail",
    "X-Mailgun-Spf: Pass",
    "DKIM-Signature: v=1; d=example.com; h=from:subject; b=x",
    "From: Alice <alice@example.com>",
    "To: team-abc123@support.streamloop.app",
    "Subject: Help",
    "Message-ID: <m1@example.com>",
    "Content-Type: text/plain; charset=utf-8",
    "",
    "Need help.",
    "",
    "On Mon, Nov 23, 2026 at 10:00 AM Bob <bob@x.com> wrote:",
    "> old",
    "",
  ].join("\r\n")
);

test("signed Mailgun form, forged verdicts stripped", async () => {
  const form = await buildForm(raw, "alice@example.com", "team-abc123@support.streamloop.app", "k");
  const expected = createHmac("sha256", "k").update(form.get("timestamp") + form.get("token")).digest("hex");
  assert.equal(form.get("signature"), expected);
  assert.equal(form.get("recipient"), "team-abc123@support.streamloop.app");
  assert.equal(form.get("Message-Id"), "<m1@example.com>");
  assert.equal(form.get("stripped-text"), "Need help.");
  assert.equal(form.get("X-Mailgun-Spf"), null);
  const hs = JSON.parse(form.get("message-headers"));
  const spf = hs.filter(([k]) => k.toLowerCase() === "x-mailgun-spf");
  assert.deepEqual(spf, [["X-Mailgun-Spf", "Pass"]]); // ours, from Cloudflare's AR, not the sender's
  assert.ok(hs.some(([k]) => k.toLowerCase() === "dkim-signature"));
});

test("sender-supplied Authentication-Results on top is not trusted", async () => {
  const forged = new TextEncoder().encode("Authentication-Results: evil; spf=pass\r\nFrom: a@b.c\r\nSubject: x\r\nMessage-ID: <x@b.c>\r\n\r\nx");
  const hs = JSON.parse((await buildForm(forged, "a@b.c", "t@d", "k")).get("message-headers"));
  assert.deepEqual(hs.filter(([k]) => k === "X-Mailgun-Spf"), [["X-Mailgun-Spf", "Fail"]]);
});

test("quote stripping", () => {
  assert.equal(stripQuotedText("hi\n\n> a\n> b\n"), "hi");
  assert.equal(stripQuotedText("hi\n> inline quote\nreply"), "hi\n> inline quote\nreply");
});

test("Mailgun API shim", async () => {
  const env = { MAILGUN_API_KEY: "s", EMAIL: { sent: [], async send(m) { this.sent.push(m); return { messageId: "<id>" }; } } };
  const auth = { Authorization: "Basic " + btoa("api:s") };
  assert.equal((await worker.fetch(new Request("https://w/v3/domains/x.com"), env)).status, 401);
  const v = await (await worker.fetch(new Request("https://w/v3/domains/x.com/verify", { method: "PUT", headers: auth }), env)).json();
  assert.equal(v.domain.state, "active");
  const fd = new FormData();
  fd.append("to", "c1@y.com");
  fd.append("to", "c2@y.com");
  fd.set("message", new File(["From: Support <help@x.com>\r\nTo: c1@y.com\r\nSubject: Re\r\n\r\nhi"], "message.mime"));
  const r = await worker.fetch(new Request("https://w/v3/x.com/messages.mime", { method: "POST", headers: auth, body: fd }), env);
  assert.equal(r.status, 200);
  assert.deepEqual(env.EMAIL.sent.map((m) => [m.f, m.t]), [["help@x.com", "c1@y.com"], ["help@x.com", "c2@y.com"]]);
});
