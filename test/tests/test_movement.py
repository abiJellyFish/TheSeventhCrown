"""移动与碰撞测试 —— 通行判断、对角阻挡、实体碰撞、A* 寻路。"""

import pytest
from core.grid import Grid
from core.entity import Creature
from core.movement import can_enter, find_path, Terrain


# ---- 辅助 ----

def make_grid(w, h, terrain_map=None):
    """创建测试网格。"""
    g = Grid[Terrain](width=w, height=h, default=Terrain.PASSABLE)
    if terrain_map:
        for (c, r), t in terrain_map.items():
            g[c, r] = t
    return g

def make_creature(name="test", col=0, row=0, faction="neutral", body_type="humanoid"):
    c = Creature(name=name, faction=faction, body_type=body_type)
    return c, (col, row)


class TestCanEnter:
    def test_open_ground_passable(self):
        g = make_grid(5, 5)
        entities = []
        assert can_enter(2, 2, g, entities) is True

    def test_wall_blocked(self):
        g = make_grid(5, 5, {(2, 2): Terrain.WALL})
        entities = []
        assert can_enter(2, 2, g, entities) is False

    def test_out_of_bounds(self):
        g = make_grid(5, 5)
        entities = []
        assert can_enter(10, 10, g, entities) is False

    def test_difficult_terrain_passable(self):
        g = make_grid(5, 5, {(2, 2): Terrain.DIFFICULT})
        entities = []
        assert can_enter(2, 2, g, entities) is True  # 可以走，只是代价高


class TestDiagonalBlocking:
    def test_diagonal_free(self):
        """对角移动两端无障碍 → 可通过"""
        g = make_grid(5, 5)
        entities = []
        assert can_enter(2, 2, g, entities, from_col=1, from_row=1) is True

    def test_diagonal_blocked_by_corner(self):
        """对角移动时两侧都有墙 → 不可通过"""
        g = make_grid(5, 5, {
            (2, 1): Terrain.WALL,  # 北
            (1, 2): Terrain.WALL,  # 西
        })
        entities = []
        # 从 (1,1) 到 (2,2) 对角，但 (2,1) 和 (1,2) 都是墙
        assert can_enter(2, 2, g, entities, from_col=1, from_row=1) is False

    def test_diagonal_one_corner_blocked_passes(self):
        """对角移动只有一侧有墙 → 可通过"""
        g = make_grid(5, 5, {
            (2, 1): Terrain.WALL,  # 北侧墙
            # (1,2) 是空地
        })
        entities = []
        assert can_enter(2, 2, g, entities, from_col=1, from_row=1) is True


class TestEntityBlocking:
    def test_entity_blocks_tile(self):
        g = make_grid(5, 5)
        blocker, _ = make_creature("blocker", col=2, row=2)
        entities = [(blocker, (2, 2))]
        assert can_enter(2, 2, g, entities) is False

    def test_friendly_entity_passable(self):
        """友好生物可以穿越（但不可在格内停止）"""
        g = make_grid(5, 5)
        friend, _ = make_creature("friend", faction="friendly")
        entities = [(friend, (2, 2))]
        # 穿越：可以穿过非敌对生物占据的格子
        assert can_enter(2, 2, g, entities, allow_pass_through=True) is True

    def test_hostile_entity_not_passable(self):
        """敌对生物不可穿越"""
        g = make_grid(5, 5)
        enemy, _ = make_creature("enemy", faction="hostile")
        entities = [(enemy, (2, 2))]
        assert can_enter(2, 2, g, entities, allow_pass_through=True) is False


class TestAStar:
    def test_simple_path(self):
        g = make_grid(5, 5)
        entities = []
        path = find_path(g, entities, (0, 0), (3, 3))
        assert path is not None
        assert len(path) >= 4  # 至少需要 (0,0)→...→(3,3)
        assert path[0] == (0, 0)
        assert path[-1] == (3, 3)

    def test_blocked_path(self):
        g = make_grid(5, 5)
        # 在中间建一堵墙
        for r in range(5):
            g[2, r] = Terrain.WALL
        entities = []
        path = find_path(g, entities, (0, 0), (4, 0))
        assert path is None or len(path) == 0  # 被墙完全挡住

    def test_path_around_obstacle(self):
        g = make_grid(5, 5)
        g[2, 2] = Terrain.WALL
        entities = []
        path = find_path(g, entities, (0, 2), (4, 2))
        assert path is not None
        # 路径应绕过 (2,2)
        assert (2, 2) not in path
