from django.db import connection
from django.test import TestCase


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
            },
            "operation": {
                "mlcc_process_stage",
                "mlcc_recipe_required",
                "mlcc_batch_required",
            },
            "operationplan": {
                "mlcc_batch_code",
                "mlcc_lot_number",
                "mlcc_recipe_version",
                "mlcc_schedulable",
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
