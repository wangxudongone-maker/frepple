"""Deterministic MLCC phase-2 demonstration data sets."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import DEFAULT_DB_ALIAS, transaction

from freppledb.input.models import (
    Buffer,
    Calendar,
    CalendarBucket,
    Customer,
    Demand,
    Item,
    Location,
    Operation,
    OperationDependency,
    OperationMaterial,
    OperationPlan,
    OperationPlanResource,
    OperationResource,
    Resource,
)
from freppledb.mlcc.models import (
    MlccCompatibilityRule,
    MlccEquipmentCapability,
    MlccFurnaceLoad,
    MlccFurnaceLoadItem,
    MlccFurnaceProgram,
    MlccFurnaceStateSnapshot,
    MlccFurnaceTransition,
    MlccFurnaceTransitionRule,
    MlccLoadUnitConversion,
    MlccQualityHold,
    MlccRecipe,
    MlccScheduleRun,
    MlccSetupMatrix,
)

VALID_SOURCE = "mlcc_valid_demo"
INVALID_SOURCE = "mlcc_invalid_demo"
SAME_PROGRAM_SOURCE = "mlcc_same_program_demo"
TRANSITION_SOURCE = "mlcc_transition_demo"
# frePPLe stores local factory datetimes with USE_TZ=False. The extractor attaches
# the configured factory timezone and publishes an offset-aware schema origin.
DEMO_ORIGIN = datetime(2026, 1, 5)

STAGES = (
    ("stacking", "叠层", 60),
    ("lamination", "层压", 60),
    ("cutting", "切割", 45),
    ("debinding", "排胶", 360),
    ("sintering", "烧结", 480),
)


class SolverDemoLoader:
    """Create repeatable data without invoking a scheduling solver."""

    def __init__(self, database=DEFAULT_DB_ALIAS):
        self.database = database

    def _delete_source(self, source):
        # Delete only the named demo namespace, in foreign-key order.
        MlccQualityHold.objects.using(self.database).filter(source=source).delete()
        MlccFurnaceTransition.objects.using(self.database).filter(
            source=source
        ).delete()
        MlccFurnaceLoadItem.objects.using(self.database).filter(
            furnace_load__source=source
        ).delete()
        MlccFurnaceLoad.objects.using(self.database).filter(source=source).delete()
        MlccScheduleRun.objects.using(self.database).filter(source=source).delete()
        MlccFurnaceStateSnapshot.objects.using(self.database).filter(
            source=source
        ).delete()
        MlccFurnaceTransitionRule.objects.using(self.database).filter(
            source=source
        ).delete()
        OperationPlanResource.objects.using(self.database).filter(
            operationplan__source=source
        ).delete()
        OperationPlan.objects.using(self.database).filter(source=source).delete()
        Demand.objects.using(self.database).filter(source=source).delete()
        OperationDependency.objects.using(self.database).filter(source=source).delete()
        OperationMaterial.objects.using(self.database).filter(source=source).delete()
        OperationResource.objects.using(self.database).filter(source=source).delete()
        MlccSetupMatrix.objects.using(self.database).filter(source=source).delete()
        MlccCompatibilityRule.objects.using(self.database).filter(
            source=source
        ).delete()
        MlccEquipmentCapability.objects.using(self.database).filter(
            source=source
        ).delete()
        MlccLoadUnitConversion.objects.using(self.database).filter(
            source=source
        ).delete()
        MlccRecipe.objects.using(self.database).filter(source=source).delete()
        MlccFurnaceProgram.objects.using(self.database).filter(source=source).delete()
        Buffer.objects.using(self.database).filter(source=source).delete()
        Operation.objects.using(self.database).filter(source=source).delete()
        Resource.objects.using(self.database).filter(source=source).delete()
        CalendarBucket.objects.using(self.database).filter(source=source).delete()
        Calendar.objects.using(self.database).filter(source=source).delete()
        Item.objects.using(self.database).filter(source=source).delete()
        Customer.objects.using(self.database).filter(source=source).delete()
        Location.objects.using(self.database).filter(source=source).delete()

    def load_valid(
        self,
        batches=100,
        *,
        source=VALID_SOURCE,
        dataset="valid_demo",
        namespace="MLCC-P2",
    ):
        batches = int(batches)
        if not 100 <= batches <= 500:
            raise ValueError("valid_demo batch count must be between 100 and 500")
        prefix = f"{namespace}-VALID"
        program_prefix = "" if source == VALID_SOURCE else f"{namespace}-"
        product_family = "X7R" if source == VALID_SOURCE else namespace
        quantity = Decimal("100")
        with transaction.atomic(using=self.database):
            self._delete_source(source)
            location = Location.objects.using(self.database).create(
                name=f"{prefix}-FACTORY",
                description="MLCC排产有效演示工厂",
                source=source,
            )
            customer = Customer.objects.using(self.database).create(
                name=f"{prefix}-CUSTOMER",
                description="MLCC有效演示客户",
                source=source,
            )
            item = Item.objects.using(self.database).create(
                name=f"{namespace}-0603-X7R",
                description="第二阶段有效演示产品",
                category="MLCC",
                source=source,
                mlcc_material_type="finished_chip",
                mlcc_product_family=product_family,
                mlcc_chip_size="0603",
                mlcc_layer_count=320,
                mlcc_quality_grade="A",
            )
            raw_item = Item.objects.using(self.database).create(
                name=f"{namespace}-RAW-TAPE",
                description="陶瓷生带",
                category="MLCC-RAW",
                source=source,
                mlcc_material_type="raw_material",
            )
            Buffer.objects.using(self.database).create(
                item=raw_item,
                location=location,
                batch="",
                onhand=quantity * batches,
                source=source,
            )

            operations = {}
            resources = {}
            recipes = {}
            programs = {}
            for sequence, (stage, chinese, minutes) in enumerate(STAGES, 1):
                furnace = stage in ("debinding", "sintering")
                resource = Resource.objects.using(self.database).create(
                    name=f"{prefix}-{stage.upper()}-01",
                    description=f"{chinese}有效演示设备",
                    location=location,
                    maximum=Decimal("1000"),
                    source=source,
                    mlcc_equipment_group=stage,
                    mlcc_is_furnace=furnace,
                    mlcc_nominal_capacity=Decimal("1000"),
                    mlcc_load_unit="tray" if furnace else "panel",
                )
                operation = Operation.objects.using(self.database).create(
                    name=f"{prefix}-{sequence:02d}-{stage.upper()}",
                    description=f"{chinese}标准工序",
                    type="fixed_time",
                    location=location,
                    item=item,
                    duration=timedelta(minutes=minutes),
                    sizeminimum=Decimal("1"),
                    sizemaximum=Decimal("5000"),
                    source=source,
                    mlcc_process_stage=stage,
                    mlcc_recipe_required=stage in ("debinding", "sintering"),
                    mlcc_batch_required=True,
                    mlcc_max_wait_time=timedelta(days=2),
                )
                OperationResource.objects.using(self.database).create(
                    operation=operation,
                    resource=resource,
                    quantity=Decimal("1"),
                    source=source,
                )
                program = None
                if furnace:
                    program = MlccFurnaceProgram.objects.using(self.database).create(
                        id=f"mlcc-demo:{source}:{stage}:v1",
                        program_key=f"{program_prefix}{stage.upper()}-PROGRAM-V1",
                        version="V1",
                        process_stage=stage,
                        atmosphere_key=f"{stage}-atmosphere-a",
                        required_pre_state_key=f"{stage}:idle",
                        resulting_post_state_key=f"{stage}:program-v1-ready",
                        effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                        active=True,
                        source=source,
                    )
                recipe = MlccRecipe.objects.using(self.database).create(
                    name=f"{namespace}-{stage.upper()}-RECIPE",
                    version="V1",
                    effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                    process_stage=stage,
                    item=item,
                    operation=operation,
                    active=True,
                    furnace_program=program,
                    furnace_program_key=(
                        (
                            f"{program_prefix}{stage.upper()}-PROGRAM-V1"
                            if furnace
                            else None
                        )
                    ),
                    compatibility_group=(
                        f"{stage.upper()}-CERTIFIED-X7R" if furnace else None
                    ),
                    parameters={"setup_family": f"{stage}-family-a", "demo": True},
                    source=source,
                )
                MlccEquipmentCapability.objects.using(self.database).create(
                    resource=resource,
                    process_stage=stage,
                    recipe=recipe,
                    item=item,
                    minimum_quantity=Decimal("1"),
                    maximum_quantity=Decimal("1000"),
                    enabled=True,
                    source=source,
                )
                operations[stage] = operation
                resources[stage] = resource
                recipes[stage] = recipe
                if program:
                    programs[stage] = program

            for stage in ("debinding", "sintering"):
                program = programs[stage]
                MlccFurnaceStateSnapshot.objects.using(self.database).create(
                    resource=resources[stage],
                    observed_at=DEMO_ORIGIN - timedelta(minutes=60),
                    state_key=program.required_pre_state_key,
                    current_program=None,
                    available_at=DEMO_ORIGIN,
                    source=source,
                )
                for index, from_state in enumerate(
                    (
                        program.required_pre_state_key,
                        program.resulting_post_state_key,
                    ),
                    1,
                ):
                    MlccFurnaceTransitionRule.objects.using(self.database).create(
                        resource=resources[stage],
                        process_stage=stage,
                        from_state_key=from_state,
                        to_program=program,
                        transition_type="none",
                        duration=timedelta(0),
                        setup_cost=Decimal("0"),
                        allowed=True,
                        enabled=True,
                        priority=index,
                        effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                        source=source,
                    )

            OperationMaterial.objects.using(self.database).create(
                operation=operations["stacking"],
                item=raw_item,
                location=location,
                quantity=Decimal("-1"),
                source=source,
            )
            for previous, current in zip(STAGES, STAGES[1:]):
                OperationDependency.objects.using(self.database).create(
                    operation=operations[current[0]],
                    blockedby=operations[previous[0]],
                    quantity=Decimal("1"),
                    source=source,
                )

            alternate_program = MlccFurnaceProgram.objects.using(self.database).create(
                id=f"mlcc-demo:{source}:sintering:v2",
                program_key=f"{program_prefix}SINTERING-PROGRAM-V2",
                version="V2",
                process_stage="sintering",
                atmosphere_key="sintering-atmosphere-b",
                required_pre_state_key="sintering:program-v1-ready",
                resulting_post_state_key="sintering:program-v2-ready",
                effective_date=DEMO_ORIGIN.date() - timedelta(days=15),
                active=True,
                source=source,
            )
            alternate = MlccRecipe.objects.using(self.database).create(
                name=f"{namespace}-SINTERING-RECIPE",
                version="V2",
                effective_date=DEMO_ORIGIN.date() - timedelta(days=15),
                process_stage="sintering",
                item=item,
                operation=operations["sintering"],
                active=True,
                furnace_program=alternate_program,
                furnace_program_key=f"{program_prefix}SINTERING-PROGRAM-V2",
                compatibility_group="SINTERING-CERTIFIED-X7R-V2",
                parameters={"setup_family": "sintering-family-b", "demo": True},
                source=source,
            )
            MlccSetupMatrix.objects.using(self.database).create(
                resource=resources["sintering"],
                process_stage="sintering",
                from_recipe=recipes["sintering"],
                to_recipe=alternate,
                setup_time=timedelta(minutes=90),
                setup_cost=Decimal("100"),
                source=source,
            )
            MlccCompatibilityRule.objects.using(self.database).create(
                name=f"{prefix}-X7R-C0G",
                process_stage="sintering",
                family_a=product_family,
                family_b=f"{product_family}-INCOMPATIBLE",
                rule_type="forbid",
                reason="烧结曲线不同",
                enabled=True,
                source=source,
            )
            for stage in ("debinding", "sintering"):
                MlccCompatibilityRule.objects.using(self.database).create(
                    name=f"{prefix}-X7R-X7R-{stage.upper()}",
                    process_stage=stage,
                    family_a=product_family,
                    family_b=product_family,
                    rule_type="allow",
                    reason="同一认证产品族允许同炉",
                    enabled=True,
                    source=source,
                )

            demands = []
            orders = []
            for batch_index in range(1, batches + 1):
                lot = f"{namespace}-V-{batch_index:04d}"
                due = DEMO_ORIGIN + timedelta(days=12)
                demands.append(
                    Demand(
                        name=f"{namespace}-V-SO-{batch_index:04d}",
                        customer=customer,
                        item=item,
                        location=location,
                        due=due,
                        status="open",
                        quantity=quantity,
                        priority=(batch_index % 10) + 1,
                        batch=lot,
                        source=source,
                    )
                )
                cursor = DEMO_ORIGIN + timedelta(days=3, minutes=batch_index * 5)
                for sequence, (stage, _, minutes) in enumerate(STAGES, 1):
                    end = cursor + timedelta(minutes=minutes)
                    orders.append(
                        OperationPlan(
                            reference=f"{namespace}-V-MO-{batch_index:04d}-{sequence}",
                            type="MO",
                            status="proposed",
                            operation=operations[stage],
                            quantity=quantity,
                            startdate=cursor,
                            enddate=end,
                            due=due,
                            batch=lot,
                            source=source,
                            mlcc_batch_code=lot,
                            mlcc_lot_number=lot,
                            mlcc_recipe_version="V1",
                            mlcc_schedulable=True,
                            mlcc_load_quantity=(
                                Decimal("1")
                                if stage in ("debinding", "sintering")
                                else None
                            ),
                            mlcc_load_unit=(
                                "tray" if stage in ("debinding", "sintering") else None
                            ),
                        )
                    )
                    cursor = end + timedelta(minutes=15)
            Demand.objects.using(self.database).bulk_create(demands, batch_size=500)
            OperationPlan.objects.using(self.database).bulk_create(
                orders, batch_size=500
            )
        return {
            "dataset": dataset,
            "source": source,
            "batches": batches,
            "tasks": batches * len(STAGES),
            "origin": DEMO_ORIGIN.isoformat(),
        }

    def load_same_program(self, batches=100):
        """Load phase-3C zero-transition data without sharing business keys."""

        return self.load_valid(
            batches,
            source=SAME_PROGRAM_SOURCE,
            dataset="same_program_demo",
            namespace="MLCC-P3C-SAME",
        )

    def load_transition(self, batches=100):
        """Load three furnace programs, two furnaces and directional changes."""

        result = self.load_valid(
            batches,
            source=TRANSITION_SOURCE,
            dataset="transition_demo",
            namespace="MLCC-P3C-TRANSITION",
        )
        source = TRANSITION_SOURCE
        namespace = "MLCC-P3C-TRANSITION"
        with transaction.atomic(using=self.database):
            location = Location.objects.using(self.database).get(
                name=f"{namespace}-VALID-FACTORY"
            )
            item = Item.objects.using(self.database).get(name=f"{namespace}-0603-X7R")
            operation = Operation.objects.using(self.database).get(
                name=f"{namespace}-VALID-05-SINTERING"
            )
            primary = Resource.objects.using(self.database).get(
                name=f"{namespace}-VALID-SINTERING-01"
            )
            secondary = Resource.objects.using(self.database).create(
                name=f"{namespace}-VALID-SINTERING-02",
                description="烧结转换演示二号炉",
                location=location,
                maximum=Decimal("1000"),
                source=source,
                mlcc_equipment_group="sintering",
                mlcc_is_furnace=True,
                mlcc_nominal_capacity=Decimal("1000"),
                mlcc_load_unit="tray",
            )
            OperationResource.objects.using(self.database).create(
                operation=operation,
                resource=secondary,
                quantity=Decimal("1"),
                source=source,
            )

            programs = list(
                MlccFurnaceProgram.objects.using(self.database)
                .filter(source=source, process_stage="sintering")
                .order_by("version")
            )
            third_program = MlccFurnaceProgram.objects.using(self.database).create(
                id=f"mlcc-demo:{source}:sintering:v3",
                program_key=f"{namespace}-SINTERING-PROGRAM-V3",
                version="V3",
                process_stage="sintering",
                atmosphere_key="sintering-atmosphere-c",
                required_pre_state_key="sintering:program-v2-ready",
                resulting_post_state_key="sintering:program-v3-ready",
                effective_date=DEMO_ORIGIN.date() - timedelta(days=10),
                active=True,
                source=source,
            )
            third_recipe = MlccRecipe.objects.using(self.database).create(
                name=f"{namespace}-SINTERING-RECIPE",
                version="V3",
                effective_date=DEMO_ORIGIN.date() - timedelta(days=10),
                process_stage="sintering",
                item=item,
                operation=operation,
                active=True,
                furnace_program=third_program,
                furnace_program_key=third_program.program_key,
                compatibility_group="SINTERING-CERTIFIED-X7R-V3",
                parameters={
                    "setup_family": "sintering-family-c",
                    "demo": True,
                },
                source=source,
            )
            programs.append(third_program)
            recipes = list(
                MlccRecipe.objects.using(self.database)
                .filter(source=source, process_stage="sintering")
                .select_related("furnace_program")
                .order_by("version")
            )
            for resource in (primary, secondary):
                for recipe in recipes:
                    MlccEquipmentCapability.objects.using(self.database).get_or_create(
                        resource=resource,
                        process_stage="sintering",
                        recipe=recipe,
                        item=item,
                        defaults={
                            "minimum_quantity": Decimal("1"),
                            "maximum_quantity": Decimal("1000"),
                            "enabled": True,
                            "source": source,
                        },
                    )

            sintering_orders = list(
                OperationPlan.objects.using(self.database)
                .filter(source=source, operation=operation)
                .order_by("reference")
            )
            versions = ("V1", "V2", "V3")
            for index, order in enumerate(sintering_orders):
                order.mlcc_recipe_version = versions[index % len(versions)]
            OperationPlan.objects.using(self.database).bulk_update(
                sintering_orders,
                ("mlcc_recipe_version",),
                batch_size=500,
            )

            MlccFurnaceTransitionRule.objects.using(self.database).filter(
                source=source,
                process_stage="sintering",
            ).delete()
            program_by_version = {item.version: item for item in programs}
            state_by_version = {
                item.version: item.resulting_post_state_key for item in programs
            }
            initial_state = program_by_version["V1"].required_pre_state_key
            transition_minutes = {
                ("V1", "V1"): 0,
                ("V1", "V2"): 60,
                ("V1", "V3"): 90,
                ("V2", "V1"): 20,
                ("V2", "V2"): 0,
                ("V2", "V3"): 40,
                ("V3", "V1"): 30,
                ("V3", "V2"): 70,
                ("V3", "V3"): 0,
            }
            rules = []
            for target_version, target_program in sorted(program_by_version.items()):
                initial_duration = {
                    "V1": 0,
                    "V2": 30,
                    "V3": 45,
                }[target_version]
                rules.append(
                    MlccFurnaceTransitionRule(
                        equipment_group="sintering",
                        process_stage="sintering",
                        from_state_key=initial_state,
                        to_program=target_program,
                        transition_type=(
                            "none" if initial_duration == 0 else "atmosphere_purge"
                        ),
                        duration=timedelta(minutes=initial_duration),
                        setup_cost=Decimal(initial_duration),
                        allowed=True,
                        enabled=True,
                        priority=10,
                        effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                        source=source,
                    )
                )
            for (from_version, target_version), minutes in sorted(
                transition_minutes.items()
            ):
                rules.append(
                    MlccFurnaceTransitionRule(
                        equipment_group="sintering",
                        process_stage="sintering",
                        from_state_key=state_by_version[from_version],
                        to_program=program_by_version[target_version],
                        transition_type="none" if minutes == 0 else "cleaning",
                        duration=timedelta(minutes=minutes),
                        setup_cost=Decimal(minutes),
                        allowed=True,
                        enabled=True,
                        priority=10,
                        effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                        source=source,
                    )
                )
            MlccFurnaceTransitionRule.objects.using(self.database).bulk_create(rules)
            # Equipment-specific A->B rule overrides the group rule on furnace 2.
            MlccFurnaceTransitionRule.objects.using(self.database).create(
                resource=secondary,
                process_stage="sintering",
                from_state_key=state_by_version["V1"],
                to_program=program_by_version["V2"],
                transition_type="cleaning",
                duration=timedelta(minutes=30),
                setup_cost=Decimal("30"),
                allowed=True,
                enabled=True,
                priority=0,
                effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                source=source,
            )
            MlccFurnaceStateSnapshot.objects.using(self.database).create(
                resource=secondary,
                observed_at=DEMO_ORIGIN - timedelta(minutes=60),
                state_key=initial_state,
                current_program=None,
                available_at=DEMO_ORIGIN,
                source=source,
            )

            frozen_order = sintering_orders[0]
            frozen_order.status = "approved"
            frozen_order.mlcc_recipe_version = "V1"
            frozen_order.save(
                using=self.database,
                update_fields=("status", "mlcc_recipe_version", "lastmodified"),
            )
            OperationPlanResource.objects.using(self.database).create(
                operationplan=frozen_order,
                resource=primary,
                quantity=Decimal("1"),
                status="confirmed",
                source=source,
            )
            run = MlccScheduleRun.objects.using(self.database).create(
                name=f"{namespace}-FROZEN-RUN",
                status="complete",
                horizon_start=DEMO_ORIGIN,
                horizon_end=DEMO_ORIGIN + timedelta(days=180),
                requested_at=DEMO_ORIGIN,
                started_at=DEMO_ORIGIN,
                finished_at=DEMO_ORIGIN,
                parameters={"demo": "phase3c frozen sequence"},
                source=source,
            )
            recipe_v1 = next(item for item in recipes if item.version == "V1")
            frozen_load = MlccFurnaceLoad.objects.using(self.database).create(
                reference=f"{namespace}-FROZEN-LOAD",
                resource=primary,
                recipe=recipe_v1,
                furnace_program=program_by_version["V1"],
                run=run,
                operation_type="sintering",
                furnace_program_key=program_by_version["V1"].program_key,
                planned_start=frozen_order.startdate,
                planned_end=frozen_order.enddate,
                status="ready",
                capacity=Decimal("1000"),
                loaded_quantity=Decimal("1"),
                load_unit="tray",
                frozen=True,
                details={"demo": "phase3c frozen load"},
                source=source,
            )
            MlccFurnaceLoadItem.objects.using(self.database).create(
                furnace_load=frozen_load,
                manufacturing_order=frozen_order,
                batch_code=frozen_order.batch,
                quantity=Decimal("1"),
                load_unit="tray",
                conversion_trace={"conversion_id": "identity"},
                source=source,
            )
            initial_rule = next(
                item
                for item in rules
                if item.from_state_key == initial_state
                and item.to_program_id == program_by_version["V1"].id
            )
            persisted_initial_rule = (
                MlccFurnaceTransitionRule.objects.using(self.database)
                .filter(
                    equipment_group="sintering",
                    from_state_key=initial_rule.from_state_key,
                    to_program=initial_rule.to_program,
                    source=source,
                )
                .order_by("id")
                .first()
            )
            MlccFurnaceTransition.objects.using(self.database).create(
                run=run,
                resource=primary,
                predecessor_load=None,
                successor_load=frozen_load,
                transition_rule=persisted_initial_rule,
                transition_type="none",
                planned_start=frozen_order.startdate,
                planned_end=frozen_order.startdate,
                status="proposed",
                details={"demo": "frozen initial transition"},
                source=source,
            )
        result["programs"] = 3
        result["sintering_furnaces"] = 2
        result["frozen_loads"] = 1
        return result

    def load_invalid(self):
        source = INVALID_SOURCE
        quantity = Decimal("100")
        with transaction.atomic(using=self.database):
            self._delete_source(source)
            location = Location.objects.using(self.database).create(
                name="MLCC-P2-INVALID-FACTORY",
                description="MLCC排产无效演示工厂",
                source=source,
            )
            customer = Customer.objects.using(self.database).create(
                name="MLCC-P2-INVALID-CUSTOMER",
                description="MLCC无效演示客户",
                source=source,
            )
            item = Item.objects.using(self.database).create(
                name="MLCC-P2-INVALID-X7R",
                description="第二阶段无效演示产品",
                category="MLCC",
                source=source,
                mlcc_material_type="finished_chip",
                mlcc_product_family="X7R",
            )
            raw_item = Item.objects.using(self.database).create(
                name="MLCC-P2-INVALID-RAW",
                description="故意缺少库存的原料",
                category="MLCC-RAW",
                source=source,
                mlcc_material_type="raw_material",
            )

            downtime = Calendar.objects.using(self.database).create(
                name="MLCC-P2-INVALID-DOWNTIME",
                description="冻结任务冲突停机日历",
                defaultvalue=Decimal("1"),
                source=source,
            )
            CalendarBucket.objects.using(self.database).create(
                calendar=downtime,
                startdate=DEMO_ORIGIN,
                enddate=DEMO_ORIGIN + timedelta(days=1),
                value=Decimal("0"),
                source=source,
            )

            operations = {}
            for sequence, (stage, chinese, minutes) in enumerate(STAGES, 1):
                operations[stage] = Operation.objects.using(self.database).create(
                    name=f"MLCC-P2-INVALID-{sequence:02d}-{stage.upper()}",
                    description=f"故意无效的{chinese}工序",
                    type="fixed_time",
                    location=location,
                    item=item,
                    duration=timedelta(minutes=0 if stage == "stacking" else minutes),
                    sizeminimum=Decimal("1"),
                    sizemaximum=Decimal("1000"),
                    source=source,
                    mlcc_process_stage=stage,
                    mlcc_recipe_required=stage in ("debinding", "sintering"),
                    mlcc_batch_required=True,
                    mlcc_max_wait_time=(
                        timedelta(minutes=1) if stage == "debinding" else None
                    ),
                )
            OperationMaterial.objects.using(self.database).create(
                operation=operations["stacking"],
                item=raw_item,
                location=location,
                quantity=Decimal("-1"),
                source=source,
            )
            # Two directed dependencies form a cycle. The cutting task is omitted.
            OperationDependency.objects.using(self.database).bulk_create(
                [
                    OperationDependency(
                        operation=operations["stacking"],
                        blockedby=operations["lamination"],
                        source=source,
                    ),
                    OperationDependency(
                        operation=operations["lamination"],
                        blockedby=operations["stacking"],
                        source=source,
                    ),
                    OperationDependency(
                        operation=operations["debinding"],
                        blockedby=operations["lamination"],
                        hard_safety_leadtime=timedelta(minutes=60),
                        source=source,
                    ),
                ]
            )

            lamination_resource = Resource.objects.using(self.database).create(
                name="MLCC-P2-INVALID-LAM-01",
                location=location,
                maximum=Decimal("1"),
                source=source,
                mlcc_equipment_group="lamination",
                mlcc_nominal_capacity=Decimal("1"),
                mlcc_load_unit="panel",
            )
            debinding_resource = Resource.objects.using(self.database).create(
                name="MLCC-P2-INVALID-DEB-01",
                location=location,
                maximum=Decimal("0"),
                source=source,
                mlcc_equipment_group="debinding",
                mlcc_is_furnace=True,
                mlcc_nominal_capacity=Decimal("0"),
                mlcc_load_unit="",
            )
            sintering_resource = Resource.objects.using(self.database).create(
                name="MLCC-P2-INVALID-SIN-01",
                location=location,
                available=downtime,
                maximum=Decimal("1000"),
                source=source,
                mlcc_equipment_group="sintering",
                mlcc_is_furnace=True,
                mlcc_nominal_capacity=Decimal("1000"),
                mlcc_load_unit="tray",
            )
            for stage, resource in (
                ("lamination", lamination_resource),
                ("debinding", debinding_resource),
                ("sintering", sintering_resource),
            ):
                OperationResource.objects.using(self.database).create(
                    operation=operations[stage],
                    resource=resource,
                    quantity=Decimal("1"),
                    source=source,
                )

            invalid_program = MlccFurnaceProgram.objects.using(self.database).create(
                id=f"mlcc-demo:{source}:sintering:invalid",
                program_key="SINTERING-INVALID-PROGRAM",
                version="V1",
                process_stage="sintering",
                atmosphere_key="invalid-atmosphere",
                required_pre_state_key="sintering:missing-initial-state",
                resulting_post_state_key="sintering:invalid-ready",
                effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                active=True,
                source=source,
            )
            expired_recipe = MlccRecipe.objects.using(self.database).create(
                name="MLCC-P2-INVALID-SINTERING-RECIPE",
                version="EXPIRED",
                effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                expiry_date=DEMO_ORIGIN.date() - timedelta(days=1),
                process_stage="sintering",
                item=item,
                operation=operations["sintering"],
                active=True,
                furnace_program=invalid_program,
                furnace_program_key=invalid_program.program_key,
                parameters={"setup_family": "invalid-family"},
                source=source,
            )
            # Bypass model validation on purpose: P021 must identify the legacy
            # key and explicit furnace-program mapping disagreement.
            MlccRecipe.objects.using(self.database).filter(pk=expired_recipe.pk).update(
                furnace_program_key=""
            )
            expired_recipe.furnace_program_key = ""

            # Two rules at the same resolution level and priority are
            # intentionally ambiguous (P023). Their only possible predecessor
            # state is the program's own post-state; the conflict also leaves
            # the furnace program unreachable on every candidate furnace (P024).
            MlccFurnaceTransitionRule.objects.using(self.database).bulk_create(
                [
                    MlccFurnaceTransitionRule(
                        process_stage="sintering",
                        from_state_key=invalid_program.resulting_post_state_key,
                        to_program=invalid_program,
                        transition_type="cleaning",
                        duration=timedelta(minutes=30),
                        setup_cost=Decimal("10"),
                        allowed=True,
                        enabled=True,
                        priority=5,
                        effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                        source=source,
                    ),
                    MlccFurnaceTransitionRule(
                        process_stage="sintering",
                        from_state_key=invalid_program.resulting_post_state_key,
                        to_program=invalid_program,
                        transition_type="empty_run",
                        duration=timedelta(minutes=45),
                        setup_cost=Decimal("20"),
                        allowed=True,
                        enabled=True,
                        priority=5,
                        effective_date=DEMO_ORIGIN.date() - timedelta(days=30),
                        source=source,
                    ),
                ]
            )
            # Lamination intentionally has no capability. Debinding has no recipe.
            MlccEquipmentCapability.objects.using(self.database).bulk_create(
                [
                    MlccEquipmentCapability(
                        resource=debinding_resource,
                        process_stage="debinding",
                        item=item,
                        minimum_quantity=Decimal("1"),
                        maximum_quantity=Decimal("1000"),
                        enabled=True,
                        source=source,
                    ),
                    MlccEquipmentCapability(
                        resource=sintering_resource,
                        process_stage="sintering",
                        recipe=expired_recipe,
                        item=item,
                        minimum_quantity=Decimal("1"),
                        maximum_quantity=Decimal("1000"),
                        enabled=True,
                        source=source,
                    ),
                ]
            )
            # Reversed family order bypasses model normalization but remains legal in
            # the database. The precheck canonicalizes it and reports the conflict.
            MlccCompatibilityRule.objects.using(self.database).bulk_create(
                [
                    MlccCompatibilityRule(
                        name="MLCC-P2-INVALID-COMPAT-ALLOW",
                        process_stage="sintering",
                        family_a="Y5V",
                        family_b="Z5U",
                        rule_type="allow",
                        enabled=True,
                        source=source,
                    ),
                    MlccCompatibilityRule(
                        name="MLCC-P2-INVALID-COMPAT-FORBID",
                        process_stage="sintering",
                        family_a="Z5U",
                        family_b="Y5V",
                        rule_type="forbid",
                        enabled=True,
                        source=source,
                    ),
                ]
            )

            lot = "MLCC-P2-I-0001"
            Demand.objects.using(self.database).create(
                name="MLCC-P2-I-SO-0001",
                customer=customer,
                item=item,
                location=location,
                due=DEMO_ORIGIN + timedelta(days=20),
                status="open",
                quantity=quantity,
                priority=1,
                batch=lot,
                source=source,
            )
            order_rows = []
            # Omitting cutting produces the missing-routing error.
            for sequence, stage in enumerate(
                ("stacking", "lamination", "debinding", "sintering"), 1
            ):
                start = DEMO_ORIGIN + timedelta(minutes=60 + sequence * 15)
                duration = (
                    0
                    if stage == "stacking"
                    else dict((name, minutes) for name, _, minutes in STAGES)[stage]
                )
                order_rows.append(
                    OperationPlan(
                        reference=f"MLCC-P2-I-MO-0001-{sequence}",
                        type="MO",
                        status="approved" if stage == "sintering" else "proposed",
                        operation=operations[stage],
                        quantity=Decimal("90") if stage == "lamination" else quantity,
                        startdate=start,
                        enddate=start + timedelta(minutes=duration),
                        due=DEMO_ORIGIN + timedelta(days=20),
                        batch=lot,
                        source=source,
                        mlcc_batch_code=lot,
                        mlcc_lot_number=lot,
                        mlcc_recipe_version=(
                            "EXPIRED" if stage == "sintering" else "MISSING"
                        ),
                        mlcc_schedulable=True,
                        mlcc_load_quantity=(
                            Decimal("2000")
                            if stage == "sintering"
                            else quantity if stage == "debinding" else None
                        ),
                        mlcc_load_unit=(
                            "tray"
                            if stage == "sintering"
                            else "piece" if stage == "debinding" else None
                        ),
                    )
                )
            OperationPlan.objects.using(self.database).bulk_create(order_rows)
            sintering_order = order_rows[-1]
            OperationPlanResource.objects.using(self.database).create(
                operationplan_id=sintering_order.reference,
                resource=sintering_resource,
                quantity=Decimal("1"),
                status="confirmed",
                source=source,
            )
            frozen_load = MlccFurnaceLoad.objects.using(self.database).create(
                reference="MLCC-P2-INVALID-FROZEN-LOAD",
                resource=sintering_resource,
                recipe=expired_recipe,
                furnace_program=invalid_program,
                operation_type="sintering",
                furnace_program_key=invalid_program.program_key,
                planned_start=sintering_order.startdate,
                planned_end=sintering_order.enddate,
                status="ready",
                capacity=Decimal("999"),
                loaded_quantity=Decimal("1"),
                load_unit="tray",
                frozen=True,
                source=source,
            )
            MlccFurnaceLoadItem.objects.using(self.database).create(
                furnace_load=frozen_load,
                manufacturing_order_id=sintering_order.reference,
                batch_code=lot,
                quantity=Decimal("1"),
                load_unit="tray",
                conversion_trace={"demo": "intentional mismatch"},
                source=source,
            )
            # bulk_create intentionally preserves the inconsistent schedulable flag.
            MlccQualityHold.objects.using(self.database).bulk_create(
                [
                    MlccQualityHold(
                        batch_code=lot,
                        manufacturing_order_id=order_rows[0].reference,
                        hold_type="invalid_demo",
                        reason="故意制造质量冻结与可排产状态冲突",
                        status="active",
                        held_at=DEMO_ORIGIN,
                        source=source,
                    )
                ]
            )
        return {
            "dataset": "invalid_demo",
            "source": source,
            "batches": 1,
            "tasks": 4,
            "origin": DEMO_ORIGIN.isoformat(),
        }
