"""实体补充验收测试 —— total_ac、meets_condition、carry_capacity、stat 方法。"""

import pytest
from core.entity import Creature, Player, Weapon, Armor, Item, stat_adjust


class TestStatAdjust:
    """模块级 stat_adjust 函数。"""

    def test_base_8_returns_0(self):
        assert stat_adjust(8) == 0

    def test_10_returns_1(self):
        assert stat_adjust(10) == 1

    def test_7_returns_minus_1(self):
        assert stat_adjust(7) == -1

    def test_20_returns_6(self):
        assert stat_adjust(20) == 6

    def test_0_returns_minus_4(self):
        assert stat_adjust(0) == -4


class TestTotalAC:
    """Creature.total_ac 部位 AC 计算。"""

    @pytest.fixture
    def creature(self):
        return Creature(
            name="Test", faction="neutral",
            stats={"str": 10, "dex": 14, "con": 8, "int": 8, "wis": 8, "cha": 8},
            ac_base=8,
            ac_chest=3, ac_head=0, ac_arms=1, ac_legs=1, ac_shield=2,
        )

    def test_chest_ac(self, creature):
        # ac_base(8) + dex_adjust(+3) + ac_chest(3) + ac_shield(2) = 16
        assert creature.total_ac("chest") == 16

    def test_head_ac(self, creature):
        # ac_base(8) + dex_adjust(+3) + ac_head(0) + ac_shield(2) = 13
        assert creature.total_ac("head") == 13

    def test_arms_ac(self, creature):
        assert creature.total_ac("arms") == 14

    def test_legs_ac(self, creature):
        assert creature.total_ac("legs") == 14

    def test_invalid_part_returns_base_plus_dex_plus_shield(self, creature):
        """非法部位名返回 base + dex + shield。"""
        assert creature.total_ac("invalid") == 13  # 8+3+2

    def test_no_shield(self):
        c = Creature(name="NoShield", faction="neutral",
                     stats={"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8},
                     ac_base=10, ac_shield=0)
        assert c.total_ac("chest") == 10  # 10 + 0 + 0


class TestCarryCapacity:
    def test_default_returns_20(self):
        c = Creature(name="Test", faction="neutral")
        assert c.carry_capacity() == 20.0

    def test_str_10_returns_22(self):
        c = Creature(name="Test", faction="neutral",
                     stats={"str": 10, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        assert c.carry_capacity() == 22.0  # 20 + (1)*2

    def test_str_6_returns_18(self):
        c = Creature(name="Test", faction="neutral",
                     stats={"str": 6, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        assert c.carry_capacity() == 18.0  # 20 + (-1)*2


class TestMeetsCondition:
    @pytest.fixture
    def creature(self):
        return Creature(name="Test", faction="neutral", language="common")

    def test_can_move_when_normal(self, creature):
        assert creature.meets_condition("can_move") is True

    def test_can_move_when_incapacitated(self, creature):
        creature.add_status("incapacitated")
        assert creature.meets_condition("can_move") is False

    def test_has_weapon_always_true(self, creature):
        assert creature.meets_condition("has_weapon") is True

    def test_has_healing_potion_always_false(self, creature):
        assert creature.meets_condition("has_healing_potion") is False

    def test_enemy_can_communicate_with_language(self, creature):
        assert creature.meets_condition("enemy_can_communicate") is True

    def test_enemy_can_communicate_without_language(self):
        c = Creature(name="Test", faction="neutral", language="")
        assert c.meets_condition("enemy_can_communicate") is False

    def test_unknown_condition_returns_true(self, creature):
        assert creature.meets_condition("nonexistent_condition") is True


class TestPlayerExtra:
    def test_player_mage_abjuration(self):
        p = Player.create_mage(name="Mage", stats={}, domain="abjuration")
        assert p.char_class == "mage"
        assert "护盾术" in p.memorized_spells
        assert "疗伤术" in p.memorized_spells

    def test_player_currency_defaults(self):
        p = Player(name="Rich", char_class="fighter")
        assert p.gp == 3
        assert p.sp == 0
        assert p.cp == 0

    def test_player_equipment_slots(self):
        p = Player(name="Test", char_class="fighter")
        assert len(p.equipment) == 9
        assert "head" in p.equipment
        assert "left_hand" in p.equipment
        assert "right_hand" in p.equipment
        assert p.equipment["head"] is None


class TestWeaponFields:
    def test_weapon_range_defaults(self):
        w = Weapon(name="Dagger", damage="1d4", damage_type="piercing")
        assert w.range_normal == 0
        assert w.range_max == 0

    def test_weapon_str_or_dex(self):
        w = Weapon(name="Rapier", damage="1d8", damage_type="piercing",
                   attack_stat="str_or_dex")
        assert w.attack_stat == "str_or_dex"

    def test_weapon_properties(self):
        w = Weapon(name="Longsword", damage="1d8", damage_type="slashing",
                   properties=["versatile(1d10)"])
        assert "versatile(1d10)" in w.properties


class TestArmorFields:
    def test_armor_tenacity_bonus(self):
        a = Armor(name="Plate", slot="chest", ac_bonus=8, tenacity_bonus=4,
                  str_requirement=15)
        assert a.tenacity_bonus == 4
        assert a.str_requirement == 15

    def test_armor_item_type_set(self):
        a = Armor(name="Leather", slot="chest", ac_bonus=2)
        assert a.item_type == "armor"


class TestItemCount:
    def test_item_count_stacking(self):
        i1 = Item(name="Arrow", item_type="ammo", count=20)
        assert i1.count == 20

    def test_item_default_count(self):
        i = Item(name="Key", item_type="misc")
        assert i.count == 1
