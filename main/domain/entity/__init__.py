"""实体领域公开接口。"""
from domain.entity.status import StatusEffect
from domain.entity.factory import EntityFactory
from domain.entity.rules import (
    SIZE_RANK,
    BLUNT_CONVERT,
    size_rank,
    stat_adjust,
    normalize_damage_type,
)
from domain.entity.entity import *  # noqa: F401,F403  # Entity + 常量 + 历史转发的 Item/Weapon/Armor 等
from domain.obstacle import ObstacleType

# 过渡期别名：现有调用方迁移完成后删除。
create_fighter = EntityFactory.create_fighter
create_mage = EntityFactory.create_mage

__all__ = [
    "Entity",
    "StatusEffect",
    "EntityFactory",
    "SIZE_RANK",
    "BLUNT_CONVERT",
    "size_rank",
    "stat_adjust",
    "normalize_damage_type",
    "ObstacleType",
]
