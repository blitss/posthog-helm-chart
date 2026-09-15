# Cyclotron migrations (vendored)

PostHog's Node Cyclotron SQLx migrations are vendored because runtime images
do not include the SQLx migration tooling. The retired Rust Cyclotron database
and migration set are no longer used.

`cyclotron-node-migrations/` serves `CYCLOTRON_NODE_DATABASE_URL`, used by the
CDP v2 worker/janitor and Hogflow consumers.

The `posthog-cyclotron-migrate` image (`Dockerfile.cyclotron-migrate`) bundles
`sqlx-cli` and the Node migration set, running `sqlx migrate run` through
`templates/hooks/cyclotron-migrate.job.yaml`.

The September image includes all 15 upstream Node migrations through
`20260821000001_add_conversion_watchers.sql`. Run them before upgrading Node
workers. Keep each SQLx `-- no-transaction` directive intact: concurrent indexes
must run outside a transaction. See [issue #69](https://github.com/blitss/posthog-helm-chart/issues/69).

Keep in sync with:
  https://github.com/PostHog/posthog/tree/master/rust/cyclotron-node-migrations
