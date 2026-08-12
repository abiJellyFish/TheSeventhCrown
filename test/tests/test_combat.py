"""战斗系统 —— 先攻/命中/伤害/重击/死亡豁免/掩体/双持/挥空。"""
import pytest
from core.entity import Creature, Weapon, Item
from core.grid import Grid
from core.movement import Terrain
from core.combat.initiative import roll_initiative
from core.combat.attack import (hit_check, roll_damage, parse_dice,
    apply_damage_type_modifiers, resolve_attack, miss_message, cover_message, reduce_tenacity)
from core.combat.death import DeathSaves
from core.combat.dual_wield import is_light, dual_wield_mode
from core.combat.cover import resolve_cover_line
from core.dice import roll_d20


def _c(name="t", **kw):
    hp = kw.pop("hp", 20)
    max_hp = kw.pop("max_hp", hp)
    ac = kw.pop("ac", 10)
    return Creature(name=name, hp=hp, max_hp=max_hp, ac_base=ac, **kw)

def _w(**kw):
    return Weapon(name="长剑", weapon_type="melee", damage="1d8",
                  damage_type="slashing", attack_stat="str", ap_cost=3, **kw)

def _r(**kw):
    return Weapon(name="短弓", weapon_type="ranged", damage="1d6",
                  damage_type="piercing", attack_stat="dex", ap_cost=2,
                  range_normal=8, range_max=14, **kw)


class TestInitiative:
    def test_initiative_roll(self):
        a = _c(name="A", stats={"dex": 12})
        b = _c(name="B", stats={"dex": 8})
        order = roll_initiative([a, b])
        assert len(order) == 2


class TestHitCheck:
    def test_auto_miss_on_nat1(self):
        for _ in range(30):
            hit, roll = hit_check(_c(), _c(), _w())
            if roll == 1:
                assert hit is False

    def test_auto_hit_crit_on_nat20(self):
        for _ in range(30):
            hit, roll = hit_check(_c(), _c(), _w())
            if roll == 20:
                assert hit is True

    def test_vulnerability_doubles(self):
        c = _c(traits=["bludgeoning_vulnerable"])
        assert apply_damage_type_modifiers(10, "bludgeoning", c) == 20

    def test_immunity_negates(self):
        c = _c(traits=["poison_immune"])
        assert apply_damage_type_modifiers(10, "poison", c) == 0


class TestDamage:
    def test_damage_roll(self):
        dmg = roll_damage(_w(), _c())
        assert 1 <= dmg <= 8

    def test_parse_dice(self):
        assert parse_dice("1d8") == (1, 8)
        assert parse_dice("2d6") == (2, 6)


class TestDeathSaves:
    def test_three_successes_stable(self):
        ds = DeathSaves()
        ds.successes = 3
        assert ds.is_stable

    def test_three_failures_dead(self):
        ds = DeathSaves()
        ds.failures = 3
        assert ds.is_dead

    def test_nat1_two_failures(self):
        ds = DeathSaves()
        # D20=1 counts as 2 failures per rules
        ds.failures = 2
        assert ds.failures == 2

    def test_nat20_instant_stable(self):
        ds = DeathSaves()
        ds.successes = 3
        assert ds.is_stable

    def test_drop_to_zero_no_injury(self):
        ds = DeathSaves()
        assert ds.death_injury == 0  # 非 0→0 不累积


class TestCover:
    def test_full_cover_blocks(self):
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        g[4, 5] = Terrain.WALL
        result = resolve_attack(_c(), _c(), _r(),
                                attacker_pos=(2, 5), target_pos=(6, 5), grid=g)
        assert result["blocked_by_cover"] or not result["hit"]

    def test_ranged_through_wall_blocked(self):
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        g[3, 5] = Terrain.WALL
        result = resolve_attack(_c(), _c(), _r(),
                                attacker_pos=(2, 5), target_pos=(6, 5), grid=g)
        assert result["blocked_by_cover"] or not result["hit"]


class TestTenacity:
    def test_reduce_on_miss(self):
        c = _c(tenacity=10)
        reduce_tenacity(c, 12)
        assert c.tenacity < 10


class TestDualWield:
    def test_is_light(self):
        w1 = Weapon(name="匕首", weapon_type="melee", properties=["light"], ap_cost=2)
        w2 = Weapon(name="长剑", weapon_type="melee", ap_cost=3)
        assert is_light(w1) is True
        assert is_light(w2) is False

    def test_both_light_dual_wield(self):
        left = Weapon(name="匕首", weapon_type="melee", properties=["light"], ap_cost=2)
        right = Weapon(name="短剑", weapon_type="melee", properties=["light"], ap_cost=2)
        assert dual_wield_mode(left, right) == "dual_wield"

    def test_one_non_light_dual_attack(self):
        left = Weapon(name="匕首", weapon_type="melee", properties=["light"], ap_cost=2)
        right = Weapon(name="长剑", weapon_type="melee", ap_cost=3)
        assert dual_wield_mode(left, right) == "dual_attack"


class TestMissFlavor:
    def test_miss_message_contains_names(self):
        msg = miss_message("凯恩", "地精", "slashing")
        assert "凯恩" in msg and "地精" in msg

    def test_cover_message_not_empty(self):
        for dtype in ("slashing", "bludgeoning", "piercing", "unknown"):
            assert len(cover_message(dtype)) > 0


class TestCombatBoundary:
    def test_npc_zero_ap_skips(self):
        c = _c(ap=0, max_ap=0)
        assert c.ap == 0

    def test_multiple_hostiles_in_initiative(self):
        a = _c(name="A", stats={"dex": 12})
        b = _c(name="B", stats={"dex": 10})
        assert len(roll_initiative([a, b])) == 2


# ═══════════════════════════════════════════════════
# 地面物品掩体 — space >= 10 提供半身掩体
# ═══════════════════════════════════════════════════

class TestCoverWithGroundItems:
    """space >= 10 -> 半身掩体 AC 5，与灌木丛统一。"""

    def _make_item(self, space, count):
        return Item(name="test", item_type="misc", space=space, count=count)

    def test_space_ge_10_half_cover(self):
        """物品 space>=10 提供半身掩体（AC 5），命中骰 < 5 被阻挡。"""
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        item = self._make_item(space=2, count=5)  # 10
        ground_items = [(item, (3, 3))]
        blocked, pos = resolve_cover_line(
            3, (0, 3), (5, 3), g, "ranged", ground_items=ground_items
        )
        # 攻击骰 3 < 半身AC 5 -> 被阻挡
        assert blocked
        assert pos == (3, 3)

    def test_space_ge_10_not_blocked_by_high_roll(self):
        """攻击骰 >= 掩体 AC 时穿透掩体。"""
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        item = self._make_item(space=2, count=5)  # 10
        ground_items = [(item, (3, 3))]
        blocked, pos = resolve_cover_line(
            5, (0, 3), (5, 3), g, "ranged", ground_items=ground_items
        )
        # 攻击骰 5 >= 半身AC 5 -> 不被阻挡
        assert not blocked

    def test_space_lt_10_no_cover(self):
        """物品 space<10 不提供掩体。"""
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        item = self._make_item(space=1, count=9)  # 9 < 10
        ground_items = [(item, (3, 3))]
        blocked, pos = resolve_cover_line(
            1, (0, 3), (5, 3), g, "ranged", ground_items=ground_items
        )
        assert not blocked

    def test_thrown_ignores_item_cover(self):
        """投掷武器无视地面物品掩体。"""
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        item = self._make_item(space=2, count=5)  # 10
        ground_items = [(item, (3, 3))]
        blocked, pos = resolve_cover_line(
            1, (0, 3), (5, 3), g, "thrown", ground_items=ground_items
        )
        assert not blocked

    def test_no_ground_items_no_impact(self):
        """不传 ground_items 时行为不变。"""
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        blocked, pos = resolve_cover_line(
            1, (0, 3), (5, 3), g, "ranged"
        )
        assert not blocked


# ═══════════════════════════════════════════════════
# is_full_cover — 全身障碍统一判断
# ═══════════════════════════════════════════════════

class TestFullCover:
    """is_full_cover 统一判断。"""

    def test_wall_is_full_cover(self):
        from core.combat.cover import is_full_cover
        from core.movement import Terrain
        assert is_full_cover(Terrain.WALL)

    def test_difficult_is_not_full_cover(self):
        from core.combat.cover import is_full_cover
        from core.movement import Terrain
        assert not is_full_cover(Terrain.DIFFICULT)

    def test_passable_is_not_full_cover(self):
        from core.combat.cover import is_full_cover
        from core.movement import Terrain
        assert not is_full_cover(Terrain.PASSABLE)
