#!/usr/bin/env python3
"""Forward-only, explicitly staged hub-production deployment. Default: offline plan."""
import argparse
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import uuid


KUBE_ENV = {**os.environ, "GODEBUG": os.environ.get("GODEBUG", "") + ",http2client=0",
            "KUBECTL_REMOTE_COMMAND_WEBSOCKETS": "false"}
import yaml

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "posthog"
RELEASE = "posthog"
POD = "posthog-upgrade-runner"
INFRA = {"temporal", "temporal-ui", "valkey", "browserless", "geoip"}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def held(documents):
    """Hold every application Deployment, not the database/dependency workloads."""
    for doc in documents:
        if doc["kind"] == "HorizontalPodAutoscaler":
            continue
        if doc["kind"] == "Deployment":
            component = doc["metadata"].get("labels", {}).get("app.kubernetes.io/component")
            require(component is not None, "Unsupported unclassified Deployment")
            if component not in INFRA:
                doc["spec"]["replicas"] = 0
        yield doc


def command(argv, data=None):
    # Never echo stdin, Helm values, Secret data, database output or credentials.
    result = subprocess.run([str(a) for a in argv], input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=KUBE_ENV)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} failed (exit {result.returncode}); output withheld because it may contain credentials")
    return result.stdout


def private_write(path, data):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def main():
    if sys.argv[1:] == ["--hold-workloads"]:
        yaml.safe_dump_all(held([d for d in yaml.safe_load_all(sys.stdin) if d]), sys.stdout)
        return
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("prepare", "backup", "logs", "migrate", "rollout", "verify"))
    p.add_argument("--context", required=True)
    p.add_argument("--kubeconfig")
    p.add_argument("--mode", choices=("fresh", "upgrade"), required=True)
    p.add_argument("--state-dir", type=Path, required=True)
    p.add_argument("--profile", type=Path, default=ROOT / "manifests/hub-production")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--writers-quiesced", action="store_true", help="Confirm external/direct writers are stopped")
    p.add_argument("--logs-phase", choices=("snapshot", "reconcile", "consumers", "drain", "verify", "finalize"))
    p.add_argument("--url", help="HTTPS PostHog origin for health and end-to-end capture proof")
    p.add_argument("--timeout", type=int, default=2700)
    args = p.parse_args()
    require(args.timeout > 0, "Timeout must be positive")
    if not args.apply:
        print(f"PLAN {args.mode} {args.phase}: context={args.context}, namespace=posthog, profile={args.profile}")
        print("prepare: suspend Flux owners; stop application writers; bootstrap dependencies/Secrets; hold application rollout")
        print("backup: private pg_dumpall + frozen ClickHouse archive, bounded transfer and remote/local SHA-256 verification")
        print("logs (legacy default database only): snapshot -> reconcile -> consumers; then migrate -> drain -> verify -> finalize")
        print("migrate: real Node SQLx, legacy model moves, Django/product/persons, ClickHouse and async migrations")
        print("rollout: release held workloads and resume Flux; verify: readiness + HTTPS capture -> ClickHouse UUID")
        print("No commands executed. --apply authorizes only the named stage. No rollback or automatic failed-stage replay.")
        return
    require(args.writers_quiesced or args.phase in {"rollout", "verify"}, "Stop external/direct writers and pass --writers-quiesced")
    args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(args.state_dir.stat().st_mode & 0o077 == 0, "State directory must be private (chmod 700)")
    state_file = args.state_dir / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {
        "context": args.context, "mode": args.mode, "steps": {}, "id": uuid.uuid4().hex[:12]}
    require(state["context"] == args.context and state["mode"] == args.mode, "State belongs to another target/mode")
    require(not args.state_dir.is_symlink(), "State directory must not be a symlink")
    kube = ["kubectl", "--context", args.context]
    if args.kubeconfig:
        kube += ["--kubeconfig", args.kubeconfig]
    def k(*argv, data=None):
        return command(kube + list(argv), data)
    def obj(*argv):
        return json.loads(k(*argv, "-o", "json"))
    def apply(doc):
        k("apply", "-f", "-", data=json.dumps(doc).encode())
    def checkpoint():
        private_write(state_file, json.dumps(state, indent=2).encode())
    def complete(name):
        require(state["steps"].get(name) == "complete", "Complete stage first: " + name)
    def execute(code):
        return k("-n", NAMESPACE, "exec", "-i", POD, "--", "python", "-", data=code.encode())
    def ch(sql):
        code = "import os,json\nfrom clickhouse_driver import Client\nc=Client(os.environ['CLICKHOUSE_HOST'],user=os.environ['CLICKHOUSE_USER'],password=os.environ['CLICKHOUSE_PASSWORD'])\n"
        return json.loads(execute(code + "print(json.dumps(c.execute(" + repr(sql) + "),default=str))"))
    def wait_resource(resource, condition="Ready"):
        k("-n", NAMESPACE, "wait", resource, "--for=condition=" + condition, "--timeout=" + str(args.timeout) + "s")
    def assert_held():
        for d in obj("-n", NAMESPACE, "get", "deployments")["items"]:
            if d["metadata"]["name"].startswith("posthog-") and d["metadata"].get("labels", {}).get("app.kubernetes.io/component") not in INFRA:
                require(d["spec"].get("replicas", 1) == 0 and d.get("status", {}).get("replicas", 0) == 0,
                        "Application writers are not stopped: " + d["metadata"]["name"])
        require(not obj("-n", NAMESPACE, "get", "hpa")["items"], "Autoscalers must remain disabled in this dedicated namespace")
    def helm_values():
        hr = state["release"]
        # Flux targetPath references override inline values as well as earlier references.
        values = copy.deepcopy(hr["spec"].get("values", {}))
        for ref in hr["spec"].get("valuesFrom", []):
            require(ref.get("kind", "Secret") == "Secret" and ref.get("targetPath"), "Only targetPath Secret valuesFrom supported")
            secret = obj("-n", NAMESPACE, "get", "secret", ref["name"])
            value = base64.b64decode(secret["data"][ref.get("valuesKey", "values.yaml")]).decode()
            target = values
            keys = ref["targetPath"].split(".")
            for key in keys[:-1]:
                target = target.setdefault(key, {})
            target[keys[-1]] = value
        return yaml.safe_dump(values).encode()
    def helm(*argv, data=None):
        options = ["helm", "--kube-context", args.context]
        if args.kubeconfig:
            options += ["--kubeconfig", args.kubeconfig]
        return command(options + list(argv), data)
    def install(hold):
        options = ["upgrade", "--install", RELEASE, state["chart"], "-n", NAMESPACE,
                   "--no-hooks", "--timeout", str(args.timeout) + "s", "-f", "-"]
        if hold:
            options += ["--post-renderer", str(Path(__file__).resolve()), "--post-renderer-args=--hold-workloads"]
        helm(*options, data=helm_values())
    stage = args.phase + (":" + str(args.logs_phase) if args.phase == "logs" else "")
    require(stage not in state["steps"], "Stage already attempted; inspect checkpoint and cluster, never blindly replay: " + stage)
    if args.phase != "prepare":
        complete("prepare")
        require(obj("get", "namespace", NAMESPACE)["metadata"]["uid"] == state["namespace_uid"], "Namespace was replaced")
        require(obj("-n", NAMESPACE, "get", "configmap", "posthog-upgrade-lock")["data"]["run"] == state["id"],
                "Upgrade lock belongs to another run")
    if args.phase in {"logs", "migrate"}:
        complete("backup")
        assert_held()
    if args.phase == "rollout":
        complete("migrate")
        if "logs:reconcile" in state["steps"]:
            complete("logs:finalize")
    if args.phase == "verify":
        complete("rollout")
    if args.phase == "prepare":
        docs = [d for d in yaml.safe_load_all(k("kustomize", str(args.profile))) if d]
        releases = [d for d in docs if d["kind"] == "HelmRelease"]
        require(len(releases) == 1 and releases[0]["metadata"]["name"] == RELEASE, "Expected one posthog HelmRelease")
        state["release"] = releases[0]
        initdb = [d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "posthog-clickhouse-initdb"]
        require(len(initdb) == 1, "Profile must include the committed ClickHouse initdb script")
        state["clickhouse_init"] = initdb[0]["data"]["01_init_posthog.sh"]
        repos = [d for d in docs if d["kind"] == "OCIRepository"
                 and d["metadata"]["name"] == state["release"]["spec"]["chartRef"]["name"]]
        require(len(repos) == 1, "Expected one matching OCIRepository")
        source = repos[0]
        digest = source["spec"].get("ref", {}).get("digest", "")
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", digest),
                "Profile must pin an exact OCI chart digest")
        version = source["metadata"].get("annotations", {}).get("posthog.streamloop.app/chart-version")
        require(isinstance(version, str) and version, "OCIRepository must record posthog.streamloop.app/chart-version")
        reference = source["spec"]["url"] + "@" + digest
        # Resolve and inspect the immutable artifact before suspending Flux or touching workloads.
        helm("pull", reference, "--untar", "--untardir", str(args.state_dir))
        state["chart"] = str(args.state_dir.resolve() / "posthog")
        chart = yaml.safe_load((Path(state["chart"]) / "Chart.yaml").read_text())
        require(chart.get("name") == RELEASE and str(chart.get("version")) == version,
                "Pulled chart name/version differs from the recorded profile")
        require(chart.get("appVersion") == "8471862b083b25d3a11b97eb7730f21aa0cb4c7f",
                "Unsupported application revision")
        state["chart_source"] = reference
    state["steps"][stage] = "started"
    checkpoint()
    if args.phase == "prepare":
        state["owners"] = []
        existing = obj("get", "helmreleases", "-A")["items"]
        live = next((d for d in existing if d["metadata"]["name"] == RELEASE and d["metadata"]["namespace"] == NAMESPACE), None)
        require(bool(live) == (args.mode == "upgrade"), "Fresh/upgrade mode does not match existing HelmRelease")
        if live:
            labels = live["metadata"].get("labels", {})
            owner = labels.get("kustomize.toolkit.fluxcd.io/name")
            if owner:
                owner_ns = labels["kustomize.toolkit.fluxcd.io/namespace"]
                k("-n", owner_ns, "patch", "kustomization", owner, "--type=merge", "-p", '{"spec":{"suspend":true}}')
                state["owners"].append([owner_ns, owner])
            k("-n", NAMESPACE, "patch", "helmrelease", RELEASE, "--type=merge", "-p", '{"spec":{"suspend":true}}')
        for d in docs:
            if d["kind"] == "Namespace":
                apply(d)
        state["namespace_uid"] = obj("get", "namespace", NAMESPACE)["metadata"]["uid"]
        checkpoint()
        # Atomic create is the cross-process lock. It is deliberately retained on failure.
        k("-n", NAMESPACE, "create", "configmap", "posthog-upgrade-lock", "--from-literal=run=" + state["id"])
        if live:
            for hpa in obj("-n", NAMESPACE, "get", "hpa")["items"]:
                k("-n", NAMESPACE, "delete", "hpa", hpa["metadata"]["name"])
            for d in obj("-n", NAMESPACE, "get", "deployments")["items"]:
                if d["metadata"]["name"].startswith("posthog-") and d["metadata"].get("labels", {}).get("app.kubernetes.io/component") not in INFRA:
                    k("-n", NAMESPACE, "scale", "deployment/" + d["metadata"]["name"], "--replicas=0")
                    selector = ",".join(a + "=" + b for a, b in d["spec"]["selector"]["matchLabels"].items())
                    k("-n", NAMESPACE, "wait", "pod", "-l", selector, "--for=delete", "--timeout=" + str(args.timeout) + "s")
        for d in docs:
            if d["kind"] == "Cluster" and d["apiVersion"].startswith("postgresql.cnpg.io/"):
                apply(d)
        wait_resource("cluster.postgresql.cnpg.io/posthog-pg")
        bootstrap = [sys.executable, ROOT / "scripts/bootstrap-hub-production-secrets.py", "--context", args.context, "--apply"]
        if args.kubeconfig:
            bootstrap += ["--kubeconfig", args.kubeconfig]
        command(bootstrap)
        for d in docs:
            if d["kind"] not in {"Namespace", "HelmRelease", "Cluster"}:
                apply(d)
        for resource in ("redpanda/posthog-redpanda",):
            wait_resource(resource)
        k("-n", NAMESPACE, "wait", "clickhouseinstallation/posthog", "--for=jsonpath={.status.status}=Completed",
          "--timeout=" + str(args.timeout) + "s")
        rendered = [d for d in yaml.safe_load_all(helm("template", RELEASE, state["chart"], "-n", NAMESPACE, "-f", "-", data=helm_values())) if d]
        jobs = {d["metadata"]["name"]: d for d in rendered if d["kind"] == "Job"}
        require(RELEASE + "-migrate" in jobs and RELEASE + "-cyclotron-migrate" in jobs, "Both migration roles must be enabled")
        state["jobs"] = jobs
        checkpoint()
        # Fresh installs need bundled Redis/Temporal/etc, but application Deployments stay at zero.
        if args.mode == "fresh":
            install(True)
        spec = copy.deepcopy(jobs[RELEASE + "-migrate"]["spec"]["template"]["spec"])
        spec["restartPolicy"] = "Never"
        container = spec["containers"][0]
        require("@sha256:" in container["image"], "Migration image must be digest pinned")
        container["command"] = ["python", "-c", "import signal; signal.pause()"]
        container.pop("args", None)
        apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": POD, "namespace": NAMESPACE}, "spec": spec})
        wait_resource("pod/" + POD)
        require(execute("from pathlib import Path; print(Path('/code/commit.txt').read_text().strip())").decode().strip() == chart["appVersion"], "Migration image source differs")
    elif args.phase == "backup":
        assert_held()
        snapshot_name = "posthog" + state["id"]
        cluster = obj("-n", NAMESPACE, "get", "cluster.postgresql.cnpg.io", "posthog-pg")
        primary = cluster["status"]["currentPrimary"]
        def remote(pod, container, *argv):
            return k("-n", NAMESPACE, "exec", pod, "-c", container, "--", *argv)
        def transfer(pod, container, source, target):
            size = int(remote(pod, container, "stat", "-c", "%s", source).strip())
            expected = remote(pod, container, "sha256sum", source).decode().split()[0]
            require(size > 0 and re.fullmatch(r"[a-f0-9]{64}", expected), "Invalid remote backup metadata")
            chunk_size = 64 * 1024 * 1024
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
                for offset in range(0, size, chunk_size):
                    argv = kube + ["-n", NAMESPACE, "exec", pod, "-c", container, "--",
                                   "dd", "if=" + source, "bs=" + str(chunk_size),
                                   "skip=" + str(offset // chunk_size), "count=1", "status=none"]
                    result = subprocess.run(argv, stdout=handle, stderr=subprocess.PIPE, env=KUBE_ENV)
                    handle.flush()
                    os.fsync(handle.fileno())
                    require(result.returncode == 0 and handle.tell() == min(offset + chunk_size, size),
                            "Incomplete backup chunk; private prefix retained, do not migrate or blindly replay")
                handle.flush()
                os.fsync(handle.fileno())
            with target.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256")
            require(target.stat().st_size == size and digest.hexdigest() == expected,
                    "Backup checksum differs from server; do not migrate")
            return {"bytes": size, "sha256": expected}
        databases = remote(primary, "postgres", "psql", "-U", "postgres", "-Atc",
                           "SELECT datname FROM pg_database WHERE NOT datistemplate").decode().splitlines()
        require({"posthog", "posthog_persons", "cyclotron_node"} <= set(databases), "Required existing PostgreSQL databases are missing")
        pg_remote = "/tmp/" + snapshot_name + ".sql"
        remote(primary, "postgres", "sh", "-ec", "umask 077; pg_dumpall -U postgres -f " + pg_remote)
        pg_local = args.state_dir / "postgres.sql"
        pg_backup = transfer(primary, "postgres", pg_remote, pg_local)
        with pg_local.open("rb") as handle:
            handle.seek(max(0, pg_local.stat().st_size - 4096))
            require(b"PostgreSQL database cluster dump complete" in handle.read(), "PostgreSQL dump completion marker missing")
        pods = obj("-n", NAMESPACE, "get", "pods", "-l", "clickhouse.altinity.com/chi=posthog")["items"]
        require(len(pods) == 1, "Frozen backup supports exactly one ClickHouse pod")
        ch_pod = pods[0]["metadata"]["name"]
        require(any(c["name"] == "clickhouse" for c in pods[0]["spec"]["containers"]), "Unexpected ClickHouse container")
        disks = ch("SELECT DISTINCT disk_name FROM system.parts WHERE active AND database IN ('default','posthog')")
        require(not disks or disks == [["default"]], "Frozen backup supports the observed single default data disk only")
        require(ch("SELECT path FROM system.disks WHERE name='default'") == [["/var/lib/clickhouse/"]],
                "Unexpected ClickHouse data path")
        metadata = ch("SELECT database,name,engine,toString(uuid),create_table_query FROM system.tables "
                      "WHERE database IN ('default','posthog') ORDER BY database,name")
        private_write(args.state_dir / "clickhouse-metadata.json", json.dumps(metadata, indent=2).encode())
        frozen = []
        state["backups"] = {"postgres": pg_backup, "snapshot_name": snapshot_name, "frozen": frozen}
        checkpoint()
        for db, name, engine, table_uuid, ddl in metadata:
            if engine.endswith("MergeTree"):
                require(re.fullmatch(r"[a-zA-Z0-9_]+", name), "Unexpected ClickHouse table name")
                ch("ALTER TABLE `" + db + "`.`" + name + "` FREEZE WITH NAME '" + snapshot_name + "'")
                frozen.append([db, name, table_uuid])
                checkpoint()
        # Empty fresh databases have nothing to freeze; preserve the metadata and empty shadow archive.
        remote(ch_pod, "clickhouse", "mkdir", "-p", "/var/lib/clickhouse/shadow/" + snapshot_name)
        ch_remote = "/tmp/" + snapshot_name + ".tar.gz"
        remote(ch_pod, "clickhouse", "sh", "-ec", "umask 077; tar -czf " + ch_remote +
               " -C /var/lib/clickhouse/shadow " + snapshot_name + "; gzip -t " + ch_remote)
        ch_local = args.state_dir / "clickhouse-shadow.tar.gz"
        state["backups"]["clickhouse"] = transfer(ch_pod, "clickhouse", ch_remote, ch_local)
        with gzip.open(ch_local, "rb") as handle:
            while handle.read(1024 * 1024):
                pass
        state["backups"]["verified"] = True
        checkpoint()
        for db, name, table_uuid in frozen:
            require(ch("SELECT toString(uuid) FROM system.tables WHERE database='" + db + "' AND name='" + name + "'") == [[table_uuid]],
                    "Table identity changed during backup")
            ch("ALTER TABLE `" + db + "`.`" + name + "` UNFREEZE WITH NAME '" + snapshot_name + "'")
        remote(primary, "postgres", "rm", pg_remote)
        remote(ch_pod, "clickhouse", "rm", ch_remote)
    elif args.phase == "logs":
        require(args.logs_phase, "--logs-phase is required")
        repair = ROOT / "scripts/reconcile-clickhouse-logs.py"
        execute("from pathlib import Path; Path('/tmp/reconcile-clickhouse-logs.py').write_bytes(" + repr(repair.read_bytes()) + ")")
        snapshot = args.state_dir / "logs-repair.json"
        if snapshot.exists():
            execute("from pathlib import Path; Path('/tmp/logs-repair.json').write_bytes(" + repr(snapshot.read_bytes()) + ")")
        try:
            k("-n", NAMESPACE, "exec", POD, "--", "python", "/tmp/reconcile-clickhouse-logs.py", args.logs_phase, "/tmp/logs-repair.json", "--writers-quiesced", "--apply")
        finally:
            # Recovery checkpoints must outlive the temporary pod, including failed phases.
            saved = execute("from pathlib import Path; p=Path('/tmp/logs-repair.json'); print(p.read_text() if p.exists() else '')")
            if saved.strip():
                private_write(snapshot, saved)
    elif args.phase == "migrate":
        old_logs = ch("SELECT count() FROM system.tables WHERE database='default' AND name IN ('logs32','logs34','kafka_logs_avro')")[0][0]
        require(old_logs == 0, "Legacy logs are still in default; complete snapshot/reconcile/consumers before migrating")
        ch_pods = obj("-n", NAMESPACE, "get", "pods", "-l", "clickhouse.altinity.com/chi=posthog")["items"]
        require(len(ch_pods) == 1, "Expected one ClickHouse pod for idempotent named collection bootstrap")
        k("-n", NAMESPACE, "exec", "-i", ch_pods[0]["metadata"]["name"], "-c", "clickhouse",
          "--", "bash", "-s", data=state["clickhouse_init"].encode())
        ch("SYSTEM FLUSH LOGS")
        require(ch("SELECT count() FROM system.tables WHERE database='system' AND name IN ('crash_log','error_log','metric_log')")[0][0] == 3,
                "Required ClickHouse system logs are unavailable; do not start migrations")
        if "logs:reconcile" in state["steps"]:
            complete("logs:consumers")
        for service in obj("-n", NAMESPACE, "get", "services")["items"]:
            if service["metadata"]["name"] == "posthog-cymbal-resolution" and service["spec"].get("clusterIP") != "None":
                require(service["spec"].get("selector", {}).get("app.kubernetes.io/instance") == RELEASE,
                        "Non-headless resolver Service is not owned by this release")
                k("-n", NAMESPACE, "delete", "service", "posthog-cymbal-resolution")
        # Prepare infrastructure/Services with every application Deployment held at zero.
        install(True)
        assert_held()
        jobs = state["jobs"]
        ordered = sorted(jobs.values(), key=lambda j: int(j["metadata"].get("annotations", {}).get("helm.sh/hook-weight", "0")))
        for source in ordered:
            job = copy.deepcopy(source)
            name = source["metadata"]["name"]
            job["metadata"] = {"name": name + "-guarded-" + state["id"], "namespace": NAMESPACE}
            job["spec"]["backoffLimit"] = 0
            job["spec"]["template"]["spec"]["restartPolicy"] = "Never"
            if name == RELEASE + "-cyclotron-migrate":
                job["spec"]["template"]["spec"]["containers"][0]["command"] = ["sh", "-ec", 'sqlx migrate run -D "$CYCLOTRON_NODE_DATABASE_URL" --source /migrations/cyclotron-node-migrations']
            k("create", "-f", "-", data=json.dumps(job).encode())
            wait_resource("job/" + job["metadata"]["name"], "Complete")
        execute("import subprocess\nsubprocess.run(['python','manage.py','migrate','--check'],check=True)\nsubprocess.run(['python','manage.py','run_async_migrations','--check'],check=True)")
    elif args.phase == "rollout":
        install(False)
        release = copy.deepcopy(state["release"])
        release["spec"]["suspend"] = False
        apply(release)
        # Reconcile the committed profile, not the former suspended live values.
        k("-n", NAMESPACE, "annotate", "helmrelease", RELEASE, "reconcile.fluxcd.io/requestedAt=" + str(time.time_ns()), "--overwrite")
        wait_resource("helmrelease/" + RELEASE)
        for ns, owner in state["owners"]:
            k("-n", ns, "patch", "kustomization", owner, "--type=merge", "-p", '{"spec":{"suspend":false}}')
        for d in obj("-n", NAMESPACE, "get", "deployments")["items"]:
            k("-n", NAMESPACE, "rollout", "status", "deployment/" + d["metadata"]["name"], "--timeout=" + str(args.timeout) + "s")
    else:
        require(args.url and args.url.startswith("https://"), "--url HTTPS origin is required")
        key = os.environ.get("POSTHOG_PROJECT_API_KEY")
        require(key, "Set POSTHOG_PROJECT_API_KEY for a real capture proof (never written to state)")
        with urllib.request.urlopen(args.url.rstrip("/") + "/preflight", timeout=30) as response:
            require(response.status == 200, "Public web preflight failed")
        event_id = str(uuid.uuid4())
        payload = {"api_key": key, "event": "deployment_verification", "uuid": event_id,
                   "properties": {"distinct_id": "deployment-" + state["id"]}}
        request = urllib.request.Request(args.url.rstrip("/") + "/capture/", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            require(200 <= response.status < 300, "Capture request failed")
        deadline = time.monotonic() + args.timeout
        while ch("SELECT count() FROM posthog.events WHERE uuid=toUUID('" + event_id + "')")[0][0] == 0:
            require(time.monotonic() < deadline, "Capture accepted but event not persisted to ClickHouse")
            time.sleep(2)
        state["capture_uuid"] = event_id
        command([sys.executable, ROOT / "scripts/check-hub-production.py", "--context", args.context] + (["--kubeconfig", args.kubeconfig] if args.kubeconfig else []))
        k("-n", NAMESPACE, "delete", "pod", POD)
        k("-n", NAMESPACE, "delete", "configmap", "posthog-upgrade-lock")
    state["steps"][stage] = "complete"
    checkpoint()
    print("Completed", stage, "on", args.context, "— private checkpoint:", state_file)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, ValueError) as error:
        sys.exit(str(error))
