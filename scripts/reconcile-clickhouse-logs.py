#!/usr/bin/env python3
"""Staged #70 repair, run inside the pinned PostHog migration image.

Use the corrected deployment environment: CLICKHOUSE_DATABASE=posthog and
CLICKHOUSE_LOGS_DATABASE=posthog. Direct writers must be paused by the operator.

python /tmp/reconcile-clickhouse-logs.py snapshot /tmp/logs-repair.json
python /tmp/reconcile-clickhouse-logs.py reconcile /tmp/logs-repair.json --writers-quiesced --apply
python /tmp/reconcile-clickhouse-logs.py consumers /tmp/logs-repair.json --writers-quiesced --apply

Then run normal manage.py migrate_clickhouse. No migration history is changed.
A failed mutation phase deliberately requires manual inspection, not blind retry.
Keep the private snapshot and detached Kafka metadata until final verification.
"""
import argparse
import importlib
import json
import os
import re
from pathlib import Path

import sys

# Absolute script paths otherwise omit the application and slim-image dependencies.
sys.path[:0] = ["/code", "/python-runtime"]

SOURCE = "default"
DEST = "posthog"
BASE = {
    "log_attributes": "ReplicatedAggregatingMergeTree",
    "log_attributes2": "ReplicatedAggregatingMergeTree",
    "log_attributes3": "ReplicatedAggregatingMergeTree",
    "logs32": "ReplicatedMergeTree",
    "logs34": "ReplicatedMergeTree",
    "logs_billing_metrics": "ReplicatedAggregatingMergeTree",
    "logs_kafka_metrics": "ReplicatedAggregatingMergeTree",
    "logs_volume_buckets": "ReplicatedAggregatingMergeTree",
    "trace_attributes": "ReplicatedMergeTree",
    "trace_attributes2": "ReplicatedAggregatingMergeTree",
    "trace_spans": "ReplicatedMergeTree",
    "trace_spans_kafka_metrics": "ReplicatedMergeTree",
}
OPTIONAL_BASE = {"metric_series1", "metric_samples1"}
KAFKA = {"kafka_logs_avro", "kafka_trace_spans_avro"}
VIEWS = {
    "kafka_logs34_avro_mv", "kafka_logs_avro_billing_metrics_mv",
    "kafka_logs_avro_kafka_metrics_mv", "kafka_trace_spans_avro_mv",
    "logs32_to_log_attributes", "logs32_to_resource_attributes",
    "logs34_to_log_attributes", "logs34_to_log_attributes3",
    "logs34_to_resource_attributes", "logs34_to_resource_attributes3",
    "logs34_to_volume_buckets", "trace_span_to_attributes",
    "trace_span_to_attributes2", "trace_span_to_resource_attributes",
    "trace_span_to_resource_attributes2", "trace_span_to_span_attributes",
    "trace_span_to_span_attributes2", "trace_spans_to_kafka_metrics_mv",
}
DISTRIBUTED = {
    "log_attributes_distributed", "logs", "logs_billing_metrics_distributed",
    "logs_distributed", "logs_kafka_metrics_distributed",
    "logs_volume_buckets_distributed", "trace_attributes_distributed",
    "trace_spans_distributed",
}
OPTIONAL_DISTRIBUTED = {"metric_series", "metric_samples"}
OWNED = set(BASE) | OPTIONAL_BASE | KAFKA | VIEWS | DISTRIBUTED | OPTIONAL_DISTRIBUTED
MODULES = [
    ("0211_logs32", 4), ("0214_logs", 1), ("0223_logs_distributed_tables", 4),
    ("0280_logs34", 14), ("0282_log_attributes_severity", 3),
    ("0283_metric_events", 4), ("0285_metric_series_temporality_samples_histograms", 5),
    ("0288_log_attributes3_distributed", 1), ("0290_trace_spans_and_attributes", 15),
    ("0298_logs34_mv_explicit_columns", 1), ("0300_logs_volume_buckets_summing", 2),
    ("0302_logs34_to_volume_buckets_mv", 1),
    # CREATE IF NOT EXISTS preserves moved storage, including its older columns.
    # Apply the genuine idempotent column migration before current Kafka SELECTs
    # reference pattern fields; normal migrate_clickhouse will still record 0304.
    ("0304_logs34_pattern_columns", 2),
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def ident(name):
    require(re.fullmatch(r"[a-zA-Z0-9_]+", name), "Unexpected identifier")
    return "`" + name + "`"


def table(db, name):
    return ident(db) + "." + ident(name)


def save(path, value, *, exclusive=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    with os.fdopen(os.open(path, flags, 0o600), "w") as handle:
        json.dump(value, handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())


def inventory(client):
    rows = client.execute(
        "SELECT database, name, engine, toString(uuid), engine_full "
        "FROM system.tables WHERE database IN %(databases)s AND name IN %(names)s "
        "ORDER BY database, name",
        {"databases": (SOURCE, DEST), "names": tuple(sorted(OWNED))},
    )
    result = {}
    for db, name, engine, uuid, engine_full in rows:
        ddl = client.execute("SHOW CREATE TABLE " + table(db, name))[0][0]
        replicas = client.execute(
            "SELECT zookeeper_path, replica_name FROM system.replicas "
            "WHERE database=%(db)s AND table=%(name)s", {"db": db, "name": name},
        )
        result[db + "." + name] = {
            "database": db, "name": name, "engine": engine, "uuid": uuid,
            "engine_full": engine_full, "ddl": ddl, "replicas": [list(r) for r in replicas],
        }
    return result


def history(client):
    return client.execute(
        "SELECT package_name, module_name, toString(applied) "
        "FROM posthog.infi_clickhouse_orm_migrations ORDER BY package_name, module_name, applied"
    )


def queue_snapshot(client):
    return client.execute(
        "SELECT database, table, data_path, data_files, data_compressed_bytes, is_blocked "
        "FROM system.distribution_queue WHERE database=%(db)s AND table IN %(names)s",
        {"db": SOURCE, "names": tuple(sorted(DISTRIBUTED | OPTIONAL_DISTRIBUTED))},
    )


def preflight(client):
    require(settings.CLICKHOUSE_DATABASE == DEST, "CLICKHOUSE_DATABASE must be posthog")
    require(settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE == DEST, "CLICKHOUSE_LOGS_DATABASE must be posthog")
    require(not settings.MULTINODE_CLICKHOUSE and not run_mode().is_deployed_cloud,
            "This repair is only for the observed self-hosted single-node topology")
    clusters = {settings.CLICKHOUSE_CLUSTER, settings.CLICKHOUSE_MIGRATIONS_CLUSTER}
    clusters.update(settings.CLICKHOUSE_SATELLITE_CLUSTERS or [])
    hosts = client.execute(
        "SELECT DISTINCT host_address, port FROM system.clusters WHERE cluster IN %(clusters)s",
        {"clusters": tuple(clusters)},
    )
    require(len(hosts) == 1, "Migration cluster aliases must resolve to one physical endpoint")
    database_engines = dict(client.execute(
        "SELECT name, engine FROM system.databases WHERE name IN %(databases)s",
        {"databases": (SOURCE, DEST)},
    ))
    require(database_engines == {SOURCE: "Atomic", DEST: "Atomic"}, "Expected two Atomic databases")
    require(client.execute(
        "SELECT type FROM system.columns WHERE database='default' "
        "AND table='logs_volume_buckets' AND name='log_count'"
    ) == [("SimpleAggregateFunction(sum, UInt64)",)],
        "Volume bucket schema differs from both 847/ec60; no automatic conversion is safe")


def operations():
    structural, consumers = [], []
    for name, count in MODULES:
        module = importlib.import_module("posthog.clickhouse.migrations." + name)
        require(len(module.operations) == count, "Unexpected operation count: " + name)
        for index, operation in enumerate(module.operations):
            sql = getattr(operation, "_sql", None)
            require(isinstance(sql, str), "Expected a canonical SQL-backed RunPython operation")
            require(re.match(r"\s*(?:CREATE|ALTER)\b", sql, re.I)
                    and not re.search(r"\bPOPULATE\b", sql, re.I),
                    "Non-DDL or data-populating operation refused: " + name + ":" + str(index))
            require(not re.search(r"(?:`?default`?)\s*\.", sql, re.I), "SQL still targets default")
            require("infi_clickhouse_orm" not in sql, "Migration-history operation refused")
            if re.match(r"\s*CREATE\s+OR\s+REPLACE", sql, re.I):
                require("ENGINE = Distributed(" in sql, "Replacement of storage is forbidden")
            # Build logs34 metrics/billing views (12/13) before starting Kafka:
            # otherwise consumers can ingest backlog without accounting for it.
            deferred = ((name == "0280_logs34" and index in (10, 11))
                        or (name == "0290_trace_spans_and_attributes" and index in (12, 13))
                        or name == "0298_logs34_mv_explicit_columns")
            (consumers if deferred else structural).append((name, index, operation))
    return structural, consumers


def run_ops(items):
    for name, index, operation in items:
        print("Applying canonical operation", name, index, flush=True)
        # These upstream RunPython closures explicitly ignore their Database argument.
        # Calling apply performs real DDL through the normal migration cluster dispatcher.
        operation.apply(None)


def validate_source(snapshot):
    source = {v["name"]: v for v in snapshot.values() if v["database"] == SOURCE}
    require((set(BASE) | KAFKA | VIEWS | DISTRIBUTED) <= set(source), "Observed source inventory is incomplete")
    for name, item in source.items():
        require(DEST + "." + name not in snapshot, "Destination collision: " + name)
        if name in BASE or name in OPTIONAL_BASE:
            require(item["engine"].endswith("MergeTree"), "Storage engine mismatch: " + name)
            if name in BASE:
                require(item["engine"] == BASE[name], "Storage engine changed: " + name)
            require(len(item["replicas"]) == 1, "Expected one replica registration: " + name)
            require(not re.search(r"\{(?:database|table)\}", item["engine_full"]),
                    "Rename-sensitive Keeper path: " + name)
            require(item["replicas"][0][0].endswith("/posthog." + name), "Unexpected Keeper path: " + name)
        elif name in VIEWS:
            require(item["engine"] == "MaterializedView", "Unexpected view engine")
            target = re.search(r"\bTO\s+`?default`?\.`?([a-zA-Z0-9_]+)`?(?:\s|\()", item["ddl"])
            require(target and target.group(1) in set(BASE) | OPTIONAL_BASE,
                    "Only explicit TO-owned views may be dropped: " + name)
            require(not re.search(r"\bENGINE\s*=", item["ddl"]), "View owns private storage: " + name)
        elif name in KAFKA:
            require(item["engine"] == "Kafka", "Unexpected consumer engine")
        else:
            require(item["engine"] == "Distributed", "Unexpected queue engine")
    return source


def finish(client, args, state):
    """Retire aliases only after genuine migrations and verified queue delivery."""
    current = inventory(client)
    original = validate_source(state["tables"])
    for name in (set(BASE) | OPTIONAL_BASE) & set(original):
        moved = current.get(DEST + "." + name)
        require(moved and moved["uuid"] == original[name]["uuid"]
                and moved["replicas"] == original[name]["replicas"],
                "Moved storage identity changed: " + name)
    before = {tuple(row) for row in state["history"]}
    require(before <= {tuple(row) for row in history(client)}, "Original migration history lost")
    applied = {row[1] for row in history(client)}
    require(all(name in applied for name, _ in MODULES), "Run genuine migrate_clickhouse first")
    require(not client.execute(
        "SELECT name FROM system.tables WHERE database=%(db)s AND name IN %(names)s",
        {"db": SOURCE, "names": tuple(sorted(KAFKA | VIEWS))},
    ), "Legacy consumers/views must remain inactive")
    aliases = sorted((DISTRIBUTED | OPTIONAL_DISTRIBUTED) & set(original))
    for name in aliases:
        item = current.get(SOURCE + "." + name)
        if state["phase"] != "finalized":
            require(item and item["uuid"] == original[name]["uuid"], "Legacy alias changed: " + name)
    if args.phase == "drain":
        require(state["phase"] == "consumers_complete", "Partial/previous drain: inspect checkpoint; do not replay")
        for name in aliases:
            # Queued blocks retain the Distributed destination. Never redirect/drop them.
            require(re.match(r"Distributed\([^,]+,\s*['`]?posthog['`]?\s*,",
                             original[name]["engine_full"]), "Queue destination needs manual review: " + name)
        state["phase"] = "draining"
        save(args.snapshot, state)
        for name in aliases:
            client.execute("SYSTEM START DISTRIBUTED SENDS " + table(SOURCE, name))
            client.execute("SYSTEM FLUSH DISTRIBUTED " + table(SOURCE, name))
        require(not any(row[3] for row in queue_snapshot(client)), "Legacy queue is not empty")
        state["phase"] = "drained"
        save(args.snapshot, state)
    elif args.phase == "verify":
        require(state["phase"] in {"drained", "verified", "finalized"}, "Drain queues before verification")
        require(not any(row[3] for row in queue_snapshot(client)), "Legacy queue is not empty")
        require(not client.execute(
            "SELECT table FROM system.replicas WHERE database='posthog' "
            "AND (is_readonly OR is_session_expired OR queue_size > 0)"
        ), "Destination replicas are not healthy")
        if state["phase"] != "finalized":
            state["phase"] = "verified"
            state["verified_inventory"] = current
            save(args.snapshot, state)
    else:
        require(state["phase"] == "verified", "Finalization requires completed verification")
        require(current == state["verified_inventory"], "Schema changed since verification")
        require(not any(row[3] for row in queue_snapshot(client)), "Never drop a nonempty queue")
        state["phase"] = "finalizing"
        save(args.snapshot, state)
        for name in aliases:
            client.execute("DROP TABLE " + table(SOURCE, name) + " SYNC")
        # Keep old Kafka metadata detached permanently: attaching it can advance offsets.
        state["phase"] = "finalized"
        save(args.snapshot, state)
    print("Checkpoint:", state["phase"], "— storage and original history preserved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("snapshot", "reconcile", "consumers", "drain", "verify", "finalize"))
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--writers-quiesced", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Required for mutation phases")
    args = parser.parse_args()
    global settings, default_client, run_mode
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()
    from django.conf import settings
    from posthog.clickhouse.client.connection import default_client
    from posthog.run_mode import run_mode
    require(Path("/code/commit.txt").read_text().strip() in {
        "8471862b083b25d3a11b97eb7730f21aa0cb4c7f",
        "ec60ec72f4cc7c2b6e55d8b5497f05db4618a946",
    }, "Run only against the reviewed 847/ec60 application source")
    structural, consumers = operations()
    with default_client() as client:
        if args.phase == "snapshot":
            preflight(client)
            tables = inventory(client)
            validate_source(tables)
            save(args.snapshot, {"phase": "snapshotted", "tables": tables,
                                 "history": history(client), "queues": queue_snapshot(client)}, exclusive=True)
            print("Private snapshot created; no database mutations performed.")
            return
        if args.phase != "verify" and not args.apply:
            print("Plan only: phase", args.phase, "requires --apply and --writers-quiesced; snapshot is read-only.")
            return
        require(args.phase == "verify" or args.writers_quiesced, "Pause direct writers first and pass --writers-quiesced")
        state = json.loads(args.snapshot.read_text())
        if args.phase in {"drain", "verify", "finalize"}:
            finish(client, args, state)
            return
        require(history(client) == [tuple(r) for r in state["history"]], "Migration history changed; review first")
        if args.phase == "reconcile":
            preflight(client)
            require(state["phase"] == "snapshotted", "Partial/previous run: inspect manually before retry")
            require(inventory(client) == state["tables"], "Schema/UUID changed since snapshot")
            source = validate_source(state["tables"])
            state["phase"] = "reconciling"
            save(args.snapshot, state)
            for name in sorted(KAFKA):
                client.execute("DETACH TABLE " + table(SOURCE, name) + " PERMANENTLY")
            for name in sorted((DISTRIBUTED | OPTIONAL_DISTRIBUTED) & set(source)):
                client.execute("SYSTEM STOP DISTRIBUTED SENDS " + table(SOURCE, name))
            for name in sorted(VIEWS):
                client.execute("DROP TABLE " + table(SOURCE, name) + " SYNC")
            for name in sorted((set(BASE) | OPTIONAL_BASE) & set(source)):
                client.execute("RENAME TABLE " + table(SOURCE, name) + " TO " + table(DEST, name))
                moved = inventory(client)[DEST + "." + name]
                require(moved["uuid"] == source[name]["uuid"] and moved["replicas"] == source[name]["replicas"],
                        "Storage identity changed during move: " + name)
            run_ops(structural)
            require(history(client) == [tuple(r) for r in state["history"]], "Unexpected migration-history mutation")
            state["phase"] = "structural_complete"
            state["destination"] = inventory(client)
            save(args.snapshot, state)
            print("Storage preserved and structural DDL complete. Old Distributed queues remain stopped and intact.")
            print("Review destination schema, then run consumers phase. Do not reattach old default Kafka tables.")
        elif args.phase == "consumers":
            require(state["phase"] == "structural_complete", "Structural reconciliation must finish first")
            require(settings.CLICKHOUSE_DATABASE == DEST and settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE == DEST,
                    "Both runtime databases must still be posthog")
            require(inventory(client) == state["destination"], "Schema changed after structural phase; review first")
            require(not client.execute(
                "SELECT name FROM system.tables WHERE database=%(db)s AND name IN %(names)s",
                {"db": SOURCE, "names": tuple(sorted(KAFKA))},
            ), "Old consumers are still attached")
            state["phase"] = "starting_consumers"
            save(args.snapshot, state)
            run_ops(consumers)
            require(history(client) == [tuple(r) for r in state["history"]], "Unexpected migration-history mutation")
            state["phase"] = "consumers_complete"
            state["queues_after"] = queue_snapshot(client)
            save(args.snapshot, state)
            print("New consumers use canonical schema. Run normal migrate_clickhouse now.")
            print("Old Distributed sends remain STOPPED: after full migration, inspect each queue, START DISTRIBUTED SENDS")
            print("and FLUSH DISTRIBUTED against verified destinations; never drop a nonempty queue table.")


if __name__ == "__main__":
    main()
