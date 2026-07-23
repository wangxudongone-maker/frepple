from django.db import migrations, models

from freppledb.common.migrate import AttributeMigration


class Migration(AttributeMigration):
    extends_app_label = "input"

    dependencies = [
        ("input", "0084_parameter_plan_solver"),
        ("mlcc", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="mlcc_material_type",
            field=models.CharField(
                blank=True, db_index=True, null=True, verbose_name="MLCC material type"
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="mlcc_product_family",
            field=models.CharField(
                blank=True, db_index=True, null=True, verbose_name="MLCC product family"
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="mlcc_chip_size",
            field=models.CharField(
                blank=True, db_index=True, null=True, verbose_name="MLCC chip size"
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="mlcc_layer_count",
            field=models.IntegerField(
                blank=True, db_index=True, null=True, verbose_name="MLCC layer count"
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="mlcc_quality_grade",
            field=models.CharField(
                blank=True, db_index=True, null=True, verbose_name="MLCC quality grade"
            ),
        ),
        migrations.AddField(
            model_name="resource",
            name="mlcc_equipment_group",
            field=models.CharField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="MLCC equipment group",
            ),
        ),
        migrations.AddField(
            model_name="resource",
            name="mlcc_is_furnace",
            field=models.BooleanField(
                blank=True, db_index=True, null=True, verbose_name="MLCC furnace"
            ),
        ),
        migrations.AddField(
            model_name="resource",
            name="mlcc_nominal_capacity",
            field=models.DecimalField(
                blank=True,
                db_index=True,
                decimal_places=6,
                max_digits=15,
                null=True,
                verbose_name="MLCC nominal capacity",
            ),
        ),
        migrations.AddField(
            model_name="operation",
            name="mlcc_process_stage",
            field=models.CharField(
                blank=True, db_index=True, null=True, verbose_name="MLCC process stage"
            ),
        ),
        migrations.AddField(
            model_name="operation",
            name="mlcc_recipe_required",
            field=models.BooleanField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="MLCC recipe required",
            ),
        ),
        migrations.AddField(
            model_name="operation",
            name="mlcc_batch_required",
            field=models.BooleanField(
                blank=True, db_index=True, null=True, verbose_name="MLCC batch required"
            ),
        ),
        migrations.AddField(
            model_name="operationplan",
            name="mlcc_batch_code",
            field=models.CharField(
                blank=True, db_index=True, null=True, verbose_name="MLCC batch code"
            ),
        ),
        migrations.AddField(
            model_name="operationplan",
            name="mlcc_lot_number",
            field=models.CharField(
                blank=True, db_index=True, null=True, verbose_name="MLCC lot number"
            ),
        ),
        migrations.AddField(
            model_name="operationplan",
            name="mlcc_recipe_version",
            field=models.CharField(
                blank=True, db_index=True, null=True, verbose_name="MLCC recipe version"
            ),
        ),
        migrations.AddField(
            model_name="operationplan",
            name="mlcc_schedulable",
            field=models.BooleanField(
                blank=True, db_index=True, null=True, verbose_name="MLCC schedulable"
            ),
        ),
    ]
