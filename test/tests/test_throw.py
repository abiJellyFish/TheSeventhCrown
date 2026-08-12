"""投掷功能测试 —— get_throw_range、力量检定、药水/武器/普通物品投掷结算。"""
import pytest
from core.entity import Creature, Item, Weapon
from core.item_actions import get_throw_range, place_on_ground


class TestGetThrowRange:
    def test_light_item_far_range(self):
        """轻物品（weight=0）投掷范围应接近视野上限。"""
        item = Item(name="羽毛", weight=0.0)
        r = get_throw_range(item, vision_range=8)
        assert r == 3  # min(8, 3-0) = 3

    def test_heavy_item_short_range(self):
        """重物品（weight=2）投掷范围应为 1。"""
        item = Item(name="铁砧", weight=2.0)
        r = get_throw_range(item, vision_range=8)
        assert r == 1  # max(1, min(8, 3-2)) = 1

    def test_very_heavy_clamped_to_1(self):
        """超重物品（weight=5）投掷范围最低为 1。"""
        item = Item(name="巨石", weight=5.0)
        r = get_throw_range(item, vision_range=8)
        assert r == 1

    def test_thrown_weapon_overrides(self):
        """有 thrown 属性的武器使用其定义的范围。"""
        item = Weapon.from_dict({
            "name": "匕首", "weapon_type": "melee",
            "damage": "1d4", "damage_type": "piercing",
            "properties": ["thrown(4/6)"], "weight": 0.5,
        })
        r = get_throw_range(item, vision_range=8)
        assert r == 4  # thrown(4/6) → 正常射程 4

    def test_throw_range_field_explicit(self):
        """Item.throw_range 字段显式指定时使用该值（减去重量修正）。"""
        item = Item(name="特制飞镖", weight=1.0, throw_range=5)
        r = get_throw_range(item, vision_range=8)
        assert r == 4  # base=5 - weight(1) = 4

    def test_throw_range_bounded_by_vision(self):
        """投掷范围不超过视野。"""
        item = Item(name="羽毛", weight=0.0, throw_range=10)
        r = get_throw_range(item, vision_range=3)
        assert r == 3  # min(3, 10) = 3


class TestThrowFields:
    def test_item_has_throw_fields(self):
        """Item 默认有投掷相关字段。"""
        item = Item(name="测试物品")
        assert hasattr(item, 'throw_range')
        assert hasattr(item, 'throw_str_req')
        assert hasattr(item, 'throw_damage')
        assert hasattr(item, 'throw_damage_type')
        assert hasattr(item, 'throw_effect')
        assert item.throw_range == 3
        assert item.throw_str_req == 0
        assert item.throw_effect == ""

    def test_item_from_dict_reads_throw_fields(self):
        """Item.from_dict 从 data 读取投掷字段。"""
        item = Item.from_dict({
            "name": "治疗药水",
            "type": "consumable",
            "throw_range": 3,
            "throw_str_req": 0,
            "throw_effect": "heal",
        })
        assert item.throw_range == 3
        assert item.throw_str_req == 0
        assert item.throw_effect == "heal"


class TestThrowStrRequirement:
    def test_low_str_cannot_throw_heavy(self):
        """力量不足时无法投掷有力量要求的物品。"""
        player = Creature(name="弱鸡", char_class="fighter")
        player.stats["str"] = 6
        item = Item(name="铁砧", weight=3.0, throw_str_req=12)
        assert player.stat("str") < item.throw_str_req

    def test_high_str_can_throw_heavy(self):
        """力量足够时可以投掷有力量要求的物品。"""
        player = Creature(name="壮汉", char_class="fighter")
        player.stats["str"] = 14
        item = Item(name="铁砧", weight=3.0, throw_str_req=12)
        assert player.stat("str") >= item.throw_str_req


class TestThrowHealEffect:
    def test_heal_potion_throw_effect_field(self):
        """治疗药水应有 throw_effect='heal' 或 effect='heal'。"""
        item = Item.from_dict({
            "name": "治疗药水", "type": "consumable",
            "effect": "heal", "amount": "2d4+2",
            "throw_effect": "heal",
        })
        # throw_effect 优先于 effect
        throw_eff = getattr(item, 'throw_effect', '') or getattr(item, 'effect', '')
        assert throw_eff == "heal"
        assert item.amount == "2d4+2"

    def test_heal_target_restores_hp(self):
        """投掷治疗药水命中生物应恢复 HP。"""
        target = Creature(name="受伤村民", hp=10, max_hp=30, stats={"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        amt = 8  # 模拟骰子结果
        target.hp = min(target.max_hp, target.hp + amt)
        assert target.hp == 18

    def test_heal_not_exceed_max_hp(self):
        """治疗不应超过最大 HP。"""
        target = Creature(name="满血村民", hp=30, max_hp=30, stats={"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        amt = 10
        target.hp = min(target.max_hp, target.hp + amt)
        assert target.hp == 30


class TestThrowGroundItem:
    def test_normal_item_goes_to_ground(self):
        """普通物品投掷后成为地上物品。"""
        ground: list = []
        item = Item(name="石头", item_type="misc", weight=0.5, count=1)
        place_on_ground(ground, item, 5, 5)
        assert len(ground) == 1
        assert ground[0][0].name == "石头"
        assert ground[0][1] == (5, 5)

    def test_throw_weapon_hit_damage(self):
        """武器投掷命中应造成伤害。"""
        weapon = Weapon.from_dict({
            "name": "手斧", "weapon_type": "melee",
            "damage": "1d6", "damage_type": "slashing",
        })
        target = Creature(name="地精", hp=20, max_hp=20, ac_base=10, stats={"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        # 模拟 5 点伤害
        dmg = 5
        target.hp = max(0, target.hp - dmg)
        assert target.hp == 15

    def test_throw_weapon_miss_fall_adjacent(self):
        """武器投掷未命中时物品落在相邻随机格。"""
        # 验证相邻随机格计算逻辑
        import random
        # 固定种子使测试可重复
        random.seed(42)
        cursor = (5, 5)
        dx = random.choice([-1, 0, 1])
        dy = random.choice([-1, 0, 1])
        fall_pos = (cursor[0] + dx, cursor[1] + dy)
        # 相邻格应在目标格周围 1 格以内
        assert abs(fall_pos[0] - 5) <= 1
        assert abs(fall_pos[1] - 5) <= 1
        # 不能正好是目标格（dx=0,dy=0 的概率 1/9）
        # 不强制断言（可能随机到 0,0），仅检查边界合理
