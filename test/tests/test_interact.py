"""交互系统 —— scan_interact_targets 扫描各类型目标。"""
import pytest
from core.interact import scan_interact_targets, InteractType
from core.game_state import GameState
from core.entity import Player, Creature
from core.movement import Terrain


@pytest.fixture
def state():
    p = Player.create_fighter("测试", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
    s = GameState(player=p, map_width=20, map_height=20)
    s.player_pos = (10, 10)
    return s


class TestScanInteract:
    def test_detect_friendly_creature(self, state):
        c = Creature(name="村民", hp=10, faction="friendly", char="v")
        state.add_entity(c, (10, 9))
        targets = scan_interact_targets(state)
        assert any(t.interact_type == InteractType.TALK and t.creature is c for t in targets)

    def test_detect_corpse(self, state):
        c = Creature(name="尸体", hp=0, faction="hostile", char="%")
        state.add_entity(c, (10, 9))
        targets = scan_interact_targets(state)
        assert any(t.interact_type == InteractType.LOOT for t in targets)

    def test_detect_door(self, state):
        state.map[10, 9] = Terrain.WALL
        state.door_states[(10, 9)] = False  # 关着的门
        targets = scan_interact_targets(state)
        assert any(t.interact_type == InteractType.OPEN for t in targets)

    def test_detect_bed(self, state):
        state.bed_positions.add((10, 9))
        targets = scan_interact_targets(state)
        assert any(t.interact_type == InteractType.REST for t in targets)

    def test_detect_bush(self, state):
        state.map[10, 9] = Terrain.DIFFICULT
        targets = scan_interact_targets(state)
        assert any(t.interact_type == InteractType.PICK for t in targets)

    def test_multiple_targets(self, state):
        c = Creature(name="村民", hp=10, faction="friendly", char="v")
        state.add_entity(c, (10, 9))
        state.map[11, 10] = Terrain.DIFFICULT
        targets = scan_interact_targets(state)
        types = {t.interact_type for t in targets}
        assert InteractType.TALK in types
        assert InteractType.PICK in types
