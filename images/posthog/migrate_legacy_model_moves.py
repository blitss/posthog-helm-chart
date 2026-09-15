"""Run original model moves before a legacy database reaches their app-label removals.

Compatibility for PostHog 8471862b083b25d3a11b97eb7730f21aa0cb4c7f:
https://github.com/blitss/posthog-helm-chart/issues/65
The image build pins the source revision; no upstream migration is rewritten.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


MODEL_MOVES = (
    ("cohorts", "0001_migrate_cohorts_models"),
    ("error_tracking", "0017_migrate_cohorts_models"),
    ("experiments", "0018_migrate_cohorts_models"),
    ("approvals", "0001_migrate_approvals_models"),
    ("managed_warehouse", "0001_migrate_managed_warehouse_models"),
)


class LegacyModelMoveLoader(MigrationLoader):
    def load_disk(self):
        super().load_disk()
        # These squashes build fresh tables and depend on posthog 1340. The
        # original moves reuse legacy tables and can run before 1216/1239/1281.
        # Keep all original operations and all other replacement handling.
        for app_label, _ in MODEL_MOVES:
            del self.disk_migrations[app_label, "0001_squash_2026_09_07_initial"]


class Command(BaseCommand):
    help = "Prepare original product model moves on pre-September-squash databases"

    def handle(self, *args, **options):
        connection = connections[DEFAULT_DB_ALIAS]
        recorder = MigrationRecorder(connection)
        applied = recorder.applied_migrations()
        if ("posthog", "0001_initial") not in applied or (
            "posthog", "1340_drop_userproductlist_reason_columns"
        ) in applied:
            self.stdout.write("Legacy model-move preparation is not required.")
            return

        for target in MODEL_MOVES:
            # Targeting an applied migration can roll newer migrations back.
            # Re-read real records after each step so interrupted runs resume.
            if target in applied:
                continue
            executor = MigrationExecutor(connection)
            executor.loader = LegacyModelMoveLoader(connection)
            executor.loader.check_consistent_history(connection)
            conflicts = executor.loader.detect_conflicts()
            if conflicts:
                raise CommandError(f"Conflicting migrations in legacy model-move graph: {conflicts}")
            plan = executor.migration_plan([target])
            if any(backwards for _, backwards in plan):
                raise CommandError(f"Refusing a backward model-move plan for {target}")
            self.stdout.write(f"Preparing legacy model move: {target[0]}.{target[1]}")
            # Ordinary execution performs every prerequisite and records only
            # successfully applied migrations. No fake or fake_initial mode.
            executor.migrate([target], plan=plan)
            applied = recorder.applied_migrations()
