from django.db import migrations, models

from freppledb.common.migrate import AttributeMigration


class Migration(AttributeMigration):
    extends_app_label = "input"

    dependencies = [("mlcc", "0005_furnace_batching")]

    operations = [
        migrations.AddField(
            model_name="operationplan",
            name="mlcc_load_quantity",
            field=models.DecimalField(
                blank=True,
                db_index=True,
                decimal_places=6,
                max_digits=15,
                null=True,
                verbose_name="MLCC furnace load quantity",
            ),
        ),
        migrations.AddField(
            model_name="operationplan",
            name="mlcc_load_unit",
            field=models.CharField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="MLCC furnace load unit",
            ),
        ),
    ]
