"""物品数据类 —— Item 基础容器 + 物品空间默认值表 + 便捷构造。

Item 只保留所有物品共有的固有属性；武器/护甲/光照是组件，按数据声明挂载。
投掷是所有物品的通用能力，throw_* 字段保留在 Item 顶层。
"""
from dataclasses import dataclass, field

from core.items.components import WeaponComponent, ArmorComponent, LightComponent

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
# Item
# ═══════════════════════════════════════════════════

@dataclass
class Item:
    """物品基础数据容器（对齐 Entity 组件模式）。"""
    name: str
    item_type: str = "misc"               # 粗分类：weapon/armor/consumable/material/misc（空间/渲染/堆叠用）
    weight: float = 0.0
    price: dict = field(default_factory=dict)
    description: str = ""
    effect: str = ""                      # 通用效果：heal/restore_mp/restore_food/material/quest_item/start_fire
    amount: str = ""                      # 效果量 (如 "6d4", "15000")
    ap_cost: int = 0                      # 使用/食用 AP 消耗（武器攻击 AP 在 weapon 组件内）
    count: int = 1                        # 物品数量
    space: int = 0                        # 占据空间，0=按 item_type 查表自动赋值
    # 投掷（通用能力，所有物品可投掷）
    throw_range: int = 3
    throw_str_req: int = 0
    throw_damage: str = ""
    throw_damage_type: str = "bludgeoning"
    throw_effect: str = ""                # "heal" | "restore_mp" | "water" | "break"
    # 预留字段
    becomes: str = ""                     # 用后变成（空玻璃瓶）
    dc_check: dict | None = None          # 食用检定（生肉中毒）
    render_char: str = ""
    render_color: str = ""
    # 组件（可空，按数据声明挂载）
    weapon: WeaponComponent | None = None
    armor: ArmorComponent | None = None
    light: LightComponent | None = None

    def __post_init__(self):
        if self.space <= 0:
            self.space = ITEM_SPACE_DEFAULT.get(self.item_type, 1)

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
    def ac_bonus(self): return self.armor.ac_bonus if self.armor else 0

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
            effect=data.get("effect", ""),
            amount=data.get("amount", ""),
            ap_cost=data.get("ap_cost", 0),
            count=data.get("count", 1),
            space=data.get("space", 0),
            throw_range=data.get("throw_range", 3),
            throw_str_req=data.get("throw_str_req", 0),
            throw_damage=data.get("throw_damage", ""),
            throw_damage_type=data.get("throw_damage_type", "bludgeoning"),
            throw_effect=data.get("throw_effect", ""),
            becomes=data.get("becomes", ""),
            dc_check=data.get("dc_check"),
            render_char=data.get("render_char", ""),
            render_color=data.get("render_color", ""),
            weapon=WeaponComponent(**data["weapon"]) if "weapon" in data else None,
            armor=ArmorComponent(**data["armor"]) if "armor" in data else None,
            light=LightComponent(**data["light"]) if "light" in data else None,
        )


# ═══════════════════════════════════════════════════
# 便捷构造（临时武器/护甲，返回带组件的 Item）
# ═══════════════════════════════════════════════════

_WEAPON_COMPONENT_FIELDS = ("weapon_type", "category", "damage", "damage_type",
                            "attack_stat", "ap_cost", "range_normal", "range_max",
                            "properties", "loaded", "melee", "special_damage")
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
