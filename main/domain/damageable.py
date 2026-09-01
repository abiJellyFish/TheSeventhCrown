"""统一可受伤对象接口。"""
from typing import Any


def current_durability(target: Any) -> int:
    if hasattr(target, "hp"):
        return int(target.hp)
    return int(target.durability)


def max_durability(target: Any) -> int:
    if hasattr(target, "max_hp"):
        return int(target.max_hp)
    return int(target.max_durability)


def apply_damage(target: Any, amount: int, damage_type: str = "bludgeoning",
                 critical: bool = False) -> int:
    amount = max(0, int(amount))
    if hasattr(target, "take_damage"):
        target.take_damage(amount, damage_type, critical=critical)
        return amount
    target.durability = max(0, current_durability(target) - amount)
    return amount


def is_destroyed(target: Any) -> bool:
    if hasattr(target, "is_dead"):
        return bool(target.is_dead)
    return current_durability(target) <= 0
