#!/usr/bin/env python3
"""Read-only production drift check; --snapshot-dir uses saved sanitized JSON/YAML."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import re
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
SECRET_FIELDS = {"secret", "password", "accessKey", "secretKey", "encryptionSaltKeys", "internalApiSecret", "signedStateKey", "token"}


def redact(value):
    """Redact before writing temporary Helm inputs, including URL/env credentials."""
    if isinstance(value, dict):
        result = {}
        secret_env = re.search(r"secret|password|token|access.?key|api.?key|private.?key|salt|authorization|credential", str(value.get("name", "")), re.I)
        for key, child in value.items():
            sensitive = key != "existingSecret" and re.search(r"password$|secret$|secret.?key$|access.?key$|api.?key$|salt.?keys$|signed.?state.?key$|token$|private.?key$|authorization$|credential", key, re.I)
            if isinstance(child, str) and (sensitive or (key == "value" and secret_env)):
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
    result = subprocess.run(command, input=payload, text=True, capture_output=True)
    if result.returncode:
        # Helm and kubectl may include secret material in errors.
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
            if "targetPath" in ref:
                targeted.append((ref["targetPath"], raw))
            else:
                values = merge(values, yaml.safe_load(raw) or {})
        values = merge(values, hr["spec"].get("values", {}))
        # Flux targetPath has Helm --set precedence, even over inline values.
        for path, value in targeted:
            if any(char in path for char in "[\\"):
                raise RuntimeError("Unsupported valuesFrom targetPath; supply plain dotted keys")
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
    }
    for name, keys in required_secrets.items():
        secret = observed({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": args.namespace}})
        if secret is None and args.snapshot_dir:
            continue
        for key in keys:
            if not (secret or {}).get("data", {}).get(key):
                drift.append(f"Required Secret key missing: {name}/{key}")
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

        def comparable(want, have, path=""):
            # Secret equality is checked in memory live; snapshots cannot establish it.
            a, b = copy.deepcopy(want), copy.deepcopy(have)
            for key in set(a) | set(b):
                child = f"{path}/{key}"
                if key in SECRET_FIELDS and not isinstance(a.get(key), dict) and not isinstance(b.get(key), dict):
                    if args.snapshot_dir and a.get(key) != b.get(key):
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
            return {"/".join(identity(doc)): doc for doc in documents if doc and doc["kind"] != "Secret"}

        try:
            drift.extend("Rendered manifests/" + path for path in changes(render(want_render, desired_hr, "desired"), render(live_render, live_hr, "observed")))
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
    except (RuntimeError, ValueError, OSError, yaml.YAMLError) as exc:
        print("ERROR: alignment check failed; check prerequisites and snapshot syntax (details withheld for secret safety)", file=sys.stderr)
        sys.exit(2)
