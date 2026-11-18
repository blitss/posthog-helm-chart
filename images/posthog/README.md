These Dockerfiles use `posthog/posthog` as an artifact source, not as the final
runtime base.

That distinction matters:

- `FROM posthog/posthog` and then deleting files does not reduce pull size, because
  the large upstream layers are still part of the final image history.
- These Dockerfiles instead copy only the required runtime artifacts out of the
  upstream image into a fresh slim base image.

Images in this directory:

- `Dockerfile.web`: Django + Granian + staticfiles and Playwright client; no local Chromium or ffmpeg.
- `Dockerfile.worker`: Celery core worker. Excludes the `exports` queue by default.
- `Dockerfile.worker-exports`: Celery `exports` worker using remote Browserless; no local browser/media tooling.
- `Dockerfile.migrate`: Django, persons SQL and ClickHouse schema migrations.
- `Dockerfile.cyclotron-migrate`: SQLx migrations for the retained Node Cyclotron database only.

Example builds:

```bash
docker build -f images/posthog/Dockerfile.web -t posthog-web .
docker build -f images/posthog/Dockerfile.worker -t posthog-worker .
docker build -f images/posthog/Dockerfile.worker-exports -t posthog-worker-exports .
docker build -f images/posthog/Dockerfile.migrate -t posthog-migrate .
```

The split Python images require the upstream Python 3.14.7 runtime layout
(November 2026, `f9239c187fe37db3755b9abfebfbcf46e288b32b`). Build all roles from the same immutable `POSTHOG_IMAGE` digest:

```bash
docker build \
  --build-arg POSTHOG_IMAGE=posthog/posthog@sha256:... \
  -f images/posthog/Dockerfile.web \
  -t posthog-web .
```

The image workflow accepts `posthog_image` (the full immutable upstream reference)
and `image_tag` (the published tag). All roles use the same pinned source.

The migration image runs the unmodified upstream migrations. The legacy
model-move command (#65) and the SCIM `ee.0058` backport (#66) are gone: upstream
fixed `ee.0058` (PostHog/posthog#101626), and the command only served databases
older than the September 2026 squash. Upgrade such a database with chart 0.23.x
(source `8471862b`) first.

Use the [guarded setup/upgrade runner](../../charts/posthog/README.md#guarded-hub-production-setup-and-upgrade)
for hub-production. The migration image's default CMD is not the complete
production migration sequence: the runner executes the chart's real
Django/product/persons/ClickHouse/async hooks and the separate Node SQLx image,
with application rollout held until those Jobs finish.

The repository also carries [`scripts/reconcile-clickhouse-logs.py`](../../scripts/reconcile-clickhouse-logs.py),
the staged storage-preserving #70 recovery. Run it inside this pinned migration
image, not a web/worker image. Absolute script paths work because it adds `/code`
and `/python-runtime` to its Python import path. The runner also explicitly sets
`PYTHONPATH=/code:/python-runtime`. Keep its private journal outside the container;
the deployment runner transfers it after each phase. Never fake migration
history or substitute a snapshot rollback for completing genuine migrations.
