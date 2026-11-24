// Cloudflare Email Service <-> PostHog Conversations, by speaking Mailgun to PostHog.
//
// Inbound:  Email Routing -> email() -> signed Mailgun route form -> POST {POSTHOG_URL}/api/conversations/v1/email/capture
// Outbound: PostHog (MAILGUN_API_BASE=<this worker>/v3) -> fetch() -> send_email binding (raw MIME)
import PostalMime from "postal-mime";
import { EmailMessage } from "cloudflare:email";

// Mailgun's own verdict headers are what PostHog trusts for SPF/DKIM, so a sender must never set them.
const FORGEABLE = /^x-mailgun-/i;

export default {
  async email(message, env) {
    const raw = new Uint8Array(await new Response(message.raw).arrayBuffer());
    const form = await buildForm(raw, message.from, message.to, env.MAILGUN_SIGNING_KEY);
    const res = await fetch(`${env.POSTHOG_URL.replace(/\/$/, "")}/api/conversations/v1/email/capture`, {
      method: "POST",
      body: form,
    });
    // Mailgun contract: 2xx accepted, 406 rejected for good, anything else retried.
    if (res.status === 406) return message.setReject("Rejected by PostHog");
    if (!res.ok) throw new Error(`PostHog ${res.status}: ${(await res.text()).slice(0, 300)}`);
  },

  async fetch(request, env) {
    if (!authorized(request, env.MAILGUN_API_KEY)) return json({ message: "Forbidden" }, 401);
    const path = new URL(request.url).pathname.replace(/\/$/, "");
    const m = path.match(/^\/v3\/(?:domains(?:\/([^/]+)(\/verify)?)?|([^/]+)\/messages\.mime)$/);
    if (!m) return json({ message: "Not found" }, 404);
    const [, domain, , sendDomain] = m;

    if (sendDomain && request.method === "POST") return sendMime(await request.formData(), env);
    // Domain management: Cloudflare onboarding is done once in the dashboard, so report every domain active.
    if (!domain && request.method === "GET") return json({ items: [], total_count: 0 });
    if (request.method === "DELETE") return json({ message: "Domain deleted" });
    const name = domain || (await request.formData()).get("name");
    return json({ domain: { id: name, name, state: "active" }, sending_dns_records: [] });
  },
};

async function sendMime(form, env) {
  const mime = form.get("message");
  const recipients = form.getAll("to");
  if (!mime || !recipients.length) return json({ message: "message and to are required" }, 400);
  const raw = await mime.text();
  const fromHeader = (raw.match(/^From:\s*(.+(?:\r?\n[ \t].+)*)/im) || [])[1] || "";
  const from = (fromHeader.match(/<([^>]+)>/) || [, fromHeader.trim()])[1];
  let id = "";
  try {
    for (const to of recipients) id = (await env.EMAIL.send(new EmailMessage(from, to, raw))).messageId || id;
  } catch (e) {
    // PostHog retries 429/5xx and gives up on other 4xx.
    const permanent = /E_(SENDER|RECIPIENT|FIELD|HEADER|CONTENT|MESSAGE)/.test(e.code || "");
    return json({ message: `${e.code || "error"}: ${e.message}` }, permanent ? 400 : 502);
  }
  return json({ id, message: "Queued. Thank you." });
}

export async function buildForm(raw, envelopeFrom, envelopeTo, signingKey, now = Date.now()) {
  const mail = await PostalMime.parse(raw);
  const headers = mail.headers.filter((h) => !FORGEABLE.test(h.key));
  const first = (k) => headers.find((h) => h.key === k.toLowerCase())?.value || "";

  const form = new FormData();
  const set = (k, v) => v && form.set(k, v);
  set("recipient", envelopeTo);
  set("sender", envelopeFrom);
  set("from", first("from"));
  set("subject", mail.subject || "");
  for (const k of ["To", "Cc", "Date", "Message-Id", "In-Reply-To", "References", "Reply-To"]) set(k, first(k));
  set("body-plain", mail.text || "");
  set("body-html", mail.html || "");
  set("stripped-text", stripQuotedText(mail.text || ""));
  set("stripped-html", stripQuotedHtml(mail.html || ""));

  const { spf, dkim } = authResults(headers);
  const mailgunHeaders = headers.map((h) => [h.originalKey || h.key, h.value]);
  mailgunHeaders.push(["X-Mailgun-Spf", spf ? "Pass" : "Fail"], ["X-Mailgun-Dkim-Check-Result", dkim ? "Pass" : "Fail"]);
  form.set("message-headers", JSON.stringify(mailgunHeaders));

  (mail.attachments || []).slice(0, 20).forEach((a, i) => {
    form.set(`attachment-${i + 1}`, new File([a.content], a.filename || `attachment-${i + 1}`, { type: a.mimeType }));
  });

  const timestamp = String(Math.floor(now / 1000));
  const token = crypto.randomUUID().replace(/-/g, "");
  form.set("timestamp", timestamp);
  form.set("token", token);
  form.set("signature", await hmacHex(signingKey, timestamp + token));
  return form;
}

// Only the topmost Authentication-Results added by Cloudflare counts; lower copies came with the message.
export function authResults(headers) {
  const ar = headers.find((h) => h.key === "authentication-results");
  if (!ar || !/^\s*[^;]*cloudflare/i.test(ar.value)) return { spf: false, dkim: false };
  return { spf: /\bspf=pass\b/i.test(ar.value), dkim: /\bdkim=pass\b/i.test(ar.value) };
}

// ponytail: heuristic quote cut (Gmail/Outlook/Apple patterns); swap for a real reply parser if replies look wrong.
export function stripQuotedText(text) {
  const lines = text.split(/\r?\n/);
  const cut = lines.findIndex(
    (l, i) =>
      /^On .+wrote:\s*$/.test(l) ||
      (/^On .+/.test(l) && /wrote:\s*$/.test(lines[i + 1] || "")) ||
      /^-{2,}\s*Original Message\s*-{2,}/i.test(l) ||
      /^From: .+/.test(l) && /^(Sent|Date): /.test(lines[i + 1] || "") ||
      (/^>/.test(l) && lines.slice(i).every((x) => /^>|^\s*$/.test(x)))
  );
  return (cut === -1 ? text : lines.slice(0, cut).join("\n")).trim();
}

export function stripQuotedHtml(html) {
  const m = html.search(/<(div|blockquote)[^>]+(class="gmail_quote|id="divRplyFwdMsg|id="appendonsend|type="cite")/i);
  return m === -1 ? html : html.slice(0, m);
}

async function hmacHex(key, data) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(data));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function authorized(request, key) {
  const [scheme, b64] = (request.headers.get("Authorization") || "").split(" ");
  return scheme === "Basic" && !!key && b64 === btoa(`api:${key}`);
}

const json = (body, status = 200) => Response.json(body, { status });
