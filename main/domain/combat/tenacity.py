"""韧性：削韧结算、击破、自然恢复、连击。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.items.weapon_types import weapon_tenacity_mult

if TYPE_CHECKING:
    from domain.entity import Entity

BREAK_PENDULUMS = 6
REGEN_PENDULUMS = 6
COMBO_ATTACKS = 2
COMBO_TENACITY = 1
COMBO_COURAGE_FRACTION = 0.05


def tenacity_cap(creature) -> int:
    return creature.tenacity_cap()


def compute_tenacity_amount(weapon, roll: int, *, tenacity_action: bool,
                            extra: int) -> int:
    amount = 0.0
    if tenacity_action:
        amount += max(roll // 5, 1)
    amount += extra
    if amount <= 0:
        return 0
    amount *= weapon_tenacity_mult(weapon)
    if getattr(weapon, "damage_type", None) == "bludgeoning":
        amount *= 2
    return int(amount)


def apply_tenacity_break(target: Entity, combat_state=None) -> None:
    initiative = []
    in_combat = bool(combat_state is not None and getattr(combat_state, "in_combat", False))
    if in_combat:
        initiative = list(getattr(combat_state, "combat_initiative", []) or [])
    if in_combat and target in initiative:
        idx = initiative.index(target)
        current = getattr(combat_state, "combat_turn_index", 0)
        rounds = 1 if idx >= current else 2
        target.add_status("incapacitated", end_event="combat_round", rounds_left=rounds)
        return
    target.add_status("incapacitated", duration=BREAK_PENDULUMS)


def apply_tenacity_loss(target: Entity, amount: int, combat_state=None) -> int:
    if amount <= 0:
        return 0
    was = target.tenacity
    target.tenacity = max(0, was - amount)
    reduced = was - target.tenacity
    if was > 0 and target.tenacity == 0:
        apply_tenacity_break(target, combat_state)
    return reduced


def restore_tenacity_full(creature: Entity) -> None:
    creature.tenacity = tenacity_cap(creature)


def settle_attack_tenacity(
    attacker: Entity,
    target: Entity,
    weapon,
    roll: int = 0,
    *,
    tenacity_action: bool = False,
    combat_state=None,
    consume_extra: bool = True,
    note_combo: bool = True,
) -> int:
    extra = 0
    if consume_extra:
        extra = getattr(attacker, "pending_tenacity_bonus", 0)
        attacker.pending_tenacity_bonus = 0
    amount = compute_tenacity_amount(
        weapon, roll, tenacity_action=tenacity_action, extra=extra,
    )
    reduced = apply_tenacity_loss(target, amount, combat_state)
    if note_combo:
        note_entity_attack(attacker)
    return reduced


def courage_combo_restore(attacker: Entity) -> int:
    cap = attacker.effective_max_courage
    gain = max(1, round(cap * COMBO_COURAGE_FRACTION))
    before = attacker.courage
    attacker.courage = min(cap, attacker.courage + gain)
    return attacker.courage - before


def note_entity_attack(attacker: Entity) -> bool:
    attacker.attack_streak += 1
    if attacker.attack_streak < COMBO_ATTACKS:
        return False
    attacker.attack_streak = 0
    attacker.pending_tenacity_bonus = 1
    cap = tenacity_cap(attacker)
    attacker.tenacity = min(cap, attacker.tenacity + COMBO_TENACITY)
    courage_combo_restore(attacker)
    return True


def reset_attack_streak(actor) -> None:
    if actor is None:
        return
    actor.attack_streak = 0


def tick_tenacity_regen(creature: Entity, delta: float = 1.0) -> int:
    if getattr(creature, "is_dead", False):
        return 0
    creature._tenacity_regen_acc += delta
    restored = 0
    cap = tenacity_cap(creature)
    while creature._tenacity_regen_acc >= REGEN_PENDULUMS:
        creature._tenacity_regen_acc -= REGEN_PENDULUMS
        if creature.tenacity < cap:
            creature.tenacity += 1
            restored += 1
    return restored


def expire_combat_round_statuses(creature: Entity) -> list[str]:
    expired = [
        effect for effect in creature.statuses
        if effect.end_event == "combat_round" and effect.rounds_left is not None
    ]
    names = []
    for effect in expired:
        effect.rounds_left -= 1
        if effect.rounds_left <= 0:
            creature.expire_status_effect(effect)
            names.append(effect.name)
    return names


def convert_combat_break_to_explore(creature: Entity) -> None:
    for effect in creature.statuses:
        if effect.name != "incapacitated":
            continue
        if effect.end_event != "combat_round":
            continue
        remaining = effect.rounds_left if effect.rounds_left is not None else 1
        effect.end_event = None
        effect.rounds_left = None
        effect.duration = BREAK_PENDULUMS * max(1, remaining)
