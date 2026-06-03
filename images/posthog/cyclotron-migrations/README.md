# Cyclotron migrations (vendored)

These are PostHog's `rust/cyclotron-core/migrations/` (the sqlx migration set used
by both the Rust cyclotron services and the Node v2 cyclotron in the plugin-server).

They are vendored here because the runtime PostHog images (`posthog/posthog`,
`posthog-node`, the cyclotron service images) do **not** ship sqlx or the
cyclotron migrations, so there is no in-image way to migrate the cyclotron /
cyclotron_node databases. The `posthog-cyclotron-migrate` image
(`Dockerfile.cyclotron-migrate`) bundles `sqlx-cli` + these files and is run as a
Helm pre-upgrade hook (`templates/hooks/cyclotron-migrate.job.yaml`).

Keep in sync with upstream:
  https://github.com/PostHog/posthog/tree/master/rust/cyclotron-core/migrations
