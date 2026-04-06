# PostHog Bundle

Standalone PostHog bundle for running the local Helm chart on another cluster.

What this repo contains:

- `charts/posthog`: the Helm chart
- `images/clickhouse/Dockerfile`: custom ClickHouse image with PostHog UDFs
- `manifests/kubeblocks`: KubeBlocks core addon wiring for ClickHouse and PostgreSQL
- `manifests/posthog`: example KubeBlocks clusters for ClickHouse and PostgreSQL
- `.github/workflows/publish-posthog-artifacts.yaml`: publishes the chart to GHCR OCI and builds the custom ClickHouse image

## Publish targets

- Chart OCI: `oci://ghcr.io/blitss/charts/posthog`
- Image: `ghcr.io/blitss/posthog-clickhouse`

## Quick start

1. Install KubeBlocks and database addons:

```bash
kubectl apply -k manifests/kubeblocks
```

2. Create the `posthog` namespace and external databases:

```bash
kubectl apply -k manifests/posthog
```

3. Adjust the example values file:

- set `ingress.hostname`
- set `externalPostgresql.url`
- set `externalPostgresql.personsUrl`
- set `externalPostgresql.cyclotronUrl`
- set `externalPostgresql.password`
- replace `manifests/posthog/clickhouse-admin-secret.example.yaml` before applying if you change the default ClickHouse admin secret

4. Install PostHog:

```bash
helm upgrade --install posthog ./charts/posthog \
  --namespace posthog \
  --create-namespace \
  -f charts/posthog/examples/values-kubeblocks-external.yaml
```

## Notes

- ClickHouse defaults to KubeBlocks. The chart does not assume an in-chart ClickHouse deployment path for this bundle.
- The example keeps Redis, Kafka, MinIO, SeaweedFS, Elasticsearch, and Temporal inside the chart so only PostgreSQL is additionally externalized in values.
- `clickhouse-component-version.yaml` is the important reproducibility bit: it binds KubeBlocks service version `25.9.7` to the custom image published by this repo.
- `clickhouse-admin-secret.example.yaml` is a placeholder. Replace `change-me` before applying.
