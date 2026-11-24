# Cloudflare Email for PostHog Conversations

A Cloudflare Worker that stands in for Mailgun. PostHog keeps its Mailgun code; nothing else changes.

- **Inbound:** Email Routing → `email()` → signed Mailgun route form → `POST {POSTHOG_URL}/api/conversations/v1/email/capture`.
  SPF/DKIM verdicts come only from Cloudflare's own topmost `Authentication-Results`; sender-supplied `X-Mailgun-*` headers are dropped.
- **Outbound replies:** PostHog calls `{MAILGUN_API_BASE}/{domain}/messages.mime` → Worker → `send_email` binding (raw MIME).
  Domain calls (`/v3/domains…`) answer "active": onboard sending domains once in Cloudflare instead.

Needs the `blitss/posthog-*` web/worker images, which make `MAILGUN_API_BASE` env-configurable.

## Setup

1. Cloudflare: onboard the reply domain under **Email Service → Email Sending**, and enable **Email Routing** on an inbound subdomain
   (for example `support.example.com`, so the apex MX stays untouched).
2. Deploy:
   ```bash
   npm install && npm test
   npx wrangler secret put MAILGUN_SIGNING_KEY   # random string, also set in PostHog
   npx wrangler secret put MAILGUN_API_KEY       # random string, also set in PostHog
   npx wrangler deploy                           # set vars.POSTHOG_URL in wrangler.jsonc first
   ```
3. Email Routing on the inbound subdomain: catch-all → **Send to a Worker** → `posthog-email`.
4. PostHog env (web and worker):
   ```yaml
   CONVERSATIONS_EMAIL_INBOUND_DOMAIN: support.example.com
   CONVERSATIONS_EMAIL_WEBHOOK_SIGNING_KEY: <MAILGUN_SIGNING_KEY>
   CONVERSATIONS_EMAIL_MAILGUN_API_KEY: <MAILGUN_API_KEY>
   MAILGUN_API_BASE: https://posthog-email.<account>.workers.dev/v3
   ```
5. Connect an email channel in PostHog Conversations and send a mail to its `team-…@support.example.com` address.
