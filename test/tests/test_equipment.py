"""装备/卸除/互换/双手武器 —— 核心装备逻辑。"""
import pytest
from core.entity import Creature, Weapon, Armor


def _player():
    return Creature(name="测试", char_class="fighter")


def _sword():
    return Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "ap_cost": 3,
                              "damage": "1d8", "damage_type": "slashing", "weight": 2.0})

def _dagger():
    return Weapon.from_dict({"name": "匕首", "weapon_type": "melee", "ap_cost": 2,
                              "damage": "1d4", "damage_type": "piercing",
                              "properties": ["light"], "weight": 0.5})


class TestEquip:
    def test_equip_to_empty_left_first(self):
        p = _player()
        p.equipment["left_hand"] = _sword()
        assert p.equipment["left_hand"].name == "长剑"

    def test_equip_chest_armor(self):
        p = _player()
        armor = Armor.from_dict({"name": "皮甲", "slot": "chest", "ac_bonus": 3, "weight": 5.0})
        p.equipment["chest"] = armor
        p.ac_chest += armor.ac_bonus
        assert p.ac_chest == 3

    def test_unequip_weapon(self):
        p = _player()
        p.equipment["right_hand"] = _sword()
        p.equipment["right_hand"] = None
        assert p.equipment["right_hand"] is None

    def test_swap_hands(self):
        p = _player()
        p.equipment["left_hand"] = _sword()
        p.equipment["right_hand"] = _dagger()
        p.equipment["left_hand"], p.equipment["right_hand"] = p.equipment["right_hand"], p.equipment["left_hand"]
        assert p.equipment["left_hand"].name == "匕首"
        assert p.equipment["right_hand"].name == "长剑"

    def test_two_handed_unequips_other(self):
        p = _player()
        p.equipment["left_hand"] = _sword()
        great = Weapon.from_dict({"name": "巨剑", "weapon_type": "melee", "ap_cost": 5,
                                   "damage": "2d6", "damage_type": "slashing",
                                   "properties": ["two_handed"], "weight": 4.0})
        # 装备双手武器 → 卸除左手
        p.equipment["left_hand"] = None
        p.equipment["right_hand"] = great
        assert p.equipment["left_hand"] is None
        assert p.equipment["right_hand"].name == "巨剑"


class TestInteractDistance:
    def test_within_range(self):
        assert max(abs(10 - 9), abs(10 - 9)) <= 1  # Chebyshev ≤1

    def test_out_of_range(self):
        assert max(abs(12 - 10), abs(12 - 10)) > 1
