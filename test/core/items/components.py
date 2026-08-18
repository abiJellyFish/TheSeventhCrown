"""物品组件 —— 按能力域拆分，按需挂载到 Item。

Item 是基础数据容器，只保留所有物品共有的固有属性。
按能力域拆分组件，物品根据数据声明自动挂载所需组件。
武器/护甲/光照是组件；投掷是所有物品的通用能力（throw_* 字段保留在 Item 顶层，不组件化）。
"""
from dataclasses import dataclass, field


@dataclass
class WeaponComponent:
    """武器组件。带伤害/命中的物品挂载。"""
    weapon_type: str = "melee"             # "melee" | "ranged"
    category: str = "simple"               # "simple" | "martial"
    damage: str = "1d4"
    damage_type: str = "bludgeoning"
    attack_stat: str = "str"               # "str" | "dex" | "str_or_dex"
    ap_cost: int = 20
    range_normal: int = 0
    range_max: int = 0
    properties: list = field(default_factory=list)
    loaded: bool = True                    # 弹药武器已装填？战斗开始时重置
    melee: dict | None = None              # 远程武器近战属性
    special_damage: dict | None = None     # 属性伤害（火把灼烧）


@dataclass
class ArmorComponent:
    """护甲组件。提供 AC/韧性的物品挂载。"""
    armor_type: str = "light"              # "light" | "heavy" | "shield" | "clothing"
    slot: str = "chest"                    # "chest" | "arms" | "legs" | "head" | "full_body"
    ac_bonus: int = 0
    tenacity_bonus: int = 0
    str_requirement: int = 8


@dataclass
class LightComponent:
    """光照组件。发光的物品（火把）挂载。"""
    radius: int = 5
    level: str = "bright"                  # 沿用 core.fov.LightLevel
    condition: str = "unlit"               # "lit" | "unlit"
