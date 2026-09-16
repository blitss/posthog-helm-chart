#!/usr/bin/env python3
"""Read-only production drift check; --snapshot-dir uses saved sanitized JSON/YAML."""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
from decimal import Decimal
import subprocess
import re
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
SECRET_FIELDS = {"secret", "password", "accessKey", "secretKey", "encryptionSaltKeys", "internalApiSecret", "signedStateKey", "token"}
GENERATED_KEYS = ("posthog-secret", "encryption-salt-keys", "internal-api-secret", "browserless-token", "mcp-signed-state-key", "valkey-password")


def target_scalar(value):
    """Helm strvals scalar types; compound/escaped expressions need full parsing."""
    if any(character in value for character in ",{}\\"):
        raise ValueError("compound or escaped targetPath value")
    lowered = value.lower()
    if lowered in ("true", "false", "null"):
        return {"true": True, "false": False, "null": None}[lowered]
    if value == "0" or (value and value[0] != "0" and re.fullmatch(r"[+-]?[0-9]+", value)):
        number = int(value)
        if -(2 ** 63) <= number < 2 ** 63:
            return number
    return value


def redaction_paths(value, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from redaction_paths(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from redaction_paths(child, f"{path}/{index}")
    elif isinstance(value, str) and re.search(r"redacted|required secret input|audit-only-secret", value, re.I):
        yield path


def runtime_spec(value, path=()):
    """Normalize API defaults/quantities and volatile metadata, not behavior."""
    if isinstance(value, dict):
        if path[-2:-1] == ("env",) and "name" in value and "value" not in value and "valueFrom" not in value:
            value = {**value, "value": ""}
        result = {}
        for key, child in value.items():
            if key == "helm.sh/chart" and path[-1:] == ("labels",):
                continue
            if key == "kubectl.kubernetes.io/restartedAt" and path[-1:] == ("annotations",):
                continue
            normalized = runtime_spec(child, path + (key,))
            if key == "annotations" and path[-1:] == ("metadata",) and not normalized:
                continue
            result[key] = normalized
        return result
    if isinstance(value, list):
        return [runtime_spec(child, path + (str(index),)) for index, child in enumerate(value)]
    if len(path) >= 2 and path[-2] in ("requests", "limits") and path[-1] in ("cpu", "memory", "storage", "ephemeral-storage"):
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(m|[KMGTPE]i?|)?", str(value))
        if match:
            suffix = match[2] or ""
            multiplier = Decimal("0.001") if suffix == "m" else Decimal(1)
            if suffix and suffix != "m":
                multiplier = Decimal(1024 if suffix.endswith("i") else 1000) ** ("KMGTPE".index(suffix[0]) + 1)
            return str((Decimal(match[1]) * multiplier).normalize())
    return value


def redact(value):
    """Redact before writing temporary Helm inputs, including URL/env credentials."""
    if isinstance(value, dict):
        result = {}
        secret_env = re.search(r"secret|password|token|access.?key|api.?key|private.?key|salt|authorization|credential", str(value.get("name", "")), re.I)
        for key, child in value.items():
            sensitive = key != "existingSecret" and re.search(r"password$|secret$|secret.?key$|access.?key$|api.?key$|salt.?keys$|signed.?state.?key$|token$|private.?key$|authorization$|credential", key, re.I)
            if isinstance(child, str) and child and (sensitive or (key == "value" and secret_env)):
                result[key] = "audit-only-secret"
            else:
                result[key] = redact(child)
        return result
    if isinstance(value, list):
        return [redact(child) for child in value]
    if isinstance(value, str):
        value = re.sub(r"(://)[^/@\s]+:[^/@\s]+@", r"\1audit:audit@", value)
        return re.sub(r"([?&](?:password|token|secret|access_key|api_key)=)[^&\s]+", r"\1audit", value, flags=re.I)
    return value


def run(command, payload=None):
    environment = {**os.environ, "GODEBUG": os.environ.get("GODEBUG", "") + ",http2client=0",
                   "KUBECTL_REMOTE_COMMAND_WEBSOCKETS": "false"}
    try:
        result = subprocess.run(command, input=payload, text=True, capture_output=True,
                                env=environment, timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{command[0]} operation timed out; command details withheld") from None
    if result.returncode:
        raise RuntimeError(f"{command[0]} operation failed (exit {result.returncode}); output withheld for secret safety")
    return result.stdout


def merge(left, right):
    result = copy.deepcopy(left)
    for key, value in right.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def changes(want, have, path="", subset=False):
    if isinstance(want, dict) and isinstance(have, dict):
        keys = set(want) if subset and want else set(want) | set(have)
        for key in sorted(keys):
            child = f"{path}/{key}"
            if key not in want or key not in have:
                yield child
            else:
                yield from changes(want[key], have[key], child, subset)
    elif isinstance(want, list) and isinstance(have, list):
        if len(want) != len(have):
            yield path + "/length"
        for index, (a, b) in enumerate(zip(want, have)):
            yield from changes(a, b, f"{path}/{index}", subset)
    elif want != have:
        yield path


def identity(obj):
    meta = obj["metadata"]
    return obj["apiVersion"], obj["kind"], meta.get("namespace", ""), meta["name"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig")
    parser.add_argument("--context")
    parser.add_argument("--namespace", default="posthog")
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--profile", type=Path, default=ROOT / "manifests/hub-production")
    parser.add_argument("--chart", type=Path, help="Local unpacked exact chart including dependencies; required offline")
    args = parser.parse_args()
    kubectl = ["kubectl"]
    helm = ["helm"]
    for key in ("kubeconfig", "context"):
        if getattr(args, key):
            kubectl += ["--" + key, getattr(args, key)]
            helm += ["--kubeconfig" if key == "kubeconfig" else "--kube-context", getattr(args, key)]
    desired = [doc for doc in yaml.safe_load_all(run(["kubectl", "kustomize", str(args.profile)])) if doc]
    desired_hr = next(obj for obj in desired if obj["kind"] == "HelmRelease" and obj["metadata"]["name"] == "posthog")
    source = next(obj for obj in desired if obj["kind"] == "OCIRepository")
    inventory_path = args.profile / "prerequisites.json"
    inventory = json.loads(inventory_path.read_text()) if inventory_path.exists() else {}
    if inventory_path.exists():
        for controller in inventory["controllers"]:
            pod = {"containers": controller["containers"], "serviceAccountName": controller["serviceAccountName"]}
            metadata = {"name": controller["name"], "namespace": controller["namespace"]}
            if controller.get("chart"):
                metadata["labels"] = {"helm.sh/chart": controller["chart"]}
            desired.append({"apiVersion": "apps/v1", "kind": controller["kind"], "metadata": metadata,
                            "spec": {"replicas": controller["replicas"], "template": {"spec": pod}}})
    snapshots = {}
    incomplete = []
    drift = []
    if args.snapshot_dir:
        for path in sorted(args.snapshot_dir.glob("*")):
            if path.suffix not in (".json", ".yaml", ".yml"):
                continue
            for doc in yaml.safe_load_all(path.read_text()):
                if not isinstance(doc, dict):
                    continue
                for obj in doc.get("items", [doc]):
                    if isinstance(obj, dict) and doc.get("kind", "").endswith("List"):
                        obj.setdefault("apiVersion", doc.get("apiVersion"))
                        obj.setdefault("kind", doc["kind"][:-4])
                    if isinstance(obj, dict) and "apiVersion" in obj and "kind" in obj and "metadata" in obj and "name" in obj["metadata"]:
                        snapshots[identity(obj)] = obj

    def observed(obj):
        key = identity(obj)
        if key in snapshots:
            return snapshots[key]
        if args.snapshot_dir:
            incomplete.append("Missing snapshot: " + "/".join(key))
            return None
        api, kind, namespace, name = key
        resource = kind + ("." + api.split("/")[0] if "/" in api else "")
        output = run(kubectl + ["get", resource, name, "-n", namespace or args.namespace, "--ignore-not-found", "-o", "json"])
        snapshots[key] = json.loads(output) if output.strip() else None
        return snapshots[key]

    for config in inventory.get("configMaps", []):
        actual = observed({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": config["name"], "namespace": config["namespace"]}})
        if actual is None:
            if not args.snapshot_dir:
                drift.append("Operator ConfigMap missing: " + config["name"])
            continue
        actual_hashes = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in actual.get("data", {}).items() if key != "readme" and not key.endswith(".example")}
        drift.extend("Operator ConfigMap/" + config["name"] + path for path in changes(config["dataSha256"], actual_hashes))

    def resolve(hr):
        values = {}
        targeted = []
        for ref in hr["spec"].get("valuesFrom", []):
            kind = ref.get("kind", "Secret")
            resource = {"apiVersion": "v1", "kind": kind, "metadata": {"name": ref["name"], "namespace": hr["metadata"].get("namespace", args.namespace)}}
            obj = observed(resource)
            key = ref.get("valuesKey", "values.yaml")
            raw = (obj or {}).get("data", {}).get(key)
            if raw is None:
                if ref.get("optional"):
                    continue
                if not args.snapshot_dir:
                    raise RuntimeError(f"Missing required {kind} {ref['name']} key {key}")
                incomplete.append(f"Unverified secret input: {ref['name']}/{key}")
                if "targetPath" not in ref:
                    raise RuntimeError("Offline valuesFrom YAML needs a sanitized snapshot; cannot guess values")
                raw = "[REQUIRED SECRET INPUT]"
            elif kind == "Secret":
                # Sanitized snapshots may retain a marker instead of base64 bytes.
                if not str(raw).startswith(("[", "<")):
                    raw = base64.b64decode(raw, validate=True).decode()
            if args.snapshot_dir and list(redaction_paths(raw)):
                incomplete.append(f"Unverified secret input: {ref['name']}/{key}")
            if "targetPath" in ref:
                targeted.append((ref["targetPath"], raw))
            else:
                values = merge(values, yaml.safe_load(raw) or {})
        values = merge(values, hr["spec"].get("values", {}))
        # Flux targetPath has Helm --set precedence, even over inline values.
        for path, value in targeted:
            if not re.fullmatch(r"[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)*", path):
                print("UNVERIFIED Unsupported valuesFrom targetPath syntax")
                raise RuntimeError("Unsupported valuesFrom targetPath syntax")
            try:
                value = target_scalar(value)
            except ValueError:
                print("UNVERIFIED Unsupported compound, escaped or unmatched-quote valuesFrom targetPath value")
                raise RuntimeError("Unsupported valuesFrom targetPath value") from None
            cursor = values
            parts = path.split(".")
            for key in parts[:-1]:
                cursor = cursor.setdefault(key, {})
            cursor[parts[-1]] = value
        return values

    live_hr = observed(desired_hr)
    if not live_hr:
        raise RuntimeError("PostHog HelmRelease missing; alignment cannot be established")
    wanted_values, live_values = resolve(desired_hr), resolve(live_hr)
    required_secrets = {
        "posthog-clickhouse-password": ("password",),
        "posthog-pg-app": ("username", "password"),
        "posthog-elastic-es-elastic-user": ("elastic",),
        "posthog-oidc-generated": ("tls.key",),
        "posthog-tls": ("tls.crt", "tls.key"),
        "posthog-secrets": GENERATED_KEYS + ("database-url", "redis-url", "postgresql-password", "object-storage-access-key", "object-storage-secret-key", "seaweedfs-access-key", "seaweedfs-secret-key"),
    }
    for name, keys in required_secrets.items():
        secret = observed({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": args.namespace}})
        if secret is None and args.snapshot_dir:
            continue
        for key in keys:
            if not (secret or {}).get("data", {}).get(key):
                drift.append(f"Required Secret key missing: {name}/{key}")
            elif args.snapshot_dir and list(redaction_paths(secret["data"][key])):
                incomplete.append(f"Unverified Secret value: {name}/{key}")
            else:
                decoded = base64.b64decode(secret["data"][key], validate=True).decode()
                if not decoded:
                    drift.append(f"Required Secret key empty: {name}/{key}")
                if args.snapshot_dir and list(redaction_paths(decoded)):
                    incomplete.append(f"Unverified Secret value: {name}/{key}")
        if name == "posthog-secrets" and secret:
            metadata = secret.get("metadata", {})
            annotations = metadata.get("annotations", {})
            if metadata.get("labels", {}).get("app.kubernetes.io/managed-by") != "Helm" or annotations.get("meta.helm.sh/release-name") != "posthog" or annotations.get("meta.helm.sh/release-namespace") != args.namespace:
                drift.append("Application Secret Helm ownership mismatch")
    for obj in desired:
        actual = live_hr if identity(obj) == identity(desired_hr) else observed(obj)
        label = obj["kind"] + "/" + obj["metadata"]["name"]
        if actual is None:
            drift.append(label + " missing")
            continue
        want_spec, actual_spec = copy.deepcopy(obj.get("spec", {})), copy.deepcopy(actual.get("spec", {}))
        if obj["kind"] == "HelmRelease":
            for spec in (want_spec, actual_spec):
                spec.pop("values", None)
                spec.setdefault("valuesFrom", [])
                spec.pop("suspend", None)
            if actual.get("spec", {}).get("suspend"):
                drift.append(label + "/spec/suspend")
        if "spec" in obj:
            drift.extend(label + "/spec" + path for path in changes(want_spec, actual_spec, subset=True))
        for field in ("data",):
            if field in obj:
                drift.extend(label + "/" + field + path for path in changes(obj[field], actual.get(field, {})))
        for field in ("annotations", "labels"):
            if field in obj["metadata"]:
                drift.extend(label + "/metadata/" + field + path for path in changes(obj["metadata"][field], actual["metadata"].get(field, {}), subset=True))

    with tempfile.TemporaryDirectory(prefix="posthog-check-") as directory:
        temporary = Path(directory)
        chart = args.chart
        if chart is None:
            if args.snapshot_dir:
                raise RuntimeError("--chart is required with --snapshot-dir; offline checks never fetch charts")
            ref = source["spec"]["ref"]
            url = source["spec"]["url"]
            pull = helm + ["pull", url, "--untar", "--untardir", str(temporary)]
            if "digest" in ref:
                pull = helm + ["pull", url + "@" + ref["digest"], "--untar", "--untardir", str(temporary)]
            else:
                pull += ["--version", ref.get("tag", ref.get("semver", "")).lstrip("=")]
            run(pull)
            chart = temporary / "posthog"
        defaults = yaml.safe_load((chart / "values.yaml").read_text())
        chart_meta = yaml.safe_load((chart / "Chart.yaml").read_text())
        expected_version = source["metadata"].get("annotations", {}).get("posthog.streamloop.app/chart-version")
        if expected_version and str(chart_meta["version"]) != expected_version:
            drift.append("Local chart version does not match production pin")
        wanted_effective = merge(defaults, wanted_values)
        live_effective = merge(defaults, live_values)
        installed_path = args.snapshot_dir / "helm-values.json" if args.snapshot_dir else None
        if installed_path and installed_path.exists():
            installed = json.loads(installed_path.read_text())
        elif args.snapshot_dir:
            installed = None
            incomplete.append("Missing helm-values.json: installed effective values not checked")
        else:
            installed = json.loads(run(helm + ["get", "values", "posthog", "-n", args.namespace, "--all", "-o", "json"]))
        if args.snapshot_dir:
            for name, values in (("desired", wanted_effective), ("live", live_effective), ("installed", installed)):
                incomplete.extend(f"Unverified redacted {name} value: {path}" for path in redaction_paths(values))

        def comparable(want, have, path=""):
            # Secret equality is checked in memory live; snapshots cannot establish it.
            a, b = copy.deepcopy(want), copy.deepcopy(have)
            for key in set(a) | set(b):
                child = f"{path}/{key}"
                if key in SECRET_FIELDS and not isinstance(a.get(key), dict) and not isinstance(b.get(key), dict):
                    if args.snapshot_dir and (a.get(key) != b.get(key) or list(redaction_paths(a.get(key))) or list(redaction_paths(b.get(key)))):
                        incomplete.append("Unverified credential equality: " + child)
                    elif a.get(key) != b.get(key):
                        drift.append("Credential drift: " + child)
                    a[key] = b[key] = "audit-only-secret"
                elif isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
                    a[key], b[key] = comparable(a[key], b[key], child)
            return a, b

        want_render, live_render = comparable(wanted_effective, live_effective)
        drift.extend("Effective values" + path for path in changes(want_render, live_render))
        if installed is not None:
            want_installed, have_installed = comparable(wanted_effective, installed)
            drift.extend("Installed values" + path for path in changes(want_installed, have_installed))

        def render(values, hr, name):
            values_path = temporary / (name + ".json")
            values_path.write_text(json.dumps(redact(values)))
            # Only redacted, non-deployable values go to disk or helm template.
            rendered = run(helm + ["template", "posthog", str(chart), "-n", args.namespace, "-f", str(values_path), "--api-versions", "traefik.io/v1alpha1", "--api-versions", "monitoring.coreos.com/v1"])
            folder = temporary / name
            folder.mkdir()
            (folder / "render.yaml").write_text(rendered)
            config = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["render.yaml"]}
            for renderer in hr["spec"].get("postRenderers", []):
                if set(renderer) != {"kustomize"}:
                    raise RuntimeError("Unsupported Helm postRenderer")
                for key, value in renderer["kustomize"].items():
                    config.setdefault(key, []).extend(value)
            (folder / "kustomization.yaml").write_text(json.dumps(config))
            documents = yaml.safe_load_all(run(["kubectl", "kustomize", str(folder)]))
            # Helm lookup/random Secret contents cannot be reproduced offline.
            result = {}
            for doc in documents:
                if not doc or doc["kind"] == "Secret" or doc.get("metadata", {}).get("annotations", {}).get("helm.sh/hook"):
                    continue
                doc["metadata"].setdefault("namespace", args.namespace)
                result["/".join(identity(doc))] = doc
            return result

        try:
            rendered = render(wanted_effective, desired_hr, "desired")
            drift.extend("Rendered manifests/" + path for path in changes(rendered, render(live_effective, live_hr, "observed")))
            for obj in rendered.values():
                if obj["kind"] not in ("Deployment", "StatefulSet", "DaemonSet", "CronJob", "Service", "Ingress", "IngressRoute", "Middleware", "ConfigMap", "HorizontalPodAutoscaler", "PodDisruptionBudget", "NetworkPolicy"):
                    continue
                actual = observed(obj)
                label = "Runtime/" + obj["kind"] + "/" + obj["metadata"]["name"]
                if actual is None:
                    if not args.snapshot_dir:
                        drift.append(label + " missing")
                    continue
                want_spec = runtime_spec(redact(obj.get("spec", {})))
                have_spec = runtime_spec(redact(actual.get("spec", {})))
                drift.extend(label + "/spec" + path for path in changes(want_spec, have_spec, subset=True))
                for key in ("selector", "data"):
                    wanted = obj.get("spec", {}).get(key) if key == "selector" else obj.get(key)
                    found = actual.get("spec", {}).get(key) if key == "selector" else actual.get(key)
                    if wanted is not None:
                        drift.extend(label + "/" + key + path for path in changes(wanted, found))
                for path in redaction_paths(obj.get("spec", {})):
                    incomplete.append(label + "/spec" + path + " inline credential equality cannot be established from redacted rendering")
        except (RuntimeError, ValueError, OSError, yaml.YAMLError):
            incomplete.append("Helm/post-render comparison failed; desired spec/value drift above remains authoritative")
    for message in sorted(set(drift)):
        print("DRIFT " + message)
    for message in sorted(set(incomplete)):
        print("UNVERIFIED " + message)
    print(f"Alignment results: {len(set(drift))} drift paths; {len(set(incomplete))} unverifiable inputs. Secret contents never printed.")
    return 1 if drift else 2 if incomplete else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(2)
    except (ValueError, OSError, yaml.YAMLError):
        print("ERROR: alignment check failed; check prerequisites and snapshot syntax (details withheld for secret safety)", file=sys.stderr)
        sys.exit(2)
