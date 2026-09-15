#!/bin/bash
set -e

# Keep the chart and split image on the same non-root server contract. Unlike
# upstream bin/docker-server, Kubernetes has already selected the application UID.
pids=()
metrics_dir=
cleanup() {
    trap '' TERM INT
    if ((${#pids[@]})); then
        kill "${pids[@]}" 2>/dev/null || true
        wait "${pids[@]}" 2>/dev/null || true
    fi
    if [[ -n "$metrics_dir" ]]; then
        rm -rf "$metrics_dir"
    fi
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# Helm migration hooks own schema changes; do not serve until all checks pass.
while true; do
    ./bin/migrate-check &
    pids=("$!")
    if wait "${pids[0]}"; then
        break
    fi
    echo "Waiting for migrations to complete before starting web..."
    sleep 10 &
    pids=("$!")
    wait "${pids[0]}"
done
pids=()

# Fresh storage per container start prevents stale worker metrics after restarts.
metrics_dir=$(mktemp -d "${TMPDIR:-/tmp}/posthog-prometheus.XXXXXX")
export PROMETHEUS_MULTIPROC_DIR="$metrics_dir"
export PROMETHEUS_METRICS_EXPORT_PORT=8001
export STATSD_PORT=${STATSD_PORT:-8125}
export GRANIAN_INTERFACE=${GRANIAN_INTERFACE:-asgi}
export GRANIAN_HOST=${GRANIAN_HOST:-0.0.0.0}
export GRANIAN_PORT=${GRANIAN_PORT:-8000}
export GRANIAN_WORKERS=${GRANIAN_WORKERS:-4}
export GRANIAN_LOG_LEVEL=${GRANIAN_LOG_LEVEL:-warning}
export GRANIAN_LOG_ACCESS_ENABLED=${GRANIAN_LOG_ACCESS_ENABLED:-true}
export GRANIAN_RESPAWN_FAILED_WORKERS=${GRANIAN_RESPAWN_FAILED_WORKERS:-true}
export GRANIAN_METRICS_ENABLED=${GRANIAN_METRICS_ENABLED:-true}
export GRANIAN_METRICS_PORT=${GRANIAN_METRICS_PORT:-9090}

if [[ "$GRANIAN_INTERFACE" = wsgi ]]; then
    app_target=posthog.wsgi:application
else
    app_target=posthog.asgi:application
    export GRANIAN_LOOP=${GRANIAN_LOOP:-uvloop}
fi

python ./bin/granian_metrics.py &
pids=("$!")
granian "$app_target" &
pids+=("$!")
# Stay as PID 1 to forward termination, reap both children, and remove metrics
# only after the server stops. Failure of either process stops the other too.
wait -n "${pids[@]}"
