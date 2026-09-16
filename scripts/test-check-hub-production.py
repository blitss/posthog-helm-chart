#!/usr/bin/env python3
"""Offline regression checks for production drift semantics; no cluster calls."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("production_check", Path(__file__).with_name("check-hub-production.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class DriftBoundaries(unittest.TestCase):
    def test_api_defaults_do_not_hide_real_environment_drift(self):
        desired = {"template": {"metadata": {"annotations": {}}, "spec": {"containers": [{"name": "web", "env": [{"name": "LOGS_REDIS_HOST", "value": ""}]}]}}}
        actual = {"template": {"metadata": {}, "spec": {"containers": [{"name": "web", "env": [{"name": "LOGS_REDIS_HOST"}]}]}}}
        self.assertEqual(list(check.changes(check.runtime_spec(desired), check.runtime_spec(actual), subset=True)), [])
        actual["template"]["spec"]["containers"][0]["env"][0]["value"] = "wrong-host"
        self.assertEqual(list(check.changes(check.runtime_spec(desired), check.runtime_spec(actual), subset=True)), ["/template/spec/containers/0/env/0/value"])

    def test_unprovable_or_unsupported_values_are_not_certified(self):
        self.assertEqual(list(check.redaction_paths({"credential": "[REDACTED]"})), ["/credential"])
        self.assertIs(check.target_scalar("false"), False)
        self.assertIsNone(check.target_scalar("null"))
        self.assertEqual(check.target_scalar('"false"'), '"false"')
        with self.assertRaises(ValueError):
            check.target_scalar("{one,two}")


if __name__ == "__main__":
    unittest.main()
