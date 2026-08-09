"""Rest system tests."""

import pytest
from core.rest import short_rest, long_rest, is_comfortable
from core.entity import Player
from core.pendulum import PendulumClock
from core.grid import Grid
from core.movement import Terrain


@pytest.fixture
def player():
    p = Player.create_fighter(name="Test",
                              stats={"str": 8, "dex": 8, "con": 8,
                                     "int": 8, "wis": 8, "cha": 8})
    p.hp = 10  # start wounded
    return p


@pytest.fixture
def clock():
    return PendulumClock(scale=10)


class TestShortRest:
    def test_restores_half_hp(self, player, clock):
        initial_hp = player.hp  # 10
        result = short_rest(player, clock)
        assert player.hp > initial_hp
        assert result["hp_restored"] == player.max_hp // 2  # 17

    def test_does_not_exceed_max_hp(self, player, clock):
        player.hp = player.max_hp - 5
        short_rest(player, clock)
        assert player.hp == player.max_hp

    def test_advances_time(self, player, clock):
        short_rest(player, clock)
        assert clock.pendulum_count == 300


class TestLongRest:
    def test_restores_full_hp(self, player, clock):
        player.hp = 5
        long_rest(player, clock)
        assert player.hp == player.max_hp

    def test_advances_time(self, player, clock):
        long_rest(player, clock)
        assert clock.pendulum_count == 1500


class TestComfort:
    def test_indoor_is_comfortable(self):
        g = Grid[Terrain](5, 5, Terrain.PASSABLE)
        # (2,2) surrounded by walls at N, W, E → 3 walls ≥ 2
        g[2, 1] = Terrain.WALL  # N
        g[1, 2] = Terrain.WALL  # W
        g[3, 2] = Terrain.WALL  # E
        assert is_comfortable((2, 2), g) is True

    def test_open_ground_not_comfortable(self):
        g = Grid[Terrain](5, 5, Terrain.PASSABLE)
        assert is_comfortable((2, 2), g) is False

    def test_short_rest_comfort_doubles(self, player, clock):
        g = Grid[Terrain](5, 5, Terrain.PASSABLE)
        # (2,2) with 2+ walls = comfortable
        g[2, 1] = Terrain.WALL  # N
        g[1, 2] = Terrain.WALL  # W
        player.hp = 5
        result = short_rest(player, clock, g, (2, 2))
        expected = int(player.max_hp * 0.5 * 2)
        assert result["hp_restored"] == expected  # doubled
        assert player.hp == min(player.max_hp, 5 + expected)
        assert player.hp == player.max_hp
