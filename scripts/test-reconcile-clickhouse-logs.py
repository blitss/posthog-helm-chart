#!/usr/bin/env python3
"""Offline safety checks; no Django, cluster, database or mocks required."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("repair", Path(__file__).with_name("reconcile-clickhouse-logs.py"))
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class StorageGuards(unittest.TestCase):
    def test_storage_cannot_be_replaced_or_dropped_as_a_view(self):
        tables = {}
        for name in repair.OWNED - repair.OPTIONAL_BASE - repair.OPTIONAL_DISTRIBUTED:
            engine = repair.BASE.get(name, "Kafka" if name in repair.KAFKA else "MaterializedView" if name in repair.VIEWS else "Distributed")
            tables["default." + name] = {
                "database": "default", "name": name, "engine": engine,
                "engine_full": engine + "('/clickhouse/posthog." + name + "', 'replica')",
                "replicas": [["/clickhouse/posthog." + name, "replica"]],
                "ddl": "CREATE MATERIALIZED VIEW default.`" + name + "` TO default.logs34 AS SELECT 1",
            }
        repair.validate_source(tables)
        for mutation in ("destination_collision", "private_view_storage", "rename_sensitive_path", "foreign_view_target"):
            changed = copy.deepcopy(tables)
            if mutation == "destination_collision":
                changed["posthog.logs34"] = {**changed["default.logs34"], "database": "posthog"}
            elif mutation == "private_view_storage":
                changed["default.logs34_to_log_attributes"]["ddl"] += " ENGINE = MergeTree()"
            elif mutation == "rename_sensitive_path":
                changed["default.logs34"]["engine_full"] = "ReplicatedMergeTree('/{database}/{table}', 'replica')"
            else:
                changed["default.logs34_to_log_attributes"]["ddl"] = "CREATE MATERIALIZED VIEW default.logs34_to_log_attributes TO default.unrelated AS SELECT 1"
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                repair.validate_source(changed)


    def test_rollout_barrier_stops_writers_but_not_dependencies(self):
        runner_spec = importlib.util.spec_from_file_location("runner", Path(__file__).with_name("deploy-hub-production.py"))
        runner = importlib.util.module_from_spec(runner_spec)
        runner_spec.loader.exec_module(runner)
        def deployment(component):
            return {"kind": "Deployment", "metadata": {"labels": {"app.kubernetes.io/component": component}}, "spec": {"replicas": 3}}
        documents = [deployment("web"), deployment("ingestion-logs"), deployment("temporal"), {"kind": "HorizontalPodAutoscaler"}]
        result = list(runner.held(documents))
        self.assertEqual([d["spec"]["replicas"] for d in result], [0, 0, 3])
        with self.assertRaises(RuntimeError):
            list(runner.held([{"kind": "Deployment", "metadata": {}, "spec": {}}]))


if __name__ == "__main__":
    unittest.main()
