# Cyclotron migrations (vendored)

PostHog's cyclotron sqlx migrations, vendored because the runtime PostHog images
(`posthog/posthog`, `posthog-node`, the cyclotron service images) ship neither
sqlx nor these migrations — so there is no in-image way to migrate the
cyclotron / cyclotron_node databases.

Two **separate** sets (see upstream `rust/bin/migrate-entry`):

- `cyclotron-core/migrations/` — the Rust cyclotron (`CYCLOTRON_DATABASE_URL`).
  Upstream: `rust/cyclotron-core/migrations/`.
- `cyclotron-node-migrations/` — the Node v2 cyclotron used by the plugin-server
  (`CYCLOTRON_NODE_DATABASE_URL`: cdp-cyclotron-v2 worker/janitor, hogflow
  consumers). Different schema (adds person/distinct_id columns + indexes).
  Upstream: `rust/cyclotron-node-migrations/`.

The `posthog-cyclotron-migrate` image (`Dockerfile.cyclotron-migrate`) bundles
`sqlx-cli` + both sets and runs `sqlx migrate run` against each DB via the Helm
hook `templates/hooks/cyclotron-migrate.job.yaml`.

Keep in sync with:
  https://github.com/PostHog/posthog/tree/master/rust/cyclotron-core/migrations
  https://github.com/PostHog/posthog/tree/master/rust/cyclotron-node-migrations
