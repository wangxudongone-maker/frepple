from django.db import migrations, models

from freppledb.common.migrate import AttributeMigration


class Migration(AttributeMigration):
    extends_app_label = "input"

    dependencies = [
        ("mlcc", "0002_core_attributes"),
    ]

    operations = [
        migrations.AddField(
            model_name="resource",
            name="mlcc_load_unit",
            field=models.CharField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="MLCC load unit",
            ),
        ),
        migrations.AddField(
            model_name="operation",
            name="mlcc_max_wait_time",
            field=models.DurationField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="MLCC maximum wait time",
            ),
        ),
    ]
