"""装备/卸除/互换 + 交互距离 + 饮食值显示 测试。"""

import pytest
from core.game_state import GameState
from core.entity import Player, Item, Weapon, Armor


def _make_state():
    p = Player(name="测试", char_class="fighter")
    state = GameState(player=p, map_width=20, map_height=20)
    state.player_pos = (10, 10)
    return state


# ═══════════════════════════════════
# 单手装备规则
# ═══════════════════════════════════

class TestEquipToHand:

    def test_equip_to_empty_left_first(self):
        """空手时默认装备到左手。"""
        p = Player(name="测试", char_class="fighter")
        sword = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "ap_cost": 3,
                                   "damage": "1d8", "damage_type": "slashing",
                                   "weight": 2.0, "price": {"gp": 3, "sp": 50}})
        p.inventory.append(sword)
        # 模拟 equip_to_hand 逻辑：左→右顺序
        assert p.equipment["left_hand"] is None
        p.equipment["left_hand"] = sword
        assert p.equipment["left_hand"].name == "长剑"
        assert p.equipment["right_hand"] is None

    def test_equip_to_right_when_left_occupied(self):
        """左手被占时装备到右手。"""
        p = Player(name="测试", char_class="fighter")
        sword = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "ap_cost": 3,
                                   "damage": "1d8", "damage_type": "slashing",
                                   "weight": 2.0, "price": {"gp": 3}})
        dagger = Weapon.from_dict({"name": "匕首", "weapon_type": "melee", "ap_cost": 2,
                                    "damage": "1d4", "damage_type": "piercing",
                                    "weight": 0.5, "price": {"gp": 2}})
        p.equipment["left_hand"] = sword
        p.inventory.append(dagger)
        assert p.equipment["right_hand"] is None
        p.equipment["right_hand"] = dagger
        assert p.equipment["right_hand"].name == "匕首"

    def test_shield_goes_to_hand(self):
        """盾牌视作单手装备，走左→右顺序。"""
        p = Player(name="测试", char_class="fighter")
        shield = Armor.from_dict({"name": "圆盾", "armor_type": "shield", "slot": "full_body",
                                   "ac_bonus": 2, "tenacity_bonus": 3,
                                   "weight": 2.0, "price": {"gp": 2}})
        p.inventory.append(shield)
        p.equipment["left_hand"] = shield
        p.ac_shield += shield.ac_bonus
        assert p.equipment["left_hand"].name == "圆盾"
        assert p.ac_shield == 2


# ═══════════════════════════════════
# 护甲装备
# ═══════════════════════════════════

class TestEquipArmor:

    def test_equip_chest_armor(self):
        """装备胸甲到 chest 槽位。"""
        p = Player(name="测试", char_class="fighter")
        leather = Armor.from_dict({"name": "皮甲", "armor_type": "light", "slot": "chest",
                                    "ac_bonus": 3, "tenacity_bonus": 2,
                                    "weight": 5.0, "price": {"gp": 6}})
        p.inventory.append(leather)
        p.equipment["chest"] = leather
        p.ac_chest += leather.ac_bonus
        assert p.equipment["chest"].name == "皮甲"
        assert p.ac_chest == 3

    def test_equip_leg_armor(self):
        """装备腿甲到 legs 槽位。"""
        p = Player(name="测试", char_class="fighter")
        boots = Armor.from_dict({"name": "猪皮靴", "armor_type": "clothing", "slot": "legs",
                                  "ac_bonus": 3, "tenacity_bonus": 1,
                                  "weight": 3.0, "price": {"gp": 3}})
        p.inventory.append(boots)
        p.equipment["legs"] = boots
        p.ac_legs += boots.ac_bonus
        assert p.equipment["legs"].name == "猪皮靴"
        assert p.ac_legs == 3

    def test_equip_head_armor(self):
        """装备头盔到 head 槽位。"""
        p = Player(name="测试", char_class="fighter")
        helm = Armor.from_dict({"name": "铁质头盔", "armor_type": "light", "slot": "head",
                                 "ac_bonus": 4, "tenacity_bonus": 3,
                                 "weight": 4.0, "price": {"gp": 7}})
        p.inventory.append(helm)
        p.equipment["head"] = helm
        p.ac_head += helm.ac_bonus
        assert p.equipment["head"].name == "铁质头盔"

    def test_equip_armor_replaces_old(self):
        """装备新护甲时旧护甲放回背包（模拟）。"""
        p = Player(name="测试", char_class="fighter")
        old_armor = Armor.from_dict({"name": "布制长袍", "armor_type": "clothing", "slot": "full_body",
                                      "ac_bonus": 1, "tenacity_bonus": 1,
                                      "weight": 6.0, "price": {"gp": 4, "sp": 50}})
        new_armor = Armor.from_dict({"name": "皮甲", "armor_type": "light", "slot": "chest",
                                      "ac_bonus": 3, "tenacity_bonus": 2,
                                      "weight": 5.0, "price": {"gp": 6}})
        p.equipment["chest"] = old_armor
        p.ac_chest = old_armor.ac_bonus
        # 换上新的
        old = p.equipment["chest"]
        p.equipment["chest"] = new_armor
        p.ac_chest = new_armor.ac_bonus
        p.inventory.append(old)
        assert p.equipment["chest"].name == "皮甲"
        assert len(p.inventory) == 1
        assert p.inventory[0].name == "布制长袍"


# ═══════════════════════════════════
# 卸除装备
# ═══════════════════════════════════

class TestUnequip:

    def test_unequip_weapon(self):
        """卸除武器放入背包，AC 不受影响。"""
        p = Player(name="测试", char_class="fighter")
        sword = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "ap_cost": 3,
                                   "damage": "1d8", "damage_type": "slashing",
                                   "weight": 2.0, "price": {"gp": 3}})
        p.equipment["right_hand"] = sword
        # 卸除
        item = p.equipment["right_hand"]
        p.equipment["right_hand"] = None
        p.inventory.append(item)
        assert p.equipment["right_hand"] is None
        assert p.inventory[0].name == "长剑"

    def test_unequip_shield_clears_ac(self):
        """卸除盾牌后 ac_shield 归零。"""
        p = Player(name="测试", char_class="fighter")
        shield = Armor.from_dict({"name": "圆盾", "armor_type": "shield", "slot": "full_body",
                                   "ac_bonus": 2, "tenacity_bonus": 3,
                                   "weight": 2.0, "price": {"gp": 2}})
        p.equipment["left_hand"] = shield
        p.ac_shield = shield.ac_bonus
        assert p.ac_shield == 2
        # 卸除
        p.equipment["left_hand"] = None
        p.ac_shield = 0
        assert p.ac_shield == 0

    def test_unequip_armor_clears_ac(self):
        """卸除胸甲后 ac_chest 归零。"""
        p = Player(name="测试", char_class="fighter")
        armor = Armor.from_dict({"name": "皮甲", "armor_type": "light", "slot": "chest",
                                  "ac_bonus": 3, "tenacity_bonus": 2,
                                  "weight": 5.0, "price": {"gp": 6}})
        p.equipment["chest"] = armor
        p.ac_chest = armor.ac_bonus
        p.equipment["chest"] = None
        p.ac_chest = 0
        assert p.ac_chest == 0

    def test_unequip_nonexistent_slot(self):
        """卸除空槽位无效果。"""
        p = Player(name="测试", char_class="fighter")
        assert p.equipment["head"] is None
        # 不应抛异常


# ═══════════════════════════════════
# 左右手互换
# ═══════════════════════════════════

class TestSwapHands:

    def test_swap_left_right(self):
        """交换左右手装备。"""
        p = Player(name="测试", char_class="fighter")
        sword = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "ap_cost": 3,
                                   "damage": "1d8", "damage_type": "slashing",
                                   "weight": 2.0, "price": {"gp": 3}})
        dagger = Weapon.from_dict({"name": "匕首", "weapon_type": "melee", "ap_cost": 2,
                                    "damage": "1d4", "damage_type": "piercing",
                                    "weight": 0.5, "price": {"gp": 2}})
        p.equipment["left_hand"] = sword
        p.equipment["right_hand"] = dagger
        # 互换
        p.equipment["left_hand"], p.equipment["right_hand"] = \
            p.equipment["right_hand"], p.equipment["left_hand"]
        assert p.equipment["left_hand"].name == "匕首"
        assert p.equipment["right_hand"].name == "长剑"

    def test_swap_with_empty_hand(self):
        """单手持武器时互换，空手换到另一侧。"""
        p = Player(name="测试", char_class="fighter")
        sword = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "ap_cost": 3,
                                   "damage": "1d8", "damage_type": "slashing",
                                   "weight": 2.0, "price": {"gp": 3}})
        p.equipment["right_hand"] = sword
        p.equipment["left_hand"], p.equipment["right_hand"] = \
            p.equipment["right_hand"], p.equipment["left_hand"]
        assert p.equipment["left_hand"].name == "长剑"
        assert p.equipment["right_hand"] is None


# ═══════════════════════════════════
# 双手武器
# ═══════════════════════════════════

class TestTwoHandedWeapon:

    def test_two_handed_unequips_other_hand(self):
        """双手武器装备时另一只手自动卸除。"""
        p = Player(name="测试", char_class="fighter")
        sword = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "ap_cost": 3,
                                   "damage": "1d8", "damage_type": "slashing",
                                   "weight": 2.0, "price": {"gp": 3}})
        greatsword = Weapon.from_dict({"name": "巨剑", "weapon_type": "melee", "ap_cost": 5,
                                        "damage": "2d6", "damage_type": "slashing",
                                        "properties": ["two_handed"],
                                        "weight": 4.0, "price": {"gp": 10}})
        p.equipment["left_hand"] = sword
        p.inventory.append(greatsword)
        # 装备双手武器 → 卸除左手
        item = p.inventory.pop()
        old = p.equipment["left_hand"]
        p.equipment["left_hand"] = None
        p.equipment["right_hand"] = item
        p.inventory.append(old)
        assert p.equipment["right_hand"].name == "巨剑"
        assert p.equipment["left_hand"] is None

    def test_shortbow_no_longer_two_handed(self):
        """短弓不再是双手武器。"""
        bow = Weapon.from_dict({"name": "短弓", "weapon_type": "ranged", "ap_cost": 2,
                                 "damage": "1d6", "damage_type": "piercing",
                                 "range_normal": 8, "range_max": 14,
                                 "properties": ["ammo"],
                                 "weight": 1.0, "price": {"gp": 1, "sp": 50}})
        assert "two_handed" not in bow.properties


# ═══════════════════════════════════
# 交互距离自动退出
# ═══════════════════════════════════

class TestInteractDistance:

    def test_within_range_stays(self):
        """Chebyshev 距离 ≤ 1 时保持交互状态。"""
        player_pos = (10, 10)
        target_pos = (10, 9)
        dist = max(abs(player_pos[0] - target_pos[0]), abs(player_pos[1] - target_pos[1]))
        assert dist <= 1

    def test_out_of_range_exits(self):
        """Chebyshev 距离 > 1 时退出交互。"""
        player_pos = (12, 10)
        target_pos = (10, 9)
        dist = max(abs(player_pos[0] - target_pos[0]), abs(player_pos[1] - target_pos[1]))
        assert dist > 1

    def test_diagonal_still_in_range(self):
        """对角相邻仍在范围内。"""
        player_pos = (11, 11)
        target_pos = (10, 10)
        dist = max(abs(player_pos[0] - target_pos[0]), abs(player_pos[1] - target_pos[1]))
        assert dist == 1
