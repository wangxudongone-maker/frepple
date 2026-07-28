import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [("mlcc", "0004_precheck_models")]

    operations = [
        migrations.AddField(
            model_name="mlccrecipe",
            name="furnace_program_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=100,
                null=True,
                verbose_name="furnace program key",
            ),
        ),
        migrations.AddField(
            model_name="mlccrecipe",
            name="compatibility_group",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=100,
                null=True,
                verbose_name="certified compatibility group",
            ),
        ),
        migrations.CreateModel(
            name="MlccLoadUnitConversion",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "from_unit",
                    models.CharField(max_length=40, verbose_name="from unit"),
                ),
                ("to_unit", models.CharField(max_length=40, verbose_name="to unit")),
                ("numerator", models.PositiveBigIntegerField(verbose_name="numerator")),
                (
                    "denominator",
                    models.PositiveBigIntegerField(verbose_name="denominator"),
                ),
                ("enabled", models.BooleanField(default=True, verbose_name="enabled")),
                (
                    "source",
                    models.CharField(
                        blank=True, db_index=True, null=True, verbose_name="source"
                    ),
                ),
                (
                    "lastmodified",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="last modified",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mlcc_load_unit_conversions",
                        to="input.item",
                        verbose_name="item",
                    ),
                ),
            ],
            options={
                "db_table": "mlcc_load_unit_conversion",
                "ordering": ("item", "from_unit", "to_unit"),
                "verbose_name": "MLCC load unit conversion",
                "verbose_name_plural": "MLCC load unit conversions",
            },
        ),
        migrations.AddConstraint(
            model_name="mlccloadunitconversion",
            constraint=models.UniqueConstraint(
                fields=("item", "from_unit", "to_unit"),
                name="mlcc_load_unit_conversion_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccloadunitconversion",
            constraint=models.UniqueConstraint(
                condition=Q(item__isnull=True),
                fields=("from_unit", "to_unit"),
                name="mlcc_load_unit_conversion_generic_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccloadunitconversion",
            constraint=models.CheckConstraint(
                check=Q(numerator__gt=0) & Q(denominator__gt=0),
                name="mlcc_load_unit_conversion_positive",
            ),
        ),
        migrations.AlterField(
            model_name="mlccfurnaceload",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "draft"),
                    ("ready", "ready"),
                    ("running", "running"),
                    ("complete", "complete"),
                    ("cancelled", "cancelled"),
                    ("proposed", "proposed"),
                ],
                default="draft",
                max_length=15,
                verbose_name="status",
            ),
        ),
        migrations.AddField(
            model_name="mlccfurnaceload",
            name="run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="furnace_loads",
                to="mlcc.mlccschedulerun",
                verbose_name="schedule run",
            ),
        ),
        migrations.AddField(
            model_name="mlccfurnaceload",
            name="operation_type",
            field=models.CharField(
                choices=[
                    ("stacking", "stacking"),
                    ("lamination", "lamination"),
                    ("cutting", "cutting"),
                    ("debinding", "debinding"),
                    ("sintering", "sintering"),
                ],
                default="sintering",
                max_length=30,
                verbose_name="operation type",
            ),
        ),
        migrations.AddField(
            model_name="mlccfurnaceload",
            name="furnace_program_key",
            field=models.CharField(
                blank=True,
                max_length=100,
                null=True,
                verbose_name="furnace program key",
            ),
        ),
        migrations.AddField(
            model_name="mlccfurnaceload",
            name="loaded_quantity",
            field=models.DecimalField(
                decimal_places=8,
                default=0,
                max_digits=20,
                verbose_name="loaded quantity",
            ),
        ),
        migrations.AddField(
            model_name="mlccfurnaceload",
            name="load_unit",
            field=models.CharField(
                blank=True, default="", max_length=40, verbose_name="load unit"
            ),
        ),
        migrations.AddField(
            model_name="mlccfurnaceload",
            name="frozen",
            field=models.BooleanField(default=False, verbose_name="frozen"),
        ),
        migrations.AddField(
            model_name="mlccfurnaceload",
            name="details",
            field=models.JSONField(blank=True, default=dict, verbose_name="details"),
        ),
        migrations.AddConstraint(
            model_name="mlccfurnaceload",
            constraint=models.CheckConstraint(
                check=Q(loaded_quantity__gte=0) & Q(loaded_quantity__lte=F("capacity")),
                name="mlcc_furnace_load_loaded_lte_capacity",
            ),
        ),
        migrations.AddField(
            model_name="mlccfurnaceloaditem",
            name="load_unit",
            field=models.CharField(
                blank=True, default="", max_length=40, verbose_name="load unit"
            ),
        ),
        migrations.AddField(
            model_name="mlccfurnaceloaditem",
            name="conversion_trace",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="conversion trace"
            ),
        ),
    ]
