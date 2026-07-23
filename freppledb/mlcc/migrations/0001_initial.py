import datetime
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

PROCESS_STAGES = [
    ("stacking", "stacking"),
    ("lamination", "lamination"),
    ("cutting", "cutting"),
    ("debinding", "debinding"),
    ("sintering", "sintering"),
]


def audit_fields():
    return [
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
    ]


class Migration(migrations.Migration):
    initial = True

    dependencies = [("input", "0084_parameter_plan_solver")]

    operations = [
        migrations.CreateModel(
            name="MlccRecipe",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        db_index=True, max_length=100, verbose_name="recipe"
                    ),
                ),
                ("version", models.CharField(max_length=40, verbose_name="version")),
                ("effective_date", models.DateField(verbose_name="effective date")),
                (
                    "expiry_date",
                    models.DateField(blank=True, null=True, verbose_name="expiry date"),
                ),
                (
                    "process_stage",
                    models.CharField(
                        choices=PROCESS_STAGES,
                        max_length=30,
                        verbose_name="process stage",
                    ),
                ),
                ("active", models.BooleanField(default=True, verbose_name="active")),
                (
                    "parameters",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="parameters"
                    ),
                ),
                *audit_fields(),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mlcc_recipes",
                        to="input.item",
                        verbose_name="item",
                    ),
                ),
                (
                    "operation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mlcc_recipes",
                        to="input.operation",
                        verbose_name="operation",
                    ),
                ),
            ],
            options={
                "verbose_name": "MLCC recipe",
                "verbose_name_plural": "MLCC recipes",
                "db_table": "mlcc_recipe",
                "ordering": ("name", "version"),
            },
        ),
        migrations.CreateModel(
            name="MlccCompatibilityRule",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "name",
                    models.CharField(max_length=100, unique=True, verbose_name="name"),
                ),
                (
                    "process_stage",
                    models.CharField(
                        choices=PROCESS_STAGES,
                        default="sintering",
                        max_length=30,
                        verbose_name="process stage",
                    ),
                ),
                (
                    "family_a",
                    models.CharField(max_length=100, verbose_name="product family A"),
                ),
                (
                    "family_b",
                    models.CharField(max_length=100, verbose_name="product family B"),
                ),
                (
                    "rule_type",
                    models.CharField(
                        choices=[("allow", "allow"), ("forbid", "forbid")],
                        max_length=10,
                        verbose_name="rule type",
                    ),
                ),
                (
                    "reason",
                    models.CharField(blank=True, null=True, verbose_name="reason"),
                ),
                ("enabled", models.BooleanField(default=True, verbose_name="enabled")),
                ("priority", models.IntegerField(default=10, verbose_name="priority")),
                *audit_fields(),
            ],
            options={
                "verbose_name": "MLCC compatibility rule",
                "verbose_name_plural": "MLCC compatibility rules",
                "db_table": "mlcc_compatibility_rule",
                "ordering": ("process_stage", "priority", "name"),
            },
        ),
        migrations.CreateModel(
            name="MlccBatchGenealogy",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "parent_batch",
                    models.CharField(
                        db_index=True, max_length=100, verbose_name="parent batch"
                    ),
                ),
                (
                    "child_batch",
                    models.CharField(
                        db_index=True, max_length=100, verbose_name="child batch"
                    ),
                ),
                (
                    "process_stage",
                    models.CharField(
                        choices=PROCESS_STAGES,
                        max_length=30,
                        verbose_name="process stage",
                    ),
                ),
                (
                    "quantity",
                    models.DecimalField(
                        blank=True,
                        decimal_places=8,
                        max_digits=20,
                        null=True,
                        verbose_name="quantity",
                    ),
                ),
                *audit_fields(),
            ],
            options={
                "verbose_name": "MLCC batch genealogy",
                "verbose_name_plural": "MLCC batch genealogies",
                "db_table": "mlcc_batch_genealogy",
                "ordering": ("parent_batch", "child_batch"),
            },
        ),
        migrations.CreateModel(
            name="MlccScheduleRun",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "name",
                    models.CharField(max_length=100, unique=True, verbose_name="name"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "draft"),
                            ("ready", "ready"),
                            ("running", "running"),
                            ("complete", "complete"),
                            ("failed", "failed"),
                        ],
                        default="draft",
                        max_length=15,
                        verbose_name="status",
                    ),
                ),
                ("horizon_start", models.DateTimeField(verbose_name="horizon start")),
                ("horizon_end", models.DateTimeField(verbose_name="horizon end")),
                (
                    "requested_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name="requested at"
                    ),
                ),
                (
                    "started_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="started at"
                    ),
                ),
                (
                    "finished_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="finished at"
                    ),
                ),
                (
                    "parameters",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="parameters"
                    ),
                ),
                (
                    "message",
                    models.TextField(blank=True, null=True, verbose_name="message"),
                ),
                *audit_fields(),
            ],
            options={
                "verbose_name": "MLCC schedule run",
                "verbose_name_plural": "MLCC schedule runs",
                "db_table": "mlcc_schedule_run",
                "ordering": ("-requested_at", "name"),
            },
        ),
        migrations.CreateModel(
            name="MlccEquipmentCapability",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "process_stage",
                    models.CharField(
                        choices=PROCESS_STAGES,
                        max_length=30,
                        verbose_name="process stage",
                    ),
                ),
                (
                    "minimum_quantity",
                    models.DecimalField(
                        blank=True,
                        decimal_places=8,
                        max_digits=20,
                        null=True,
                        verbose_name="minimum quantity",
                    ),
                ),
                (
                    "maximum_quantity",
                    models.DecimalField(
                        blank=True,
                        decimal_places=8,
                        max_digits=20,
                        null=True,
                        verbose_name="maximum quantity",
                    ),
                ),
                ("enabled", models.BooleanField(default=True, verbose_name="enabled")),
                *audit_fields(),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mlcc_capabilities",
                        to="input.item",
                        verbose_name="item",
                    ),
                ),
                (
                    "recipe",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="equipment_capabilities",
                        to="mlcc.mlccrecipe",
                        verbose_name="recipe",
                    ),
                ),
                (
                    "resource",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mlcc_capabilities",
                        to="input.resource",
                        verbose_name="resource",
                    ),
                ),
            ],
            options={
                "verbose_name": "MLCC equipment capability",
                "verbose_name_plural": "MLCC equipment capabilities",
                "db_table": "mlcc_equipment_capability",
                "ordering": ("resource", "process_stage", "recipe"),
            },
        ),
        migrations.CreateModel(
            name="MlccSetupMatrix",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "process_stage",
                    models.CharField(
                        choices=PROCESS_STAGES,
                        max_length=30,
                        verbose_name="process stage",
                    ),
                ),
                (
                    "setup_time",
                    models.DurationField(
                        default=datetime.timedelta, verbose_name="setup time"
                    ),
                ),
                (
                    "setup_cost",
                    models.DecimalField(
                        decimal_places=8,
                        default=Decimal("0"),
                        max_digits=20,
                        verbose_name="setup cost",
                    ),
                ),
                *audit_fields(),
                (
                    "from_recipe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="setup_rules_from",
                        to="mlcc.mlccrecipe",
                        verbose_name="from recipe",
                    ),
                ),
                (
                    "resource",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mlcc_setup_rules",
                        to="input.resource",
                        verbose_name="resource",
                    ),
                ),
                (
                    "to_recipe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="setup_rules_to",
                        to="mlcc.mlccrecipe",
                        verbose_name="to recipe",
                    ),
                ),
            ],
            options={
                "verbose_name": "MLCC setup matrix",
                "verbose_name_plural": "MLCC setup matrices",
                "db_table": "mlcc_setup_matrix",
                "ordering": ("resource", "process_stage", "from_recipe", "to_recipe"),
            },
        ),
        migrations.CreateModel(
            name="MlccFurnaceLoad",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "reference",
                    models.CharField(
                        max_length=100, unique=True, verbose_name="reference"
                    ),
                ),
                (
                    "planned_start",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="planned start"
                    ),
                ),
                (
                    "planned_end",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="planned end"
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "draft"),
                            ("ready", "ready"),
                            ("running", "running"),
                            ("complete", "complete"),
                            ("cancelled", "cancelled"),
                        ],
                        default="draft",
                        max_length=15,
                        verbose_name="status",
                    ),
                ),
                (
                    "capacity",
                    models.DecimalField(
                        decimal_places=8,
                        max_digits=20,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("1E-8"))
                        ],
                        verbose_name="capacity",
                    ),
                ),
                *audit_fields(),
                (
                    "recipe",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="furnace_loads",
                        to="mlcc.mlccrecipe",
                        verbose_name="recipe",
                    ),
                ),
                (
                    "resource",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mlcc_furnace_loads",
                        to="input.resource",
                        verbose_name="resource",
                    ),
                ),
            ],
            options={
                "verbose_name": "MLCC furnace load",
                "verbose_name_plural": "MLCC furnace loads",
                "db_table": "mlcc_furnace_load",
                "ordering": ("-planned_start", "reference"),
            },
        ),
        migrations.CreateModel(
            name="MlccQualityHold",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "batch_code",
                    models.CharField(
                        db_index=True, max_length=100, verbose_name="batch code"
                    ),
                ),
                (
                    "hold_type",
                    models.CharField(
                        default="quality", max_length=50, verbose_name="hold type"
                    ),
                ),
                ("reason", models.CharField(verbose_name="reason")),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "active"), ("released", "released")],
                        default="active",
                        max_length=15,
                        verbose_name="status",
                    ),
                ),
                (
                    "held_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name="held at"
                    ),
                ),
                (
                    "released_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="released at"
                    ),
                ),
                *audit_fields(),
                (
                    "manufacturing_order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mlcc_quality_holds",
                        to="input.operationplan",
                        verbose_name="manufacturing order",
                    ),
                ),
            ],
            options={
                "verbose_name": "MLCC quality hold",
                "verbose_name_plural": "MLCC quality holds",
                "db_table": "mlcc_quality_hold",
                "ordering": ("-held_at", "batch_code"),
            },
        ),
        migrations.CreateModel(
            name="MlccFurnaceLoadItem",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "batch_code",
                    models.CharField(
                        db_index=True, max_length=100, verbose_name="batch code"
                    ),
                ),
                (
                    "quantity",
                    models.DecimalField(
                        decimal_places=8,
                        max_digits=20,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("1E-8"))
                        ],
                        verbose_name="quantity",
                    ),
                ),
                (
                    "sequence",
                    models.PositiveIntegerField(default=1, verbose_name="sequence"),
                ),
                *audit_fields(),
                (
                    "furnace_load",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="mlcc.mlccfurnaceload",
                        verbose_name="furnace load",
                    ),
                ),
                (
                    "manufacturing_order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mlcc_furnace_items",
                        to="input.operationplan",
                        verbose_name="manufacturing order",
                    ),
                ),
            ],
            options={
                "verbose_name": "MLCC furnace load item",
                "verbose_name_plural": "MLCC furnace load items",
                "db_table": "mlcc_furnace_load_item",
                "ordering": ("furnace_load", "sequence"),
            },
        ),
        migrations.CreateModel(
            name="MlccScheduleResult",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                (
                    "batch_code",
                    models.CharField(
                        db_index=True, max_length=100, verbose_name="batch code"
                    ),
                ),
                (
                    "planned_start",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="planned start"
                    ),
                ),
                (
                    "planned_end",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="planned end"
                    ),
                ),
                (
                    "quantity",
                    models.DecimalField(
                        decimal_places=8, max_digits=20, verbose_name="quantity"
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("proposed", "proposed"),
                            ("scheduled", "scheduled"),
                            ("blocked", "blocked"),
                            ("not_schedulable", "not schedulable"),
                        ],
                        default="proposed",
                        max_length=20,
                        verbose_name="status",
                    ),
                ),
                (
                    "sequence",
                    models.PositiveIntegerField(default=1, verbose_name="sequence"),
                ),
                (
                    "score",
                    models.DecimalField(
                        blank=True,
                        decimal_places=8,
                        max_digits=20,
                        null=True,
                        verbose_name="score",
                    ),
                ),
                (
                    "details",
                    models.JSONField(blank=True, default=dict, verbose_name="details"),
                ),
                *audit_fields(),
                (
                    "furnace_load",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="schedule_results",
                        to="mlcc.mlccfurnaceload",
                        verbose_name="furnace load",
                    ),
                ),
                (
                    "manufacturing_order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mlcc_schedule_results",
                        to="input.operationplan",
                        verbose_name="manufacturing order",
                    ),
                ),
                (
                    "resource",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mlcc_schedule_results",
                        to="input.resource",
                        verbose_name="resource",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="results",
                        to="mlcc.mlccschedulerun",
                        verbose_name="schedule run",
                    ),
                ),
            ],
            options={
                "verbose_name": "MLCC schedule result",
                "verbose_name_plural": "MLCC schedule results",
                "db_table": "mlcc_schedule_result",
                "ordering": ("run", "sequence", "manufacturing_order"),
            },
        ),
        migrations.AddConstraint(
            model_name="mlccrecipe",
            constraint=models.UniqueConstraint(
                fields=("name", "version"), name="mlcc_recipe_name_version_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccequipmentcapability",
            constraint=models.UniqueConstraint(
                fields=("resource", "process_stage", "recipe", "item"),
                name="mlcc_equipment_capability_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccequipmentcapability",
            constraint=models.UniqueConstraint(
                condition=models.Q(("item__isnull", True), ("recipe__isnull", False)),
                fields=("resource", "process_stage", "recipe"),
                name="mlcc_equipment_capability_no_item_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccequipmentcapability",
            constraint=models.UniqueConstraint(
                condition=models.Q(("item__isnull", False), ("recipe__isnull", True)),
                fields=("resource", "process_stage", "item"),
                name="mlcc_equipment_capability_no_recipe_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccequipmentcapability",
            constraint=models.UniqueConstraint(
                condition=models.Q(("item__isnull", True), ("recipe__isnull", True)),
                fields=("resource", "process_stage"),
                name="mlcc_equipment_capability_generic_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlcccompatibilityrule",
            constraint=models.UniqueConstraint(
                fields=("process_stage", "family_a", "family_b", "rule_type"),
                name="mlcc_compatibility_rule_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlcccompatibilityrule",
            constraint=models.UniqueConstraint(
                condition=models.Q(("enabled", True)),
                fields=("process_stage", "family_a", "family_b"),
                name="mlcc_compatibility_rule_enabled_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccsetupmatrix",
            constraint=models.UniqueConstraint(
                fields=("resource", "process_stage", "from_recipe", "to_recipe"),
                name="mlcc_setup_matrix_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccbatchgenealogy",
            constraint=models.UniqueConstraint(
                fields=("parent_batch", "child_batch"), name="mlcc_batch_genealogy_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccfurnaceload",
            constraint=models.CheckConstraint(
                check=models.Q(("capacity__gt", 0)),
                name="mlcc_furnace_load_capacity_gt_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccfurnaceloaditem",
            constraint=models.UniqueConstraint(
                fields=("furnace_load", "manufacturing_order"),
                name="mlcc_furnace_load_item_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccfurnaceloaditem",
            constraint=models.CheckConstraint(
                check=models.Q(("quantity__gt", 0)),
                name="mlcc_furnace_load_item_qty_gt_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="mlccscheduleresult",
            constraint=models.UniqueConstraint(
                fields=("run", "manufacturing_order"), name="mlcc_schedule_result_uniq"
            ),
        ),
    ]
