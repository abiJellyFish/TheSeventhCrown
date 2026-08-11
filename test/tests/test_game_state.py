"""游戏状态 —— 实体管理、移动、休息、存档。"""
import pytest
import os
import tempfile
from core.game_state import GameState
from core.entity import Player, Creature
from core.movement import Terrain
from core.rest import short_rest, long_rest
from core.save.database import SaveManager


@pytest.fixture
def state():
    p = Player.create_fighter("测试", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
    s = GameState(player=p, map_width=20, map_height=20)
    s.player_pos = (10, 10)
    return s


class TestEntities:
    def test_add_entity(self, state):
        c = Creature(name="地精", hp=10, char="g")
        state.add_entity(c, (5, 5))
        assert any(e is c for e, _ in state.entities)

    def test_remove_entity(self, state):
        c = Creature(name="地精", hp=10, char="g")
        state.add_entity(c, (5, 5))
        state.remove_entity(c)
        assert not any(e is c for e, _ in state.entities)

    def test_get_entity_at(self, state):
        c = Creature(name="地精", hp=10, char="g")
        state.add_entity(c, (5, 5))
        assert state.get_entity_at(5, 5) is c
        assert state.get_entity_at(0, 0) is None

    def test_npc_cannot_move_onto_player(self, state):
        c = Creature(name="地精", hp=10, char="g")
        state.add_entity(c, (9, 10))
        result = state.move_entity(c, 9, 10, 10, 10)
        assert result is False


class TestMovement:
    def test_player_move_blocked_by_wall(self, state):
        state.map[11, 10] = Terrain.WALL
        old = state.player_pos
        result = state.move_player(11, 10)
        assert result is False
        assert state.player_pos == old

    def test_move_advances_clock(self, state):
        assert state.clock.pendulum_count == 0
        state.move_player(11, 10)
        assert state.clock.pendulum_count >= 1


class TestRest:
    def test_short_rest_heals(self, state):
        state.player.hp = 10
        state.player.max_hp = 30
        short_rest(state.player, state.clock, state.map, state.player_pos, set())
        assert state.player.hp > 10

    def test_long_rest_heals_full(self, state):
        state.player.hp = 10
        state.player.max_hp = 30
        long_rest(state.player, state.clock, state.map, state.player_pos, set())
        assert state.player.hp == 30


class TestSave:
    @pytest.fixture
    def tmp_dir(self):
        d = tempfile.mkdtemp()
        yield d
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_save_and_load(self, state, tmp_dir):
        sm = SaveManager(tmp_dir)
        sm.save(state, "test")  # returns None, raises on error
        state2 = GameState(player=Player.create_fighter("测试", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}), map_width=20, map_height=20)
        success = sm.load(state2, slot="test")
        assert success is True
