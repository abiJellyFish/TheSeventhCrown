"""GameState 补充验收测试 —— move_entity、战斗状态、观察模式、边界条件。"""

import pytest
from core.game_state import GameState
from core.entity import Player, Creature
from core.movement import Terrain


@pytest.fixture
def player():
    return Player.create_fighter(name="Hero",
                                 stats={"str": 8, "dex": 8, "con": 8,
                                        "int": 8, "wis": 8, "cha": 8})


@pytest.fixture
def state(player):
    return GameState(player=player, map_width=30, map_height=20)


class TestMoveEntity:
    def test_move_entity_success(self, state):
        goblin = Creature(name="Goblin", faction="hostile")
        state.add_entity(goblin, (10, 10))
        result = state.move_entity(goblin, 10, 10, 11, 10)
        assert result is True
        # 验证位置更新
        found = False
        for c, (ec, er) in state.entities:
            if c is goblin and (ec, er) == (11, 10):
                found = True
        assert found

    def test_move_entity_blocked_by_wall(self, state):
        goblin = Creature(name="Goblin", faction="hostile")
        state.add_entity(goblin, (10, 10))
        state.map[11, 10] = Terrain.WALL
        result = state.move_entity(goblin, 10, 10, 11, 10)
        assert result is False

    def test_move_entity_not_found(self, state):
        goblin = Creature(name="Goblin", faction="hostile")
        state.add_entity(goblin, (10, 10))
        # 尝试移动不在该位置的实体
        result = state.move_entity(goblin, 99, 99, 10, 11)
        assert result is False


class TestGetEntityAt:
    def test_get_entity_at_empty(self, state):
        assert state.get_entity_at(5, 5) is None

    def test_get_entity_at_returns_correct(self, state):
        goblin = Creature(name="Goblin", faction="hostile")
        state.add_entity(goblin, (5, 5))
        assert state.get_entity_at(5, 5) is goblin


class TestMovePlayerCombatMode:
    def test_move_player_not_in_combat_advances_clock(self, state):
        state.player_pos = (5, 5)
        initial_pc = state.clock.pendulum_count
        state.move_player(6, 5)
        assert state.clock.pendulum_count > initial_pc


class TestCombatStateFields:
    def test_combat_fields_default(self, state):
        assert state.in_combat is False
        assert state.combat_initiative == []
        assert state.current_turn_index == 0
        assert state.combat_turn_entity is None
        assert state.combat_phase == "idle"
        assert state.pending_attack is None

    def test_combat_fields_settable(self, state):
        state.in_combat = True
        goblin = Creature(name="Goblin", faction="hostile")
        state.combat_initiative = [goblin]
        state.combat_turn_entity = goblin
        assert state.in_combat is True
        assert state.combat_turn_entity is goblin


class TestObserveAndSlowMode:
    def test_observe_defaults(self, state):
        assert state.observe_mode is False
        assert state.observe_cursor == (0, 0)

    def test_slow_mode_toggle(self, state):
        assert state.slow_mode is False
        state.slow_mode = True
        assert state.slow_mode is True


class TestRemoveEntity:
    def test_remove_entity_preserves_others(self, state):
        a = Creature(name="A", faction="neutral")
        b = Creature(name="B", faction="neutral")
        state.add_entity(a, (1, 1))
        state.add_entity(b, (2, 2))
        state.remove_entity(a)
        assert len(state.entities) == 1
        assert state.get_entity_at(1, 1) is None
        assert state.get_entity_at(2, 2) is b


class TestMapMetadata:
    def test_dungeon_fields(self, state):
        assert state.in_dungeon is False
        assert state.dungeon_entrance is None
        assert state.dungeon_exit is None

    def test_bed_positions(self, state):
        state.bed_positions = {(3, 3)}
        assert (3, 3) in state.bed_positions
        assert (0, 0) not in state.bed_positions

    def test_door_states(self, state):
        state.door_states[(4, 5)] = False
        assert state.door_states[(4, 5)] is False


class TestMapInitialization:
    def test_map_created_in_post_init(self, state):
        assert state.map is not None
        assert state.map.width == 30
        assert state.map.height == 20

    def test_map_default_terrain_passable(self, state):
        # 默认所有格子可通行
        assert state.map[15, 10] == Terrain.PASSABLE


class TestNPCCallbackRegistered:
    def test_callback_registered_on_init(self, state):
        """__post_init__ 注册了 NPC 推进回调。"""
        assert state.clock._on_advance_npcs is not None
