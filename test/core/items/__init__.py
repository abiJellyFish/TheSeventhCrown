"""物品包 —— Item 基础容器 + 能力组件（武器/护甲/光照）。"""
from core.items.item import Item, Weapon, Armor, ITEM_SPACE_DEFAULT
from core.items.components import WeaponComponent, ArmorComponent, LightComponent

__all__ = [
    "Item", "Weapon", "Armor", "ITEM_SPACE_DEFAULT",
    "WeaponComponent", "ArmorComponent", "LightComponent",
]
