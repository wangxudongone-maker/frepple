import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


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
    dependencies = [("mlcc", "0003_solver_attributes")]

    operations = [
        migrations.CreateModel(
            name="MlccPrecheckRun",
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
                    "status",
                    models.CharField(
                        choices=[("passed", "passed"), ("blocked", "blocked")],
                        default="passed",
                        max_length=15,
                        verbose_name="status",
                    ),
                ),
                ("horizon_start", models.DateTimeField(verbose_name="horizon start")),
                ("horizon_end", models.DateTimeField(verbose_name="horizon end")),
                (
                    "freeze_minutes",
                    models.PositiveIntegerField(
                        default=0, verbose_name="freeze minutes"
                    ),
                ),
                (
                    "factory_timezone",
                    models.CharField(max_length=100, verbose_name="factory timezone"),
                ),
                (
                    "instance_hash",
                    models.CharField(
                        db_index=True, max_length=64, verbose_name="instance hash"
                    ),
                ),
                (
                    "order_count",
                    models.PositiveIntegerField(default=0, verbose_name="order count"),
                ),
                (
                    "batch_count",
                    models.PositiveIntegerField(default=0, verbose_name="batch count"),
                ),
                (
                    "task_count",
                    models.PositiveIntegerField(default=0, verbose_name="task count"),
                ),
                (
                    "equipment_count",
                    models.PositiveIntegerField(
                        default=0, verbose_name="equipment count"
                    ),
                ),
                (
                    "blocker_count",
                    models.PositiveIntegerField(
                        default=0, verbose_name="blocker count"
                    ),
                ),
                (
                    "warning_count",
                    models.PositiveIntegerField(
                        default=0, verbose_name="warning count"
                    ),
                ),
                (
                    "info_count",
                    models.PositiveIntegerField(default=0, verbose_name="info count"),
                ),
                (
                    "duration_ms",
                    models.PositiveIntegerField(
                        default=0, verbose_name="duration milliseconds"
                    ),
                ),
                (
                    "parameters",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="parameters"
                    ),
                ),
                *audit_fields(),
            ],
            options={
                "verbose_name": "MLCC precheck run",
                "verbose_name_plural": "MLCC precheck runs",
                "db_table": "mlcc_precheck_run",
                "ordering": ("-lastmodified", "reference"),
            },
        ),
        migrations.CreateModel(
            name="MlccPrecheckIssue",
            fields=[
                (
                    "id",
                    models.AutoField(
                        primary_key=True, serialize=False, verbose_name="identifier"
                    ),
                ),
                ("sequence", models.PositiveIntegerField(verbose_name="sequence")),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("BLOCKER", "blocker"),
                            ("WARNING", "warning"),
                            ("INFO", "info"),
                        ],
                        max_length=10,
                        verbose_name="severity",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        db_index=True, max_length=20, verbose_name="error code"
                    ),
                ),
                (
                    "object_type",
                    models.CharField(
                        db_index=True, max_length=50, verbose_name="object type"
                    ),
                ),
                (
                    "object_id",
                    models.CharField(
                        db_index=True, max_length=300, verbose_name="object identifier"
                    ),
                ),
                ("reason", models.TextField(verbose_name="reason")),
                ("suggestion", models.TextField(verbose_name="suggestion")),
                (
                    "source_field",
                    models.CharField(max_length=300, verbose_name="source field"),
                ),
                (
                    "object_url",
                    models.CharField(
                        blank=True,
                        max_length=500,
                        null=True,
                        verbose_name="object URL",
                    ),
                ),
                *audit_fields(),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="issues",
                        to="mlcc.mlccprecheckrun",
                        verbose_name="precheck run",
                    ),
                ),
            ],
            options={
                "verbose_name": "MLCC precheck issue",
                "verbose_name_plural": "MLCC precheck issues",
                "db_table": "mlcc_precheck_issue",
                "ordering": ("run", "sequence"),
            },
        ),
        migrations.AddConstraint(
            model_name="mlccprecheckissue",
            constraint=models.UniqueConstraint(
                fields=("run", "sequence"),
                name="mlcc_precheck_issue_sequence_uniq",
            ),
        ),
    ]
