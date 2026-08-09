"""实体数据类测试 —— Creature, Player, Item, Weapon, Armor。"""

import pytest
from core.entity import Armor, Creature, Item, Player, Weapon


class TestCreature:
    def test_creature_from_dict(self):
        """用地精打手数据构造 Creature"""
        data = {
            "name": "地精打手",
            "body_type": "humanoid",
            "faction": "hostile",
            "hp": 20, "max_hp": 20,
            "mp": 0, "max_mp": 0,
            "tenacity": 6, "max_tenacity": 6,
            "ap": 6, "max_ap": 6,
            "speed": 1,
            "ac_base": 10,
            "stats": {"str": 8, "dex": 12, "con": 8, "int": 6, "wis": 8, "cha": 6},
            "vision_range": 8,
            "food_value": 15000,
            "food_locked": False,
            "darkvision_range": 0,
            "language": "",
            "actions": [
                {"name": "短棒", "type": "melee", "weapon": "短棒", "two_hand": True, "reach": 1},
                {"name": "跃起", "type": "special", "description": "跳跃+攻击"},
            ],
            "traits": [],
            "loot": {"dc_items": {"短棒": 6, "地精角": 10}, "always": ["20 SP"]},
        }
        c = Creature.from_dict(data)
        assert c.name == "地精打手"
        assert c.faction == "hostile"
        assert c.hp == 20
        assert c.max_hp == 20
        assert c.speed == 1
        assert c.stats["dex"] == 12
        assert c.ac_base == 10
        assert c.darkvision_range == 0
        assert c.food_locked is False

    def test_creature_hp_clamped(self):
        """HP 不应超过 max_hp"""
        c = Creature(name="test", faction="neutral", hp=30, max_hp=20)
        assert c.hp == 20

    def test_creature_tenacity_min_zero(self):
        """韧性最低为 0"""
        c = Creature(name="test", faction="neutral", tenacity=-5, max_tenacity=10)
        assert c.tenacity == 0

    def test_stat_adjustment(self):
        """属性调整值 = (属性值 - 8) // 2"""
        c = Creature(
            name="test", faction="neutral",
            stats={"str": 10, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8},
        )
        assert c.stat_adjust("str") == 1   # (10-8)//2 = 1
        assert c.stat_adjust("dex") == 0   # (8-8)//2 = 0

    def test_initiative_bonus(self):
        """先攻加值 = 敏捷调整值"""
        c = Creature(
            name="test", faction="neutral",
            stats={"str": 8, "dex": 14, "con": 8, "int": 8, "wis": 8, "cha": 8},
        )
        assert c.initiative_bonus() == 3  # (14-8)//2 = 3

    def test_reserved_fields(self):
        """预留字段存在且默认值正确"""
        c = Creature(name="test", faction="neutral")
        assert c.ally_slot is None
        assert c.food_locked is False
        assert c.darkvision_range == 0


class TestPlayer:
    def test_player_creation_fighter(self):
        """人类战士初始属性"""
        p = Player.create_fighter(
            name="凯恩",
            stats={"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8},
        )
        assert p.name == "凯恩"
        assert p.char_class == "fighter"
        assert p.faction == "friendly"
        assert p.max_hp == 35  # 30 + 5(fighter)
        assert p.max_ap == 6
        assert p.max_mp == 0
        assert p.speed == 1
        assert p.stat_adjust("str") == 1   # 8+2=10 → (10-8)//2=1

    def test_player_creation_mage(self):
        """魔法使初始属性"""
        p = Player.create_mage(
            name="test_mage",
            stats={"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8},
            domain="evocation",
        )
        assert p.max_mp == 100
        assert p.char_class == "mage"
        assert p.stat_adjust("int") == 1   # 8+2=10 → (10-8)//2=1
        assert "魔法飞弹" in p.memorized_spells

    def test_player_party_reserved(self):
        """队伍槽位预留"""
        p = Player(name="test", char_class="fighter")
        assert p.party == []


class TestItem:
    def test_weapon_from_dict(self):
        data = {
            "name": "长剑",
            "type": "weapon",
            "weapon_type": "melee",
            "category": "martial",
            "damage": "1d8",
            "damage_type": "slashing",
            "attack_stat": "str",
            "ap_cost": 3,
            "properties": ["versatile(1d10)"],
            "weight": 2.0,
            "price": {"gp": 3, "sp": 50},
        }
        w = Weapon.from_dict(data)
        assert w.name == "长剑"
        assert w.damage == "1d8"
        assert w.ap_cost == 3
        assert w.weight == 2.0

    def test_armor_from_dict(self):
        data = {
            "name": "皮甲",
            "type": "armor",
            "armor_type": "light",
            "slot": "chest",
            "ac_bonus": 3,
            "tenacity_bonus": 2,
            "str_requirement": 8,
            "weight": 5.0,
            "price": {"gp": 6},
        }
        a = Armor.from_dict(data)
        assert a.name == "皮甲"
        assert a.slot == "chest"
        assert a.ac_bonus == 3

    def test_consumable_from_dict(self):
        data = {
            "name": "治疗药水",
            "type": "consumable",
            "effect": "heal",
            "amount": "6d4",
            "ap_cost": 1,
            "weight": 0.5,
            "price": {"gp": 2},
            "description": "恢复 6d4 生命值",
        }
        item = Item.from_dict(data)
        assert item.name == "治疗药水"
        assert item.item_type == "consumable"
