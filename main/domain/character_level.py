"""角色等级：各成长系统整数等级之和，仅作标识。"""
from domain.classes import (
    ARMOR_CATEGORIES,
    DOMAIN_THRESHOLDS,
    WEAPON_CATEGORIES,
    domain_level_for_exp,
    expertise_level,
    proficiency_level,
)

CRAFT_KINDS = ("cook", "make", "alchemy")


def _training_levels(experience: float) -> int:
    return proficiency_level(experience) + expertise_level(experience)


def _class_route_total(entity) -> int:
    levels = {key: int(value) for key, value in entity.class_levels.items()}
    total = sum(levels.values())
    class_level = int(entity.class_level)
    if entity.char_class:
        stored = levels.get(entity.char_class, 0)
        return total + max(0, class_level - stored)
    if class_level > total:
        return class_level
    return total


def _domain_total(entity) -> int:
    return sum(
        domain_level_for_exp(domain, entity.domain_experience.get(domain, 0.0))
        for domain in DOMAIN_THRESHOLDS
    )


def _craft_total(entity) -> int:
    kinds = set(CRAFT_KINDS) | set(entity.craft_experience)
    return sum(entity.craft_level(kind) for kind in kinds)


def _category_training_total(experience: dict, known: tuple[str, ...]) -> int:
    categories = set(known) | set(experience)
    return sum(_training_levels(experience.get(category, 0.0)) for category in categories)


def character_level(entity) -> int:
    """职业路线 + 领域 + 制作 + 武器/护甲/工具训练（熟练+专精）。不含属性。"""
    return (
        _class_route_total(entity)
        + _domain_total(entity)
        + _craft_total(entity)
        + _category_training_total(entity.weapon_experience, WEAPON_CATEGORIES)
        + _category_training_total(entity.armor_experience, ARMOR_CATEGORIES)
        + sum(_training_levels(exp) for exp in entity.tool_experience.values())
    )
