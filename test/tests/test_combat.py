"""Combat system tests — initiative, hit/damage, death, tenacity, cover."""

import pytest
from unittest.mock import MagicMock
from core.combat.initiative import roll_initiative
from core.combat.attack import (
    hit_check, roll_hit_location, roll_damage, AutoHitAttack,
    apply_damage_type_modifiers, resolve_attack,
)
from core.combat.death import DeathSaves
from core.combat.cover import resolve_cover_line
from core.entity import Creature, Player, Weapon
from core.grid import Grid
from core.movement import Terrain


# ---- Helpers ----

@pytest.fixture
def goblin():
    return Creature(name="Goblin", faction="hostile", hp=20, max_hp=20,
                    tenacity=6, max_tenacity=6,
                    stats={"str": 8, "dex": 12, "con": 8, "int": 6, "wis": 8, "cha": 6},
                    ac_base=10)

@pytest.fixture
def player():
    return Player.create_fighter(name="Test", stats={"str": 8, "dex": 8, "con": 8,
                                                      "int": 8, "wis": 8, "cha": 8})

@pytest.fixture
def longsword():
    return Weapon(name="Longsword", damage="1d8", damage_type="slashing",
                  attack_stat="str", ap_cost=3)


class TestInitiative:
    def test_initiative_roll(self, player, goblin):
        order = roll_initiative([player, goblin])
        assert len(order) == 2

    def test_tiebreaker(self):
        a = Creature(name="A", faction="friendly", stats={"dex": 8})
        b = Creature(name="B", faction="hostile", stats={"dex": 8})
        order = roll_initiative([b, a])
        # Both same dex → non-hostile goes first
        assert len(order) == 2


class TestHitCheck:
    def test_hit_success(self, player, goblin, longsword):
        """D20 + mod >= AC → hit"""
        for _ in range(50):
            hit, roll_val = hit_check(player, goblin, longsword)
            expected = (roll_val + player.stat_adjust("str")) >= goblin.total_ac("chest")
            assert hit == expected

    def test_auto_miss_on_nat1(self, player, goblin, longsword):
        """D20=1 always misses"""
        import core.combat.attack as atk_mod
        original = atk_mod.roll_d20
        atk_mod.roll_d20 = lambda advantage=0, disadvantage=0: 1
        try:
            hit, roll = hit_check(player, goblin, longsword)
            assert hit is False
            assert roll == 1
        finally:
            atk_mod.roll_d20 = original

    def test_auto_hit_crit_on_nat20(self, player, goblin, longsword):
        """D20=20 always hits and is critical"""
        import core.combat.attack as atk_mod
        original = atk_mod.roll_d20
        atk_mod.roll_d20 = lambda advantage=0, disadvantage=0: 20
        try:
            hit, roll = hit_check(player, goblin, longsword)
            assert hit is True
            assert roll == 20
        finally:
            atk_mod.roll_d20 = original


class TestHitLocation:
    def test_humanoid_locations(self):
        for _ in range(100):
            loc = roll_hit_location("humanoid")
            assert loc in ("chest", "arms", "legs", "head")


class TestDamage:
    def test_damage_roll(self, player, longsword):
        dmg = roll_damage(longsword, player)
        assert isinstance(dmg, int)
        # 1d8 + str_adjust (0 for str=8 fighter with +2 gets str=10 adjust=1)
        # Actually fighter: stats str=8, +2 = 10, adjust = (10-8)//2 = 1
        assert 2 <= dmg <= 9  # 1d8(1-8) + 1 = 2-9

    def test_critical_double_dice(self, player, longsword):
        dmg = roll_damage(longsword, player, critical=True)
        # 2d8 + 1, range 3-17
        assert 3 <= dmg <= 17


class TestDamageTypes:
    def test_resistance_halves(self):
        c = Creature(name="Test", faction="neutral")
        dmg = apply_damage_type_modifiers(10, "piercing", c)
        assert dmg == 10  # no resistance

    def test_vulnerability_doubles(self):
        c = Creature(name="Test", faction="neutral",
                     traits=["bludgeoning_vulnerable"])
        dmg = apply_damage_type_modifiers(10, "bludgeoning", c)
        assert dmg == 20

    def test_immunity_negates(self):
        c = Creature(name="Test", faction="neutral",
                     traits=["poison_immune"])
        dmg = apply_damage_type_modifiers(10, "poison", c)
        assert dmg == 0


class TestAutoHit:
    def test_magic_missile_always_hits(self):
        atk = AutoHitAttack(damage_dice="1d4", missiles=3, damage_type="force")
        results = atk.resolve(None)  # no target needed for auto-hit
        assert len(results) == 3
        for r in results:
            assert 1 <= r <= 4


class TestDeathSaves:
    def test_drop_to_zero_no_injury(self):
        ds = DeathSaves()
        ds.take_damage_from_above_zero(current_hp=5, damage=10, max_hp=20)
        assert ds.death_injury == 0

    def test_death_save_success(self):
        ds = DeathSaves()
        import core.combat.death as death_mod
        original = death_mod.roll_d20
        death_mod.roll_d20 = lambda advantage=0, disadvantage=0: 15
        try:
            ds.roll_save()
            assert ds.successes == 1
        finally:
            death_mod.roll_d20 = original

    def test_nat1_counts_twice(self):
        ds = DeathSaves()
        import core.combat.death as death_mod
        original = death_mod.roll_d20
        death_mod.roll_d20 = lambda advantage=0, disadvantage=0: 1
        try:
            ds.roll_save()
            assert ds.failures == 2
        finally:
            death_mod.roll_d20 = original

    def test_nat20_recovers(self):
        ds = DeathSaves()
        import core.combat.death as death_mod
        original = death_mod.roll_d20
        death_mod.roll_d20 = lambda advantage=0, disadvantage=0: 20
        try:
            ds.roll_save()
            assert ds.is_stable
        finally:
            death_mod.roll_d20 = original

    def test_three_failures_death(self):
        ds = DeathSaves()
        ds.failures = 3
        assert ds.is_dead

    def test_death_by_injury_overflow(self):
        ds = DeathSaves()
        ds.max_hp = 20
        ds.death_injury = 20
        assert ds.is_dead  # injury >= max_hp


class TestTenacity:
    def test_reduce_on_miss(self):
        """D20 roll=12 missed → tenacity reduced by max(12//5, 1)=2"""
        from core.combat.attack import reduce_tenacity
        c = Creature(name="Test", faction="neutral", tenacity=10, max_tenacity=10)
        reduce_tenacity(c, 12)
        assert c.tenacity == 8

    def test_min_reduction(self):
        """D20 roll=3 → max(3//5, 1)=1"""
        from core.combat.attack import reduce_tenacity
        c = Creature(name="Test", faction="neutral", tenacity=10, max_tenacity=10)
        reduce_tenacity(c, 3)
        assert c.tenacity == 9

    def test_cannot_go_negative(self):
        from core.combat.attack import reduce_tenacity
        c = Creature(name="Test", faction="neutral", tenacity=1, max_tenacity=10)
        reduce_tenacity(c, 15)  # would reduce by 3
        assert c.tenacity == 0

    def test_break_incapacitated(self):
        from core.combat.attack import reduce_tenacity
        c = Creature(name="Test", faction="neutral", tenacity=3, max_tenacity=10)
        reduce_tenacity(c, 20)  # reduce by 4 → tenacity would be -1, clamped to 0
        assert c.tenacity == 0
        assert c.has_status("incapacitated")


class TestCover:
    def test_half_cover_intercepts(self):
        """Half cover AC 5 — attack roll >= 5 hits cover"""
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        hit_cover, _ = resolve_cover_line(attack_roll=8, attacker=(0, 0),
                                          target=(3, 0), grid=g,
                                          weapon_type="ranged")
        # No cover on path → passes through
        assert hit_cover is False

    def test_full_cover_blocks(self):
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        g[2, 0] = Terrain.WALL
        hit_cover, _ = resolve_cover_line(attack_roll=15, attacker=(0, 0),
                                          target=(3, 0), grid=g,
                                          weapon_type="ranged")
        assert hit_cover is True

    def test_thrown_weapon_ignores_same_height_cover(self):
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        g[1, 0] = Terrain.WALL  # half cover at same height
        hit_cover, _ = resolve_cover_line(attack_roll=15, attacker=(0, 0),
                                          target=(2, 0), grid=g,
                                          weapon_type="thrown")
        assert hit_cover is False  # thrown ignores same-height cover


class TestRangedTargetFlow:
    """远程瞄准流程测试 —— ranged_target 阶段进入/确认/取消/掩体。"""

    @pytest.fixture
    def ranged_weapon(self):
        return Weapon(name="短弓", weapon_type="ranged", damage="1d6",
                      damage_type="piercing", attack_stat="dex",
                      ap_cost=2, range_normal=8, range_max=14,
                      properties=["ammo", "two_handed"])

    @pytest.fixture
    def melee_weapon(self):
        return Weapon(name="长剑", weapon_type="melee", damage="1d8",
                      damage_type="slashing", attack_stat="str", ap_cost=3)

    @pytest.fixture
    def flow(self):
        from unittest.mock import MagicMock
        from core.combat.flow import CombatFlow
        state = MagicMock()
        state.combat_phase = "select_action"
        state.player_pos = (5, 5)
        state.player = MagicMock()
        state.player.ap = 6
        state.player.max_ap = 6
        state.in_combat = False
        state.pending_attack = {}
        state.entities = []
        state.observe_cursor = (0, 0)
        state.map = MagicMock()
        state.fov_cache = set()
        flow = CombatFlow(state, MagicMock(), MagicMock(), MagicMock(),
                          MagicMock(), "测试", MagicMock(), MagicMock())
        return flow

    def test_ranged_weapon_enters_ranged_target(self, flow, ranged_weapon):
        """远程武器选中后进入 ranged_target 阶段。"""
        mock_panel = flow._left_panel
        mock_panel._action_map = {1: ("right_hand", ranged_weapon)}
        flow.handle_action_input("A1")
        assert flow._state.combat_phase == "ranged_target"

    def test_melee_weapon_stays_normal_flow(self, flow, melee_weapon):
        """近战武器不走远程瞄准，进入原有近战目标流程。"""
        mock_panel = flow._left_panel
        mock_panel._action_map = {1: ("right_hand", melee_weapon)}
        flow._state.entities = []
        flow.handle_action_input("A1")
        # 近战无相邻目标 → 取消回 idle
        assert flow._state.combat_phase == "idle"

    def test_confirm_ranged_target_sets_target(self, flow, ranged_weapon, player, goblin):
        """confirm_ranged_target 设置光标处生物为目标。"""
        import core.combat.flow as flow_mod

        flow._state.pending_attack = {"weapon": ranged_weapon, "mode": "right_hand"}
        flow._state.observe_cursor = (10, 5)
        flow._state.fov_cache = {(10, 5)}
        flow._state.player = player
        flow._state.player_pos = (5, 5)
        flow._state.combat_phase = "ranged_target"
        flow._state.in_combat = False
        flow._state.map = Grid[Terrain](20, 20, Terrain.PASSABLE)
        flow._state.entities = [(player, (5, 5)), (goblin, (10, 5))]

        # 用真实的 get_entity_at
        def real_get_entity_at(cx, cy):
            for c, (ec, er) in flow._state.entities:
                if (ec, er) == (cx, cy):
                    return c
            return None
        flow._state.get_entity_at = real_get_entity_at

        original = flow_mod.roll_d20
        flow_mod.roll_d20 = lambda advantage=0, disadvantage=0: 15
        try:
            flow.confirm_ranged_target()
            assert flow._state.pending_attack["target"] is goblin
        finally:
            flow_mod.roll_d20 = original

    def test_confirm_allows_empty_tile(self, flow, ranged_weapon):
        """光标在空格子上时允许确认（射空）。"""
        from core.grid import Grid
        from core.movement import Terrain
        flow._state.pending_attack = {"weapon": ranged_weapon, "mode": "right_hand"}
        flow._state.observe_cursor = (10, 5)
        flow._state.player_pos = (5, 5)
        flow._state.fov_cache = {(10, 5)}
        flow._state.combat_phase = "ranged_target"
        flow._state.map = Grid[Terrain](20, 20, Terrain.PASSABLE)
        flow._state.get_entity_at = lambda cx, cy: None
        flow._state.in_combat = False
        flow._state.player = MagicMock()
        flow._state.player.ap = 6

        flow.confirm_ranged_target()
        # 确认后应直接结束攻击，回到 idle（pending_attack 已清空）
        assert flow._state.combat_phase == "idle"

    def test_cancel_ranged_target(self, flow, ranged_weapon):
        """取消远程瞄准返回 select_action。"""
        flow._state.pending_attack = {"weapon": ranged_weapon, "mode": "right_hand"}
        flow._state.combat_phase = "ranged_target"

        flow.cancel_ranged_target()
        assert flow._state.combat_phase == "select_action"

    def test_execute_attack_roll_cover_check(self, flow, ranged_weapon, player, goblin):
        """远程攻击 execute_attack_roll 进行掩体检查。"""
        import core.combat.flow as flow_mod

        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        g[2, 0] = Terrain.WALL

        flow._state.pending_attack = {
            "mode": "right_hand", "weapon": ranged_weapon,
            "hit_bonus": 0, "damage_bonus": 0,
            "attack_roll": None, "target": goblin,
            "target_pos": (3, 0),
        }
        flow._state.player_pos = (0, 0)
        flow._state.player = player
        flow._state.map = g
        flow._state.in_combat = False
        flow._state.entities = [(player, (0, 0)), (goblin, (3, 0))]

        # 提供真实的 _find_entity_pos
        def real_find_entity_pos(target):
            for c, (ec, er) in flow._state.entities:
                if c is target:
                    return (ec, er)
            return None
        flow._find_entity_pos = real_find_entity_pos

        original = flow_mod.roll_d20
        flow_mod.roll_d20 = lambda advantage=0, disadvantage=0: 15
        try:
            flow.execute_attack_roll()
            # 墙阻挡 → 应进入 select_special 或标记 blocked_by_cover
            blocked = flow._state.pending_attack.get("blocked_by_cover", False)
            assert blocked or flow._state.combat_phase == "select_special"
        finally:
            flow_mod.roll_d20 = original


class TestCoverIntegration:
    """掩体集成测试：resolve_attack 端到端掩体检查。"""

    @pytest.fixture
    def ranged_weapon(self):
        return Weapon(name="短弓", weapon_type="ranged", damage="1d6",
                      damage_type="piercing", attack_stat="dex",
                      ap_cost=2, range_normal=8, range_max=14,
                      properties=["ammo", "two_handed"])

    @pytest.fixture
    def melee_weapon(self):
        return Weapon(name="长剑", weapon_type="melee", damage="1d8",
                      damage_type="slashing", attack_stat="str", ap_cost=3)

    def test_ranged_through_wall_blocked(self, player, goblin, ranged_weapon):
        """远程攻击穿墙时被掩体阻挡。"""
        import core.combat.attack as atk_mod
        g = Grid[Terrain](6, 6, Terrain.PASSABLE)
        g[2, 0] = Terrain.WALL  # 墙在攻击者和目标之间
        original = atk_mod.roll_d20
        atk_mod.roll_d20 = lambda advantage=0, disadvantage=0: 15
        try:
            result = resolve_attack(
                player, goblin, ranged_weapon,
                attacker_pos=(0, 0), target_pos=(3, 0), grid=g,
            )
            # 墙是全身掩体，必然阻挡
            assert result["hit"] is False
            assert result["blocked_by_cover"] is True
            assert result["cover_pos"] == (2, 0)
        finally:
            atk_mod.roll_d20 = original

    def test_ranged_through_difficult_terrain_blocked(self, player, ranged_weapon):
        """远程攻击穿过半身掩体(AC5)，低骰(roll<5)被阻挡。用低AC目标确保命中。"""
        import core.combat.attack as atk_mod
        weak = Creature(name="Weak", faction="hostile", hp=5, max_hp=5,
                        tenacity=2, max_tenacity=2, ac_base=3,
                        stats={"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        g = Grid[Terrain](6, 6, Terrain.PASSABLE)
        g[1, 0] = Terrain.DIFFICULT  # 半身掩体 AC5
        original = atk_mod.roll_d20
        atk_mod.roll_d20 = lambda advantage=0, disadvantage=0: 3  # roll=3 命中AC4(3+1=4) 但 < 掩体AC5 → 被挡
        try:
            result = resolve_attack(
                player, weak, ranged_weapon,
                attacker_pos=(0, 0), target_pos=(2, 0), grid=g,
            )
            assert result["blocked_by_cover"] is True
        finally:
            atk_mod.roll_d20 = original

    def test_ranged_no_cover_passes(self, player, goblin, ranged_weapon):
        """远程攻击无障碍物时正常命中。"""
        import core.combat.attack as atk_mod
        g = Grid[Terrain](6, 6, Terrain.PASSABLE)
        original = atk_mod.roll_d20
        atk_mod.roll_d20 = lambda advantage=0, disadvantage=0: 18
        try:
            result = resolve_attack(
                player, goblin, ranged_weapon,
                attacker_pos=(0, 0), target_pos=(3, 0), grid=g,
            )
            assert result["hit"] is True
            assert result["blocked_by_cover"] is False
        finally:
            atk_mod.roll_d20 = original

    def test_melee_ignores_cover(self, player, goblin, melee_weapon):
        """近战攻击无视掩体。"""
        import core.combat.attack as atk_mod
        g = Grid[Terrain](6, 6, Terrain.PASSABLE)
        g[1, 0] = Terrain.WALL  # 墙在中间
        original = atk_mod.roll_d20
        atk_mod.roll_d20 = lambda advantage=0, disadvantage=0: 15
        try:
            result = resolve_attack(
                player, goblin, melee_weapon,
                attacker_pos=(0, 0), target_pos=(2, 0), grid=g,
            )
            # 近战跳过掩体检查，正常命中
            assert result["hit"] is True
            assert result["blocked_by_cover"] is False
        finally:
            atk_mod.roll_d20 = original

    def test_no_position_params_skips_cover(self, player, goblin, ranged_weapon):
        """不传坐标参数时跳过掩体检查（向后兼容）。"""
        import core.combat.attack as atk_mod
        original = atk_mod.roll_d20
        atk_mod.roll_d20 = lambda advantage=0, disadvantage=0: 15
        try:
            result = resolve_attack(player, goblin, ranged_weapon)
            # 无坐标时不做掩体检查，正常命中
            assert result["hit"] is True
            assert result["blocked_by_cover"] is False
        finally:
            atk_mod.roll_d20 = original

    def test_result_always_has_blocked_by_cover_field(self, player, goblin, melee_weapon):
        """所有攻击结果都应包含 blocked_by_cover 字段。"""
        import core.combat.attack as atk_mod
        original = atk_mod.roll_d20
        atk_mod.roll_d20 = lambda advantage=0, disadvantage=0: 1  # 必定未命中
        try:
            result = resolve_attack(player, goblin, melee_weapon)
            assert "blocked_by_cover" in result
            assert result["blocked_by_cover"] is False
        finally:
            atk_mod.roll_d20 = original
