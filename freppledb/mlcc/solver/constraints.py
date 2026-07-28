"""Shared pure helpers for model construction and solution validation."""

from collections import defaultdict

FURNACE_STAGES = ("debinding", "sintering")


def load_requirement(step, resource_id):
    return next(
        (item for item in step.load_requirements if item.resource_id == resource_id),
        None,
    )


def schedulable_steps(instance):
    batches = {item.id: item for item in instance.batches}
    return tuple(
        step
        for step in instance.steps
        if batches.get(step.batch_id) is None
        or batches[step.batch_id].schedulable
        or step.started
        or step.frozen
    )


def merge_intervals(intervals, horizon):
    clipped = sorted(
        (
            max(0, interval.start_minute),
            min(horizon, interval.end_minute),
        )
        for interval in intervals
        if interval.end_minute > 0 and interval.start_minute < horizon
    )
    result = []
    for start, end in clipped:
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return tuple(result)


def subtract_intervals(available, unavailable):
    result = list(available)
    for blocked_start, blocked_end in unavailable:
        updated = []
        for start, end in result:
            if blocked_end <= start or blocked_start >= end:
                updated.append((start, end))
                continue
            if start < blocked_start:
                updated.append((start, blocked_start))
            if blocked_end < end:
                updated.append((blocked_end, end))
        result = updated
    return tuple((start, end) for start, end in result if end > start)


def available_segments(equipment, horizon):
    shifts = merge_intervals(equipment.shifts, horizon)
    if not shifts:
        return ()
    blocked = merge_intervals(
        equipment.downtimes + equipment.maintenance,
        horizon,
    )
    return subtract_intervals(shifts, blocked)


def capability_index(instance):
    result = defaultdict(list)
    for capability in instance.capabilities:
        if capability.enabled:
            result[(capability.resource_id, capability.stage)].append(capability)
    return result


def eligible_resources(instance, step, indexed_capabilities=None):
    equipment = {item.id: item for item in instance.equipment}
    batches = {item.id: item for item in instance.batches}
    batch = batches.get(step.batch_id)
    capabilities = indexed_capabilities or capability_index(instance)
    candidates = set(step.candidate_resource_ids) & set(step.certified_resource_ids)
    result = []
    for resource_id in sorted(candidates):
        resource = equipment.get(resource_id)
        if resource is None:
            continue
        valid = False
        for capability in capabilities.get((resource_id, step.stage), ()):
            if batch and capability.item_id not in (None, batch.item_id):
                continue
            if capability.recipe_id not in (None, step.recipe_id):
                continue
            if (
                capability.minimum_quantity is not None
                and step.quantity < capability.minimum_quantity
            ):
                continue
            if (
                capability.maximum_quantity is not None
                and step.quantity > capability.maximum_quantity
            ):
                continue
            valid = True
            break
        if not valid:
            continue
        if step.stage in FURNACE_STAGES:
            requirement = load_requirement(step, resource_id)
            if (
                requirement is None
                or requirement.quantity is None
                or requirement.quantity <= 0
                or resource.capacity is None
                or resource.capacity != resource.capacity.to_integral_value()
                or requirement.quantity > int(resource.capacity)
                or requirement.load_unit != resource.load_unit
            ):
                continue
            if not (resource.load_unit or "").strip():
                continue
        result.append(resource_id)
    return tuple(result)


def material_ready_minute(instance, step):
    materials = {item.id: item for item in instance.materials}
    values = [
        materials[material_id].available_minute
        for material_id in step.required_material_ids
        if material_id in materials
        and materials[material_id].available_minute is not None
    ]
    return max(values, default=0)
