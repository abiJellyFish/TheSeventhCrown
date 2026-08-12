"""移动与碰撞 —— 通行判断、对角阻挡、A* 寻路。"""
import pytest
from core.movement import can_enter, find_path, Terrain, _step_cost
from core.grid import Grid
from core.entity import Creature, Item


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


# ═══════════════════════════════════════════════════
# _step_cost — 地面物品空间 ≥10 视作困难地形
# ═══════════════════════════════════════════════════

class TestStepCostWithGroundItems:
    """space >= 10 -> 困难地形代价 3；space < 10 -> 正常代价 1。"""

    def _make_item(self, space, count):
        return Item(name="test", item_type="misc", space=space, count=count)

    def test_space_ge_10_returns_3(self):
        g = _grid()
        item = self._make_item(space=2, count=5)  # 2*5=10
        ground_items = [(item, (3, 3))]
        cost = _step_cost(g, [], (3, 3), ground_items=ground_items)
        assert cost == 3  # 困难地形

    def test_space_lt_10_returns_normal(self):
        g = _grid()
        item = self._make_item(space=2, count=4)  # 2*4=8
        ground_items = [(item, (3, 3))]
        # tile 是 PASSABLE，没有实体，space<10 -> 代价 1
        cost = _step_cost(g, [], (3, 3), ground_items=ground_items)
        assert cost == 1

    def test_space_ge_10_on_difficult(self):
        """物品 space>=10 + 已是困难地形 -> 仍返回 3（统一代价）。"""
        g = _grid()
        g[3, 3] = Terrain.DIFFICULT
        item = self._make_item(space=2, count=5)  # 10
        ground_items = [(item, (3, 3))]
        cost = _step_cost(g, [], (3, 3), ground_items=ground_items)
        assert cost == 3  # 统一困难代价

    def test_no_ground_items_ignored(self):
        """无 ground_items 参数时正常计算。"""
        g = _grid()
        cost = _step_cost(g, [], (3, 3))
        assert cost == 1


# ═══════════════════════════════════════════════════
# can_enter — 物品不阻挡生物移动
# ═══════════════════════════════════════════════════

class TestCanEnterNotBlockedByItems:
    """物品不阻挡生物移动。"""

    def test_can_enter_with_items(self):
        g = _grid()
        item = Item(name="test", item_type="misc", space=10, count=10)  # space >> 10
        # can_enter 不接收 ground_items，物品不影响通行
        assert can_enter(3, 3, g, [], 2, 2)
