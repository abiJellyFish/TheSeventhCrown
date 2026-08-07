"""实体数据类 —— Entity 基类、Creature、Player、Item、Weapon、Armor。

字段对齐 test/docs/MVP2.md。
"""

from dataclasses import dataclass, field
from typing import Any


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
class Creature:
    """生物数据类。字段对齐 MVP2.md 六、生物 定义。"""

    name: str
    faction: str = "neutral"              # "friendly" | "neutral" | "hostile"
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

    # 状态标记
    statuses: list[str] = field(default_factory=list)

    # ---- AI 字段 ----
    template_name: str = ""               # AI 行为模板名
    bravery_tier: str = "medium"          # "low" | "medium" | "high"
    aggression_tier: str = "medium"       # "low" | "medium" | "high"
    schedule: str = "idle"               # 当前日程

    def meets_condition(self, cond: str) -> bool:
        """检查硬过滤条件。"""
        if cond == "can_move":
            return "incapacitated" not in self.statuses
        if cond == "has_weapon":
            return True  # MVP 暂定都有武器
        if cond == "has_healing_potion":
            return False  # MVP NPC 不带药水
        if cond == "enemy_can_communicate":
            return self.language != ""
        return True

    # ---- 预留字段 ----
    ally_slot: Any = None                 # None = 未入队; 入队后设为槽位索引

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

    # ---- 状态 ----

    def has_status(self, name: str) -> bool:
        return name in self.statuses

    # ---- 构造 ----

    @classmethod
    def from_dict(cls, data: dict) -> "Creature":
        stats = {**DEFAULT_STATS, **data.get("stats", {})}
        return cls(
            name=data["name"],
            faction=data.get("faction", "neutral"),
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
        )


# ═══════════════════════════════════════════════════
# Player
# ═══════════════════════════════════════════════════

@dataclass
class Player(Creature):
    """玩家角色。"""

    char_class: str = ""                   # "fighter" | "mage"
    background: str = ""
    personality: str = ""
    gp: int = 3                            # 金币
    sp: int = 0                            # 银币
    cp: int = 0                            # 铜币
    inventory: list["Item"] = field(default_factory=list)
    equipment: dict[str, "Item | None"] = field(default_factory=lambda: {
        "head": None, "chest": None, "arms": None, "legs": None,
        "left_hand": None, "right_hand": None, "accessory1": None,
        "accessory2": None, "accessory3": None,
    })
    memorized_spells: list[str] = field(default_factory=list)  # 法术位中的法术名

    # ---- 预留 ----
    party: list["Creature"] = field(default_factory=list)     # 队伍成员

    @classmethod
    def create_fighter(cls, name: str, stats: dict) -> "Player":
        """创建战士。"""
        s = {**DEFAULT_STATS, **stats}
        s["str"] += 2
        s["con"] += 2
        return cls(
            name=name,
            char_class="fighter",
            faction="friendly",
            hp=35, max_hp=35,         # 30 + 5
            max_ap=6,
            stats=s,
            gp=3,
            inventory=[],
        )

    @classmethod
    def create_mage(cls, name: str, stats: dict, domain: str = "evocation") -> "Player":
        """创建魔法使。domain: "evocation" | "abjuration" """
        s = {**DEFAULT_STATS, **stats}
        s["int"] += 2
        spells = {
            "evocation": ["魔法飞弹"],
            "abjuration": ["护盾术", "疗伤术"],
        }
        return cls(
            name=name,
            char_class="mage",
            faction="friendly",
            hp=30, max_hp=30,
            mp=100, max_mp=100,
            max_ap=6,
            stats=s,
            gp=3,
            inventory=[],
            memorized_spells=spells.get(domain, []),
        )


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

    def __post_init__(self):
        self.item_type = "weapon"

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
