"""物品工厂：统一从原始数据创建物品实例。"""

from domain.items.item import (
    Armor,
    Item,
    _ARMOR_COMPONENT_FIELDS,
    _WEAPON_COMPONENT_FIELDS,
    normalize_item_type,
)
from domain.items.components import ArmorComponent, LightComponent, SpellbookComponent, WeaponComponent
from domain.ports import RepositoryPort, get_repository


class ItemFactory:
    """物品创建入口，业务模块不需要了解组件装配细节。"""

    @staticmethod
    def create(data: dict) -> Item:
        if not isinstance(data, dict):
            raise TypeError("物品数据必须是字典")
        item_type = normalize_item_type(data.get("item_type", data.get("type", {"misc": True})))
        weapon_data = data.get("weapon")
        armor_data = data.get("armor")
        if weapon_data is None and item_type.get("weapon"):
            weapon_data = {
                key: data[key] for key in _WEAPON_COMPONENT_FIELDS if key in data
            }
        if armor_data is None and item_type.get("armor"):
            armor_data = {
                key: data[key] for key in _ARMOR_COMPONENT_FIELDS if key in data
            }
        return Item(
            name=data["name"],
            item_type=item_type,
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
            obstacle_type=data.get("obstacle_type", ""),
            block_value=data.get("block_value", 0),
            stack_limit=data.get("stack_limit", 99),
            throw_range=data.get("throw_range", 3),
            throw_str_req=data.get("throw_str_req", 0),
            throw_damage=data.get("throw_damage", ""),
            throw_damage_type=data.get("throw_damage_type", "bludgeoning"),
            throw_effect=data.get("throw_effect", ""),
            becomes=data.get("becomes", ""),
            dc_check=data.get("dc_check"),
            read_text=data.get("read_text", ""),
            render_char=data.get("render_char", ""),
            render_color=data.get("render_color", ""),
            can_pickup=data.get("can_pickup", True),
            accessory=data.get("accessory", bool(item_type.get("accessory"))),
            equip_effect=data.get("equip_effect", {}),
            weapon=WeaponComponent(**weapon_data) if weapon_data is not None else None,
            armor=ArmorComponent(**armor_data) if armor_data is not None else None,
            light=LightComponent(**data["light"]) if "light" in data else None,
            spellbook=SpellbookComponent(**data["spellbook"]) if "spellbook" in data else None,
        )

    from_dict = create

    @staticmethod
    def create_weapon(data: dict) -> Item:
        item_type = data.get("item_type", "weapon")
        return ItemFactory.create({**data, "item_type": item_type})

    @staticmethod
    def create_armor(data: dict) -> Item:
        return ItemFactory.create({**data, "item_type": "armor"})

    @staticmethod
    def create_from_name(name: str, repository: RepositoryPort) -> Item | None:
        data = repository.load_item_data(name)
        return ItemFactory.create(data) if data is not None else None

