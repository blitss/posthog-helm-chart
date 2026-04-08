# PostHog Bundle

Standalone PostHog bundle for running the local Helm chart on another cluster.

What this repo contains:

- `charts/posthog`: the Helm chart
- `images/clickhouse/Dockerfile`: custom ClickHouse image with PostHog UDFs
- `vendor/posthog/user_scripts`: vendored upstream PostHog UDF assets
- `vendor/posthog/docker/clickhouse/user_defined_function.xml`: vendored upstream ClickHouse UDF registration file
- `manifests/kubeblocks`: KubeBlocks core addon wiring for ClickHouse and PostgreSQL
- `manifests/posthog`: example KubeBlocks clusters for ClickHouse and PostgreSQL
- `.github/workflows/publish-posthog-artifacts.yaml`: publishes the chart to GHCR OCI and builds the custom ClickHouse image
- `.github/workflows/sync-posthog-user-scripts.yaml`: syncs `posthog/user_scripts` and `docker/clickhouse/user_defined_function.xml` from upstream PostHog

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

That second apply now does all of:

- creates the `posthog` namespace
- provisions ClickHouse and PostgreSQL clusters
- relies on KubeBlocks-generated account secrets for ClickHouse and PostgreSQL
- bootstraps the `posthog`, `cyclotron`, `temporal`, and `temporal_visibility` databases
- creates a Flux `OCIRepository` for the chart
- creates a Flux `HelmRelease` that deploys PostHog from GHCR OCI

3. Adjust the example values file:

- set `ingress.hostname`
- replace the R2 placeholders in `manifests/posthog/release.yaml`
- create your own `posthog-oidc` Secret from `manifests/posthog/oidc-secret.example.yaml`
- if you rename the KubeBlocks clusters, update the generated secret references in `manifests/posthog/release.yaml`

## Local kind

For local chart testing with the split PostHog images, use the bootstrap script:

```bash
./scripts/kind-bootstrap.sh --recreate
```

What it does:

- creates a single-node kind cluster from `kind-config.local.yaml`
- writes containerd mirror config for `docker.io` and `ghcr.io`
- points both registries at `https://registry.streamloop.app/docker.io` and `https://registry.streamloop.app/ghcr.io`
- loads any locally built `local/posthog-*` images into the cluster

If you also want the script to install the chart with the local values file:

```bash
./scripts/kind-bootstrap.sh --recreate --install-posthog
```

Notes:

- `manifests/posthog/kind-values.local.yaml` is the local chart override file
- that local values file rewrites Kafka to `docker.io/redpandadata/redpanda` so it also goes through the Docker Hub mirror path
- the split PostHog images still need to exist locally if you want the local install to succeed

## Notes

- ClickHouse defaults to KubeBlocks. The chart does not assume an in-chart ClickHouse deployment path for this bundle.
- The example keeps Redis, Kafka, MinIO, SeaweedFS, Elasticsearch, and Temporal inside the chart so only PostgreSQL is additionally externalized in values.
- `posthog-clickhouse-component-version.yaml` is the important reproducibility bit: it binds the custom KubeBlocks service version `25.9.7-posthog.1` to the ClickHouse image published by this repo.
- The image binding lives in `manifests/kubeblocks/posthog-clickhouse-component-version.yaml`.
  - `images.clickhouse` controls the main ClickHouse component container image.
  - `images.memberJoin`, `images.memberLeave`, `images.role-probe`, and `images.switchover` control the Keeper kbagent/action image path.
  - The live KubeBlocks Keeper main `clickhouse` container still uses the addon default `apecloud/clickhouse` image unless you customize the addon/component-definition layer further.
- The ClickHouse Dockerfile no longer depends on `posthog/posthog`; it copies vendored files from `vendor/posthog/user_scripts` and uses the upstream source-of-truth registration file from `vendor/posthog/docker/clickhouse/user_defined_function.xml`.
- KubeBlocks generates the credential secrets used by the bundle.
  - ClickHouse admin secret follows the standard pattern `<cluster>-<component>-account-admin`, which is `posthog-ch-clickhouse-account-admin` in the example.
  - PostgreSQL postgres superuser secret follows `<cluster>-<component>-account-postgres`, which is `posthog-pg-postgresql-account-postgres` in the example.
- The PostHog release manifest uses direct `docker.io` / `ghcr.io` image references and generic placeholder infrastructure values.
- `release.yaml` currently uses `posthog.example.com` as the ingress host. Change it before applying if you want a real hostname.
