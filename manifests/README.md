# PostHog manifests (Flux and operators)

There are two independent profiles. **Use `manifests/hub-production` to reproduce hub-production.** `manifests/posthog` is a generic, smaller example with different ingress, images, resources and storage. Do not apply both: they use the same resource names. Neither a Git checkout nor an operator CR backs up application data.

## hub-production

The YAML profile records the working PostHog release and namespace configuration without credentials, status, controller bookkeeping or cluster-wide operator installations. Explicit digest pins strengthen the observed configuration without changing the selected application code.

- PostHog chart 0.22.4, OCI digest `sha256:d65943cdce3d349375dab1f485ac1f563bc1ed108f33f4ffe63301f926bdd434`, app source `8471862b083b25d3a11b97eb7730f21aa0cb4c7f`; images use individual observed digests, not an assumption that every component runs that source commit.
- Web, workers, exports and migration roles use verified `blitss` split images. Worker/beat/Temporal use `registry.streamloop.app/ghcr.io/blitss/posthog-worker` with digest `sha256:e4431263fde4f10e935b2da9f10bd293aa4ac06ce564de21c5c8033e91af8316`; exports uses `posthog-worker-exports` with digest `sha256:a35615349e3aa0f38050dbc06e2ccf4a70bd65d1e929e61ec5b5c6f0952b1e00`. The earlier `docker.io/posthog/posthog` locators were incorrect and depended on node caches. Their repository names were corrected with approval, without changing image digests or application code. [`image-provenance.json`](hub-production/image-provenance.json) records the verified GHCR origins and build revision `32253c7e9d511fb214ef2f8da83b29de7dde6f30`.
- Web requests 500m/2Gi and limits 8Gi; worker requests 500m/1Gi and limits 8Gi, with `CELERY_WORKER_CONCURRENCY=2`; beat requests 100m/512Mi and limits 6Gi; Temporal Django worker requests 500m/1Gi and limits 6Gi. Other chart settings inherit the pinned chart, not the generic profile's reduced resources.
- One CNPG PostgreSQL 16 instance, 20Gi; no explicit CPU/memory reservation in the observed CR. PostHog and persons both connect to database `posthog`. Bootstrap also creates `cyclotron`, `cyclotron_node`, `posthog_persons`, `behavioral_cohorts`, `ducklake`, `temporal`, and `temporal_visibility`; the existence of `posthog_persons` does not mean production uses it.
- One ClickHouse shard/replica (custom 26.6.2.158 image), requests 1 CPU/4Gi, limits 2 CPU/8Gi, 50Gi; one Keeper 25.3.6.10034.altinitystable, 5Gi. This is not HA. Runtime SQL schema and named collections require the deployment runner as well as manifests.
- One Redpanda v26.1.1 broker, 1 core/2Gi, 20Gi, plaintext internal Kafka on 9093, no SASL or external listeners. This intentionally differs from the generic v26.1.9 example.
- ECK Elasticsearch 8.17.3, one node, 10Gi, 2Gi memory, 1Gi JVM heap; internal HTTP without TLS. Temporal server 1.29.6, admin tools 1.31.0 and UI 2.50.0 are chart-managed, as are Redis and Valkey.
- External Cloudflare R2: `https://f7bb26785c99f3c0603872623fa23bdf.r2.cloudflarestorage.com`. AI blobs use bucket `posthog`, prefix `ai-blobs/aio/`, all teams. RustFS, SeaweedFS and MinIO servers are disabled; `externalSeaweedfs` is the session-recording S3 endpoint, not a deployed SeaweedFS service.
- `posthog.streamloop.app` uses Traefik `websecure`, `posthog-tls`, and the `/static/` cache/compression route. The retained post-renderer sets all web HTTP probes to **`/preflight`**. NetworkPolicies are disabled, as observed; do not describe this single-node internal-plaintext profile as a hardened HA deployment.
- The profile encodes the observed Deployment environment `CLICKHOUSE_LOGS_DATABASE=posthog` as `captureLogs.extraEnv`. This override exists in the running Deployment but not in the installed Helm values; the checker reports that difference so a fresh deployment preserves the runtime behavior.

PostgreSQL, Keeper, Elasticsearch, Redpanda and the Redpanda sidecar are pinned to the digests recorded in [`stateful-image-provenance.json`](hub-production/stateful-image-provenance.json), retaining their semantic version tags. CNPG uses `imageName`, Keeper its container image, ECK `spec.image` with `version` unchanged, and Redpanda the documented named-container `statefulset.podTemplate` merge override (not a nonexistent `image.digest` field). The evidence records observed running Pod imageIDs; it is not a claim that a later cluster still runs those bytes. Registry retention and database backups remain external prerequisites.

**These stateful pin-strengthening edits have not been applied to production.** Changing an image locator can roll stateful pods even when its digest identifies the same code. Do not bulk-apply the profile merely to correct worker repository names; schedule any stateful CR reconciliation separately. The alignment checker deliberately continues reporting the CR spec differences as drift while live CRs use tag-only locators. It does not silently waive drift based on a tag or a stale evidence file.

Browserless, GeoIP's Alpine init image, Redis and Valkey are also pinned to their observed digests in the profile, but their live Helm values still use tags. These unapplied locator changes likewise remain visible as drift. The profile reproduces the observed runtime selections; it is not a claim that the live declarative configuration already contains all of these pins.

### External prerequisites and install ordering

Install the existing cluster-wide operators and CRDs first; do not apply `manifests/infra` to an existing production cluster just to deploy this profile. [`hub-production/prerequisites.json`](hub-production/prerequisites.json) inventories the observed controller images, arguments, environment references and ConfigMap names; it is not an install manifest. Versions: Flux distribution 2.6.4 (helm-controller 1.3.0, source-controller 1.6.2, kustomize-controller 1.6.1), cert-manager 1.17.2, CNPG 1.29.0, Altinity ClickHouse/Keeper operator 0.26.1, Redpanda operator/chart 26.1.2, ECK 2.7.0, Traefik chart 26.0.0/image 2.10.6. Flux must support `helm.toolkit.fluxcd.io/v2`, `source.toolkit.fluxcd.io/v1` OCIRepository and `chartRef`; all corresponding CRDs/controllers must be ready. The `posthog/clickhouse-operator` HelmRelease must be Ready because PostHog explicitly depends on it. Production has no secretgen Password API; this profile does not require or install it.

The inventory also pins SHA-256 hashes of active operator ConfigMap files (ignoring packaged `.example`/`readme` files). Recreate them from the specified operator/chart versions and sources, then check their hashes; do not copy generated controller defaults into application manifests. The alignment checker checks these hashes and the operator workloads' images/arguments/environment, reporting any difference rather than overwriting platform configuration. The generic `manifests/infra` uses newer Altinity/ECK releases and is not an exact production bootstrap.

Other required platform configuration:

- A default dynamically provisioned ReadWriteOnce storage class with capacity for the requested PVCs; working cluster DNS and scheduling capacity for the chart's actual requests. PVCs and database backups are separate from this repository.
- Reachability and pull access to `registry.streamloop.app` (GHCR/Docker Hub mirror), GHCR, Docker Hub, Redpanda's registry and Elastic's registry. Any private mirror credentials belong in the platform's pull-secret/service-account configuration, not Git.
- Traefik CRDs/controller with entry point `websecure`; DNS `posthog.streamloop.app` points at it. A working `ClusterIssuer/letsencrypt-prod` must issue `posthog-tls`; its ACME account/DNS provider credentials are external. The namespaced self-signed issuer independently generates the RSA OIDC key.
- Existing R2 buckets and permissions for the object-storage operations used by PostHog, including bucket `posthog` for AI blobs and `posthog` session/object data. The chart does **not** provision buckets when RustFS is disabled. Configure R2 access before the first migration; don't assume a Helm hook creates external buckets.
- Reachability of `https://r2.streamloop.app/GeoIP2-City.mmdb` and an appropriate license for that database.

For a fresh environment, use the staged deployment runner rather than applying all resources in an unordered first pass. Its default is a plan; an explicit apply is required. See `scripts/deploy-hub-production.py --help`. Namespace and CNPG must exist before secret bootstrap; CRDs must exist before their CRs; bootstrap and certificate controllers must provide Secrets before dependent pods can start. Wait for stateful dependencies, run the forward-only migrations, then allow the PostHog HelmRelease to reconcile. A single root Kustomization does not encode these readiness dependencies. Flux users should represent the same ordering with separate Kustomizations and `dependsOn`/health checks.

### Secrets: preserve, never rotate implicitly

`posthog-secrets` remains **Helm-managed**. Switching a currently managed Secret to `existingSecret` can cause Helm to delete the previous resource during upgrade; this profile does not make that cutover. Four required `valuesFrom` references resolve the existing Secret's `object-storage-access-key`, `object-storage-secret-key`, `seaweedfs-access-key`, and `seaweedfs-secret-key` into chart values. There are no redaction markers or credentials in the deployable profile.

Run the bootstrap after CNPG creates `posthog-pg-app`:

```sh
python3 scripts/bootstrap-hub-production-secrets.py --context hub-production
# Fresh environment only: provide POSTHOG_R2_ACCESS_KEY_ID and
# POSTHOG_R2_SECRET_ACCESS_KEY through your secret manager's environment injection.
# Review the plan, then use the same command with --apply.
```

The helper reads Secret values only in memory, prints key names only, validates missing external R2 inputs, generates missing application signing/browserless/MCP/Valkey keys, derives missing database credentials from CNPG, and never replaces any existing key. Fresh `posthog-secrets` receives the exact Helm release ownership labels/annotations so the first Helm install can adopt it. Foreign-owned or immutable application Secrets and empty/redacted keys are rejected; optimistic concurrency prevents races from overwriting newly supplied keys. The helper separately preserves `posthog-clickhouse-password`, or creates a secure independent Secret when absent—no Helm ownership or secretgen controller is attached to that Secret. Run bootstrap before ClickHouse readiness and keep the PostHog HelmRelease suspended until complete. Plan mode performs read-only API calls, validates prerequisites, and changes nothing.

Other Secret producers are declared: CNPG creates `posthog-pg-app`, ECK creates `posthog-elastic-es-elastic-user`, and cert-manager creates `posthog-oidc-generated` and `posthog-tls`. Preserve/restore them and the independently bootstrapped ClickHouse Secret with database recovery where required. R2 credentials, external issuer configuration, image-pull credentials, existing data and backups are not generated by this repo.

Intentional differences from the original live snapshot: the OCI selector is strengthened from `=0.22.4` to its observed immutable digest; inline R2 credentials become required Secret references; install remediation changes from five uninstall/retry attempts to zero retries with `remediateLastFailure: false`; and the ClickHouse init script explicitly authenticates against `system` before creating `posthog`. It preserves the live SQL-created named collections and uses `IF NOT EXISTS`, avoiding duplicate XML/SQL definitions. None of these changes has been applied to production. Operator-managed/default fields are intentionally omitted from namespace manifests rather than copied as desired configuration.

### Read-only alignment check

Requirements: the tools pinned in `mise.toml`, plus `pip install -r requirements-ops.txt` in a private virtual environment. The checker never applies resources or reconciles Flux.

```sh
python3 scripts/check-hub-production.py --context hub-production
python3 scripts/check-hub-production.py \
  --snapshot-dir /path/to/sanitized-snapshots \
  --chart /path/to/unpacked-exact-production-chart
```

Live mode reads namespace resources, resolves Flux values references in memory and retrieves installed effective Helm values. It compares desired spec fields (ignoring extra admission defaults), the pinned chart defaults plus overrides, and Helm output including Kustomize post-renderers. It reports paths, never credential values. Rendering excludes generated Secret bodies because offline Helm lookup/random key generation is not evidence of drift. It is an alignment check, not a full workload/database health audit.

Offline snapshots are Kubernetes JSON/YAML objects or Lists named arbitrarily in the selected directory; include the HelmRelease, OCIRepository, Namespace, all profile CRs/ConfigMaps/Middlewares and sanitized referenced Secrets when available. Optional `helm-values.json` is sanitized `helm get values posthog -n posthog --all -o json`. Redaction markers are evidence only. Missing snapshots and secret equality that cannot be established are explicitly `UNVERIFIED`; they are never treated as proven alignment. Supply an unpacked exact chart with its vendored dependencies; offline mode makes no cluster or registry calls. Exit codes: **0** aligned, **1** drift, **2** incomplete evidence or error. Source-pin/credential-reference changes from the original live configuration remain visible rather than being whitelisted away.

### Hooks and recovery

`install.disableWait` and `upgrade.disableWait` skip Helm's normal workload readiness waiting, **not** hook execution/waiting. They avoid workloads waiting for post-install migration/bucket hooks while Helm waits for workloads. The enabled hooks in the selected chart are authoritative: external Kafka does not automatically imply that `kafka-init` is skipped. The create-buckets hook is for bundled RustFS, not external R2. CNPG `postInitApplicationSQL` only runs when initializing a new database cluster; changing that list is not a migration of an existing cluster.

Both installs and upgrades use `retries: 0` and `remediateLastFailure: false`: SQL/schema changes are forward-only; automatic Helm rollback does not undo them. Disabling fresh-install uninstall remediation also prevents a failed hook from deleting the newly adopted application Secret and stranding its required `valuesFrom` references. Do not use `helm rollback`, `--atomic`, or automatic uninstall remediation to recover migrated data. The runner owns compatibility migrations and forward recovery; backups are required before changes.

For application diagnostics, use the real web service and endpoint:

```sh
kubectl --context hub-production -n posthog port-forward svc/posthog-web 8000:8000
# In another terminal:
curl --fail http://127.0.0.1:8000/preflight
```

Preflight is not a substitute for topic, migration, SQL-consumer or Temporal checks. Validate Kafka with the broker/topic checks and an actual capture-to-ClickHouse event, not a version-specific preflight flag. Do not assert a fixed pod count or treat Flux Ready with workload waiting disabled as proof all workloads are healthy.

## Generic/local operator example

`manifests/infra` installs shared prerequisites for a new test cluster; `manifests/posthog` then installs namespace CRs and a separate generic HelmRelease. Install Flux, apply infra, wait for each operator and CRD to become ready, then apply `manifests/posthog`. For GitOps, use dependent Kustomizations; do not rely on applying the combined root twice. Customize the example's ingress host, reachable images and object-store configuration before installation. The root includes both phases for composition, not a readiness-aware installer.

The generic profile bundles RustFS through the chart but uses operator-managed ClickHouse/Keeper, PostgreSQL, Redpanda and Elasticsearch. Redis, Valkey and Temporal are chart-managed, so not every stateful service is operator-managed. `kind-values.local.yaml` is an optional local override, not part of either Kustomization. See the root README and `scripts/kind-bootstrap.sh --help` for the local cluster workflow.
