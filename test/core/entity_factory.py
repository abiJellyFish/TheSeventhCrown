"""实体工厂与通用公式 —— 体型、属性调整值、伤害类型归一化、通用动作集。"""

# 体型大小次序（用于体型差比较，D11 推撞/协助目标体型最多高一级）
SIZE_RANK = {"tiny": 0, "small": 1, "medium": 2, "large": 3}


def size_rank(size_str: str) -> int:
    """体型大小排名（数字越大体型越大）。未知体型默认 medium。"""
    return SIZE_RANK.get(size_str, 2)

# 通用动作集（data/actions.json，单一事实源，D22）：所有实体注入到 actions 表
_GENERIC_ACTIONS_CACHE: list[dict] | None = None


def _generic_actions() -> list[dict]:
    """返回通用动作集（惰性加载并缓存）。"""
    global _GENERIC_ACTIONS_CACHE
    if _GENERIC_ACTIONS_CACHE is None:
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "data", "actions.json")
        with open(path, "r", encoding="utf-8") as f:
            _GENERIC_ACTIONS_CACHE = json.load(f)
    return _GENERIC_ACTIONS_CACHE

def stat_adjust(stat_value: int) -> int:
    """属性调整值 = (属性值 - 8) // 2，向下取整。"""
    return (stat_value - 8) // 2

# 命中伤害类型归一化（阶段10补丁）：穿刺/挥砍/力场 → 一律转为钝击
BLUNT_CONVERT = {"piercing": "bludgeoning", "slashing": "bludgeoning", "force": "bludgeoning"}


def normalize_damage_type(damage_type: str) -> str:
    """命中伤害类型归一化：穿刺/挥砍/力场一律转为钝击，其余类型不变。"""
    return BLUNT_CONVERT.get(damage_type, damage_type)
