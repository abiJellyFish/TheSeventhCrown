"""物品包 —— Item 基础容器 + 能力组件（武器/护甲/光照）。"""
from domain.items.item import Item, Weapon, Armor
from domain.items.components import WeaponComponent, ArmorComponent, LightComponent
from domain.items.factory import ItemFactory

__all__ = [
    "Item", "Weapon", "Armor",
    "WeaponComponent", "ArmorComponent", "LightComponent",
    "ItemFactory",
]
