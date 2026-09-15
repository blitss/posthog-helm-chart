#!/usr/bin/env python3
"""Plan (default) or create missing hub-production Secret keys without rotation."""
import argparse
import base64
import json
import os
import re
import secrets
import subprocess
import sys
from urllib.parse import quote


GENERATED = {
    "posthog-secret": 56,
    "encryption-salt-keys": 32,
    "internal-api-secret": 48,
    "browserless-token": 64,
    "mcp-signed-state-key": 64,
    "valkey-password": 48,
}
STORAGE = {
    "object-storage-access-key": "POSTHOG_R2_ACCESS_KEY_ID",
    "object-storage-secret-key": "POSTHOG_R2_SECRET_ACCESS_KEY",
    "seaweedfs-access-key": "POSTHOG_R2_ACCESS_KEY_ID",
    "seaweedfs-secret-key": "POSTHOG_R2_SECRET_ACCESS_KEY",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig")
    parser.add_argument("--context")
    parser.add_argument("--namespace", default="posthog")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    command = ["kubectl"]
    for key in ("kubeconfig", "context"):
        if getattr(args, key):
            command += ["--" + key, getattr(args, key)]
    command += ["--namespace", args.namespace]

    def kubectl(*argv, payload=None):
        result = subprocess.run(command + list(argv), input=payload, text=True, capture_output=True)
        if result.returncode:
            # API errors can echo request bodies; never print stderr for Secret operations.
            raise RuntimeError("kubectl Secret operation failed; check access, context and resource state")
        return json.loads(result.stdout) if result.stdout.strip() else None

    clickhouse = kubectl("get", "secret", "posthog-clickhouse-password", "--ignore-not-found", "-o", "json")
    if clickhouse:
        password = base64.b64decode(clickhouse.get("data", {}).get("password", ""), validate=True).decode()
        if not password or any(marker in password.upper() for marker in ("[REQUIRED", "[REDACTED", "<REDACTED", "CHANGEME")):
            raise RuntimeError("Existing ClickHouse password is missing, empty or redacted; refusing rotation")

    current = kubectl("get", "secret", "posthog-secrets", "--ignore-not-found", "-o", "json")
    data = dict((current or {}).get("data", {}))
    metadata = (current or {}).get("metadata", {})
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})
    expected_annotations = {"meta.helm.sh/release-name": "posthog", "meta.helm.sh/release-namespace": args.namespace}
    if labels.get("app.kubernetes.io/managed-by", "Helm") != "Helm":
        raise RuntimeError("posthog-secrets is owned by another manager; refusing adoption")
    if any(annotations.get(k, v) != v for k, v in expected_annotations.items()) or metadata.get("ownerReferences"):
        raise RuntimeError("posthog-secrets belongs to another release/controller; refusing adoption")
    if (current or {}).get("immutable"):
        raise RuntimeError("posthog-secrets is immutable; Helm cannot safely manage it")
    required = set(GENERATED) | set(STORAGE) | {"database-url", "redis-url", "postgresql-password"}
    for key in required & data.keys():
        value = base64.b64decode(data[key], validate=True).decode()
        if not value or any(marker in value.upper() for marker in ("[REQUIRED", "[REDACTED", "<REDACTED", "CHANGEME")):
            raise RuntimeError(f"Existing key {key} is empty or redacted; refusing to replace it")
    missing = required - data.keys()
    additions = {}
    # A partial storage pair may reuse the existing equivalent pair, never overwrite it.
    aliases = {"object-storage-access-key": "seaweedfs-access-key", "object-storage-secret-key": "seaweedfs-secret-key", "seaweedfs-access-key": "object-storage-access-key", "seaweedfs-secret-key": "object-storage-secret-key"}
    for key in sorted(missing & STORAGE.keys()):
        if aliases[key] in data:
            additions[key] = base64.b64decode(data[aliases[key]], validate=True).decode()
        else:
            value = os.environ.get(STORAGE[key], "")
            length = 32 if key.endswith("access-key") else 64
            if not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value):
                raise RuntimeError(f"Missing {key}: supply valid {STORAGE[key]} via environment ({length} hexadecimal characters)")
            additions[key] = value
    if missing & {"database-url", "postgresql-password"}:
        pg = kubectl("get", "secret", "posthog-pg-app", "--ignore-not-found", "-o", "json")
        if not pg or not all(pg.get("data", {}).get(k) for k in ("username", "password")):
            raise RuntimeError("CNPG must create posthog-pg-app (username/password) before bootstrap")
        user, password = (base64.b64decode(pg["data"][key], validate=True).decode() for key in ("username", "password"))
        for value in (user, password):
            if not value.strip() or any(marker in value.upper() for marker in ("[REQUIRED", "[REDACTED", "<REDACTED", "CHANGEME")):
                raise RuntimeError("CNPG application credentials are empty or redacted")
        if "database-url" in missing:
            additions["database-url"] = f"postgres://{quote(user, safe='')}:{quote(password, safe='')}@posthog-pg-rw:5432/posthog"
        if "postgresql-password" in missing:
            additions["postgresql-password"] = password
    if "redis-url" in missing:
        additions["redis-url"] = "redis://posthog-redis:6379/"
    ownership_change = labels.get("app.kubernetes.io/managed-by") != "Helm" or any(annotations.get(k) != v for k, v in expected_annotations.items())
    print(f"{'Apply' if args.apply else 'Plan'}: preserve {len(data)} existing keys; add {', '.join(sorted(missing)) or 'none'}; Helm ownership {'set' if ownership_change else 'preserved'}")
    print("ClickHouse password: " + ("preserve existing Secret" if clickhouse else "create independent Secret with a secure random password"))
    if not args.apply:
        return
    if not clickhouse:
        manifest = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                    "metadata": {"name": "posthog-clickhouse-password", "namespace": args.namespace},
                    "stringData": {"password": secrets.token_urlsafe(48)}}
        kubectl("create", "-f", "-", "-o", "json", payload=json.dumps(manifest))
    for key in missing & GENERATED.keys():
        additions[key] = ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(GENERATED[key]))
    encoded = {k: base64.b64encode(v.encode()).decode() for k, v in additions.items()}
    labels = {**labels, "app.kubernetes.io/managed-by": "Helm"}
    annotations = {**annotations, **expected_annotations}
    if current:
        if not missing and not ownership_change:
            print("No changes required")
            return
        # Optimistic concurrency prevents replacing a key another reconciler just created.
        patch = [{"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
                 {"op": "add", "path": "/metadata/labels", "value": labels},
                 {"op": "add", "path": "/metadata/annotations", "value": annotations},
                 {"op": "add", "path": "/data", "value": {**data, **encoded}}]
        kubectl("patch", "secret", "posthog-secrets", "--type=json", "--patch-file=/dev/stdin", "-o", "json", payload=json.dumps(patch))
    else:
        manifest = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "metadata": {"name": "posthog-secrets", "namespace": args.namespace, "labels": labels, "annotations": annotations}, "data": encoded}
        kubectl("create", "-f", "-", "-o", "json", payload=json.dumps(manifest))
    print("Secret ready; existing key values were not changed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
