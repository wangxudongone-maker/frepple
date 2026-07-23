from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from freppledb.input.models import ManufacturingOrder, OperationPlan

from .models import MlccQualityHold


@receiver(
    pre_save,
    sender=OperationPlan,
    dispatch_uid="mlcc_quality_hold_schedulable_operationplan",
)
@receiver(
    pre_save,
    sender=ManufacturingOrder,
    dispatch_uid="mlcc_quality_hold_schedulable_manufacturingorder",
)
def validate_quality_hold_schedulable(sender, instance, using=None, **kwargs):
    """Block a held MO from being marked schedulable via core APIs/imports."""
    if instance.type not in ("MO", "WO") or not getattr(
        instance, "mlcc_schedulable", False
    ):
        return
    batch_code = getattr(instance, "mlcc_batch_code", None) or instance.batch
    if MlccQualityHold.is_held(
        batch_code=batch_code,
        manufacturing_order_id=instance.pk,
        database=using or instance._state.db or DEFAULT_DB_ALIAS,
    ):
        raise ValidationError(_("A quality-held batch cannot be marked schedulable."))
