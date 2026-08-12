"""双持武器判定 —— 轻型检查、模式判定、AP 计算。"""

from core.entity import Weapon


def is_light(weapon: Weapon) -> bool:
    """武器是否具有轻型 (light) 属性。"""
    props = getattr(weapon, 'properties', None) or []
    return "light" in props


def dual_wield_mode(left, right) -> str | None:
    """判定双持模式。

    Returns:
        "dual_wield"  — 两把都是轻型，消耗一次 AP 同时攻击
        "dual_attack" — 至少一把非轻型，分别消耗 AP 依次攻击
        None          — 不满足双持条件（如任一手为空或不是武器）
    """
    if left is None or right is None:
        return None
    if not hasattr(left, 'weapon_type') or not hasattr(right, 'weapon_type'):
        return None
    if is_light(left) and is_light(right):
        return "dual_wield"
    return "dual_attack"


def dual_wield_ap_cost(left, right) -> int:
    """双持武器模式（两把轻型）的 AP 消耗 = max(两把武器 ap_cost)。"""
    return max(getattr(left, 'ap_cost', 2), getattr(right, 'ap_cost', 2))
