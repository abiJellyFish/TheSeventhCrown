"""实体数据类 —— Creature, Player, Item, Weapon, Armor, 载重系统。"""
import pytest
from core.entity import Creature, Player, Weapon, Armor, Item, stat_adjust, CARRY_STATUS


# ── Creature ──

class TestCreature:
    def test_creature_from_dict(self):
        data = {"name": "地精", "hp": 20, "max_hp": 20, "faction": "混乱",
                "stats": {"str": 8, "dex": 12}, "char": "g"}
        c = Creature.from_dict(data)
        assert c.name == "地精"
        assert c.hp == 20
        assert c.stat("dex") == 12

    def test_stat_adjustment(self):
        assert stat_adjust(8) == 0
        assert stat_adjust(10) == 1
        assert stat_adjust(6) == -1

    def test_total_ac(self):
        c = Creature(name="t", ac_base=8, stats={"dex": 12})
        c.ac_chest = 3
        # base(8) + dex(12→+1) + chest(3) + shield(0) = 12
        assert c.total_ac("chest") >= 12


# ── Player ──

class TestPlayer:
    def test_player_creation_fighter(self):
        p = Player.create_fighter("凯恩", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        assert p.char_class == "fighter"
        assert p.max_hp == 35
        assert p.stat("str") == 10  # +2

    def test_player_mage_abjuration(self):
        p = Player.create_mage("法师", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}, "abjuration")
        assert p.char_class == "mage"
        assert "护盾术" in p.memorized_spells

    def test_carry_weight(self):
        p = Player.create_fighter("测试", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        p.inventory = [Item(name="口粮", weight=1.0, count=3)]
        p.equipment["right_hand"] = Weapon(name="长剑", weight=2.0, ap_cost=3)
        assert p.total_carry_weight() == 5.0

    def test_carry_light(self):
        p = Player.create_fighter("测试", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        p.inventory = [Item(name="light", weight=10.0)]  # 10/20 = 50%
        assert "轻" in p.carry_status()["label"]

    def test_carry_encumbered(self):
        p = Player.create_fighter("t", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        p.inventory = [Item(name="heavy", weight=17.0)]  # 17/20 = 85%
        status = p.carry_status()
        # 超过80% → 至少是 encumbered
        assert status["threshold"] >= 0.8

    def test_carry_overloaded(self):
        p = Player.create_fighter("测试", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        p.inventory = [Item(name="over", weight=25.0)]  # 25/20 = 125%
        assert "超重" in p.carry_status()["label"]


# ── Item / Weapon / Armor ──

class TestItems:
    def test_weapon_from_dict(self):
        w = Weapon.from_dict({"name": "长剑", "damage": "1d8", "damage_type": "slashing",
                               "ap_cost": 3, "weight": 2.0})
        assert w.name == "长剑"
        assert w.damage == "1d8"

    def test_weapon_melee_field(self):
        w = Weapon.from_dict({"name": "短弓", "weapon_type": "ranged",
                               "damage": "1d6", "melee": {"damage": "1d4", "damage_type": "bludgeoning",
                               "attack_stat": "str", "ap_cost": 2}})
        assert w.melee["damage"] == "1d4"

    def test_carry_status_table(self):
        assert len(CARRY_STATUS) == 3
        for key in ("light", "encumbered", "overloaded"):
            assert "label" in CARRY_STATUS[key]

    def test_can_move_normal(self):
        c = Creature(name="测试", hp=10, stats={"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        assert not c.has_status("不可移动")
