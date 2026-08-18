"""实体包 —— Entity + StatusEffect + 工厂函数。

原 core/entity.py 拆分为 entity.py（Entity 类）、status.py（StatusEffect）、
factory.py（create_fighter/create_mage）。历史 facade 转发的符号（Item/Weapon/Armor/
are_hostile 等）继续从这里转发，旧 import 无需改动。
"""
from core.entity.status import StatusEffect
from core.entity.factory import create_fighter, create_mage
from core.entity.entity import *  # noqa: F401,F403  # Entity + 常量 + 历史转发的 Item/Weapon/Armor 等

# 永久兼容别名（审查报告7 决策：不删除）
Creature = Entity
