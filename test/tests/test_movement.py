"""移动与碰撞 —— 通行判断、对角阻挡、A* 寻路。"""
import pytest
from core.movement import can_enter, find_path, Terrain
from core.grid import Grid
from core.entity import Creature


def _grid(w=10, h=10):
    return Grid[Terrain](w, h, Terrain.PASSABLE)


class TestCanEnter:
    def test_open_ground_passable(self):
        g = _grid()
        assert can_enter(3, 3, g, [], 2, 2)

    def test_wall_blocked(self):
        g = _grid()
        g[3, 3] = Terrain.WALL
        assert not can_enter(3, 3, g, [], 2, 2)

    def test_diagonal_blocked_by_corner(self):
        g = _grid()
        g[3, 2] = Terrain.WALL  # 北侧墙
        g[2, 3] = Terrain.WALL  # 西侧墙
        assert not can_enter(3, 3, g, [], 2, 2)  # 对角被墙角阻挡

    def test_entity_blocks_tile(self):
        g = _grid()
        c = Creature(name="goblin", hp=10, char="g")
        assert not can_enter(3, 3, g, [(c, (3, 3))], 2, 2)


class TestFindPath:
    def test_simple_path(self):
        g = _grid()
        path = find_path(g, [], (0, 0), (2, 2))
        assert len(path) >= 3
        assert path[-1] == (2, 2)

    def test_blocked_path(self):
        g = _grid(3, 3)
        g[0, 1] = Terrain.WALL
        g[1, 1] = Terrain.WALL
        g[2, 1] = Terrain.WALL
        path = find_path(g, [], (0, 0), (0, 2))
        assert path is None or path == []  # find_path returns None for no path
