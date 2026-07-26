from django.utils.translation import gettext_lazy as _

from freppledb.boot import registerAttribute

registerAttribute(
    "freppledb.input.models.Item",
    [
        ("mlcc_material_type", _("MLCC material type"), "string"),
        ("mlcc_product_family", _("MLCC product family"), "string"),
        ("mlcc_chip_size", _("MLCC chip size"), "string"),
        ("mlcc_layer_count", _("MLCC layer count"), "integer"),
        ("mlcc_quality_grade", _("MLCC quality grade"), "string"),
    ],
)

registerAttribute(
    "freppledb.input.models.Resource",
    [
        ("mlcc_equipment_group", _("MLCC equipment group"), "string"),
        ("mlcc_is_furnace", _("MLCC furnace"), "boolean"),
        ("mlcc_nominal_capacity", _("MLCC nominal capacity"), "number"),
        ("mlcc_load_unit", _("MLCC load unit"), "string"),
    ],
)

registerAttribute(
    "freppledb.input.models.Operation",
    [
        ("mlcc_process_stage", _("MLCC process stage"), "string"),
        ("mlcc_recipe_required", _("MLCC recipe required"), "boolean"),
        ("mlcc_batch_required", _("MLCC batch required"), "boolean"),
        ("mlcc_max_wait_time", _("MLCC maximum wait time"), "duration"),
    ],
)

# ManufacturingOrder is a proxy over OperationPlan. Registering on the concrete
# model exposes the fields on manufacturing orders and the standard REST API.
registerAttribute(
    "freppledb.input.models.OperationPlan",
    [
        ("mlcc_batch_code", _("MLCC batch code"), "string"),
        ("mlcc_lot_number", _("MLCC lot number"), "string"),
        ("mlcc_recipe_version", _("MLCC recipe version"), "string"),
        ("mlcc_schedulable", _("MLCC schedulable"), "boolean"),
    ],
)
