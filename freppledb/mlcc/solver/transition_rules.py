"""Pure deterministic furnace-transition rule resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib

SCOPE_RANK = {
    "global": 1,
    "equipment_group": 2,
    "resource": 3,
}


def _business_id(kind, values):
    payload = "\x1f".join("" if value is None else str(value) for value in values)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{kind}:{digest}"


def stable_furnace_state_id(resource_id, observed_at):
    return _business_id("furnace_state", (resource_id, observed_at))


def stable_transition_rule_id(
    resource_id,
    equipment_group,
    stage,
    from_state_key,
    to_program_id,
    transition_type,
    duration_minutes,
    setup_cost,
    allowed,
    enabled,
    priority,
    effective_date,
    expiry_date,
):
    return _business_id(
        "transition_rule",
        (
            resource_id,
            equipment_group,
            stage,
            from_state_key,
            to_program_id,
            transition_type,
            duration_minutes,
            setup_cost,
            allowed,
            enabled,
            priority,
            effective_date,
            expiry_date,
        ),
    )


def stable_furnace_transition_id(
    resource_id,
    predecessor_load_id,
    successor_load_id,
):
    return _business_id(
        "furnace_transition",
        (resource_id, predecessor_load_id, successor_load_id),
    )


@dataclass(frozen=True)
class TransitionResolution:
    rule: object | None
    scope_level: str | None
    conflict: bool
    candidate_rule_ids: tuple[str, ...]

    @property
    def allowed(self):
        return bool(self.rule is not None and self.rule.allowed and not self.conflict)


def rule_is_effective(rule, on_date):
    try:
        effective = date.fromisoformat(rule.effective_date)
        expiry = date.fromisoformat(rule.expiry_date) if rule.expiry_date else None
    except (TypeError, ValueError):
        return False
    return (
        rule.enabled and effective <= on_date and (expiry is None or expiry >= on_date)
    )


def resolve_transition_rule(
    instance,
    resource_id,
    stage,
    from_state_key,
    to_program_id,
):
    """Resolve exact-resource > equipment-group > global, then lowest priority."""

    origin_date = date.fromisoformat(instance.window.origin[:10])
    resource = next(
        (item for item in instance.equipment if item.id == resource_id),
        None,
    )
    if resource is None:
        return TransitionResolution(None, None, False, ())

    candidates = []
    for rule in instance.furnace_transition_rules:
        if (
            not rule_is_effective(rule, origin_date)
            or rule.stage != stage
            or rule.from_state_key != from_state_key
            or rule.to_program_id != to_program_id
        ):
            continue
        if rule.resource_id:
            if rule.resource_id != resource_id:
                continue
            level = "resource"
        elif rule.equipment_group:
            if rule.equipment_group != resource.equipment_group:
                continue
            level = "equipment_group"
        else:
            level = "global"
        candidates.append((SCOPE_RANK[level], rule.priority, rule.id, level, rule))

    if not candidates:
        return TransitionResolution(None, None, False, ())
    best_scope = max(item[0] for item in candidates)
    scoped = [item for item in candidates if item[0] == best_scope]
    best_priority = min(item[1] for item in scoped)
    selected = sorted(
        (item for item in scoped if item[1] == best_priority),
        key=lambda item: item[2],
    )
    if len(selected) != 1:
        return TransitionResolution(
            None,
            selected[0][3],
            True,
            tuple(item[2] for item in selected),
        )
    return TransitionResolution(
        selected[0][4],
        selected[0][3],
        False,
        (selected[0][2],),
    )
