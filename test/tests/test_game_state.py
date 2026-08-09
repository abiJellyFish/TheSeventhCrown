"""GameState tests."""

import pytest
from core.game_state import GameState
from core.entity import Player, Creature
from core.grid import Grid
from core.movement import Terrain


@pytest.fixture
def player():
    return Player.create_fighter(name="TestHero",
                                 stats={"str": 8, "dex": 8, "con": 8,
                                        "int": 8, "wis": 8, "cha": 8})


@pytest.fixture
def state(player):
    return GameState(player=player, map_width=20, map_height=15)


class TestGameState:
    def test_init(self, state, player):
        assert state.player is player
        assert state.map.width == 20
        assert state.in_combat is False

    def test_add_entity(self, state):
        goblin = Creature(name="Goblin", faction="hostile")
        state.add_entity(goblin, (5, 5))
        assert len(state.entities) == 1
        assert state.get_entity_at(5, 5) is goblin

    def test_player_move(self, state):
        state.player_pos = (3, 3)
        state.move_player(4, 3)
        assert state.player_pos == (4, 3)

    def test_player_move_blocked_by_wall(self, state):
        state.map[4, 3] = Terrain.WALL
        state.player_pos = (3, 3)
        result = state.move_player(4, 3)
        assert result is False
        assert state.player_pos == (3, 3)

    def test_remove_entity(self, state):
        goblin = Creature(name="Goblin", faction="hostile")
        state.add_entity(goblin, (5, 5))
        state.remove_entity(goblin)
        assert state.get_entity_at(5, 5) is None

    def test_npc_cannot_move_onto_player(self, state):
        """NPC 不能移动到玩家所在格。"""
        state.player_pos = (5, 5)
        goblin = Creature(name="Goblin", faction="hostile")
        state.add_entity(goblin, (5, 4))
        # NPC 尝试移动到玩家位置
        result = state.move_entity(goblin, 5, 4, 5, 5)
        assert result is False
        # NPC 仍在原位
        assert state.get_entity_at(5, 4) is goblin
