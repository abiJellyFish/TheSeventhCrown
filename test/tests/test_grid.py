"""泛型网格 —— Grid[T] 基础读写、边界检查、邻居获取。"""
import pytest
from core.grid import Grid


class TestGrid:
    def test_create_and_access(self):
        g = Grid[int](width=10, height=10, default=0)
        g[3, 5] = 42
        assert g[3, 5] == 42
        assert g.width == 10

    def test_within_bounds(self):
        g = Grid[int](width=5, height=5, default=0)
        assert g.within_bounds(0, 0) is True
        assert g.within_bounds(-1, 0) is False
        assert g.within_bounds(0, 5) is False

    def test_neighbors_middle(self):
        g = Grid[int](width=5, height=5, default=0)
        n = g.neighbors(2, 2)
        assert len(n) == 8
        coords = {(c, r) for c, r in n}
        expected = {(1, 1), (2, 1), (3, 1), (1, 2), (3, 2), (1, 3), (2, 3), (3, 3)}
        assert coords == expected
