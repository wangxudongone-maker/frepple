from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import DEFAULT_DB_ALIAS, models
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from freppledb.common.models import AuditModel

PROCESS_STAGES = (
    ("stacking", _("stacking")),
    ("lamination", _("lamination")),
    ("cutting", _("cutting")),
    ("debinding", _("debinding")),
    ("sintering", _("sintering")),
)


class ValidatedAuditModel(AuditModel):
    """Audit model that applies model validation to every write path."""

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        abstract = True


class MlccFurnaceProgram(ValidatedAuditModel):
    """A versioned executable furnace program with explicit state semantics."""

    id = models.CharField(
        _("stable business identifier"),
        primary_key=True,
        max_length=200,
    )
    program_key = models.CharField(
        _("furnace program key"), max_length=100, db_index=True
    )
    version = models.CharField(_("version"), max_length=40)
    process_stage = models.CharField(
        _("process stage"), max_length=30, choices=PROCESS_STAGES
    )
    atmosphere_key = models.CharField(_("atmosphere key"), max_length=100)
    required_pre_state_key = models.CharField(
        _("required pre-state key"), max_length=100
    )
    resulting_post_state_key = models.CharField(
        _("resulting post-state key"), max_length=100
    )
    effective_date = models.DateField(_("effective date"))
    expiry_date = models.DateField(_("expiry date"), null=True, blank=True)
    active = models.BooleanField(_("active"), default=True)

    def __str__(self):
        return f"{self.program_key} {self.version}"

    def clean(self):
        errors = {}
        for field_name in (
            "id",
            "program_key",
            "version",
            "atmosphere_key",
            "required_pre_state_key",
            "resulting_post_state_key",
        ):
            value = (getattr(self, field_name, None) or "").strip()
            if not value:
                errors[field_name] = _("This value is required.")
            else:
                setattr(self, field_name, value)
        if self.process_stage not in ("debinding", "sintering"):
            errors["process_stage"] = _(
                "A furnace program is only valid for debinding or sintering."
            )
        if (
            self.expiry_date
            and self.effective_date
            and self.expiry_date < self.effective_date
        ):
            errors["expiry_date"] = _("Expiry date cannot precede effective date.")
        if errors:
            raise ValidationError(errors)

    class Meta(AuditModel.Meta):
        db_table = "mlcc_furnace_program"
        ordering = ("process_stage", "program_key", "version")
        constraints = [
            models.UniqueConstraint(
                fields=("program_key", "version"),
                name="mlcc_furnace_program_key_version_uniq",
            )
        ]
        verbose_name = _("MLCC furnace program")
        verbose_name_plural = _("MLCC furnace programs")


class MlccRecipe(ValidatedAuditModel):
    id = models.AutoField(_("identifier"), primary_key=True)
    name = models.CharField(_("recipe"), max_length=100, db_index=True)
    version = models.CharField(_("version"), max_length=40)
    effective_date = models.DateField(_("effective date"))
    expiry_date = models.DateField(_("expiry date"), null=True, blank=True)
    process_stage = models.CharField(
        _("process stage"), max_length=30, choices=PROCESS_STAGES
    )
    item = models.ForeignKey(
        "input.Item",
        verbose_name=_("item"),
        related_name="mlcc_recipes",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    operation = models.ForeignKey(
        "input.Operation",
        verbose_name=_("operation"),
        related_name="mlcc_recipes",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    active = models.BooleanField(_("active"), default=True)
    furnace_program_key = models.CharField(
        _("furnace program key"), max_length=100, null=True, blank=True, db_index=True
    )
    furnace_program = models.ForeignKey(
        MlccFurnaceProgram,
        verbose_name=_("furnace program"),
        related_name="recipes",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    compatibility_group = models.CharField(
        _("certified compatibility group"),
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
    )
    parameters = models.JSONField(_("parameters"), default=dict, blank=True)

    def __str__(self):
        return f"{self.name} {self.version}"

    def clean(self):
        errors = {}
        if not (self.version or "").strip():
            errors["version"] = _("A recipe version is required.")
        if not self.effective_date:
            errors["effective_date"] = _("An effective date is required.")
        if (
            self.expiry_date
            and self.effective_date
            and self.expiry_date < self.effective_date
        ):
            errors["expiry_date"] = _("Expiry date cannot precede effective date.")
        if self.furnace_program_id:
            if self.furnace_program.process_stage != self.process_stage:
                errors["furnace_program"] = _(
                    "Recipe and furnace program must use the same process stage."
                )
            legacy_key = (self.furnace_program_key or "").strip()
            if legacy_key and legacy_key != self.furnace_program.program_key:
                errors["furnace_program_key"] = _(
                    "Legacy furnace program key must match the linked program."
                )
            elif not legacy_key:
                self.furnace_program_key = self.furnace_program.program_key
        if errors:
            raise ValidationError(errors)

    class Meta(AuditModel.Meta):
        db_table = "mlcc_recipe"
        ordering = ("name", "version")
        constraints = [
            models.UniqueConstraint(
                fields=("name", "version"), name="mlcc_recipe_name_version_uniq"
            )
        ]
        verbose_name = _("MLCC recipe")
        verbose_name_plural = _("MLCC recipes")


class MlccLoadUnitConversion(ValidatedAuditModel):
    id = models.AutoField(_("identifier"), primary_key=True)
    item = models.ForeignKey(
        "input.Item",
        verbose_name=_("item"),
        related_name="mlcc_load_unit_conversions",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    from_unit = models.CharField(_("from unit"), max_length=40)
    to_unit = models.CharField(_("to unit"), max_length=40)
    numerator = models.PositiveBigIntegerField(_("numerator"))
    denominator = models.PositiveBigIntegerField(_("denominator"))
    enabled = models.BooleanField(_("enabled"), default=True)

    def __str__(self):
        return (
            f"{self.item_id or '*'}: {self.from_unit} * "
            f"{self.numerator}/{self.denominator} = {self.to_unit}"
        )

    def clean(self):
        self.from_unit = (self.from_unit or "").strip()
        self.to_unit = (self.to_unit or "").strip()
        if not self.from_unit or not self.to_unit:
            raise ValidationError(_("Both load units are required."))
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValidationError(_("Load conversion ratio must be positive."))
        if self.from_unit == self.to_unit and self.numerator != self.denominator:
            raise ValidationError(
                _("An identity unit conversion must have a ratio of one.")
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_load_unit_conversion"
        ordering = ("item", "from_unit", "to_unit")
        constraints = [
            models.UniqueConstraint(
                fields=("item", "from_unit", "to_unit"),
                name="mlcc_load_unit_conversion_uniq",
            ),
            models.UniqueConstraint(
                fields=("from_unit", "to_unit"),
                condition=Q(item__isnull=True),
                name="mlcc_load_unit_conversion_generic_uniq",
            ),
            models.CheckConstraint(
                check=Q(numerator__gt=0) & Q(denominator__gt=0),
                name="mlcc_load_unit_conversion_positive",
            ),
        ]
        verbose_name = _("MLCC load unit conversion")
        verbose_name_plural = _("MLCC load unit conversions")


class MlccEquipmentCapability(ValidatedAuditModel):
    id = models.AutoField(_("identifier"), primary_key=True)
    resource = models.ForeignKey(
        "input.Resource",
        verbose_name=_("resource"),
        related_name="mlcc_capabilities",
        on_delete=models.CASCADE,
    )
    process_stage = models.CharField(
        _("process stage"), max_length=30, choices=PROCESS_STAGES
    )
    recipe = models.ForeignKey(
        MlccRecipe,
        verbose_name=_("recipe"),
        related_name="equipment_capabilities",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    item = models.ForeignKey(
        "input.Item",
        verbose_name=_("item"),
        related_name="mlcc_capabilities",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    minimum_quantity = models.DecimalField(
        _("minimum quantity"), max_digits=20, decimal_places=8, null=True, blank=True
    )
    maximum_quantity = models.DecimalField(
        _("maximum quantity"), max_digits=20, decimal_places=8, null=True, blank=True
    )
    enabled = models.BooleanField(_("enabled"), default=True)

    def __str__(self):
        return f"{self.resource_id} / {self.process_stage}"

    def clean(self):
        database = self._state.db or DEFAULT_DB_ALIAS
        duplicate = self.__class__.objects.using(database).filter(
            resource_id=self.resource_id,
            process_stage=self.process_stage,
            recipe_id=self.recipe_id,
            item_id=self.item_id,
        )
        if self.pk:
            duplicate = duplicate.exclude(pk=self.pk)
        if duplicate.exists():
            raise ValidationError(
                _("This resource, stage, recipe and item capability already exists.")
            )
        if (
            self.minimum_quantity is not None
            and self.maximum_quantity is not None
            and self.minimum_quantity > self.maximum_quantity
        ):
            raise ValidationError(
                {
                    "maximum_quantity": _(
                        "Maximum quantity must not be below minimum quantity."
                    )
                }
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_equipment_capability"
        ordering = ("resource", "process_stage", "recipe")
        constraints = [
            models.UniqueConstraint(
                fields=("resource", "process_stage", "recipe", "item"),
                name="mlcc_equipment_capability_uniq",
            ),
            models.UniqueConstraint(
                fields=("resource", "process_stage", "recipe"),
                condition=Q(item__isnull=True, recipe__isnull=False),
                name="mlcc_equipment_capability_no_item_uniq",
            ),
            models.UniqueConstraint(
                fields=("resource", "process_stage", "item"),
                condition=Q(recipe__isnull=True, item__isnull=False),
                name="mlcc_equipment_capability_no_recipe_uniq",
            ),
            models.UniqueConstraint(
                fields=("resource", "process_stage"),
                condition=Q(recipe__isnull=True, item__isnull=True),
                name="mlcc_equipment_capability_generic_uniq",
            ),
        ]
        verbose_name = _("MLCC equipment capability")
        verbose_name_plural = _("MLCC equipment capabilities")


class MlccCompatibilityRule(ValidatedAuditModel):
    RULE_TYPES = (("allow", _("allow")), ("forbid", _("forbid")))

    id = models.AutoField(_("identifier"), primary_key=True)
    name = models.CharField(_("name"), max_length=100, unique=True)
    process_stage = models.CharField(
        _("process stage"), max_length=30, choices=PROCESS_STAGES, default="sintering"
    )
    family_a = models.CharField(_("product family A"), max_length=100)
    family_b = models.CharField(_("product family B"), max_length=100)
    rule_type = models.CharField(_("rule type"), max_length=10, choices=RULE_TYPES)
    reason = models.CharField(_("reason"), null=True, blank=True)
    enabled = models.BooleanField(_("enabled"), default=True)
    priority = models.IntegerField(_("priority"), default=10)

    def __str__(self):
        return self.name

    def _normalize_families(self):
        a = (self.family_a or "").strip()
        b = (self.family_b or "").strip()
        self.family_a, self.family_b = sorted((a, b))

    def clean(self):
        self._normalize_families()
        if self.family_a == self.family_b and self.rule_type == "forbid":
            raise ValidationError(
                _(
                    "A product family cannot be forbidden from sharing a furnace with itself."
                )
            )
        database = self._state.db or DEFAULT_DB_ALIAS
        conflict = self.__class__.objects.using(database).filter(
            process_stage=self.process_stage,
            family_a=self.family_a,
            family_b=self.family_b,
            enabled=True,
        )
        if self.pk:
            conflict = conflict.exclude(pk=self.pk)
        if self.enabled and conflict.exists():
            raise ValidationError(
                _(
                    "An enabled compatibility rule already exists for this unordered pair."
                )
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_compatibility_rule"
        ordering = ("process_stage", "priority", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("process_stage", "family_a", "family_b", "rule_type"),
                name="mlcc_compatibility_rule_uniq",
            ),
            models.UniqueConstraint(
                fields=("process_stage", "family_a", "family_b"),
                condition=Q(enabled=True),
                name="mlcc_compatibility_rule_enabled_uniq",
            ),
        ]
        verbose_name = _("MLCC compatibility rule")
        verbose_name_plural = _("MLCC compatibility rules")


class MlccSetupMatrix(ValidatedAuditModel):
    id = models.AutoField(_("identifier"), primary_key=True)
    resource = models.ForeignKey(
        "input.Resource",
        verbose_name=_("resource"),
        related_name="mlcc_setup_rules",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    process_stage = models.CharField(
        _("process stage"), max_length=30, choices=PROCESS_STAGES
    )
    from_recipe = models.ForeignKey(
        MlccRecipe,
        verbose_name=_("from recipe"),
        related_name="setup_rules_from",
        on_delete=models.CASCADE,
    )
    to_recipe = models.ForeignKey(
        MlccRecipe,
        verbose_name=_("to recipe"),
        related_name="setup_rules_to",
        on_delete=models.CASCADE,
    )
    setup_time = models.DurationField(_("setup time"), default=timedelta)
    setup_cost = models.DecimalField(
        _("setup cost"), max_digits=20, decimal_places=8, default=Decimal("0")
    )

    def __str__(self):
        return f"{self.from_recipe} -> {self.to_recipe}"

    def clean(self):
        database = self._state.db or DEFAULT_DB_ALIAS
        duplicate = self.__class__.objects.using(database).filter(
            resource_id=self.resource_id,
            process_stage=self.process_stage,
            from_recipe_id=self.from_recipe_id,
            to_recipe_id=self.to_recipe_id,
        )
        if self.pk:
            duplicate = duplicate.exclude(pk=self.pk)
        if duplicate.exists():
            raise ValidationError(_("This setup matrix row already exists."))
        if self.setup_time and self.setup_time.total_seconds() < 0:
            raise ValidationError({"setup_time": _("Setup time cannot be negative.")})
        if self.setup_cost is not None and self.setup_cost < 0:
            raise ValidationError({"setup_cost": _("Setup cost cannot be negative.")})

    class Meta(AuditModel.Meta):
        db_table = "mlcc_setup_matrix"
        ordering = ("resource", "process_stage", "from_recipe", "to_recipe")
        constraints = [
            models.UniqueConstraint(
                fields=("resource", "process_stage", "from_recipe", "to_recipe"),
                name="mlcc_setup_matrix_uniq",
            )
        ]
        verbose_name = _("MLCC setup matrix")
        verbose_name_plural = _("MLCC setup matrices")


class MlccBatchGenealogy(ValidatedAuditModel):
    id = models.AutoField(_("identifier"), primary_key=True)
    parent_batch = models.CharField(_("parent batch"), max_length=100, db_index=True)
    child_batch = models.CharField(_("child batch"), max_length=100, db_index=True)
    process_stage = models.CharField(
        _("process stage"), max_length=30, choices=PROCESS_STAGES
    )
    quantity = models.DecimalField(
        _("quantity"), max_digits=20, decimal_places=8, null=True, blank=True
    )

    def __str__(self):
        return f"{self.parent_batch} -> {self.child_batch}"

    def clean(self):
        self.parent_batch = (self.parent_batch or "").strip()
        self.child_batch = (self.child_batch or "").strip()
        if self.parent_batch == self.child_batch:
            raise ValidationError(_("A batch cannot be its own parent."))

        database = self._state.db or DEFAULT_DB_ALIAS
        edges = self.__class__.objects.using(database)
        if self.pk:
            edges = edges.exclude(pk=self.pk)
        frontier = {self.child_batch}
        visited = set()
        while frontier:
            if self.parent_batch in frontier:
                raise ValidationError(_("The batch genealogy would contain a cycle."))
            visited.update(frontier)
            frontier = (
                set(
                    edges.filter(parent_batch__in=frontier).values_list(
                        "child_batch", flat=True
                    )
                )
                - visited
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_batch_genealogy"
        ordering = ("parent_batch", "child_batch")
        constraints = [
            models.UniqueConstraint(
                fields=("parent_batch", "child_batch"),
                name="mlcc_batch_genealogy_uniq",
            )
        ]
        verbose_name = _("MLCC batch genealogy")
        verbose_name_plural = _("MLCC batch genealogies")


class MlccFurnaceStateSnapshot(ValidatedAuditModel):
    id = models.AutoField(_("identifier"), primary_key=True)
    resource = models.ForeignKey(
        "input.Resource",
        verbose_name=_("resource"),
        related_name="mlcc_furnace_state_snapshots",
        on_delete=models.CASCADE,
    )
    observed_at = models.DateTimeField(_("observed at"), db_index=True)
    state_key = models.CharField(_("state key"), max_length=100)
    current_program = models.ForeignKey(
        MlccFurnaceProgram,
        verbose_name=_("current furnace program"),
        related_name="state_snapshots",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    available_at = models.DateTimeField(_("available at"))

    def __str__(self):
        return f"{self.resource_id} @ {self.observed_at}: {self.state_key}"

    def clean(self):
        self.state_key = (self.state_key or "").strip()
        if not self.state_key:
            raise ValidationError({"state_key": _("A furnace state key is required.")})
        if (
            self.available_at
            and self.observed_at
            and self.available_at < self.observed_at
        ):
            raise ValidationError(
                {"available_at": _("Available time cannot precede observation time.")}
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_furnace_state_snapshot"
        ordering = ("resource", "-observed_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("resource", "observed_at"),
                name="mlcc_furnace_state_resource_time_uniq",
            )
        ]
        verbose_name = _("MLCC furnace state snapshot")
        verbose_name_plural = _("MLCC furnace state snapshots")


class MlccFurnaceTransitionRule(ValidatedAuditModel):
    TRANSITION_TYPES = (
        ("none", _("none")),
        ("cleaning", _("cleaning")),
        ("atmosphere_purge", _("atmosphere purge")),
        ("empty_run", _("empty run")),
        ("heating", _("heating")),
        ("cooling", _("cooling")),
        ("composite", _("composite")),
    )

    id = models.AutoField(_("identifier"), primary_key=True)
    resource = models.ForeignKey(
        "input.Resource",
        verbose_name=_("resource"),
        related_name="mlcc_furnace_transition_rules",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    equipment_group = models.CharField(
        _("equipment group"), max_length=100, null=True, blank=True, db_index=True
    )
    process_stage = models.CharField(
        _("process stage"), max_length=30, choices=PROCESS_STAGES
    )
    from_state_key = models.CharField(_("from state key"), max_length=100)
    to_program = models.ForeignKey(
        MlccFurnaceProgram,
        verbose_name=_("target furnace program"),
        related_name="transition_rules",
        on_delete=models.CASCADE,
    )
    transition_type = models.CharField(
        _("transition type"),
        max_length=30,
        choices=TRANSITION_TYPES,
        default="none",
    )
    duration = models.DurationField(_("duration"), default=timedelta(0))
    setup_cost = models.DecimalField(
        _("setup cost"),
        max_digits=20,
        decimal_places=8,
        default=Decimal("0"),
    )
    allowed = models.BooleanField(_("allowed"), default=True)
    enabled = models.BooleanField(_("enabled"), default=True)
    priority = models.IntegerField(_("priority"), default=0)
    effective_date = models.DateField(_("effective date"))
    expiry_date = models.DateField(_("expiry date"), null=True, blank=True)

    def __str__(self):
        scope = self.resource_id or self.equipment_group or "*"
        return f"{scope}: {self.from_state_key} -> {self.to_program_id}"

    @property
    def scope_level(self):
        if self.resource_id:
            return "resource"
        if self.equipment_group:
            return "equipment_group"
        return "global"

    def clean(self):
        errors = {}
        self.from_state_key = (self.from_state_key or "").strip()
        self.equipment_group = (self.equipment_group or "").strip() or None
        if not self.from_state_key:
            errors["from_state_key"] = _("A source furnace state is required.")
        if self.resource_id and self.equipment_group:
            errors["equipment_group"] = _(
                "A transition rule can target a resource or an equipment group, not both."
            )
        if self.process_stage not in ("debinding", "sintering"):
            errors["process_stage"] = _(
                "A furnace transition is only valid for debinding or sintering."
            )
        if self.to_program_id and self.to_program.process_stage != self.process_stage:
            errors["to_program"] = _(
                "Transition rule and target program must use the same process stage."
            )
        if self.duration is None or self.duration < timedelta(0):
            errors["duration"] = _("Transition duration cannot be negative.")
        if self.setup_cost is None or self.setup_cost < 0:
            errors["setup_cost"] = _("Setup cost cannot be negative.")
        if (
            self.expiry_date
            and self.effective_date
            and self.expiry_date < self.effective_date
        ):
            errors["expiry_date"] = _("Expiry date cannot precede effective date.")
        if errors:
            raise ValidationError(errors)

        database = self._state.db or DEFAULT_DB_ALIAS
        end_date = self.expiry_date or date.max
        duplicate = (
            self.__class__.objects.using(database)
            .filter(
                resource_id=self.resource_id,
                equipment_group=self.equipment_group,
                process_stage=self.process_stage,
                from_state_key=self.from_state_key,
                to_program_id=self.to_program_id,
                enabled=True,
                priority=self.priority,
                effective_date__lte=end_date,
            )
            .filter(
                Q(expiry_date__isnull=True) | Q(expiry_date__gte=self.effective_date)
            )
        )
        if self.pk:
            duplicate = duplicate.exclude(pk=self.pk)
        if self.enabled and duplicate.exists():
            raise ValidationError(
                _("An overlapping transition rule exists at the same scope.")
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_furnace_transition_rule"
        ordering = (
            "process_stage",
            "resource",
            "equipment_group",
            "from_state_key",
            "to_program",
            "priority",
            "id",
        )
        constraints = [
            models.CheckConstraint(
                check=Q(duration__gte=timedelta(0)),
                name="mlcc_transition_rule_duration_nonnegative",
            ),
            models.CheckConstraint(
                check=Q(setup_cost__gte=0),
                name="mlcc_transition_rule_cost_nonnegative",
            ),
            models.CheckConstraint(
                check=~(Q(resource__isnull=False) & Q(equipment_group__isnull=False)),
                name="mlcc_transition_rule_single_scope",
            ),
        ]
        verbose_name = _("MLCC furnace transition rule")
        verbose_name_plural = _("MLCC furnace transition rules")


class MlccFurnaceLoad(ValidatedAuditModel):
    STATUSES = (
        ("draft", _("draft")),
        ("ready", _("ready")),
        ("running", _("running")),
        ("complete", _("complete")),
        ("cancelled", _("cancelled")),
        ("proposed", _("proposed")),
    )

    id = models.AutoField(_("identifier"), primary_key=True)
    reference = models.CharField(_("reference"), max_length=100, unique=True)
    resource = models.ForeignKey(
        "input.Resource",
        verbose_name=_("resource"),
        related_name="mlcc_furnace_loads",
        on_delete=models.PROTECT,
    )
    recipe = models.ForeignKey(
        MlccRecipe,
        verbose_name=_("recipe"),
        related_name="furnace_loads",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    furnace_program = models.ForeignKey(
        MlccFurnaceProgram,
        verbose_name=_("furnace program"),
        related_name="furnace_loads",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    run = models.ForeignKey(
        "mlcc.MlccScheduleRun",
        verbose_name=_("schedule run"),
        related_name="furnace_loads",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    operation_type = models.CharField(
        _("operation type"), max_length=30, choices=PROCESS_STAGES, default="sintering"
    )
    furnace_program_key = models.CharField(
        _("furnace program key"), max_length=100, null=True, blank=True
    )
    planned_start = models.DateTimeField(_("planned start"), null=True, blank=True)
    planned_end = models.DateTimeField(_("planned end"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=15, choices=STATUSES, default="draft"
    )
    capacity = models.DecimalField(
        _("capacity"),
        max_digits=20,
        decimal_places=8,
        validators=[MinValueValidator(Decimal("0.00000001"))],
    )
    loaded_quantity = models.DecimalField(
        _("loaded quantity"),
        max_digits=20,
        decimal_places=8,
        default=Decimal("0"),
    )
    load_unit = models.CharField(_("load unit"), max_length=40, default="", blank=True)
    frozen = models.BooleanField(_("frozen"), default=False)
    details = models.JSONField(_("details"), default=dict, blank=True)

    def __str__(self):
        return self.reference

    @property
    def used_capacity(self):
        return self.items.aggregate(total=Sum("quantity"))["total"] or Decimal("0")

    def clean(self):
        if self.capacity is None or self.capacity <= 0:
            raise ValidationError(
                {"capacity": _("Furnace load capacity must be greater than zero.")}
            )
        if (
            self.planned_start
            and self.planned_end
            and self.planned_end <= self.planned_start
        ):
            raise ValidationError(
                {"planned_end": _("Planned end must be after planned start.")}
            )
        if self.loaded_quantity < 0 or self.loaded_quantity > self.capacity:
            raise ValidationError(
                {"loaded_quantity": _("Loaded quantity must fit furnace capacity.")}
            )
        if self.status == "proposed" and not self.run_id:
            raise ValidationError(
                {"run": _("A proposed furnace load must belong to a schedule run.")}
            )
        if self.furnace_program_id:
            if self.furnace_program.process_stage != self.operation_type:
                raise ValidationError(
                    {
                        "furnace_program": _(
                            "Furnace load and program must use the same process stage."
                        )
                    }
                )
            if (
                self.furnace_program_key
                and self.furnace_program_key != self.furnace_program.program_key
            ):
                raise ValidationError(
                    {
                        "furnace_program_key": _(
                            "Legacy furnace program key must match the linked program."
                        )
                    }
                )
            if not self.furnace_program_key:
                self.furnace_program_key = self.furnace_program.program_key
        if (
            self.recipe_id
            and self.furnace_program_id
            and self.recipe.furnace_program_id != self.furnace_program_id
        ):
            raise ValidationError(
                {"recipe": _("Furnace load recipe must map to its furnace program.")}
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_furnace_load"
        ordering = ("-planned_start", "reference")
        constraints = [
            models.CheckConstraint(
                check=Q(capacity__gt=0), name="mlcc_furnace_load_capacity_gt_0"
            ),
            models.CheckConstraint(
                check=Q(loaded_quantity__gte=0)
                & Q(loaded_quantity__lte=models.F("capacity")),
                name="mlcc_furnace_load_loaded_lte_capacity",
            ),
        ]
        verbose_name = _("MLCC furnace load")
        verbose_name_plural = _("MLCC furnace loads")


class MlccQualityHold(ValidatedAuditModel):
    STATUSES = (("active", _("active")), ("released", _("released")))

    id = models.AutoField(_("identifier"), primary_key=True)
    batch_code = models.CharField(_("batch code"), max_length=100, db_index=True)
    manufacturing_order = models.ForeignKey(
        "input.OperationPlan",
        verbose_name=_("manufacturing order"),
        related_name="mlcc_quality_holds",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    hold_type = models.CharField(_("hold type"), max_length=50, default="quality")
    reason = models.CharField(_("reason"))
    status = models.CharField(
        _("status"), max_length=15, choices=STATUSES, default="active"
    )
    held_at = models.DateTimeField(_("held at"), default=timezone.now)
    released_at = models.DateTimeField(_("released at"), null=True, blank=True)

    def __str__(self):
        return f"{self.batch_code} ({self.status})"

    @classmethod
    def is_held(cls, batch_code=None, manufacturing_order_id=None, database=None):
        lookup = Q()
        if batch_code:
            lookup |= Q(batch_code=batch_code)
        if manufacturing_order_id:
            lookup |= Q(manufacturing_order_id=manufacturing_order_id)
        if not lookup:
            return False
        return (
            cls.objects.using(database or DEFAULT_DB_ALIAS)
            .filter(lookup, status="active")
            .exists()
        )

    def clean(self):
        if self.manufacturing_order_id and self.manufacturing_order.type not in (
            "MO",
            "WO",
        ):
            raise ValidationError(
                {
                    "manufacturing_order": _(
                        "Quality holds can only reference manufacturing orders."
                    )
                }
            )
        if self.status == "released" and not self.released_at:
            raise ValidationError(
                {"released_at": _("A released hold needs a release timestamp.")}
            )
        if self.status == "active" and self.released_at:
            raise ValidationError(
                {"released_at": _("An active hold cannot have a release timestamp.")}
            )

    def save(self, *args, **kwargs):
        result = super().save(*args, **kwargs)
        if self.status == "active":
            from freppledb.input.models import OperationPlan

            database = self._state.db or kwargs.get("using") or DEFAULT_DB_ALIAS
            held_orders = OperationPlan.objects.using(database).filter(
                type__in=("MO", "WO")
            )
            lookup = Q()
            if self.manufacturing_order_id:
                lookup |= Q(pk=self.manufacturing_order_id)
            if self.batch_code:
                lookup |= Q(batch=self.batch_code) | Q(mlcc_batch_code=self.batch_code)
            if lookup:
                held_orders.filter(lookup).update(mlcc_schedulable=False)
        return result

    class Meta(AuditModel.Meta):
        db_table = "mlcc_quality_hold"
        ordering = ("-held_at", "batch_code")
        verbose_name = _("MLCC quality hold")
        verbose_name_plural = _("MLCC quality holds")


class MlccFurnaceLoadItem(ValidatedAuditModel):
    id = models.AutoField(_("identifier"), primary_key=True)
    furnace_load = models.ForeignKey(
        MlccFurnaceLoad,
        verbose_name=_("furnace load"),
        related_name="items",
        on_delete=models.CASCADE,
    )
    manufacturing_order = models.ForeignKey(
        "input.OperationPlan",
        verbose_name=_("manufacturing order"),
        related_name="mlcc_furnace_items",
        on_delete=models.PROTECT,
    )
    batch_code = models.CharField(_("batch code"), max_length=100, db_index=True)
    quantity = models.DecimalField(
        _("quantity"),
        max_digits=20,
        decimal_places=8,
        validators=[MinValueValidator(Decimal("0.00000001"))],
    )
    sequence = models.PositiveIntegerField(_("sequence"), default=1)
    load_unit = models.CharField(_("load unit"), max_length=40, default="", blank=True)
    conversion_trace = models.JSONField(_("conversion trace"), default=dict, blank=True)

    def __str__(self):
        return f"{self.furnace_load_id}: {self.batch_code}"

    def clean(self):
        database = self._state.db or DEFAULT_DB_ALIAS
        if self.manufacturing_order_id and self.manufacturing_order.type not in (
            "MO",
            "WO",
        ):
            raise ValidationError(
                {
                    "manufacturing_order": _(
                        "A furnace can only load manufacturing orders."
                    )
                }
            )
        if MlccQualityHold.is_held(
            self.batch_code, self.manufacturing_order_id, database
        ):
            raise ValidationError(
                _("A quality-held batch cannot enter a schedulable furnace load.")
            )
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError(
                {"quantity": _("Load quantity must be greater than zero.")}
            )
        if self.furnace_load_id and self.quantity is not None:
            siblings = self.__class__.objects.using(database).filter(
                furnace_load_id=self.furnace_load_id
            )
            if self.pk:
                siblings = siblings.exclude(pk=self.pk)
            used = siblings.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
            if used + self.quantity > self.furnace_load.capacity:
                raise ValidationError(
                    _("Furnace load items exceed the furnace capacity.")
                )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_furnace_load_item"
        ordering = ("furnace_load", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("furnace_load", "manufacturing_order"),
                name="mlcc_furnace_load_item_uniq",
            ),
            models.CheckConstraint(
                check=Q(quantity__gt=0), name="mlcc_furnace_load_item_qty_gt_0"
            ),
        ]
        verbose_name = _("MLCC furnace load item")
        verbose_name_plural = _("MLCC furnace load items")


class MlccScheduleRun(ValidatedAuditModel):
    STATUSES = (
        ("draft", _("draft")),
        ("ready", _("ready")),
        ("running", _("running")),
        ("complete", _("complete")),
        ("failed", _("failed")),
    )

    id = models.AutoField(_("identifier"), primary_key=True)
    name = models.CharField(_("name"), max_length=100, unique=True)
    status = models.CharField(
        _("status"), max_length=15, choices=STATUSES, default="draft"
    )
    horizon_start = models.DateTimeField(_("horizon start"))
    horizon_end = models.DateTimeField(_("horizon end"))
    requested_at = models.DateTimeField(_("requested at"), default=timezone.now)
    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)
    parameters = models.JSONField(_("parameters"), default=dict, blank=True)
    message = models.TextField(_("message"), null=True, blank=True)

    def __str__(self):
        return self.name

    def clean(self):
        if (
            self.horizon_start
            and self.horizon_end
            and self.horizon_end <= self.horizon_start
        ):
            raise ValidationError(
                {"horizon_end": _("Horizon end must be after horizon start.")}
            )
        if self.finished_at and self.started_at and self.finished_at < self.started_at:
            raise ValidationError(
                {"finished_at": _("Finished time cannot precede started time.")}
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_schedule_run"
        ordering = ("-requested_at", "name")
        verbose_name = _("MLCC schedule run")
        verbose_name_plural = _("MLCC schedule runs")


class MlccFurnaceTransition(ValidatedAuditModel):
    STATUSES = (("proposed", _("proposed")),)

    id = models.AutoField(_("identifier"), primary_key=True)
    run = models.ForeignKey(
        MlccScheduleRun,
        verbose_name=_("schedule run"),
        related_name="furnace_transitions",
        on_delete=models.CASCADE,
    )
    resource = models.ForeignKey(
        "input.Resource",
        verbose_name=_("resource"),
        related_name="mlcc_furnace_transitions",
        on_delete=models.PROTECT,
    )
    predecessor_load = models.ForeignKey(
        MlccFurnaceLoad,
        verbose_name=_("predecessor furnace load"),
        related_name="outgoing_transitions",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    successor_load = models.ForeignKey(
        MlccFurnaceLoad,
        verbose_name=_("successor furnace load"),
        related_name="incoming_transitions",
        on_delete=models.CASCADE,
    )
    transition_rule = models.ForeignKey(
        MlccFurnaceTransitionRule,
        verbose_name=_("transition rule"),
        related_name="planned_transitions",
        on_delete=models.PROTECT,
    )
    transition_type = models.CharField(
        _("transition type"),
        max_length=30,
        choices=MlccFurnaceTransitionRule.TRANSITION_TYPES,
    )
    planned_start = models.DateTimeField(_("planned start"))
    planned_end = models.DateTimeField(_("planned end"))
    status = models.CharField(
        _("status"), max_length=15, choices=STATUSES, default="proposed"
    )
    details = models.JSONField(_("details"), default=dict, blank=True)

    def __str__(self):
        predecessor = self.predecessor_load_id or "initial"
        return f"{predecessor} -> {self.successor_load_id}"

    def clean(self):
        errors = {}
        if self.status != "proposed":
            errors["status"] = _("Furnace transition status must remain proposed.")
        if (
            self.planned_start
            and self.planned_end
            and self.planned_end < self.planned_start
        ):
            errors["planned_end"] = _("Transition end cannot precede transition start.")
        if self.successor_load_id:
            if self.successor_load.resource_id != self.resource_id:
                errors["successor_load"] = _(
                    "Successor load must use the transition resource."
                )
            if (
                self.successor_load.status == "proposed"
                and self.successor_load.run_id != self.run_id
            ):
                errors["successor_load"] = _(
                    "Successor load and transition must belong to the same run."
                )
        if (
            self.predecessor_load_id
            and self.predecessor_load.resource_id != self.resource_id
        ):
            errors["predecessor_load"] = _(
                "Predecessor load must use the transition resource."
            )
        if self.transition_rule_id:
            if self.transition_rule.transition_type != self.transition_type:
                errors["transition_type"] = _(
                    "Transition type must match the resolved rule."
                )
            if (
                self.transition_rule.resource_id
                and self.transition_rule.resource_id != self.resource_id
            ):
                errors["transition_rule"] = _(
                    "Resource-specific rule does not match the transition resource."
                )
        if errors:
            raise ValidationError(errors)

    class Meta(AuditModel.Meta):
        db_table = "mlcc_furnace_transition"
        ordering = ("resource", "planned_start", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("run", "successor_load"),
                name="mlcc_furnace_transition_successor_uniq",
            ),
            models.CheckConstraint(
                check=Q(status="proposed"),
                name="mlcc_furnace_transition_proposed",
            ),
        ]
        verbose_name = _("MLCC furnace transition")
        verbose_name_plural = _("MLCC furnace transitions")


class MlccScheduleResult(ValidatedAuditModel):
    STATUSES = (
        ("proposed", _("proposed")),
        ("scheduled", _("scheduled")),
        ("blocked", _("blocked")),
        ("not_schedulable", _("not schedulable")),
    )

    id = models.AutoField(_("identifier"), primary_key=True)
    run = models.ForeignKey(
        MlccScheduleRun,
        verbose_name=_("schedule run"),
        related_name="results",
        on_delete=models.CASCADE,
    )
    manufacturing_order = models.ForeignKey(
        "input.OperationPlan",
        verbose_name=_("manufacturing order"),
        related_name="mlcc_schedule_results",
        on_delete=models.CASCADE,
    )
    resource = models.ForeignKey(
        "input.Resource",
        verbose_name=_("resource"),
        related_name="mlcc_schedule_results",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    furnace_load = models.ForeignKey(
        MlccFurnaceLoad,
        verbose_name=_("furnace load"),
        related_name="schedule_results",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    batch_code = models.CharField(_("batch code"), max_length=100, db_index=True)
    planned_start = models.DateTimeField(_("planned start"), null=True, blank=True)
    planned_end = models.DateTimeField(_("planned end"), null=True, blank=True)
    quantity = models.DecimalField(_("quantity"), max_digits=20, decimal_places=8)
    status = models.CharField(
        _("status"), max_length=20, choices=STATUSES, default="proposed"
    )
    sequence = models.PositiveIntegerField(_("sequence"), default=1)
    score = models.DecimalField(
        _("score"), max_digits=20, decimal_places=8, null=True, blank=True
    )
    details = models.JSONField(_("details"), default=dict, blank=True)

    def __str__(self):
        return f"{self.run_id}: {self.manufacturing_order_id}"

    def clean(self):
        database = self._state.db or DEFAULT_DB_ALIAS
        if self.manufacturing_order_id and self.manufacturing_order.type not in (
            "MO",
            "WO",
        ):
            raise ValidationError(
                {
                    "manufacturing_order": _(
                        "Schedule results can only reference manufacturing orders."
                    )
                }
            )
        if self.status in ("proposed", "scheduled") and MlccQualityHold.is_held(
            self.batch_code, self.manufacturing_order_id, database
        ):
            raise ValidationError(_("A quality-held batch cannot be schedulable."))
        if (
            self.planned_start
            and self.planned_end
            and self.planned_end <= self.planned_start
        ):
            raise ValidationError(
                {"planned_end": _("Planned end must be after planned start.")}
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_schedule_result"
        ordering = ("run", "sequence", "manufacturing_order")
        constraints = [
            models.UniqueConstraint(
                fields=("run", "manufacturing_order"),
                name="mlcc_schedule_result_uniq",
            )
        ]
        verbose_name = _("MLCC schedule result")
        verbose_name_plural = _("MLCC schedule results")


class MlccPrecheckRun(ValidatedAuditModel):
    STATUSES = (("passed", _("passed")), ("blocked", _("blocked")))

    id = models.AutoField(_("identifier"), primary_key=True)
    reference = models.CharField(_("reference"), max_length=100, unique=True)
    status = models.CharField(
        _("status"), max_length=15, choices=STATUSES, default="passed"
    )
    horizon_start = models.DateTimeField(_("horizon start"))
    horizon_end = models.DateTimeField(_("horizon end"))
    freeze_minutes = models.PositiveIntegerField(_("freeze minutes"), default=0)
    factory_timezone = models.CharField(_("factory timezone"), max_length=100)
    instance_hash = models.CharField(_("instance hash"), max_length=64, db_index=True)
    order_count = models.PositiveIntegerField(_("order count"), default=0)
    batch_count = models.PositiveIntegerField(_("batch count"), default=0)
    task_count = models.PositiveIntegerField(_("task count"), default=0)
    equipment_count = models.PositiveIntegerField(_("equipment count"), default=0)
    blocker_count = models.PositiveIntegerField(_("blocker count"), default=0)
    warning_count = models.PositiveIntegerField(_("warning count"), default=0)
    info_count = models.PositiveIntegerField(_("info count"), default=0)
    duration_ms = models.PositiveIntegerField(_("duration milliseconds"), default=0)
    parameters = models.JSONField(_("parameters"), default=dict, blank=True)

    def __str__(self):
        return self.reference

    def clean(self):
        if (
            self.horizon_start
            and self.horizon_end
            and self.horizon_end <= self.horizon_start
        ):
            raise ValidationError(
                {"horizon_end": _("Horizon end must be after horizon start.")}
            )
        expected = "blocked" if self.blocker_count else "passed"
        if self.status != expected:
            raise ValidationError(
                {"status": _("Precheck status must match the blocker count.")}
            )

    class Meta(AuditModel.Meta):
        db_table = "mlcc_precheck_run"
        ordering = ("-lastmodified", "reference")
        verbose_name = _("MLCC precheck run")
        verbose_name_plural = _("MLCC precheck runs")


class MlccPrecheckIssue(ValidatedAuditModel):
    SEVERITIES = (
        ("BLOCKER", _("blocker")),
        ("WARNING", _("warning")),
        ("INFO", _("info")),
    )

    id = models.AutoField(_("identifier"), primary_key=True)
    run = models.ForeignKey(
        MlccPrecheckRun,
        verbose_name=_("precheck run"),
        related_name="issues",
        on_delete=models.CASCADE,
    )
    sequence = models.PositiveIntegerField(_("sequence"))
    severity = models.CharField(_("severity"), max_length=10, choices=SEVERITIES)
    code = models.CharField(_("error code"), max_length=20, db_index=True)
    object_type = models.CharField(_("object type"), max_length=50, db_index=True)
    object_id = models.CharField(_("object identifier"), max_length=300, db_index=True)
    reason = models.TextField(_("reason"))
    suggestion = models.TextField(_("suggestion"))
    source_field = models.CharField(_("source field"), max_length=300)
    object_url = models.CharField(
        _("object URL"), max_length=500, null=True, blank=True
    )

    def __str__(self):
        return f"{self.code}: {self.object_type} {self.object_id}"

    class Meta(AuditModel.Meta):
        db_table = "mlcc_precheck_issue"
        ordering = ("run", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("run", "sequence"), name="mlcc_precheck_issue_sequence_uniq"
            )
        ]
        verbose_name = _("MLCC precheck issue")
        verbose_name_plural = _("MLCC precheck issues")
