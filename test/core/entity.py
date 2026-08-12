"""实体数据类 —— Creature、Item、Weapon、Armor。

Phase 3: Player 类已删除，统一使用 Creature + controlled 标记。
字段对齐 test/docs/MVP2.md。
"""

from dataclasses import dataclass, field
from typing import Any

from core.ai.components import DEFAULT_BEHAVIOR


# ═══════════════════════════════════════════════════
# 属性
# ═══════════════════════════════════════════════════

DEFAULT_STATS = {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}

STAT_NAMES = ["str", "dex", "con", "int", "wis", "cha"]


def stat_adjust(stat_value: int) -> int:
    """属性调整值 = (属性值 - 8) // 2，向下取整。"""
    return (stat_value - 8) // 2


# ═══════════════════════════════════════════════════
# Creature
# ═══════════════════════════════════════════════════

@dataclass
class StatusEffect:
    """状态效果。duration=None 表示永久（如 incapacitated），>0 表示剩余钟摆数。"""
    name: str
    duration: int | None = None


@dataclass
class Creature:
    """生物数据类。字段对齐 MVP2.md 六、生物 定义。"""

    name: str
    faction: str = "中立"                  # "守序" | "中立" | "混乱"
    body_type: str = "humanoid"           # "humanoid" | "beast" | "undead" | ...

    # 核心数值
    hp: int = 30
    max_hp: int = 30
    mp: int = 0
    max_mp: int = 0
    tenacity: int = 10
    max_tenacity: int = 10
    ap: int = 6
    max_ap: int = 6
    speed: int = 1                        # 速度等级 (格子/钟摆)
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

    # 其他
    vision_range: int = 8
    food_value: int = 15000
    food_locked: bool = False             # True = 饮食值不消耗
    darkvision_range: int = 0             # 0 = 无黑暗视觉
    language: str = ""

    # 动作、特性、掉落
    actions: list[dict] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)
    loot: dict = field(default_factory=dict)

    # 智慧生物物品栏
    inventory: list = field(default_factory=list)
    equipment: dict[str, "Item | None"] = field(default_factory=lambda: {
        "head": None, "chest": None, "arms": None, "legs": None,
        "left_hand": None, "right_hand": None, "accessory1": None,
        "accessory2": None, "accessory3": None,
    })
    # 货币
    gp: int = 0
    sp: int = 0
    cp: int = 0
    # 角色
    char_class: str = ""
    background: str = ""
    # 法术
    memorized_spells: list[str] = field(default_factory=list)
    # 控制组件
    controlled: bool = False
    _hunt_target: Any = field(default=None, repr=False)  # 临时捕猎目标 (creature, pos)
    _hostile_to: set = field(default_factory=set, repr=False)  # 临时敌对的生物 id 集合
    curS_ticks: int = 0                    # 里程累积 [0, maxS*SCALE)，SCALE=10
    _action_remaining_cost: float = 0.0    # 当前动作剩余耗时（钟摆），0=无活跃动作
    _cached_path: Any = field(default=None, repr=False)   # 寻路缓存
    _path_target: Any = field(default=None, repr=False)   # 路径目标缓存
    _current_action: str = "idle"   # 当前选中的行为（渲染场景描述用）
    _ally_count: int = 0            # 盟友数（渲染用，扫描时顺带算好）
    behavior_table: list = field(default_factory=list)  # 可用组件名列表
    behavior_overrides: dict = field(default_factory=dict)  # 权重覆盖

    # 状态效果
    statuses: list[StatusEffect] = field(default_factory=list)

    # ---- 状态管理 ----

    def has_status(self, name: str) -> bool:
        """检查是否有指定名称的状态。"""
        return any(s.name == name for s in self.statuses)

    def add_status(self, name: str, duration: int | None = None) -> None:
        """添加状态。若已存在则刷新 duration。"""
        for s in self.statuses:
            if s.name == name:
                if duration is not None:
                    s.duration = duration
                return
        self.statuses.append(StatusEffect(name=name, duration=duration))

    def remove_status(self, name: str) -> None:
        """移除状态。"""
        self.statuses = [s for s in self.statuses if s.name != name]

    def tick_statuses(self) -> list[str]:
        """每钟摆推进有持续时间的状态。返回本次到期的状态名列表。"""
        expired = []
        for s in self.statuses:
            if s.duration is not None:
                s.duration -= 1
                if s.duration <= 0:
                    expired.append(s.name)
        for name in expired:
            self.remove_status(name)
        return expired

    # ---- AI 字段 ----
    template_name: str = ""               # AI 行为模板名
    bravery_tier: str = "medium"          # "low" | "medium" | "high"
    aggression_tier: str = "medium"       # "low" | "medium" | "high"
    schedule: str = "idle"               # 当前日程

    def meets_condition(self, cond: str) -> bool:
        """检查硬过滤条件。"""
        if cond == "can_move":
            return not self.has_status("incapacitated")
        if cond == "has_weapon":
            return True  # MVP 暂定都有武器
        if cond == "has_healing_potion":
            return False  # MVP NPC 不带药水
        if cond == "enemy_can_communicate":
            return self.language != ""
        return True

    def __post_init__(self):
        # 钳制 HP/MP/韧性
        self.hp = max(0, min(self.hp, self.max_hp))
        self.tenacity = max(0, min(self.tenacity, self.max_tenacity))

    # ---- 属性 ----

    def stat(self, name: str) -> int:
        return self.stats.get(name, 8)

    def stat_adjust(self, name: str) -> int:
        return stat_adjust(self.stat(name))

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
        return base + part_bonus + self.ac_shield

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
    def from_dict(cls, data: dict) -> "Creature":
        stats = {**DEFAULT_STATS, **data.get("stats", {})}
        creature = cls(
            name=data["name"],
            faction=data.get("faction", "中立"),
            body_type=data.get("body_type", "humanoid"),
            hp=data.get("hp", data.get("max_hp", 30)),
            max_hp=data.get("max_hp", data.get("hp", 30)),
            mp=data.get("mp", 0),
            max_mp=data.get("max_mp", 0),
            tenacity=data.get("tenacity", 10),
            max_tenacity=data.get("max_tenacity", 10),
            ap=data.get("ap", 6),
            max_ap=data.get("max_ap", 6),
            speed=data.get("speed", 1),
            ac_base=data.get("ac_base", data.get("ac", 8)),
            char=data.get("char", "?"),
            stats=stats,
            vision_range=data.get("vision_range", 8),
            food_value=data.get("food_value", 15000),
            food_locked=data.get("food_locked", False),
            darkvision_range=data.get("darkvision_range", 0),
            language=data.get("language", ""),
            actions=data.get("actions", []),
            traits=data.get("traits", []),
            loot=data.get("loot", {}),
            inventory=data.get("inventory", []),
            statuses=[StatusEffect(name=s["name"], duration=s.get("duration")) if isinstance(s, dict) else StatusEffect(name=s) for s in data.get("statuses", [])],
        )
        behavior = data.get("behavior", None)
        if behavior:
            creature.behavior_table = behavior.get("components", DEFAULT_BEHAVIOR["components"])
            creature.behavior_overrides = behavior.get("overrides", {})
        else:
            creature.behavior_table = list(DEFAULT_BEHAVIOR["components"])
            creature.behavior_overrides = dict(DEFAULT_BEHAVIOR["overrides"])
        return creature


# ═══════════════════════════════════════════════════
# 阵营关系
# ═══════════════════════════════════════════════════

FACTION_RELATIONS = {
    "守序": {"allies": ["守序"], "enemies": ["混乱"]},
    "混乱": {"allies": ["混乱"], "enemies": ["守序"]},
    "中立": {"allies": [],        "enemies": []},
}


def are_hostile(a: "Creature", b: "Creature") -> bool:
    """两生物是否敌对。同阵营不敌对，中立通过 _hostile_to 被动反击。"""
    if a is b:
        return False
    af, bf = a.faction, b.faction
    if af == bf:
        return False
    if af == "中立" and id(b) in a._hostile_to:
        return True
    if bf == "中立" and id(a) in b._hostile_to:
        return True
    enemies = FACTION_RELATIONS.get(af, {}).get("enemies", [])
    return bf in enemies


def is_ally(a: "Creature", b: "Creature") -> bool:
    """两生物是否同盟（同阵营且非临时敌对）。"""
    if a is b:
        return True
    return a.faction == b.faction


# ═══════════════════════════════════════════════════
# 负重状态表（哈希表驱动）
# ═══════════════════════════════════════════════════

CARRY_STATUS = {
    "light":      {"threshold": 0.8,  "label": "轻便",   "effects": []},
    "encumbered": {"threshold": 1.0,  "label": "负重",   "effects": ["speed_halved", "dex_disadvantage", "ap_penalty_1"]},
    "overloaded": {"threshold": float("inf"), "label": "超重", "effects": ["immobilized", "dex_auto_fail", "ap_penalty_2"]},
}


# ═══════════════════════════════════════════════════
# 物品空间默认值（按 item_type 查表）
# ═══════════════════════════════════════════════════

ITEM_SPACE_DEFAULT = {
    "weapon":     3,
    "armor":      4,
    "consumable": 1,
    "material":   1,
    "misc":       2,
}


# ═══════════════════════════════════════════════════
# Item / Weapon / Armor
# ═══════════════════════════════════════════════════

@dataclass
class Item:
    """通用物品。"""
    name: str
    item_type: str = "misc"               # "weapon" | "armor" | "consumable" | "material" | "misc"
    weight: float = 0.0
    price: dict = field(default_factory=dict)
    description: str = ""
    effect: str = ""
    amount: str = ""                       # 效果量 (如 "6d4", "15000")
    ap_cost: int = 0                       # 使用 AP 消耗
    count: int = 1                         # 物品数量
    space: int = 0                         # 占据空间，0=按 item_type 查表自动赋值
    # 投掷相关字段
    throw_range: int = 3                  # 投掷基础射程（Chebyshev 距离），0 表示不可投掷
    throw_str_req: int = 0                # 投掷力量要求（0=无要求）
    throw_damage: str = ""                # 投掷伤害骰（空=用 weight 推算或近战伤害）
    throw_damage_type: str = "bludgeoning"
    throw_effect: str = ""                # 投掷特效: "heal"|""

    def __post_init__(self):
        if self.space <= 0:
            self.space = ITEM_SPACE_DEFAULT.get(self.item_type, 1)

    @classmethod
    def from_dict(cls, data: dict) -> "Item":
        return cls(
            name=data["name"],
            count=data.get("count", 1),
            item_type=data.get("type", "misc"),
            weight=data.get("weight", 0.0),
            price=data.get("price", {}),
            description=data.get("description", ""),
            effect=data.get("effect", ""),
            amount=data.get("amount", ""),
            ap_cost=data.get("ap_cost", 0),
            space=data.get("space", 0),
            throw_range=data.get("throw_range", 3),
            throw_str_req=data.get("throw_str_req", 0),
            throw_damage=data.get("throw_damage", ""),
            throw_damage_type=data.get("throw_damage_type", "bludgeoning"),
            throw_effect=data.get("throw_effect", ""),
        )


@dataclass
class Weapon(Item):
    """武器。"""
    weapon_type: str = "melee"             # "melee" | "ranged"
    category: str = "simple"               # "simple" | "martial"
    damage: str = "1d4"
    damage_type: str = "bludgeoning"
    attack_stat: str = "str"               # "str" | "dex" | "str_or_dex"
    ap_cost: int = 2
    range_normal: int = 0
    range_max: int = 0
    properties: list[str] = field(default_factory=list)
    loaded: bool = True                    # 弹药武器已装填？战斗开始时重置
    melee: dict | None = None              # 远程武器近战属性 {"damage":"1d4","damage_type":"bludgeoning","attack_stat":"str","ap_cost":2}

    def __post_init__(self):
        self.item_type = "weapon"
        super().__post_init__()

    @classmethod
    def from_dict(cls, data: dict) -> "Weapon":
        return cls(
            name=data["name"],
            weapon_type=data.get("weapon_type", "melee"),
            category=data.get("category", "simple"),
            damage=data.get("damage", "1d4"),
            damage_type=data.get("damage_type", "bludgeoning"),
            attack_stat=data.get("attack_stat", "str"),
            ap_cost=data.get("ap_cost", 2),
            range_normal=data.get("range_normal", 0),
            range_max=data.get("range_max", 0),
            properties=data.get("properties", []),
            loaded=data.get("loaded", True),
            melee=data.get("melee"),
            weight=data.get("weight", 0.0),
            price=data.get("price", {}),
            description=data.get("description", ""),
        )


@dataclass
class Armor(Item):
    """护甲。"""
    armor_type: str = "light"              # "light" | "heavy" | "shield" | "clothing"
    slot: str = "chest"                    # "chest" | "arms" | "legs" | "head" | "full_body"
    ac_bonus: int = 0
    tenacity_bonus: int = 0
    str_requirement: int = 8

    def __post_init__(self):
        self.item_type = "armor"
        super().__post_init__()

    @classmethod
    def from_dict(cls, data: dict) -> "Armor":
        return cls(
            name=data["name"],
            armor_type=data.get("armor_type", "light"),
            slot=data.get("slot", "chest"),
            ac_bonus=data.get("ac_bonus", 0),
            tenacity_bonus=data.get("tenacity_bonus", 0),
            str_requirement=data.get("str_requirement", 8),
            weight=data.get("weight", 0.0),
            price=data.get("price", {}),
            description=data.get("description", ""),
        )


# ═══════════════════════════════════════════════════
# 工厂函数（Phase 3: 替代已删除的 Player.create_fighter / create_mage）
# ═══════════════════════════════════════════════════

def create_fighter(name: str, stats: dict) -> Creature:
    """创建战士。"""
    s = {**DEFAULT_STATS, **stats}
    s["str"] += 2
    s["con"] += 2
    return Creature(name=name, char_class="fighter", faction="守序",
                    hp=35, max_hp=35, max_ap=6, stats=s, gp=3)


def create_mage(name: str, stats: dict, domain: str = "evocation") -> Creature:
    """创建魔法使。domain: "evocation" | "abjuration" """
    s = {**DEFAULT_STATS, **stats}
    s["int"] += 2
    spells = {"evocation": ["魔法飞弹"], "abjuration": ["护盾术", "疗伤术"]}
    return Creature(name=name, char_class="mage", faction="守序",
                    hp=30, max_hp=30, mp=100, max_mp=100, max_ap=6,
                    stats=s, gp=3, memorized_spells=spells.get(domain, []))
