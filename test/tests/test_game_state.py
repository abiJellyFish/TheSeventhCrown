"""游戏状态 —— 实体管理、移动、休息、存档。"""
import pytest
import os
import tempfile
from core.game_state import GameState
from core.entity import Creature, create_fighter
from core.movement import Terrain
from core.rest import short_rest, long_rest
from core.save.database import SaveManager


@pytest.fixture
def state():
    p = create_fighter("测试", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
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
        state2 = GameState(player=create_fighter("测试", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}), map_width=20, map_height=20)
        success = sm.load(state2, slot="test")
        assert success is True


# ═══════════════════════════════════════════════════
# _scan_context 敌人检测含 player
# ═══════════════════════════════════════════════════

class TestScanContextEnemy:
    """_scan_context 敌人检测含 player。"""

    @pytest.fixture
    def state(self):
        from core.game_state import GameState
        from core.entity import create_fighter
        p = create_fighter("Test", {"str":10,"dex":10,"con":10,"int":10,"wis":10,"cha":10})
        s = GameState(player=p, map_width=30, map_height=30)
        s.player_pos = (5, 5)
        return s

    def test_enemy_adjacent_when_hostile_nearby(self, state):
        from core.entity import Creature
        hostile = Creature(name="goblin", faction="混乱", hp=10, char="g")
        state.entities = [(hostile, (6, 5))]
        ctx = state._scan_context(state.player, 5, 5)
        assert ctx["enemy_adjacent"]

    def test_no_enemy_when_same_faction(self, state):
        from core.entity import Creature
        ally = Creature(name="friend", faction="守序", hp=10, char="f")
        state.entities = [(ally, (6, 5))]
        ctx = state._scan_context(state.player, 5, 5)
        assert not ctx["enemy_adjacent"]


# ═══════════════════════════════════════════════════
# _tick_food 中 player HP 保底 1
# ═══════════════════════════════════════════════════

class TestPlayerHPFloor:
    """_tick_food 中 player HP 保底 1。"""

    def test_player_hp_floor_at_one(self):
        from core.game_state import GameState
        p = create_fighter("Test", {"str":10,"dex":10,"con":10,"int":10,"wis":10,"cha":10})
        p.hp = 0
        p.food_value = 0
        s = GameState(player=p, map_width=30, map_height=30)
        s._tick_food()
        assert p.hp == 1
