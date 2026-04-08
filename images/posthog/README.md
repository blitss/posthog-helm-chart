These Dockerfiles use `posthog/posthog` as an artifact source, not as the final
runtime base.

That distinction matters:

- `FROM posthog/posthog` and then deleting files does not reduce pull size, because
  the large upstream layers are still part of the final image history.
- These Dockerfiles instead copy only the required runtime artifacts out of the
  upstream image into a fresh slim base image.

Images in this directory:

- `Dockerfile.web`: Django + Granian + staticfiles. No Chromium, Playwright, or ffmpeg.
- `Dockerfile.worker`: Celery core worker. Excludes the `exports` queue by default.
- `Dockerfile.worker-exports`: Celery worker for the `exports` queue. Keeps browser/media tooling.
- `Dockerfile.migrate`: Python-only image for Django and ClickHouse schema migrations.
- `Dockerfile.bootstrap-clickhouse`: tiny helper image for the ClickHouse bootstrap hook.

Example builds:

```bash
docker build -f images/posthog/Dockerfile.web -t posthog-web .
docker build -f images/posthog/Dockerfile.worker -t posthog-worker .
docker build -f images/posthog/Dockerfile.worker-exports -t posthog-worker-exports .
docker build -f images/posthog/Dockerfile.migrate -t posthog-migrate .
docker build -f images/posthog/Dockerfile.bootstrap-clickhouse -t posthog-bootstrap-clickhouse .
```

All Dockerfiles accept `POSTHOG_IMAGE` as a build arg if you want to pin an
upstream tag or digest:

```bash
docker build \
  --build-arg POSTHOG_IMAGE=posthog/posthog@sha256:... \
  -f images/posthog/Dockerfile.web \
  -t posthog-web .
```
