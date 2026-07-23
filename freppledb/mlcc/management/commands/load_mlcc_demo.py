from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from freppledb.common.middleware import _thread_locals
from freppledb.input.models import (
    Item,
    Location,
    ManufacturingOrder,
    Operation,
    OperationResource,
    Resource,
)
from freppledb.mlcc.models import (
    MlccBatchGenealogy,
    MlccCompatibilityRule,
    MlccEquipmentCapability,
    MlccFurnaceLoad,
    MlccFurnaceLoadItem,
    MlccQualityHold,
    MlccRecipe,
    MlccScheduleResult,
    MlccScheduleRun,
    MlccSetupMatrix,
)

STAGES = (
    ("stacking", "叠层", "MLCC-STACK-01", "MLCC-STK-B001"),
    ("lamination", "层压", "MLCC-LAM-01", "MLCC-LAM-B001"),
    ("cutting", "切割", "MLCC-CUT-01", "MLCC-CUT-B001"),
    ("debinding", "排胶", "MLCC-DEB-F01", "MLCC-DEB-B001"),
    ("sintering", "烧结", "MLCC-SIN-F01", "MLCC-SIN-B001"),
)


class Command(BaseCommand):
    help = "Load an idempotent five-stage MLCC demonstration data set"

    def add_arguments(self, parser):
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)

    def handle(self, *args, **options):
        database = options["database"]
        previous_database = getattr(_thread_locals, "database", None)
        setattr(_thread_locals, "database", database)
        try:
            with transaction.atomic(using=database):
                return self.load_demo(database)
        finally:
            if previous_database is None:
                try:
                    delattr(_thread_locals, "database")
                except AttributeError:
                    pass
            else:
                setattr(_thread_locals, "database", previous_database)

    def load_demo(self, database):
        now = timezone.now().replace(microsecond=0)
        today = now.date()
        source = "mlcc_demo"

        location, _ = Location.objects.using(database).update_or_create(
            name="MLCC示范工厂",
            defaults={"description": "MLCC五工序演示工厂", "source": source},
        )
        item, _ = Item.objects.using(database).update_or_create(
            name="MLCC-0603-X7R-10UF",
            defaults={
                "description": "0603 X7R 10uF MLCC示范产品",
                "category": "MLCC",
                "source": source,
                "mlcc_material_type": "finished_chip",
                "mlcc_product_family": "X7R",
                "mlcc_chip_size": "0603",
                "mlcc_layer_count": 320,
                "mlcc_quality_grade": "A",
            },
        )

        resources = {}
        operations = {}
        recipes = {}
        orders = {}
        for sequence, (stage, chinese, resource_name, batch) in enumerate(STAGES, 1):
            is_furnace = stage in ("debinding", "sintering")
            capacity = Decimal("1200") if is_furnace else Decimal("1")
            resource, _ = Resource.objects.using(database).update_or_create(
                name=resource_name,
                defaults={
                    "description": f"{chinese}设备",
                    "location": location,
                    "maximum": capacity,
                    "source": source,
                    "mlcc_equipment_group": stage,
                    "mlcc_is_furnace": is_furnace,
                    "mlcc_nominal_capacity": capacity,
                },
            )
            operation, _ = Operation.objects.using(database).update_or_create(
                name=f"MLCC-{sequence:02d}-{chinese}",
                defaults={
                    "description": f"MLCC {chinese}工序",
                    "type": "fixed_time",
                    "location": location,
                    "item": item,
                    "duration": timedelta(hours=2 if not is_furnace else 8),
                    "source": source,
                    "mlcc_process_stage": stage,
                    "mlcc_recipe_required": True,
                    "mlcc_batch_required": True,
                },
            )
            OperationResource.objects.using(database).update_or_create(
                operation=operation,
                resource=resource,
                defaults={"quantity": Decimal("1"), "source": source},
            )
            recipe, _ = MlccRecipe.objects.using(database).update_or_create(
                name=f"{chinese}标准配方",
                version="V1.0",
                defaults={
                    "effective_date": today,
                    "process_stage": stage,
                    "item": item,
                    "operation": operation,
                    "active": True,
                    "parameters": {
                        "demo": True,
                        "temperature_c": 1250 if stage == "sintering" else None,
                    },
                    "source": source,
                },
            )
            MlccEquipmentCapability.objects.using(database).update_or_create(
                resource=resource,
                process_stage=stage,
                recipe=recipe,
                item=item,
                defaults={
                    "minimum_quantity": Decimal("1"),
                    "maximum_quantity": capacity,
                    "enabled": True,
                    "source": source,
                },
            )
            start = now + timedelta(hours=(sequence - 1) * 10)
            order, _ = ManufacturingOrder.objects.using(database).update_or_create(
                reference=f"MLCC-MO-{sequence:03d}",
                defaults={
                    "status": "approved",
                    "operation": operation,
                    "quantity": Decimal("500"),
                    "startdate": start,
                    "enddate": start + timedelta(hours=8 if is_furnace else 2),
                    "batch": batch,
                    "source": source,
                    "mlcc_batch_code": batch,
                    "mlcc_lot_number": "MLCC-DEMO-LOT-001",
                    "mlcc_recipe_version": "V1.0",
                    "mlcc_schedulable": True,
                },
            )
            resources[stage] = resource
            operations[stage] = operation
            recipes[stage] = recipe
            orders[stage] = order

        batches = [entry[3] for entry in STAGES]
        for index in range(len(batches) - 1):
            MlccBatchGenealogy.objects.using(database).update_or_create(
                parent_batch=batches[index],
                child_batch=batches[index + 1],
                defaults={
                    "process_stage": STAGES[index + 1][0],
                    "quantity": Decimal("500"),
                    "source": source,
                },
            )

        MlccCompatibilityRule.objects.using(database).update_or_create(
            name="X7R与C0G禁止同炉",
            defaults={
                "process_stage": "sintering",
                "family_a": "C0G",
                "family_b": "X7R",
                "rule_type": "forbid",
                "reason": "烧结曲线和气氛窗口不同",
                "enabled": True,
                "priority": 1,
                "source": source,
            },
        )

        sintering_v2, _ = MlccRecipe.objects.using(database).update_or_create(
            name="烧结标准配方",
            version="V2.0",
            defaults={
                "effective_date": today + timedelta(days=30),
                "process_stage": "sintering",
                "item": item,
                "operation": operations["sintering"],
                "active": False,
                "parameters": {"temperature_c": 1260, "demo": True},
                "source": source,
            },
        )
        MlccSetupMatrix.objects.using(database).update_or_create(
            resource=resources["sintering"],
            process_stage="sintering",
            from_recipe=recipes["sintering"],
            to_recipe=sintering_v2,
            defaults={
                "setup_time": timedelta(hours=1),
                "setup_cost": Decimal("200"),
                "source": source,
            },
        )

        furnace_load, _ = MlccFurnaceLoad.objects.using(database).update_or_create(
            reference="MLCC-FL-001",
            defaults={
                "resource": resources["sintering"],
                "recipe": recipes["sintering"],
                "planned_start": orders["sintering"].startdate,
                "planned_end": orders["sintering"].enddate,
                "status": "ready",
                "capacity": Decimal("1200"),
                "source": source,
            },
        )
        MlccFurnaceLoadItem.objects.using(database).update_or_create(
            furnace_load=furnace_load,
            manufacturing_order=orders["sintering"],
            defaults={
                "batch_code": batches[-1],
                "quantity": Decimal("500"),
                "sequence": 1,
                "source": source,
            },
        )

        # A second cutting order demonstrates the hold-to-schedule validation.
        held_order, _ = ManufacturingOrder.objects.using(database).update_or_create(
            reference="MLCC-MO-HOLD-001",
            defaults={
                "status": "approved",
                "operation": operations["cutting"],
                "quantity": Decimal("100"),
                "startdate": now + timedelta(hours=22),
                "enddate": now + timedelta(hours=24),
                "batch": "MLCC-CUT-HOLD-001",
                "source": source,
                "mlcc_batch_code": "MLCC-CUT-HOLD-001",
                "mlcc_lot_number": "MLCC-DEMO-LOT-HOLD",
                "mlcc_recipe_version": "V1.0",
                # Create it non-schedulable before applying the active hold.
                "mlcc_schedulable": False,
            },
        )
        MlccQualityHold.objects.using(database).update_or_create(
            batch_code="MLCC-CUT-HOLD-001",
            manufacturing_order=held_order,
            status="active",
            defaults={
                "hold_type": "dimension_check",
                "reason": "切割尺寸抽检待判定",
                "held_at": now,
                "released_at": None,
                "source": source,
            },
        )

        run, _ = MlccScheduleRun.objects.using(database).update_or_create(
            name="MLCC-DEMO-RUN-001",
            defaults={
                "status": "complete",
                "horizon_start": now,
                "horizon_end": now + timedelta(days=7),
                "requested_at": now,
                "started_at": now,
                "finished_at": now,
                "parameters": {"solver": None, "demo": True},
                "message": "数据交换演示；本阶段未调用求解器",
                "source": source,
            },
        )
        for sequence, (stage, _, _, batch) in enumerate(STAGES, 1):
            order = orders[stage]
            MlccScheduleResult.objects.using(database).update_or_create(
                run=run,
                manufacturing_order=order,
                defaults={
                    "resource": resources[stage],
                    "furnace_load": furnace_load if stage == "sintering" else None,
                    "batch_code": batch,
                    "planned_start": order.startdate,
                    "planned_end": order.enddate,
                    "quantity": order.quantity,
                    "status": "scheduled",
                    "sequence": sequence,
                    "score": None,
                    "details": {"demo": True, "solver_generated": False},
                    "source": source,
                },
            )
        MlccScheduleResult.objects.using(database).update_or_create(
            run=run,
            manufacturing_order=held_order,
            defaults={
                "resource": resources["cutting"],
                "batch_code": "MLCC-CUT-HOLD-001",
                "planned_start": None,
                "planned_end": None,
                "quantity": held_order.quantity,
                "status": "blocked",
                "sequence": 99,
                "details": {"blocked_by": "quality_hold", "solver_generated": False},
                "source": source,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                "MLCC demo loaded: 5 stages, 5 resources, 6 orders, 6 recipes and 1 furnace load."
            )
        )
