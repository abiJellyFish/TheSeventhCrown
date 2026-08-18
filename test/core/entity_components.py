"""实体组件 —— 按能力域拆分，按需挂载到 Entity。

Entity 是基础数据容器，只保留所有生物共有的固有属性。
按能力域拆分组件，生物根据数据声明自动挂载所需组件。
玩家控制是组件之一（ControlComponent），角色首先是独立实体，玩家选择后挂载控制组件。
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ControlComponent:
    """玩家控制组件。挂载此组件的生物由玩家控制。"""
    controlled: bool = True  # 挂载即代表被控


@dataclass
class AIComponent:
    """AI 行为组件。所有非玩家控制的生物挂载此组件。"""
    # 行为表
    behavior_table: list = field(default_factory=list)
    behavior_overrides: dict = field(default_factory=dict)
    template_name: str = ""
    bravery_tier: str = "medium"
    aggression_tier: str = "medium"
    schedule: str = "idle"
    # 运行时状态
    _hunt_target: Any = None
    _cached_path: Any = None
    _path_target: Any = None
    _action_remaining_cost: float = 0.0
    curS_ticks: int = 0
    _current_action: str = "idle"
    _ally_count: int = 0
    _attitude: dict = field(default_factory=dict)
    _interrupted: bool = False          # 受到伤害 → 打断当前动作并重新评估


@dataclass
class CasterComponent:
    """施法组件。会施法的生物（法师、未来 NPC 法师）挂载。"""
    mp: int = 0
    max_mp: int = 0
    memorized_spells: list = field(default_factory=list)
    spell_slots: dict = field(default_factory=dict)
    spell_domains: list = field(default_factory=list)


@dataclass
class ClassComponent:
    """职业组件。有职业的生物（角色、未来 NPC 职业者）挂载。"""
    char_class: str = ""
    background: str = ""
    class_level: float = 0.0
    class_exp: float = 0.0


@dataclass
class InventoryComponent:
    """物品栏组件。智慧生物（有装备/物品栏）挂载。"""
    inventory: list = field(default_factory=list)
    equipment: dict = field(default_factory=lambda: {
        "head": None, "chest": None, "arms": None, "legs": None,
        "left_hand": None, "right_hand": None, "accessory1": None,
        "accessory2": None, "accessory3": None,
    })
    gp: int = 0
    sp: int = 0
    cp: int = 0