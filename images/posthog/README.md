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
- `Dockerfile.bootstrap-clickhouse`: tiny helper image for the ClickHouse bootstrap hook.

Example builds:

```bash
docker build -f images/posthog/Dockerfile.web -t posthog-web .
docker build -f images/posthog/Dockerfile.worker -t posthog-worker .
docker build -f images/posthog/Dockerfile.worker-exports -t posthog-worker-exports .
docker build -f images/posthog/Dockerfile.migrate -t posthog-migrate .
docker build -f images/posthog/Dockerfile.bootstrap-clickhouse -t posthog-bootstrap-clickhouse .
```

The split Python images require the September 2026 upstream Python 3.13.13
runtime layout. Build all roles from the same immutable `POSTHOG_IMAGE` digest:

```bash
docker build \
  --build-arg POSTHOG_IMAGE=posthog/posthog@sha256:... \
  -f images/posthog/Dockerfile.web \
  -t posthog-web .
```
