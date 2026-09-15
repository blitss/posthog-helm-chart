# Cyclotron migrations (vendored)

PostHog's Node Cyclotron SQLx migrations are vendored because runtime images
do not include the SQLx migration tooling. The retired Rust Cyclotron database
and migration set are no longer used.

`cyclotron-node-migrations/` serves `CYCLOTRON_NODE_DATABASE_URL`, used by the
CDP v2 worker/janitor and Hogflow consumers.

The `posthog-cyclotron-migrate` image (`Dockerfile.cyclotron-migrate`) bundles
`sqlx-cli` and the Node migration set, running `sqlx migrate run` through
`templates/hooks/cyclotron-migrate.job.yaml`.

Keep in sync with:
  https://github.com/PostHog/posthog/tree/master/rust/cyclotron-node-migrations
