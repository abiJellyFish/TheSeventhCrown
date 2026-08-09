"""泛型网格 —— Grid[T] 支持 get/set/neighbors/bounds。

坐标统一为 (col, row)，col 向右递增，row 向下递增。
"""

import pytest
from core.grid import Grid


class TestGridCreate:
    def test_create_and_access(self):
        g = Grid[int](width=10, height=10, default=0)
        assert g.width == 10
        assert g.height == 10

        g[3, 5] = 42
        assert g[3, 5] == 42

    def test_default_value(self):
        g = Grid[str](width=5, height=5, default=".")
        assert g[2, 2] == "."


class TestGridBounds:
    def test_within_bounds(self):
        g = Grid[int](width=5, height=5, default=0)
        assert g.within_bounds(0, 0) is True
        assert g.within_bounds(4, 4) is True
        assert g.within_bounds(-1, 0) is False
        assert g.within_bounds(0, 5) is False
        assert g.within_bounds(5, 0) is False

    def test_get_out_of_bounds_returns_none(self):
        g = Grid[int](width=5, height=5, default=0)
        assert g.get(-1, 0) is None
        assert g.get(0, 5) is None
        assert g.get(5, 5) is None

    def test_set_out_of_bounds_does_nothing(self):
        g = Grid[int](width=5, height=5, default=0)
        g[-1, 0] = 99  # 不应抛异常
        assert g[0, 0] == 0  # 没有被影响


class TestGridNeighbors:
    def test_neighbors_middle(self):
        """中间格子有 8 个邻居"""
        g = Grid[int](width=5, height=5, default=0)
        n = g.neighbors(2, 2)
        assert len(n) == 8

    def test_neighbors_corner(self):
        """角落格子只有 3 个邻居"""
        g = Grid[int](width=5, height=5, default=0)
        n = g.neighbors(0, 0)
        assert len(n) == 3

    def test_neighbors_edge(self):
        """边缘格子有 5 个邻居"""
        g = Grid[int](width=5, height=5, default=0)
        n = g.neighbors(0, 2)
        assert len(n) == 5

    def test_neighbors_include_diagonals(self):
        """邻居包含对角方向"""
        g = Grid[int](width=5, height=5, default=0)
        n = g.neighbors(2, 2)
        coords = {(c, r) for c, r in n}
        # 8 方向
        expected = {
            (1, 1), (2, 1), (3, 1),
            (1, 2), (3, 2),
            (1, 3), (2, 3), (3, 3),
        }
        assert coords == expected
