"""障碍能力定义。

障碍只是对象的一项能力，不构成独立对象类型。实体通过组件拥有障碍能力，
物品则直接保存障碍属性和耐久。
"""
from enum import Enum


class ObstacleType(str, Enum):
    NONE = "none"
    HALF = "half"
    THREE_QUARTER = "three_quarter"
    FULL = "full"


OBSTACLE_DEFAULTS: dict[ObstacleType, tuple[int, int, bool]] = {
    ObstacleType.HALF: (40, 5, True),
    ObstacleType.THREE_QUARTER: (50, 10, True),
    ObstacleType.FULL: (80, 30, False),
}


def normalize_obstacle_type(value: str | ObstacleType | None) -> ObstacleType:
    if value is None or value == "":
        return ObstacleType.NONE
    return value if isinstance(value, ObstacleType) else ObstacleType(value)


def obstacle_defaults(obstacle_type: str | ObstacleType) -> tuple[int, int, bool]:
    kind = normalize_obstacle_type(obstacle_type)
    if kind is ObstacleType.NONE:
        return 0, 0, False
    return OBSTACLE_DEFAULTS[kind]


def obstacle_info(obstacle) -> tuple[int, str] | None:
    """读取实体或物品自身的障碍能力：(阻挡值, 类型标签)。"""
    if obstacle is None or not getattr(obstacle, "is_obstacle", False):
        return None
    kind = normalize_obstacle_type(getattr(obstacle, "obstacle_type", None))
    if kind is ObstacleType.NONE:
        return None
    block_value = getattr(obstacle, "block_value", 0)
    return block_value, kind.value


def is_full_obstacle(obstacle) -> bool:
    """判断对象是否具备全身障碍能力。"""
    info = obstacle_info(obstacle)
    return info is not None and normalize_obstacle_type(info[1]) is ObstacleType.FULL


def obstacle_at(pos, entities=None, ground_items=None):
    """返回坐标上的第一个障碍实体或物品；没有则返回 None。"""
    for entity, entity_pos in entities or ():
        if entity_pos[:2] == pos[:2] and not getattr(entity, "is_dead", False):
            if obstacle_info(entity) is not None:
                return entity
    for item, item_pos in ground_items or ():
        if item_pos[:2] == pos[:2] and obstacle_info(item) is not None:
            return item
    return None
