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
    def build_graph(self):
        # Build the complete graph first: schema_addons/finalize_fks migrations
        # depend on squash nodes, so deleting those files leaves dangling edges.
        self.replace_migrations = False
        super().build_graph()
        self.replace_migrations = True
        model_move_apps = {app_label for app_label, _ in MODEL_MOVES}
        for key, migration in self.replacements.items():
            applied = [target in self.applied_migrations for target in migration.replaces]
            # Match Django 5.2's replacement-history bookkeeping.
            if all(applied):
                self.applied_migrations[key] = migration
            else:
                self.applied_migrations.pop(key, None)
            legacy_move = key[0] in model_move_apps and key[1] == "0001_squash_2026_09_07_initial"
            if not legacy_move and (all(applied) or not any(applied)):
                self.graph.remove_replaced_nodes(key, migration.replaces)
            else:
                # Django reconnects every dependent to the terminal original
                # migrations, including cross-app schema-addon dependencies.
                self.graph.remove_replacement_node(key, migration.replaces)
        self.graph.validate_consistency()
        self.graph.ensure_not_cyclic()


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
