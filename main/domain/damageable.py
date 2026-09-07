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


def purge_item_list(items: list) -> list:
    """就地删除耐久归零的物品，并清理箱内物品。返回被删列表。"""
    destroyed: list = []
    kept: list = []
    for item in items:
        destroyed.extend(purge_container(item))
        if is_destroyed(item):
            destroyed.append(item)
        else:
            kept.append(item)
    items[:] = kept
    return destroyed


def purge_container(item: Any) -> list:
    data = getattr(item, "chest_data", None)
    if not isinstance(data, dict) or "inventory" not in data:
        return []
    return purge_item_list(data["inventory"])


def purge_equipment(entity: Any) -> list:
    destroyed: list = []
    equipment = getattr(entity, "equipment", None)
    if not isinstance(equipment, dict):
        return destroyed
    for slot, item in list(equipment.items()):
        if item is not None and is_destroyed(item):
            destroyed.append(item)
            equipment[slot] = None
    return destroyed
