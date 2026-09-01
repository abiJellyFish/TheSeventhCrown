"""核心层对外发布的领域事件。"""
from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class LogCategory(str, Enum):
    """日志展示分类，由事件产生位置显式指定。"""

    COMBAT = "combat"
    EXPLORE = "explore"
    INTERACTION = "interaction"
    ITEM = "item"
    QUEST = "quest"
    SYSTEM = "system"


@dataclass(frozen=True)
class DomainEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, init=False)
class LogEvent(DomainEvent):
    message: str
    category: LogCategory
    position: tuple[int, int] | None

    def __init__(
        self,
        message: str,
        category: LogCategory = LogCategory.SYSTEM,
        position: tuple[int, int] | None = None,
    ):
        object.__setattr__(self, "name", "LogEvent")
        payload = {"message": message}
        if category is not LogCategory.SYSTEM:
            payload["category"] = category.value
        if position is not None:
            payload["position"] = position
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "position", position)


@dataclass(frozen=True, init=False)
class CombatStarted(DomainEvent):
    def __init__(self):
        object.__setattr__(self, "name", "CombatStarted")
        object.__setattr__(self, "payload", {})


@dataclass(frozen=True, init=False)
class CombatEnded(DomainEvent):
    def __init__(self):
        object.__setattr__(self, "name", "CombatEnded")
        object.__setattr__(self, "payload", {})


@dataclass(frozen=True, init=False)
class TurnChanged(DomainEvent):
    entity_id: int | None

    def __init__(self, entity_id: int | None):
        object.__setattr__(self, "name", "TurnChanged")
        object.__setattr__(self, "payload", {"entity_id": entity_id})
        object.__setattr__(self, "entity_id", entity_id)


@dataclass(frozen=True, init=False)
class ReactionRequired(DomainEvent):
    kind: str

    def __init__(self, kind: str):
        object.__setattr__(self, "name", "ReactionRequired")
        object.__setattr__(self, "payload", {"kind": kind})
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True, init=False)
class StateChanged(DomainEvent):
    version: int

    def __init__(self, version: int):
        object.__setattr__(self, "name", "StateChanged")
        object.__setattr__(self, "payload", {"version": version})
        object.__setattr__(self, "version", version)


@dataclass(frozen=True, init=False)
class DamageDealt(DomainEvent):
    attacker_id: int
    target_id: int
    amount: int
    damage_type: str

    def __init__(self, attacker_id: int, target_id: int, amount: int, damage_type: str):
        object.__setattr__(self, "name", "DamageDealt")
        object.__setattr__(self, "payload", {
            "attacker_id": attacker_id, "target_id": target_id,
            "amount": amount, "damage_type": damage_type,
        })
        object.__setattr__(self, "attacker_id", attacker_id)
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "damage_type", damage_type)


@dataclass(frozen=True, init=False)
class EntityDied(DomainEvent):
    entity_id: int
    entity_name: str

    def __init__(self, entity_id: int, name: str):
        object.__setattr__(self, "name", "EntityDied")
        object.__setattr__(self, "payload", {"entity_id": entity_id, "name": name})
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "entity_name", name)


@dataclass(frozen=True, init=False)
class ItemPickedUp(DomainEvent):
    entity_id: int
    item_name: str
    position: tuple[int, int] | None

    def __init__(self, entity_id: int, item_name: str,
                 position: tuple[int, int] | None = None):
        payload = {"entity_id": entity_id, "item_name": item_name}
        if position is not None:
            payload["position"] = position
        object.__setattr__(self, "name", "ItemPickedUp")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "item_name", item_name)
        object.__setattr__(self, "position", position)


@dataclass(frozen=True, init=False)
class ItemEquipped(DomainEvent):
    entity_id: int
    item_name: str
    slot: str

    def __init__(self, entity_id: int, item_name: str, slot: str):
        object.__setattr__(self, "name", "ItemEquipped")
        object.__setattr__(self, "payload", {
            "entity_id": entity_id, "item_name": item_name, "slot": slot,
        })
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "item_name", item_name)
        object.__setattr__(self, "slot", slot)


@dataclass(frozen=True, init=False)
class TradeCompleted(DomainEvent):
    entity_id: int
    direction: str
    item_name: str
    amount: int

    def __init__(self, entity_id: int, direction: str, item_name: str, amount: int):
        object.__setattr__(self, "name", "TradeCompleted")
        object.__setattr__(self, "payload", {
            "entity_id": entity_id, "direction": direction,
            "item_name": item_name, "amount": amount,
        })
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "item_name", item_name)
        object.__setattr__(self, "amount", amount)


@dataclass(frozen=True, init=False)
class StatusChanged(DomainEvent):
    entity_id: int
    status: str
    active: bool

    def __init__(self, entity_id: int, status: str, active: bool):
        object.__setattr__(self, "name", "StatusChanged")
        object.__setattr__(self, "payload", {
            "entity_id": entity_id, "status": status, "active": active,
        })
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "active", active)


def damage_dealt(
    attacker_id: int,
    target_id: int,
    amount: int,
    damage_type: str,
) -> DamageDealt:
    return DamageDealt(attacker_id, target_id, amount, damage_type)


def entity_died(entity_id: int, name: str) -> EntityDied:
    return EntityDied(entity_id, name)


def item_picked_up(entity_id: int, item_name: str, position: tuple[int, int] | None = None) -> ItemPickedUp:
    return ItemPickedUp(entity_id, item_name, position)


def item_equipped(entity_id: int, item_name: str, slot: str) -> ItemEquipped:
    return ItemEquipped(entity_id, item_name, slot)


def trade_completed(
    entity_id: int,
    direction: str,
    item_name: str,
    amount: int,
) -> TradeCompleted:
    return TradeCompleted(entity_id, direction, item_name, amount)


def status_changed(entity_id: int, status: str, active: bool) -> StatusChanged:
    return StatusChanged(entity_id, status, active)


def state_changed(version: int) -> StateChanged:
    return StateChanged(version)


def log_event(
    message: str,
    category: LogCategory = LogCategory.SYSTEM,
    position: tuple[int, int] | None = None,
) -> LogEvent:
    return LogEvent(message, category, position=position)

def combat_started() -> CombatStarted:
    return CombatStarted()


def combat_ended() -> CombatEnded:
    return CombatEnded()


def turn_changed(entity_id: int | None) -> TurnChanged:
    return TurnChanged(entity_id)


def reaction_required(kind: str = "opportunity_attack") -> ReactionRequired:
    return ReactionRequired(kind)
