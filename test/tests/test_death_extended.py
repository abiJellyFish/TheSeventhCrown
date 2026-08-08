"""死亡豁免补充验收测试 —— 边界条件、完整生命周期。"""

import pytest
from core.combat.death import DeathSaves


class TestDeathSavesLifecycle:
    """完整死亡豁免生命周期测试。"""

    @pytest.fixture
    def ds(self):
        return DeathSaves()

    def test_initial_state(self, ds):
        assert ds.successes == 0
        assert ds.failures == 0
        assert ds.death_injury == 0
        assert ds.is_stable is False
        assert ds.is_dead is False

    def test_three_successes_stable(self, ds):
        ds.successes = 3
        assert ds.is_stable is True

    def test_three_failures_dead(self, ds):
        ds.failures = 3
        assert ds.is_dead is True

    def test_injury_equals_maxhp_dead(self, ds):
        ds.max_hp = 20
        ds.death_injury = 20
        assert ds.is_dead is True

    def test_injury_exceeds_maxhp_dead(self, ds):
        ds.max_hp = 20
        ds.death_injury = 25
        assert ds.is_dead is True

    def test_injury_below_maxhp_not_dead(self, ds):
        ds.max_hp = 20
        ds.death_injury = 19
        assert ds.is_dead is False

    def test_take_damage_from_above_zero_drops_to_zero(self, ds):
        new_hp = ds.take_damage_from_above_zero(current_hp=10, damage=15, max_hp=30)
        assert new_hp == 0
        assert ds.death_injury == 0  # 从非0降到0不累积濒死受伤

    def test_take_damage_from_above_zero_does_not_go_negative(self, ds):
        new_hp = ds.take_damage_from_above_zero(current_hp=2, damage=20, max_hp=30)
        assert new_hp == 0

    def test_take_damage_at_zero_accumulates(self, ds):
        ds.take_damage_at_zero(damage=5, max_hp=30)
        assert ds.death_injury == 5
        ds.take_damage_at_zero(damage=3, max_hp=30)
        assert ds.death_injury == 8


class TestDeathSaveRolls:
    """豁免检定精确值测试。"""

    def test_dc10_success(self):
        ds = DeathSaves()
        import core.combat.death as death_mod
        original = death_mod.roll_d20
        death_mod.roll_d20 = lambda advantage=0, disadvantage=0: 10
        try:
            ds.roll_save()
            assert ds.successes == 1
        finally:
            death_mod.roll_d20 = original

    def test_dc9_failure(self):
        ds = DeathSaves()
        import core.combat.death as death_mod
        original = death_mod.roll_d20
        death_mod.roll_d20 = lambda advantage=0, disadvantage=0: 9
        try:
            ds.roll_save()
            assert ds.failures == 1
        finally:
            death_mod.roll_d20 = original

    def test_nat1_two_failures(self):
        ds = DeathSaves()
        import core.combat.death as death_mod
        original = death_mod.roll_d20
        death_mod.roll_d20 = lambda advantage=0, disadvantage=0: 1
        try:
            ds.roll_save()
            assert ds.failures == 2
        finally:
            death_mod.roll_d20 = original

    def test_nat20_instant_stable(self):
        ds = DeathSaves()
        ds.failures = 2  # on the brink
        import core.combat.death as death_mod
        original = death_mod.roll_d20
        death_mod.roll_d20 = lambda advantage=0, disadvantage=0: 20
        try:
            ds.roll_save()
            assert ds.successes == 3
            assert ds.is_stable is True
        finally:
            death_mod.roll_d20 = original

    def test_nat20_ignores_existing_successes(self):
        """nat20 直接把 successes 设为 3，而不是 +1。"""
        ds = DeathSaves()
        ds.successes = 1
        import core.combat.death as death_mod
        original = death_mod.roll_d20
        death_mod.roll_d20 = lambda advantage=0, disadvantage=0: 20
        try:
            ds.roll_save()
            assert ds.successes == 3  # 设为 3，不是 2
        finally:
            death_mod.roll_d20 = original


class TestDeathSavesInjuryDeath:
    """濒死受伤致死测试。"""

    def test_combined_path_to_death(self):
        """完整死亡路径：受伤累积导致 death_injury >= max_hp。"""
        ds = DeathSaves()
        ds.take_damage_from_above_zero(current_hp=10, damage=12, max_hp=30)
        # HP 归零
        assert ds.death_injury == 0
        # 后续受伤
        ds.take_damage_at_zero(damage=15, max_hp=30)
        ds.take_damage_at_zero(damage=15, max_hp=30)
        assert ds.death_injury == 30
        assert ds.is_dead is True
