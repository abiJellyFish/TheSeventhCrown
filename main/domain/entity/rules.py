"""实体领域通用规则。"""

SIZE_RANK = {"tiny": 0, "small": 1, "medium": 2, "large": 3}
BLUNT_CONVERT = {
    "piercing": "bludgeoning",
    "slashing": "bludgeoning",
    "force": "bludgeoning",
}


def size_rank(size: str) -> int:
    return SIZE_RANK.get(size, SIZE_RANK["medium"])


def stat_adjust(value: int) -> int:
    return (value - 8) // 2


def normalize_damage_type(damage_type: str) -> str:
    return BLUNT_CONVERT.get(damage_type, damage_type)
