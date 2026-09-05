"""实体数据类 —— Entity、Item、Weapon、Armor。

Phase 3: Player 类已删除，统一使用 Entity + controlled 标记。
字段对齐 test/docs/MVP2.md。
"""

import random
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from domain.ai.components import DEFAULT_BEHAVIOR
from domain.items import Item, Weapon, Armor
from domain.items.factory import ItemFactory
from domain.faction import (
    are_hostile, get_attitude, is_ally, adjust_favor,
    default_favor, get_favor, set_favor, FACTION_RELATIONS,
)
from domain.entity.rules import size_rank, SIZE_RANK, stat_adjust, normalize_damage_type, BLUNT_CONVERT
from domain.entity_components import (
    ControlComponent, AIComponent, CasterComponent,
    AllyComponent, ClassComponent, InventoryComponent, ObstacleComponent,
)
from domain.obstacle import ObstacleType, normalize_obstacle_type, obstacle_defaults
from domain.entity.status import StatusEffect


# ═══════════════════════════════════════════════════
# 属性
# ═══════════════════════════════════════════════════

DEFAULT_STATS = {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}

STAT_NAMES = ["str", "dex", "con", "int", "wis", "cha"]






# ═══════════════════════════════════════════════════
# 状态常量表（沿用字符串，避免魔法值）
# ═══════════════════════════════════════════════════

STATUS_PRONE = "prone"                # 倒地：移动速度减半、攻击劣势、被近战优势/被远程劣势
STATUS_INCAPACITATED = "incapacitated"  # 失能（韧性归零）
STATUS_DYING = "濒死"                  # 濒死：HP=0，进行死亡豁免
STATUS_COMATOSE = "昏迷"               # 昏迷（击晕产物，HP≥1 也可能昏迷）
STATUS_STUNNED = "震慑"               # 震慑：检定最终点数减半，长休解除
STATUS_HIDING = "hiding"              # 躲藏：携带锁定对抗值 hide_dc
STATUS_DISENGAGED = "disengaged"      # 已撤离：本回合移动不触发借机攻击
STATUS_DODGE = "dodge"                # 回避中：可见敌人对其攻击劣势、敏捷豁免优势
STATUS_ASSISTED = "assisted"          # 被协助：下一次属性检定优势
STATUS_BURNING = "灼烧"
STATUS_WET = "潮湿"
STATUS_IMMOBILE = "不可移动"
STATUS_WOUNDED = "重伤"
STATUS_BLOODIED = "浴血"
STATUS_BLEEDING = "流血"

MIN_SPEED = 1 / 8
MAX_EFFECTIVE_SPEED = 10

# 昏迷自然清醒：累积 1500 钟摆后自动清除（期间持续昏迷；失去昏迷后累积清零）
COMATOSE_AUTO_WAKE_PENDULUMS = 1500



# ═══════════════════════════════════════════════════
# Entity
# ═══════════════════════════════════════════════════

_UID_COUNTER = count(1)


def _next_uid() -> int:
    """分配全局唯一实体 id（好感度键/行动顺序平局决胜用，deepcopy 保留）。"""
    return next(_UID_COUNTER)


def _entity_obstacle_type(data: dict) -> str:
    """按实体数据确定覆盖物类型；普通实体默认四分之三掩体。"""
    explicit = data.get("obstacle_type")
    if explicit:
        return explicit
    return ObstacleType.THREE_QUARTER.value


@dataclass(init=False)
class Entity:
    """生物数据类（组合模式）。只保留所有生物共有的固有属性，能力域由组件承载。

    字段对齐 MVP2.md 六、生物 定义。
    玩家控制是组件之一（ControlComponent），角色首先是独立实体，玩家选择后挂载控制组件。
    """

    name: str
    faction: str = "中立"                  # "守序" | "中立" | "混乱"
    body_type: str = "humanoid"           # "humanoid" | "beast" | "undead" | ...
    size: str = "medium"                  # "tiny" | "small" | "medium" | "large"（以 MVP2.md 生物定义为准）
    reach: int | None = None              # 固有触及范围；未指定时按体型提供默认值
    facing: tuple[int, int] = (0, 1)      # 朝向 = DIRS_8 方向向量，默认 (0,1) 东；移动自动转向，手动转向模式可改
    z: int = 0                            # 绝对高度层
    climb_speed: float = 0                # 显式攀爬速度；0 表示使用普通速度的一半
    fly_speed: float = 0                  # 显式飞行速度；0 表示不能飞行
    is_hovering: bool = False             # 是否处于悬浮状态

    # 核心数值（所有生物共有）
    max_hp: int = 30
    tenacity: int = 10
    max_tenacity: int = 10
    ap: int = 60
    max_ap: int = 60
    courage: int = 0
    max_courage: int = 0
    speed: float = 1                      # 速度等级 (格子/钟摆)
    ac_base: int = 8                      # 天生 AC（不含敏捷）
    char: str = "?"                       # 地图显示字符（ASCII 单个字符）

    # 属性
    stats: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_STATS))

    # 装备部位 AC 加成
    ac_chest: int = 0
    ac_arms: int = 0
    ac_legs: int = 0
    ac_head: int = 0
    ac_shield: int = 0                    # 全身

    # 其他（所有生物共有）
    vision_range: int = 8
    food_value: int = 15000
    food_locked: bool = False             # True = 饮食值不消耗
    darkvision_range: int = 0             # 0 = 无黑暗视觉
    language: str = ""

    # 动作、特性、掉落（所有生物共有）
    actions: list[dict] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)
    loot: dict = field(default_factory=dict)
    shop_id: str = ""                     # 商店 id（商人等可交易生物指向 data/shops/{id}.json）
    shop_gold: int = 0                    # 实体收购资金（铜币总值，P1 3.2 非商人实体交易）

    # 状态效果（所有生物共有）
    statuses: list[StatusEffect] = field(default_factory=list)
    armor_experience: dict[str, float] = field(default_factory=dict)
    armor_training_progress: dict[str, float] = field(default_factory=dict)

    # ── 组件容器（按需挂载，None=未挂载）──
    _control: ControlComponent | None = None
    _ally: AllyComponent | None = None
    _ai: AIComponent | None = None
    _caster: CasterComponent | None = None
    _class: ClassComponent | None = None
    _inventory: InventoryComponent | None = None
    _obstacle: ObstacleComponent | None = None

    # ── 唯一稳定 id（P1 修复）：好感度键/行动顺序平局决胜用；deepcopy 保留，不参与比较/哈希
    uid: int = field(default=0, compare=False, repr=False)

    # ── 相对好感度表（P1 3.1）：{目标实体 uid → 好感度数值}，顶层字段不受 AI 组件摘除影响
    _favor: dict[int, int] = field(default_factory=dict, repr=False)
    _attitude: dict[int, str] = field(default_factory=dict, repr=False)
    party_member: bool = False
    _bleeding_pendulums: int = field(default=0, repr=False)
    _death_callback: Any = field(default=None, compare=False, repr=False)
    _death_save_callback: Any = field(default=None, compare=False, repr=False)

    # ── HP 属性（死亡系统，D24）──
    # HP 增加（恢复生命）→ 自动清除濒死/昏迷并重置死亡豁免。
    # 所有治疗入口（药水/投掷/休息/疗伤术/食物）都走 hp 赋值，统一接管。

    @property
    def hp(self) -> int:
        return self._hp

    @hp.setter
    def hp(self, value: int) -> None:
        old = getattr(self, "_hp", 0)
        value = max(0, min(int(value), self.max_hp))
        self._hp = value
        # 生命恢复（增加）→ 清除濒死/昏迷（D24：恢复任何生命值即解除）
        if value > old and not getattr(self, "_reviving", False):
            ds = getattr(self, "death_saves", None)
            if ds is not None:
                ds.reset()
            if getattr(self, "statuses", None) is not None:
                self.remove_status(STATUS_DYING)
                self.remove_status(STATUS_COMATOSE)
                self.remove_status(STATUS_BLEEDING)
                self._bleeding_pendulums = 0
        if hasattr(self, "statuses") and value < self.max_hp * 0.2:
            self._enter_wounded()
        elif hasattr(self, "statuses") and value >= self.max_hp * 0.2:
            self._leave_wounded()

    @property
    def is_dead(self) -> bool:
        """真正死亡（尸体）。濒死（hp=0）≠ 死亡。"""
        return self._is_dead

    @is_dead.setter
    def is_dead(self, value: bool) -> None:
        self._is_dead = value

    @property
    def obstacle(self) -> ObstacleComponent | None:
        return self._obstacle

    @obstacle.setter
    def obstacle(self, value: ObstacleComponent | None) -> None:
        self._obstacle = value

    @property
    def obstacle_type(self) -> str:
        return self._obstacle.obstacle_type.value if self._obstacle else ""

    @property
    def block_value(self) -> int:
        return self._obstacle.block_value if self._obstacle else 0

    @property
    def is_obstacle(self) -> bool:
        return self._obstacle is not None

    # ── 组件代理属性（业务层无感知访问）──

    # 控制组件
    @property
    def controlled(self) -> bool:
        return self._control is not None and self._control.controlled

    @controlled.setter
    def controlled(self, value: bool) -> None:
        if value:
            if self._control is None:
                self._control = ControlComponent(controlled=True)
            else:
                self._control.controlled = True
        else:
            self._control = None

    @property
    def ally(self) -> bool:
        """是否挂载盟友组件。实体本身不因盟友身份改变。"""
        return self._ally is not None and self._ally.active

    @ally.setter
    def ally(self, value: bool) -> None:
        self._ally = AllyComponent() if value else None

    # 物品栏组件
    @property
    def inventory(self) -> list:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        return self._inventory.inventory

    @inventory.setter
    def inventory(self, value: list) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.inventory = value

    @property
    def equipment(self) -> dict:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        return self._inventory.equipment

    @property
    def accessories(self) -> list:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        return self._inventory.accessories

    def add_accessory(self, item) -> None:
        if not getattr(item, "accessory", False):
            raise ValueError("item is not an accessory")
        if item in self.accessories:
            raise ValueError("accessory is already equipped")
        self.accessories.append(item)
        for key, value in getattr(item, "equip_effect", {}).items():
            if key == "max_courage":
                amount = int(value)
                self.max_courage += amount
                self.courage += amount

    def remove_accessory(self, item) -> None:
        if item not in self.accessories:
            raise ValueError("accessory is not equipped")
        self.accessories.remove(item)
        for key, value in getattr(item, "equip_effect", {}).items():
            if key == "max_courage":
                amount = int(value)
                self.max_courage = max(0, self.max_courage - amount)
                self.courage = min(self.courage, self.max_courage)

    @equipment.setter
    def equipment(self, value: dict) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.equipment = value

    @property
    def gp(self) -> int:
        return self._inventory.gp if self._inventory else 0

    @gp.setter
    def gp(self, value: int) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.gp = value

    @property
    def sp(self) -> int:
        return self._inventory.sp if self._inventory else 0

    @sp.setter
    def sp(self, value: int) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.sp = value

    @property
    def cp(self) -> int:
        return self._inventory.cp if self._inventory else 0

    @cp.setter
    def cp(self, value: int) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.cp = value

    # 职业组件
    @property
    def char_class(self) -> str:
        return self._class.char_class if self._class else ""

    @char_class.setter
    def char_class(self, value: str) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.char_class = value

    @property
    def background(self) -> str:
        return self._class.background if self._class else ""

    @background.setter
    def background(self, value: str) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.background = value

    @property
    def class_level(self) -> int:
        return self._class.class_level if self._class else 0

    @class_level.setter
    def class_level(self, value: int) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.class_level = int(value)

    @property
    def class_exp(self) -> float:
        return self._class.class_exp if self._class else 0.0

    @class_exp.setter
    def class_exp(self, value: float) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.class_exp = value
        if self._class.char_class:
            self._class.class_experience[self._class.char_class] = value

    @property
    def class_levels(self) -> dict[str, int]:
        return self._class.class_levels if self._class else {}

    @class_levels.setter
    def class_levels(self, value: dict[str, int]) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.class_levels = value

    @property
    def class_experience(self) -> dict[str, float]:
        return self._class.class_experience if self._class else {}

    @class_experience.setter
    def class_experience(self, value: dict[str, float]) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.class_experience = value

    @property
    def domain_talents(self) -> list[str]:
        return self._class.domain_talents if self._class else []

    @domain_talents.setter
    def domain_talents(self, value: list[str]) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.domain_talents = value

    @property
    def domain_experience(self) -> dict[str, float]:
        return self._class.domain_experience if self._class else {}

    @domain_experience.setter
    def domain_experience(self, value: dict[str, float]) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.domain_experience = value

    @property
    def weapon_experience(self) -> dict[str, float]:
        return self._class.weapon_experience if self._class else {}

    @weapon_experience.setter
    def weapon_experience(self, value: dict[str, float]) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.weapon_experience = value

    @property
    def attribute_experience(self) -> dict[str, float]:
        return self._class.attribute_experience if self._class else {}

    @attribute_experience.setter
    def attribute_experience(self, value: dict[str, float]) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.attribute_experience = value

    @property
    def titles(self) -> list[str]:
        return self._class.titles if self._class else []

    @titles.setter
    def titles(self, value: list[str]) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.titles = value

    # 施法组件
    @property
    def mp(self) -> int:
        return self._caster.mp if self._caster else 0

    @mp.setter
    def mp(self, value: int) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.mp = value

    @property
    def max_mp(self) -> int:
        return self._caster.max_mp if self._caster else 0

    @max_mp.setter
    def max_mp(self, value: int) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.max_mp = value

    @property
    def memorized_spells(self) -> list:
        return self._caster.memorized_spells if self._caster else []

    @memorized_spells.setter
    def memorized_spells(self, value: list) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.memorized_spells = value

    @property
    def spell_slots(self) -> dict:
        return self._caster.spell_slots if self._caster else {}

    @spell_slots.setter
    def spell_slots(self, value: dict) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.spell_slots = value

    @property
    def spell_domains(self) -> list:
        return self._caster.spell_domains if self._caster else []

    @spell_domains.setter
    def spell_domains(self, value: list) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.spell_domains = value

    # AI 组件
    @property
    def behavior_table(self) -> list:
        return self._ai.behavior_table if self._ai else []

    @behavior_table.setter
    def behavior_table(self, value: list) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.behavior_table = value

    @property
    def behavior_overrides(self) -> dict:
        return self._ai.behavior_overrides if self._ai else {}

    @behavior_overrides.setter
    def behavior_overrides(self, value: dict) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.behavior_overrides = value

    @property
    def template_name(self) -> str:
        return self._ai.template_name if self._ai else ""

    @template_name.setter
    def template_name(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.template_name = value

    @property
    def bravery_tier(self) -> str:
        return self._ai.bravery_tier if self._ai else "medium"

    @bravery_tier.setter
    def bravery_tier(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.bravery_tier = value

    @property
    def aggression_tier(self) -> str:
        return self._ai.aggression_tier if self._ai else "medium"

    @aggression_tier.setter
    def aggression_tier(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.aggression_tier = value

    @property
    def schedule(self) -> str:
        return self._ai.schedule if self._ai else "idle"

    @schedule.setter
    def schedule(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.schedule = value

    @property
    def _hunt_target(self) -> Any:
        return self._ai._hunt_target if self._ai else None

    @_hunt_target.setter
    def _hunt_target(self, value: Any) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._hunt_target = value

    @property
    def _cached_path(self) -> Any:
        return self._ai._cached_path if self._ai else None

    @_cached_path.setter
    def _cached_path(self, value: Any) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._cached_path = value

    @property
    def _path_target(self) -> Any:
        return self._ai._path_target if self._ai else None

    @_path_target.setter
    def _path_target(self, value: Any) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._path_target = value

    @property
    def _action_remaining_cost(self) -> float:
        return self._ai._action_remaining_cost if self._ai else 0.0

    @_action_remaining_cost.setter
    def _action_remaining_cost(self, value: float) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._action_remaining_cost = value

    @property
    def curS_ticks(self) -> int:
        return self._ai.curS_ticks if self._ai else 0

    @curS_ticks.setter
    def curS_ticks(self, value: int) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.curS_ticks = value

    @property
    def _current_action(self) -> str:
        return self._ai._current_action if self._ai else "idle"

    @_current_action.setter
    def _current_action(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._current_action = value

    @property
    def _ally_count(self) -> int:
        return self._ai._ally_count if self._ai else 0

    @_ally_count.setter
    def _ally_count(self, value: int) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._ally_count = value

    @property
    def _attitude(self) -> dict:
        if self._ai is None:
            self._ai = AIComponent()
        return self._ai._attitude

    @_attitude.setter
    def _attitude(self, value: dict) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._attitude = value

    @property
    def _interrupted(self) -> bool:
        """是否被伤害打断（AI 运行时状态）。"""
        if self._ai is None:
            self._ai = AIComponent()
        return self._ai._interrupted

    @_interrupted.setter
    def _interrupted(self, value: bool) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._interrupted = value

    # ---- 状态管理 ----

    def has_status(self, name: str) -> bool:
        """检查是否有指定名称的状态。"""
        return any(s.name == name for s in self.statuses)

    def add_status(self, name: str, duration: int | None = None) -> None:
        """添加状态。若已存在则刷新 duration。"""
        if name == STATUS_BLEEDING:
            self.statuses.append(StatusEffect(name=name, duration=duration))
            return
        for s in self.statuses:
            if s.name == name:
                if duration is not None:
                    s.duration = duration
                # 失能/不可移动顺带清除回避（阶段7 D19）
                if name in ("incapacitated", "不可移动"):
                    self.remove_status("dodge")
                return
        self.statuses.append(StatusEffect(name=name, duration=duration))
        # 失能/不可移动顺带清除回避（阶段7 D19）
        if name in ("incapacitated", "不可移动"):
            self.remove_status("dodge")
        # 倒地打断进行中的多钟摆动作；主动打滚等已完成动作不遗留打断标记
        if name == "prone" and self._action_remaining_cost > 0:
            self._interrupted = True
        # 昏迷：进入时重置自然清醒累积（重新累计 1500 钟摆）
        if name == STATUS_COMATOSE:
            self._comatose_pendulums = 0.0
            self.add_status(STATUS_INCAPACITATED)
            self.add_status(STATUS_PRONE)
            self.add_status(STATUS_IMMOBILE)

    def remove_status(self, name: str) -> None:
        """移除状态。"""
        self.statuses = [s for s in self.statuses if s.name != name]
        if name == STATUS_BLEEDING:
            self._bleeding_pendulums = 0
        # 失去昏迷 → 清空自然清醒累积（1500 钟摆累计中断）
        if name == STATUS_COMATOSE:
            self._comatose_pendulums = 0.0

    def _enter_wounded(self) -> None:
        """进入重伤；仅从阈值外首次进入时投掷一次重伤结果。"""
        if self.has_status(STATUS_WOUNDED):
            return
        self.add_status(STATUS_WOUNDED)
        self.add_status(STATUS_BLOODIED)
        self.add_status(STATUS_WET)
        result = random.randint(1, 20)
        if result == 1:
            self.add_status(STATUS_INCAPACITATED)
        elif result <= 10:
            self.add_status(STATUS_BLEEDING)
        elif result <= 19:
            self.add_status(STATUS_PRONE)
        else:
            self.add_status(STATUS_COMATOSE)

    def _leave_wounded(self) -> None:
        """恢复到重伤阈值以上时清除重伤链的阈值状态。"""
        if not self.has_status(STATUS_WOUNDED):
            return
        self.remove_status(STATUS_WOUNDED)
        self.remove_status(STATUS_BLOODIED)
        self.remove_status(STATUS_WET)
        self.remove_status(STATUS_INCAPACITATED)
        self.remove_status(STATUS_IMMOBILE)
        self.remove_status(STATUS_BLEEDING)
        self._bleeding_pendulums = 0

    @property
    def can_act(self) -> bool:
        return not self.has_status(STATUS_INCAPACITATED)

    @property
    def effective_max_ap(self) -> int:
        return self.max_ap // 2 if self.has_status(STATUS_WOUNDED) else self.max_ap

    @property
    def effective_max_courage(self) -> int:
        return self.max_courage // 2 if self.has_status(STATUS_WOUNDED) else self.max_courage

    @property
    def effective_vision_range(self) -> int:
        return self.vision_range // 2 if self.has_status(STATUS_WOUNDED) else self.vision_range

    def ignite(self, duration: int) -> None:
        """点燃实体。潮湿状态使灼烧持续时间减半（并消耗潮湿）。"""
        if self.has_status("潮湿"):
            duration = max(1, duration // 2)
            self.remove_status("潮湿")
        self.add_status("灼烧", duration)

    def take_damage(self, amount: int, damage_type: str = "physical", critical: bool = False) -> bool:
        """扣血并标记打断。返回 True 表示触发了打断。

        死亡规则（D24）：
        - 从非 0 降至 0 → 不累积濒死受伤，进入濒死（开始死亡豁免）
        - 已濒死（hp=0）再受伤 → 累积濒死受伤 + 失败计数（重击 +2）
        - 濒死受伤 >= 生命上限 → 立即死亡
        """
        damage_type = normalize_damage_type(damage_type)
        if self._is_dead:
            return False
        if getattr(self, 'controlled', False):
            if self.hp <= 0:
                ds = self._get_death_saves()
                ds.take_damage_at_zero(amount, self.max_hp, critical=critical)
                if ds.death_injury >= self.max_hp:
                    self._die()
            elif self.hp - amount <= 0:
                self.hp = 0
                self._enter_dying()
            else:
                self.hp -= amount
            self._interrupted = True
            return True
        if self.hp <= 0:
            # 已濒死再受伤：累积濒死受伤 + 失败计数
            ds = self._get_death_saves()
            ds.take_damage_at_zero(amount, self.max_hp, critical=critical)
            if ds.death_injury >= self.max_hp:
                self._die()
        elif self.hp - amount <= 0:
            # 从非 0 降至 0 → 进入濒死（不累积濒死受伤）
            self.hp = 0
            self._enter_dying()
        else:
            self.hp -= amount
        self._interrupted = True  # 任何伤害都打断当前动作
        return True

    # ── 死亡系统（D24）──

    def _get_death_saves(self):
        """懒初始化死亡豁免记录。"""
        from domain.death import DeathSaves
        if self.death_saves is None:
            self.death_saves = DeathSaves()
            self.death_saves.max_hp = self.max_hp
        return self.death_saves

    def _enter_dying(self):
        """进入濒死：HP=0，开始死亡豁免。陷入濒死会失去昏迷状态。"""
        self.add_status(STATUS_DYING)
        self.remove_status(STATUS_COMATOSE)
        self._get_death_saves().reset()
        if self._death_save_callback is not None:
            self._death_save_callback(self)

    def accumulate_comatose(self, delta: float) -> None:
        """昏迷自然清醒累积（1500 钟摆）。仅在持续昏迷时累计；达到阈值自动清除。

        失去昏迷（治疗/濒死/自然清醒）时累积由 remove_status 清空。
        """
        if not self.has_status(STATUS_COMATOSE):
            return
        self._comatose_pendulums += delta
        if self._comatose_pendulums >= COMATOSE_AUTO_WAKE_PENDULUMS:
            self.remove_status(STATUS_COMATOSE)  # remove_status 会清零累积

    def _die(self):
        """真正死亡：置死亡标记，移除濒死/昏迷状态。"""
        if self._is_dead:
            return
        self._is_dead = True
        self.remove_status(STATUS_DYING)
        self.remove_status(STATUS_COMATOSE)
        if self._death_callback is not None:
            self._death_callback(self)

    def heal(self, amount: int) -> None:
        """恢复生命。恢复后自动清除濒死/昏迷（由 hp setter 统一处理）。"""
        if self._is_dead:
            return
        self.hp = min(self.max_hp, self.hp + amount)

    def revive(self, hp: int | None = None) -> None:
        """复活：恢复半血，清死亡豁免并施加震慑。"""
        self._is_dead = False
        self.remove_status(STATUS_DYING)
        self._get_death_saves().reset()
        self._reviving = True
        try:
            self.hp = max(1, self.max_hp // 2) if hp is None else hp
            self.remove_status(STATUS_COMATOSE)
            self.remove_status(STATUS_INCAPACITATED)
            self.remove_status(STATUS_PRONE)
            self.remove_status(STATUS_IMMOBILE)
            self.add_status(STATUS_STUNNED)
        finally:
            self._reviving = False

    def tick_statuses(self, delta: float = 1.0) -> list[str]:
        """推进状态；流血按完整 6 钟摆结算一次。"""
        from domain.combat.attack import roll_dice
        expired = []
        full = int(delta)
        if self.has_status(STATUS_BLEEDING):
            self._bleeding_pendulums += delta
            while self._bleeding_pendulums >= 6:
                self._bleeding_pendulums -= 6
                for _ in range(sum(s.name == STATUS_BLEEDING for s in self.statuses)):
                    self.take_damage(roll_dice(1, 4), "physical")
        for s in self.statuses:
            if s.duration is not None:
                # 灼烧：本钟摆仍燃烧 → 先结算火焰伤害，再扣计时
                if s.name == "灼烧" and s.duration > 0 and full > 0:
                    fire_traits = self.temp_traits.get("fire", {})
                    burn_mult = fire_traits.get("burn_mult", 1.0)
                    ticks = min(s.duration, full)
                    total_dmg = 0
                    for _ in range(ticks):
                        total_dmg += max(1, int(roll_dice(1, 4) * burn_mult))
                    self.take_damage(total_dmg, "fire")
                s.duration -= full
                if s.duration <= 0:
                    expired.append(s.name)
        for name in expired:
            self.remove_status(name)
            if name == "攀爬药效":
                self.climb_speed = 0
            elif name == "飞行药效":
                self.fly_speed = 0
            elif name == "悬浮药效":
                self.is_hovering = False
        return expired

    # ---- AI 字段 ----
    template_name: str = ""               # AI 行为模板名
    bravery_tier: str = "medium"          # "low" | "medium" | "high"
    aggression_tier: str = "medium"       # "low" | "medium" | "high"
    schedule: str = "idle"               # 当前日程

    def meets_condition(self, cond: str) -> bool:
        """检查硬过滤条件。"""
        if cond == "can_move":
            return not self.has_status("incapacitated") and not self.has_status(STATUS_IMMOBILE)
        if cond == "has_weapon":
            return True  # MVP 暂定都有武器
        if cond == "has_healing_potion":
            return False  # MVP NPC 不带药水
        if cond == "enemy_can_communicate":
            return self.language != ""
        return True

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        value = float(value)
        previous = getattr(self, "_speed", None)
        if value <= 0:
            if previous is None:
                self._speed = MIN_SPEED
                return
            self._speed = previous
            self.add_status(STATUS_IMMOBILE)
            return
        self._speed = max(MIN_SPEED, value)

    def apply_speed_modifier(self, delta: float) -> float:
        """应用速度等级修正；结果无效时保留原速度并使实体不可移动。"""
        previous = self.speed
        self.speed = previous + float(delta)
        return self.speed

    @property
    def effective_speed(self) -> float:
        """用于时间换算的速度；超过10的部分不再缩短时间。"""
        return min(self.speed, MAX_EFFECTIVE_SPEED)

    def __init__(
        self,
        name: str,
        faction: str = "中立",
        body_type: str = "humanoid",
        size: str = "medium",
        reach: int | None = None,
        facing: tuple = (0, 1),
        hp: int = 30,
        max_hp: int = 30,
        tenacity: int = 10,
        max_tenacity: int = 10,
        ap: int = 60,
        max_ap: int = 60,
        courage: int = 0,
        max_courage: int = 0,
        speed: int = 1,
        ac_base: int = 8,
        char: str = "?",
        obstacle_type: str = ObstacleType.THREE_QUARTER.value,
        block_value: int = 0,
        stats: dict | None = None,
        ac_chest: int = 0,
        ac_arms: int = 0,
        ac_legs: int = 0,
        ac_head: int = 0,
        ac_shield: int = 0,
        vision_range: int = 8,
        food_value: int = 15000,
        food_locked: bool = False,
        darkvision_range: int = 0,
        language: str = "",
        actions: list | None = None,
        traits: list | None = None,
        loot: dict | None = None,
        shop_id: str = "",
        shop_gold: int = 0,
        corpse: dict | None = None,
        statuses: list | None = None,
        armor_experience: dict[str, float] | None = None,
        armor_training_progress: dict[str, float] | None = None,
        # 组件字段（兼容旧构造方式，通过 property setter 挂载组件）
        controlled: bool = False,
        inventory: list | None = None,
        equipment: dict | None = None,
        gp: int | None = None,
        sp: int | None = None,
        cp: int | None = None,
        char_class: str = "",
        background: str = "",
        class_level: int = 0,
        class_exp: float = 0.0,
        mp: int | None = None,
        max_mp: int | None = None,
        memorized_spells: list | None = None,
        spell_slots: dict | None = None,
        spell_domains: list | None = None,
        behavior_table: list | None = None,
        behavior_overrides: dict | None = None,
        template_name: str = "",
        bravery_tier: str = "medium",
        aggression_tier: str = "medium",
        schedule: str = "idle",
        _hunt_target: Any = None,
        _cached_path: Any = None,
        _path_target: Any = None,
        _action_remaining_cost: float = 0.0,
        curS_ticks: int = 0,
        _current_action: str = "idle",
        _ally_count: int = 0,
        _attitude: dict | None = None,
        _favor: dict | None = None,
        uid: int | None = None,
        temp_traits: dict | None = None,
        z: int = 0,
        climb_speed: float = 0,
        fly_speed: float = 0,
        is_hovering: bool = False,
    ):
        # 固有字段（所有生物共有）
        self.name = name
        self.faction = faction
        self.body_type = body_type
        self.size = size
        self.reach = reach
        self.facing = tuple(facing) if facing is not None else (0, 1)
        self.z = int(z)
        self.climb_speed = max(0.0, float(climb_speed))
        self.fly_speed = max(0.0, float(fly_speed))
        self.is_hovering = bool(is_hovering)
        self._is_dead = False
        self.death_saves = None
        self._comatose_pendulums = 0.0
        self._hp = 0
        self.max_hp = max_hp
        self.hp = hp
        self.tenacity = tenacity
        self.max_tenacity = max_tenacity
        self.ap = ap
        self.max_ap = max_ap
        self.max_courage = max(0, int(max_courage))
        self.courage = max(0, min(int(courage), self.max_courage))
        self.speed = speed
        self.ac_base = ac_base
        self.char = char
        kind = normalize_obstacle_type(obstacle_type)
        default_block = obstacle_defaults(kind)[1]
        self._obstacle = ObstacleComponent(kind, block_value or default_block)
        self.stats = dict(stats) if stats else dict(DEFAULT_STATS)
        self.ac_chest = ac_chest
        self.ac_arms = ac_arms
        self.ac_legs = ac_legs
        self.ac_head = ac_head
        self.ac_shield = ac_shield
        self.vision_range = vision_range
        self.food_value = food_value
        self.food_locked = food_locked
        self.darkvision_range = darkvision_range
        self.language = language
        self.actions = actions if actions is not None else []
        self.traits = traits if traits is not None else []
        self.loot = loot if loot is not None else {}
        self.shop_id = shop_id
        self.shop_gold = shop_gold
        # 尸体武器：每生物独立的尸体物品（普通双手武器）。None 表示无尸体。
        self.corpse = ItemFactory.create_weapon(corpse) if corpse else None
        if self.corpse is not None:
            self.corpse.item_type = "corpse"
            self.corpse.stack_limit = 1
        self.statuses = statuses if statuses is not None else []
        self.armor_experience = dict(armor_experience or {})
        self.armor_training_progress = dict(armor_training_progress or {})
        self.temp_traits = dict(temp_traits) if temp_traits else {}
        self._oa_suspended = False
        self._reviving = False
        # 组件容器初始化为未挂载
        self._control = None
        self._ally = None
        self._ai = None
        self.party_member = False
        self._caster = None
        self._class = None
        self._inventory = None
        # 组件字段通过 property setter 挂载（None/默认值表示未挂载）
        if controlled:
            self.controlled = True
        if gp is not None:
            self.gp = gp
        if sp is not None:
            self.sp = sp
        if cp is not None:
            self.cp = cp
        if inventory is not None:
            self.inventory = inventory
        if equipment is not None:
            self.equipment = equipment
        if char_class:
            self.char_class = char_class
        if background:
            self.background = background
        if class_level:
            self.class_level = class_level
        if class_exp:
            self.class_exp = class_exp
        if char_class or class_level or class_exp:
            from domain.classes import ensure_class_progress, sync_all_titles
            ensure_class_progress(self)
            sync_all_titles(self)
        if mp is not None:
            self.mp = mp
        if max_mp is not None:
            self.max_mp = max_mp
        if memorized_spells is not None:
            self.memorized_spells = memorized_spells
        if spell_slots is not None:
            self.spell_slots = spell_slots
        if spell_domains is not None:
            self.spell_domains = spell_domains
        if behavior_table is not None:
            self.behavior_table = behavior_table
        if behavior_overrides is not None:
            self.behavior_overrides = behavior_overrides
        if template_name:
            self.template_name = template_name
        if bravery_tier != "medium":
            self.bravery_tier = bravery_tier
        if aggression_tier != "medium":
            self.aggression_tier = aggression_tier
        if schedule != "idle":
            self.schedule = schedule
        if _hunt_target is not None:
            self._hunt_target = _hunt_target
        if _cached_path is not None:
            self._cached_path = _cached_path
        if _path_target is not None:
            self._path_target = _path_target
        if _action_remaining_cost:
            self._action_remaining_cost = _action_remaining_cost
        if curS_ticks:
            self.curS_ticks = curS_ticks
        if _current_action != "idle":
            self._current_action = _current_action
        if _ally_count:
            self._ally_count = _ally_count
        if _attitude is not None:
            self._attitude = _attitude
        self._favor = dict(_favor) if _favor else {}
        self.uid = _next_uid() if uid is None else uid
        self.__post_init__()

    def __post_init__(self):
        # 钳制 HP/MP/韧性
        self.hp = max(0, min(self.hp, self.max_hp))
        self.tenacity = max(0, min(self.tenacity, self.max_tenacity))
        if self.body_type == "humanoid":
            from domain.classes import ensure_class_progress, sync_all_titles
            ensure_class_progress(self)
            if self.char_class:
                sync_all_titles(self)

    # ---- 属性 ----

    def stat(self, name: str) -> int:
        return self.stats.get(name, 8)

    def stat_adjust(self, name: str) -> int:
        return stat_adjust(self.stat(name))

    def grant_route_exp(self, class_name: str, amount: float) -> bool:
        """累积指定职业路线经验，满足条件时升级并发放奖励。"""
        from domain.classes import (
            ALL_CLASS_KEYS,
            apply_level_rewards,
            effective_level_for_class,
            ensure_class_progress,
            _route_experience,
        )

        if class_name not in ALL_CLASS_KEYS or amount <= 0:
            return False
        ensure_class_progress(self)
        old_level = effective_level_for_class(self, class_name)
        new_exp = _route_experience(self, class_name) + amount
        self.class_experience[class_name] = new_exp
        new_level = effective_level_for_class(self, class_name)
        self.class_levels[class_name] = new_level
        if class_name == self.char_class:
            self.class_exp = new_exp
            self.class_level = new_level
        if new_level > old_level:
            apply_level_rewards(self, class_name, old_level, new_level)
        return new_level > old_level

    def grant_class_exp(self, amount: float = 0.01) -> bool:
        """累积主职业总经验，并按新职业表刷新等级。"""
        if not self.char_class:
            return False
        return self.grant_route_exp(self.char_class, amount)

    def grant_domain_exp(self, domain: str, amount: float) -> bool:
        """累积领域总经验，并返回是否刚刚提升领域等级。"""
        from domain.classes import domain_level_for_exp

        old_exp = self.domain_experience.get(domain, 0.0)
        old_level = domain_level_for_exp(domain, old_exp)
        new_exp = old_exp + amount
        new_level = domain_level_for_exp(domain, new_exp)
        self.domain_experience[domain] = new_exp
        if new_level > old_level and domain not in self.domain_talents:
            self.domain_talents.append(domain)
        return new_level > old_level

    def grant_weapon_exp(self, category: str, amount: float) -> None:
        """累积武器类别熟练经验。"""
        if category:
            self.weapon_experience[category] = (
                self.weapon_experience.get(category, 0.0) + amount
            )

    def weapon_proficiency_level(self, category: str) -> int:
        """返回指定武器类别的熟练项等级（0~5）。"""
        from domain.classes import proficiency_level
        return proficiency_level(self.weapon_experience.get(category, 0.0))

    def weapon_expertise_level(self, category: str) -> int:
        """返回指定武器类别的专精项等级（0~5）。"""
        from domain.classes import expertise_level
        return expertise_level(self.weapon_experience.get(category, 0.0))

    def armor_proficiency_level(self, armor_type: str) -> int:
        """返回指定护甲类别的熟练项等级（0~5）。"""
        from domain.classes import proficiency_level
        return proficiency_level(self.armor_experience.get(armor_type, 0.0))

    def armor_expertise_level(self, armor_type: str) -> int:
        """返回指定护甲类别的专精项等级（0~5）。"""
        from domain.classes import expertise_level
        return expertise_level(self.armor_experience.get(armor_type, 0.0))

    def advance_armor_training(self, pendulums: float) -> None:
        """按已穿戴护甲类别累计训练时间，每100钟摆获得0.01经验。"""
        if pendulums < 0:
            raise ValueError("护甲训练时间不能为负数")
        worn_categories = {
            item.armor_type for item in self.equipment.values()
            if getattr(item, "armor", None) is not None
            and item.armor_type in ("clothing", "light", "medium", "heavy")
        }
        for armor_type in worn_categories:
            progress = self.armor_training_progress.get(armor_type, 0.0) + pendulums
            gained, remainder = divmod(progress, 100.0)
            if gained:
                self.armor_experience[armor_type] = (
                    self.armor_experience.get(armor_type, 0.0)
                    + gained * 0.01
                )
            self.armor_training_progress[armor_type] = remainder

    def has_armor_proficiency(self, armor_type: str) -> bool:
        """判断是否具备指定护甲类别熟练项；服饰不要求熟练。"""
        if armor_type in ("clothing", "shield"):
            return True
        return self.armor_proficiency_level(armor_type) > 0

    def armor_penalty(self) -> dict:
        """返回当前装备护甲造成的统一惩罚数据。"""
        armor_items = [
            item for item in self.equipment.values()
            if getattr(item, "armor", None) is not None
        ]
        worn = [
            item for item in armor_items
            if item.armor_type not in ("clothing", "shield")
        ]
        unproficient = any(
            not self.has_armor_proficiency(item.armor_type) for item in worn
        )
        strength_penalty = any(
            self.stat("str") < item.str_requirement
            for item in worn
        )
        return {
            "unproficient": unproficient,
            "dex_disadvantage": unproficient or strength_penalty,
            "str_disadvantage": unproficient,
            "spell_cost_multiplier": 2 if unproficient else 1,
            "strength_penalty": strength_penalty,
            "speed_multiplier": 0.5 if strength_penalty else 1.0,
        }

    def grant_attribute_exp(self, attribute: str, amount: float) -> None:
        """累积属性经验，不改变基础属性值。"""
        if attribute:
            self.attribute_experience[attribute] = (
                self.attribute_experience.get(attribute, 0.0) + amount
            )

    # ---- 衍生值 ----

    def initiative_bonus(self) -> int:
        return self.stat_adjust("dex")

    def total_ac(self, body_part: str = "chest") -> int:
        """计算指定部位的总 AC。"""
        base = self.ac_base + self.stat_adjust("dex")
        part_bonus = {
            "chest": self.ac_chest,
            "arms": self.ac_arms,
            "legs": self.ac_legs,
            "head": self.ac_head,
        }.get(body_part, 0)
        # 状态 AC 加成：guarding(+1) / shield(+5 护盾术，全身)
        status_bonus = 0
        if self.has_status("guarding"):
            status_bonus += 1
        if self.has_status("shield"):
            status_bonus += 5
        return base + part_bonus + self.ac_shield + status_bonus

    def carry_capacity(self) -> float:
        """负重上限 (kg) = 20 + 力量调整值 * 2"""
        return 20.0 + self.stat_adjust("str") * 2

    @property
    def total_carry_weight(self) -> float:
        """总负重 = 装备栏 + 物品栏重量之和。"""
        total = 0.0
        for item in self.equipment.values():
            if item is not None:
                total += getattr(item, 'weight', 0.0)
        for item in self.inventory:
            w = getattr(item, 'weight', 0.0)
            count = getattr(item, 'count', 1)
            total += w * count
        return total

    def carry_status(self) -> dict:
        """返回当前负重状态 {threshold, label, effects}。"""
        cap = self.carry_capacity()
        if cap <= 0:
            return CARRY_STATUS["overloaded"]
        ratio = self.total_carry_weight / cap
        if ratio < CARRY_STATUS["light"]["threshold"]:
            return CARRY_STATUS["light"]
        elif ratio < CARRY_STATUS["encumbered"]["threshold"]:
            return CARRY_STATUS["encumbered"]
        else:
            return CARRY_STATUS["overloaded"]

    # ---- 构造 ----

    @classmethod
    def from_dict(cls, data: dict, repository=None) -> "Entity":
        stats = {**DEFAULT_STATS, **data.get("stats", {})}
        creature = cls(
            name=data["name"],
            faction=data.get("faction", "中立"),
            body_type=data.get("body_type", "humanoid"),
            size=data.get("size", "medium"),
            reach=data.get("reach"),
            facing=tuple(data.get("facing", (0, 1))),
            hp=data.get("hp", data.get("max_hp", 30)),
            max_hp=data.get("max_hp", data.get("hp", 30)),
            tenacity=data.get("tenacity", 10),
            max_tenacity=data.get("max_tenacity", 10),
            ap=data.get("ap", 6),
            max_ap=data.get("max_ap", 6),
            courage=data.get("courage", 0),
            max_courage=data.get("max_courage", 0),
            speed=data.get("speed", 1),
            ac_base=data.get("ac_base", data.get("ac", 8)),
            char=data.get("char") or data.get("key", "?")[0].lower(),
            stats=stats,
            obstacle_type=_entity_obstacle_type(data),
            block_value=data.get("block_value", 0),
            vision_range=data.get("vision_range", 8),
            food_value=data.get("food_value", 15000),
            food_locked=data.get("food_locked", False),
            darkvision_range=data.get("darkvision_range", 0),
            language=data.get("language", ""),
            actions=data.get("actions", []),
            traits=data.get("traits", []),
            loot=data.get("loot", {}),
            shop_id=data.get("shop_id", ""),
            shop_gold=data.get("shop_gold", 0),
            corpse=data.get("corpse"),
            statuses=[StatusEffect(name=s["name"], duration=s.get("duration")) if isinstance(s, dict) else StatusEffect(name=s) for s in data.get("statuses", [])],
            armor_experience=data.get("armor_experience", {}),
            temp_traits=data.get("temperature", {}),
        )

        # 数据驱动挂载组件
        # 1. 物品栏组件（有 inventory 或 equipment 字段则挂载）
        if "inventory" in data or "equipment" in data:
            from domain.ports import RepositoryPort, get_repository
            repository = repository or get_repository()
            inv_comp = InventoryComponent(
                gp=data.get("gp", 0),
                sp=data.get("sp", 0),
                cp=data.get("cp", 0),
            )
            for slot, item_name in data.get("equipment", {}).items():
                if item_name and slot in inv_comp.equipment:
                    item = ItemFactory.create_from_name(item_name, repository)
                    if item:
                        inv_comp.equipment[slot] = item
            for item_name in data.get("accessories", []):
                item = ItemFactory.create_from_name(item_name, repository)
                if item:
                    inv_comp.accessories.append(item)
            inv_comp.inventory = []
            for ref in data.get("inventory", []):
                item = ItemFactory.create_from_name(ref["name"], repository)
                if item is None:
                    raise ValueError(f"实体库存物品不存在：{ref['name']}")
                item.count = ref.get("count", 1)
                inv_comp.inventory.append(item)
            creature._inventory = inv_comp

        # 2. 施法组件（有 spell_domains 或 memorized_spells 字段则挂载）
        if any(key in data for key in ("spell_domains", "memorized_spells", "spell_slots", "domain_talents")):
            creature._caster = CasterComponent(
                mp=data.get("mp", 0),
                max_mp=data.get("max_mp", 0),
                memorized_spells=data.get("memorized_spells", []),
                spell_slots=data.get("spell_slots", {}),
                spell_domains=data.get("spell_domains", data.get("domain_talents", [])),
            )

        # 3. 职业组件（有 char_class 或 class 字段则挂载）
        if "char_class" in data or "class" in data:
            creature._class = ClassComponent(
                char_class=data.get("char_class", data.get("class", "")),
                background=data.get("background", ""),
                class_level=int(data.get("class_level", 0)),
                class_exp=data.get("class_exp", 0.0),
                class_levels=data.get("class_levels", {}),
                class_experience=data.get("class_experience", {}),
                domain_talents=data.get("domain_talents", []),
                domain_experience=data.get("domain_experience", {}),
                weapon_experience=data.get("weapon_experience", {}),
                attribute_experience=data.get("attribute_experience", {}),
                titles=data.get("titles", []),
            )
            from domain.classes import ensure_class_progress, sync_all_titles
            ensure_class_progress(creature)
            sync_all_titles(creature)

        # 4. AI 组件（默认挂载；玩家选中后由 set_controlled 摘除）
        ai_comp = AIComponent()
        behavior = data.get("behavior", None)
        if behavior:
            ai_comp.behavior_table = behavior.get("components", DEFAULT_BEHAVIOR["components"])
            ai_comp.behavior_overrides = behavior.get("overrides", {})
        else:
            ai_comp.behavior_table = list(DEFAULT_BEHAVIOR["components"])
            ai_comp.behavior_overrides = dict(DEFAULT_BEHAVIOR["overrides"])
        creature._ai = ai_comp

        # 5. 合并通用动作（D22：所有实体获得部分动作存入行动表，注入不筛）
        existing_keys = {a.get("key") for a in creature.actions if isinstance(a, dict) and a.get("key")}
        merged = list(creature.actions)
        from domain.entity.factory import _generic_actions
        for ga in _generic_actions():
            if ga.get("key") not in existing_keys:
                merged.append(ga)
        creature.actions = merged

        return creature




# ═══════════════════════════════════════════════════
# 负重状态表（哈希表驱动）
# ═══════════════════════════════════════════════════

CARRY_STATUS = {
    "light":      {"threshold": 0.8,  "label": "轻便",   "effects": []},
    "encumbered": {"threshold": 1.0,  "label": "负重",   "effects": ["speed_halved", "dex_disadvantage", "ap_penalty_1"]},
    "overloaded": {"threshold": float("inf"), "label": "超重", "effects": ["immobilized", "dex_auto_fail", "ap_penalty_2"]},
}




