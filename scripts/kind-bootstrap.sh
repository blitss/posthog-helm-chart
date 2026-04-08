#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CLUSTER_NAME="${KIND_CLUSTER_NAME:-posthog-test}"
KIND_CONFIG="${KIND_CONFIG:-${REPO_ROOT}/kind-config.local.yaml}"
VALUES_FILE="${VALUES_FILE:-${REPO_ROOT}/manifests/posthog/kind-values.local.yaml}"
NAMESPACE="${POSTHOG_NAMESPACE:-posthog-kind}"
RELEASE_NAME="${POSTHOG_RELEASE_NAME:-posthog-kind}"
MIRROR_HOST="${MIRROR_HOST:-REDACTED_MIRROR_HOST}"
RECREATE=0
INSTALL_POSTHOG=0
LOAD_LOCAL_IMAGES=1

LOCAL_IMAGES=(
  "local/posthog-migrate:test"
  "local/posthog-web:test"
  "local/posthog-worker:test"
  "local/posthog-worker-exports:test"
)

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Creates a local kind cluster configured to pull docker.io and ghcr.io images
through ${MIRROR_HOST}, and optionally loads the local PostHog split images and
installs the chart.

Options:
  --cluster-name NAME     kind cluster name (default: ${CLUSTER_NAME})
  --kind-config PATH      kind config file (default: ${KIND_CONFIG})
  --values PATH           values file for optional Helm install (default: ${VALUES_FILE})
  --recreate              delete any existing cluster with the same name first
  --skip-load-images      do not load local posthog images into kind
  --install-posthog       run helm upgrade --install after cluster creation
  --mirror-host HOST      mirror host prefix (default: ${MIRROR_HOST})
  --help                  show this message
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "missing required command: ${cmd}" >&2
    exit 1
  fi
}

kind_cluster_exists() {
  kind get clusters | grep -Fxq "${CLUSTER_NAME}"
}

write_hosts_toml() {
  local node="$1"
  local registry="$2"
  local upstream="$3"
  local mirror_path="$4"
  local registry_dir="/etc/containerd/certs.d/${registry}"

  docker exec "${node}" mkdir -p "${registry_dir}"
  cat <<EOF | docker exec -i "${node}" cp /dev/stdin "${registry_dir}/hosts.toml"
server = "${upstream}"

[host."https://${MIRROR_HOST}/${mirror_path}"]
  capabilities = ["pull", "resolve"]
  override_path = true
EOF
}

configure_node_mirrors() {
  local node
  while IFS= read -r node; do
    write_hosts_toml "${node}" "docker.io" "https://registry-1.docker.io" "v2/docker.io"
    write_hosts_toml "${node}" "registry-1.docker.io" "https://registry-1.docker.io" "v2/docker.io"
    write_hosts_toml "${node}" "ghcr.io" "https://ghcr.io" "v2/ghcr.io"
    write_hosts_toml "${node}" "docker.redpanda.com" "https://docker.redpanda.com" "v2/docker.redpanda.com"
  done < <(kind get nodes --name "${CLUSTER_NAME}")
}

load_local_images() {
  local available=()
  local image

  for image in "${LOCAL_IMAGES[@]}"; do
    if docker image inspect "${image}" >/dev/null 2>&1; then
      available+=("${image}")
    fi
  done

  if [[ "${#available[@]}" -eq 0 ]]; then
    echo "no local posthog images found, skipping kind load" >&2
    return 0
  fi

  kind load docker-image "${available[@]}" --name "${CLUSTER_NAME}"
}

install_posthog() {
  helm upgrade --install "${RELEASE_NAME}" "${REPO_ROOT}/charts/posthog" \
    -n "${NAMESPACE}" \
    --create-namespace \
    -f "${VALUES_FILE}"
}

while [[ "${#}" -gt 0 ]]; do
  case "$1" in
    --cluster-name)
      CLUSTER_NAME="$2"
      shift 2
      ;;
    --kind-config)
      KIND_CONFIG="$2"
      shift 2
      ;;
    --values)
      VALUES_FILE="$2"
      shift 2
      ;;
    --mirror-host)
      MIRROR_HOST="$2"
      shift 2
      ;;
    --recreate)
      RECREATE=1
      shift
      ;;
    --skip-load-images)
      LOAD_LOCAL_IMAGES=0
      shift
      ;;
    --install-posthog)
      INSTALL_POSTHOG=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_cmd docker
require_cmd kind
require_cmd kubectl
if [[ "${INSTALL_POSTHOG}" -eq 1 ]]; then
  require_cmd helm
fi

if [[ ! -f "${KIND_CONFIG}" ]]; then
  echo "kind config not found: ${KIND_CONFIG}" >&2
  exit 1
fi

if [[ "${RECREATE}" -eq 1 ]] && kind_cluster_exists; then
  kind delete cluster --name "${CLUSTER_NAME}"
fi

if ! kind_cluster_exists; then
  kind create cluster --name "${CLUSTER_NAME}" --config "${KIND_CONFIG}"
fi

configure_node_mirrors

if [[ "${LOAD_LOCAL_IMAGES}" -eq 1 ]]; then
  load_local_images
fi

if [[ "${INSTALL_POSTHOG}" -eq 1 ]]; then
  install_posthog
fi

echo "kind cluster ready: ${CLUSTER_NAME}"
