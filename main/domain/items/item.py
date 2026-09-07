"""物品数据类 —— Item 基础容器 + 便捷构造。

Item 只保留所有物品共有的固有属性；武器/护甲/光照是组件，按数据声明挂载。
投掷是所有物品的通用能力，throw_* 字段保留在 Item 顶层。
"""
from dataclasses import dataclass, field

from domain.items.components import WeaponComponent, ArmorComponent, LightComponent, SpellbookComponent
from domain.obstacle import ObstacleType, normalize_obstacle_type, obstacle_defaults

ITEM_TYPE_LABELS: dict[str, str] = {
    "weapon": "武器",
    "armor": "护甲",
    "accessory": "饰品",
    "consumable": "消耗品",
    "fragile": "易碎",
    "material": "材料",
    "tool": "工具",
    "seed": "种子",
    "spell_scroll": "卷轴",
    "spellbook": "法术书",
    "container": "容器",
    "structure": "结构",
    "obstacle": "障碍",
    "misc": "杂项",
    "corpse": "尸体",
    "feature": "地形",
}


def normalize_item_type(value) -> dict[str, bool]:
    """物品类型只存哈希表。构造时字符串立即转成表，存储形态不再切换。"""
    if isinstance(value, str):
        if not value:
            raise ValueError("item_type 不能为空")
        return {value: True}
    if isinstance(value, dict):
        types = {key: True for key, flag in value.items() if flag}
        if not types:
            raise ValueError("item_type 不能为空")
        if not all(isinstance(key, str) for key in types):
            raise TypeError("item_type 键必须是字符串")
        return types
    raise TypeError(f"item_type 必须是哈希表: {type(value).__name__}")


def item_type_key(item) -> tuple[str, ...]:
    types = getattr(item, "item_type", {}) or {}
    return tuple(sorted(name for name, flag in types.items() if flag))


def format_item_type_labels(item) -> str:
    types = getattr(item, "item_type", {}) or {}
    labels = [
        ITEM_TYPE_LABELS[name]
        for name in ITEM_TYPE_LABELS
        if types.get(name)
    ]
    labels.extend(
        name for name, flag in types.items()
        if flag and name not in ITEM_TYPE_LABELS
    )
    return "、".join(labels)


# ═══════════════════════════════════════════════════
@dataclass
class Item:
    """物品基础数据容器（对齐 Entity 组件模式）。"""
    name: str
    item_type: dict[str, bool] = field(default_factory=lambda: {"misc": True})
    weight: float = 0.0
    price: dict = field(default_factory=dict)
    description: str = ""
    effect: str = ""                      # 通用效果：heal/restore_mp/restore_food/material/quest_item/start_fire
    amount: str = ""                      # 效果量 (如 "6d4", "15000")
    ap_cost: int = 0                      # 使用/食用 AP 消耗（武器攻击 AP 在 weapon 组件内）
    count: int = 1                        # 物品数量
    spell: str = ""                       # 法术卷轴引用的法术名
    level: int = 0                        # 法术卷轴环阶
    cast_time_pendulum: int = 0           # 法术卷轴施法钟摆数
    range: int = 0                        # 法术卷轴施法距离
    needs_hit: bool = False               # 法术卷轴是否需要命中
    effect_data: dict = field(default_factory=dict)  # 法术卷轴效果定义
    traits: list[str] = field(default_factory=list)
    quality: str = "普通"
    unfinished: bool = False
    craft_progress: int = 0
    recipe_id: str = ""
    craft_tool: str = ""
    craft_required: int = 0
    quality_traits: dict = field(default_factory=dict)
    durability: int = 20
    max_durability: int = 20
    flammable: bool = False
    fuel: int = 0
    burning: int = 0
    wet: int = 0
    obstacle_type: ObstacleType = ObstacleType.NONE
    block_value: int = 0
    stack_limit: int = 0
    # 投掷（通用能力，所有物品可投掷）
    throw_range: int = 3
    throw_str_req: int = 0
    throw_damage: str = ""
    throw_damage_type: str = "bludgeoning"
    throw_effect: str = ""                # "heal" | "restore_mp" | "water" | "break"
    # 预留字段
    becomes: str = ""                     # 用后变成（空玻璃瓶）
    dc_check: dict | None = None          # 食用检定（生肉中毒）
    owner: str = ""                       # 归属人名称（P1 3.3 偷窃）
    read_text: str = ""                   # 阅读文本（物品栏"阅读"操作显示，P1 3.4 长老的提示）
    render_char: str = ""
    render_color: str = ""
    can_pickup: bool = True
    accessory: bool = False
    equip_effect: dict = field(default_factory=dict)
    # 组件（可空，按数据声明挂载）
    weapon: WeaponComponent | None = None
    armor: ArmorComponent | None = None
    light: LightComponent | None = None
    spellbook: SpellbookComponent | None = None

    def __post_init__(self):
        from domain.craft.quality import QUALITIES

        self.item_type = normalize_item_type(self.item_type)
        self.obstacle_type = normalize_obstacle_type(self.obstacle_type)
        if self.max_durability <= 0:
            self.max_durability = obstacle_defaults(self.obstacle_type)[0] or 20
        if self.durability <= 0:
            self.durability = self.max_durability
        if self.stack_limit <= 0:
            self.stack_limit = 1 if self.is_obstacle else 99
        if self.obstacle_type is ObstacleType.FULL:
            self.can_pickup = False
        if self.unfinished:
            self.quality = ""
            self.price = {}
        elif self.quality not in QUALITIES:
            raise ValueError(f"非法品质: {self.quality}")

    def has_type(self, name: str) -> bool:
        return bool(self.item_type.get(name))

    @property
    def is_obstacle(self) -> bool:
        return self.obstacle_type is not ObstacleType.NONE

    # ── 武器字段代理（对齐 Entity property 代理模式，业务层无感知）──

    @property
    def weapon_type(self): return self.weapon.weapon_type if self.weapon else None

    @property
    def category(self): return self.weapon.category if self.weapon else None

    @property
    def damage(self): return self.weapon.damage if self.weapon else None

    @property
    def damage_type(self): return self.weapon.damage_type if self.weapon else None

    @property
    def attack_stat(self): return self.weapon.attack_stat if self.weapon else None

    @property
    def range_normal(self): return self.weapon.range_normal if self.weapon else 0

    @property
    def range_max(self): return self.weapon.range_max if self.weapon else 0

    @property
    def melee_range(self):
        return self.weapon.melee_range if self.weapon else None

    @property
    def properties(self): return self.weapon.properties if self.weapon else []

    @property
    def loaded(self): return self.weapon.loaded if self.weapon else True

    @loaded.setter
    def loaded(self, value):
        if self.weapon:
            self.weapon.loaded = value

    @property
    def melee(self): return self.weapon.melee if self.weapon else None

    @property
    def special_damage(self): return self.weapon.special_damage if self.weapon else None

    # ── 护甲字段代理 ──

    @property
    def armor_type(self): return self.armor.armor_type if self.armor else None

    @property
    def slot(self): return self.armor.slot if self.armor else None

    @property
    def ac_bonus(self):
        from domain.craft.quality import scale_value

        base = self.armor.ac_bonus if self.armor else 0
        if not self.quality:
            return base
        return scale_value(base, self.quality)

    @property
    def tenacity_bonus(self): return self.armor.tenacity_bonus if self.armor else 0

    @property
    def str_requirement(self): return self.armor.str_requirement if self.armor else 8

    @classmethod
    def from_dict(cls, data: dict) -> "Item":
        return cls(
            name=data["name"],
            item_type=data.get("item_type", data.get("type", "misc")),
            weight=data.get("weight", 0.0),
            price=data.get("price", {}),
            description=data.get("description", ""),
            effect=data.get("effect", "") if isinstance(data.get("effect", ""), str) else "",
            amount=data.get("amount", ""),
            ap_cost=data.get("ap_cost", 0),
            count=data.get("count", 1),
            spell=data.get("spell", ""),
            level=data.get("level", 0),
            cast_time_pendulum=data.get("cast_time_pendulum", 0),
            range=data.get("range", 0),
            needs_hit=data.get("needs_hit", False),
            effect_data=data.get("effect", {}) if isinstance(data.get("effect"), dict) else {},
            traits=list(data.get("traits", [])),
            quality=data.get("quality", "普通"),
            unfinished=data.get("unfinished", False),
            craft_progress=data.get("craft_progress", 0),
            recipe_id=data.get("recipe_id", ""),
            craft_tool=data.get("craft_tool", ""),
            craft_required=data.get("craft_required", 0),
            quality_traits=dict(data.get("quality_traits", {})),
            durability=data.get("durability", 0),
            max_durability=data.get("max_durability", data.get("durability", 0)),
            flammable=data.get("flammable", False),
            fuel=data.get("fuel", 0),
            burning=data.get("burning", 0),
            wet=data.get("wet", 0),
            obstacle_type=data.get("obstacle_type", ObstacleType.NONE.value),
            block_value=data.get("block_value", 0),
            stack_limit=data.get("stack_limit", 0),
            throw_range=data.get("throw_range", 3),
            throw_str_req=data.get("throw_str_req", 0),
            throw_damage=data.get("throw_damage", ""),
            throw_damage_type=data.get("throw_damage_type", "bludgeoning"),
            throw_effect=data.get("throw_effect", ""),
            becomes=data.get("becomes", ""),
            dc_check=data.get("dc_check"),
            owner=data.get("owner", ""),
            read_text=data.get("read_text", ""),
            render_char=data.get("render_char", ""),
            render_color=data.get("render_color", ""),
            can_pickup=data.get("can_pickup", True),
            accessory=data.get(
                "accessory",
                bool(normalize_item_type(
                    data.get("item_type", data.get("type", {"misc": True}))
                ).get("accessory")),
            ),
            equip_effect=data.get("equip_effect", {}),
            weapon=WeaponComponent(**data["weapon"]) if "weapon" in data else None,
            armor=ArmorComponent(**data["armor"]) if "armor" in data else None,
            light=LightComponent(**data["light"]) if "light" in data else None,
            spellbook=SpellbookComponent(**data["spellbook"]) if "spellbook" in data else None,
        )


# ═══════════════════════════════════════════════════
# 便捷构造（临时武器/护甲，返回带组件的 Item）
# ═══════════════════════════════════════════════════

_WEAPON_COMPONENT_FIELDS = ("weapon_type", "category", "damage", "damage_type",
                            "attack_stat", "ap_cost", "range_normal", "range_max",
                            "melee_range", "properties", "loaded", "melee", "special_damage")
_ARMOR_COMPONENT_FIELDS = ("armor_type", "slot", "ac_bonus", "tenacity_bonus",
                           "str_requirement")


def Weapon(name: str, **kw) -> Item:
    """便捷构造：创建带 weapon 组件的 Item（ap_cost/melee 等进组件，light_source 进 light 组件）。"""
    wc = {}
    light = None
    for k in list(kw):
        if k in _WEAPON_COMPONENT_FIELDS:
            wc[k] = kw.pop(k)
        elif k == "light_source":
            light = kw.pop(k)
    item = Item(name=name, item_type="weapon", **kw)
    item.weapon = WeaponComponent(**wc)
    if light:
        item.light = LightComponent(**light)
    return item


def Armor(name: str, **kw) -> Item:
    """便捷构造：创建带 armor 组件的 Item。"""
    ac = {}
    for k in list(kw):
        if k in _ARMOR_COMPONENT_FIELDS:
            ac[k] = kw.pop(k)
    item = Item(name=name, item_type="armor", **kw)
    item.armor = ArmorComponent(**ac)
    return item


def _weapon_from_dict(data: dict) -> Item:
    """兼容 from_dict：接受平铺武器数据，转嵌套组件。"""
    wc = {}
    light = None
    rest = {}
    for k, v in data.items():
        if k in _WEAPON_COMPONENT_FIELDS:
            wc[k] = v
        elif k == "light_source":
            light = v
        else:
            rest[k] = v
    item = Item.from_dict({**rest, "item_type": "weapon", "weapon": wc})
    if light:
        item.light = LightComponent(**light)
    return item


def _armor_from_dict(data: dict) -> Item:
    """兼容 from_dict：接受平铺护甲数据，转嵌套组件。"""
    ac = {}
    rest = {}
    for k, v in data.items():
        if k in _ARMOR_COMPONENT_FIELDS:
            ac[k] = v
        else:
            rest[k] = v
    return Item.from_dict({**rest, "item_type": "armor", "armor": ac})


Weapon.from_dict = staticmethod(_weapon_from_dict)
Armor.from_dict = staticmethod(_armor_from_dict)
