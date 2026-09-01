"""领域行动值对象。

行动只描述意图，不直接修改 GameState。执行器在提交前重新验证实体、
位置和状态版本，从而避免使用过期决策。
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Action:
    actor_id: int
    expected_state_version: int


@dataclass(frozen=True)
class MoveAction(Action):
    destination: tuple[int, int]


@dataclass(frozen=True)
class AttackAction(Action):
    target_id: int
    attack_name: str = ""


@dataclass(frozen=True)
class HideAction(Action):
    pass


@dataclass(frozen=True)
class SearchAction(Action):
    target_id: int | None = None


@dataclass(frozen=True)
class StandAction(Action):
    pass


@dataclass(frozen=True)
class InteractAction(Action):
    target: Any = None


@dataclass(frozen=True)
class WaitAction(Action):
    pass


@dataclass(frozen=True)
class StatusAction(Action):
    status: str
    duration: int | None = None
    remove: bool = False


@dataclass(frozen=True)
class PickupAction(Action):
    item_id: int
    position: tuple[int, int]
    item: Any = None


@dataclass(frozen=True)
class EatAction(Action):
    item_id: int | None = None
    position: tuple[int, int] | None = None


@dataclass(frozen=True)
class DoorAction(Action):
    position: tuple[int, int]
    opened: bool


@dataclass(frozen=True)
class EquipAction(Action):
    item_id: int
    slot: str | None = None


@dataclass(frozen=True)
class LootAction(Action):
    target_id: int


@dataclass(frozen=True)
class HarvestAction(Action):
    position: tuple[int, int]
