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

1. Install KubeBlocks, database addons, and the ClickHouse image binding:

```bash
kubectl apply -k manifests/kubeblocks
```

2. Create the `posthog` namespace and external databases:

```bash
kubectl apply -k manifests/posthog
```

Or equivalently:

```bash
kubectl apply -k manifests
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
- The image binding lives in `manifests/kubeblocks/clickhouse-component-version.yaml`.
  - `images.clickhouse` controls the main ClickHouse component container image.
  - `images.memberJoin`, `images.memberLeave`, `images.role-probe`, and `images.switchover` control the Keeper kbagent/action image path.
  - The live KubeBlocks Keeper main `clickhouse` container still uses the addon default `apecloud/clickhouse` image unless you customize the addon/component-definition layer further.
- `clickhouse-admin-secret.example.yaml` is a placeholder. Replace `change-me` before applying.
