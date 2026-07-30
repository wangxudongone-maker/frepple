from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase


class MlccMigrationTest(TestCase):
    def test_mlcc_tables_and_core_attribute_columns_exist(self):
        tables = set(connection.introspection.table_names())
        expected_tables = {
            "mlcc_recipe",
            "mlcc_equipment_capability",
            "mlcc_compatibility_rule",
            "mlcc_setup_matrix",
            "mlcc_batch_genealogy",
            "mlcc_furnace_load",
            "mlcc_furnace_load_item",
            "mlcc_quality_hold",
            "mlcc_schedule_run",
            "mlcc_schedule_result",
            "mlcc_precheck_run",
            "mlcc_precheck_issue",
            "mlcc_load_unit_conversion",
            "mlcc_furnace_program",
            "mlcc_furnace_state_snapshot",
            "mlcc_furnace_transition_rule",
            "mlcc_furnace_transition",
        }
        self.assertTrue(expected_tables.issubset(tables))

        expected_columns = {
            "item": {
                "mlcc_material_type",
                "mlcc_product_family",
                "mlcc_chip_size",
                "mlcc_layer_count",
                "mlcc_quality_grade",
            },
            "resource": {
                "mlcc_equipment_group",
                "mlcc_is_furnace",
                "mlcc_nominal_capacity",
                "mlcc_load_unit",
            },
            "operation": {
                "mlcc_process_stage",
                "mlcc_recipe_required",
                "mlcc_batch_required",
                "mlcc_max_wait_time",
            },
            "operationplan": {
                "mlcc_batch_code",
                "mlcc_lot_number",
                "mlcc_recipe_version",
                "mlcc_schedulable",
                "mlcc_load_quantity",
                "mlcc_load_unit",
            },
        }
        with connection.cursor() as cursor:
            for table, columns in expected_columns.items():
                actual = {
                    col.name
                    for col in connection.introspection.get_table_description(
                        cursor, table
                    )
                }
                self.assertTrue(columns.issubset(actual), f"Missing columns on {table}")


class MlccUpgradeMigrationTest(TransactionTestCase):
    """Exercise the phase-1 PostgreSQL schema upgrade and idempotent re-migrate."""

    migrate_from = ("mlcc", "0002_core_attributes")
    migrate_to = ("mlcc", "0007_furnace_transitions")

    def tearDown(self):
        MigrationExecutor(connection).migrate([self.migrate_to])
        super().tearDown()

    def test_phase1_data_survives_upgrade_and_second_migrate_has_no_plan(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        recipe_model = old_apps.get_model("mlcc", "MlccRecipe")
        recipe_model.objects.create(
            name="MLCC-MIGRATION-V1",
            version="V1",
            effective_date=date(2026, 1, 1),
            process_stage="sintering",
            active=True,
            parameters={"phase": 1},
            source="mlcc_migration_test",
        )

        executor = MigrationExecutor(connection)
        plan = executor.migration_plan([self.migrate_to])
        self.assertEqual(
            [
                node.name
                for node, backwards in plan
                if node.app_label == "mlcc" and not backwards
            ],
            [
                "0003_solver_attributes",
                "0004_precheck_models",
                "0005_furnace_batching",
                "0006_furnace_load_attributes",
                "0007_furnace_transitions",
            ],
        )
        executor.migrate([self.migrate_to])
        new_apps = executor.loader.project_state([self.migrate_to]).apps
        upgraded_recipe = new_apps.get_model("mlcc", "MlccRecipe").objects.get(
            name="MLCC-MIGRATION-V1",
            version="V1",
        )
        self.assertEqual(upgraded_recipe.parameters, {"phase": 1})

        repeat_executor = MigrationExecutor(connection)
        self.assertEqual(repeat_executor.migration_plan([self.migrate_to]), [])
