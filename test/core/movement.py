"""移动与碰撞 —— 通行判断、对角阻挡、实体碰撞、A* 寻路。

坐标统一为 (col, row)。
"""

import heapq
from enum import Enum, auto

from core.grid import Grid


class Terrain(Enum):
    """地形类型。"""
    PASSABLE = auto()
    DIFFICULT = auto()
    WALL = auto()


# 8 方向偏移
_DIRS = [
    (-1, -1), (0, -1), (1, -1),
    (-1,  0),          (1,  0),
    (-1,  1), (0,  1), (1,  1),
]

# 对角线方向的邻边
_DIAG_CORNERS = {
    (-1, -1): [(-1, 0), (0, -1)],
    (1, -1):  [(1, 0),  (0, -1)],
    (-1, 1):  [(-1, 0), (0, 1)],
    (1, 1):   [(1, 0),  (0, 1)],
}


# ═══════════════════════════════════════════════════
# 通行判断
# ═══════════════════════════════════════════════════

def can_enter(
    col: int, row: int,
    grid: Grid[Terrain],
    entities: list[tuple["Creature", tuple[int, int]]],
    from_col: int | None = None,
    from_row: int | None = None,
    allow_pass_through: bool = False,
) -> bool:
    """判断是否可以进入 (col, row)。

    Args:
        col, row: 目标坐标
        grid: 地形网格
        entities: [(creature, (col, row)), ...]
        from_col, from_row: 来源坐标（用于检测对角阻挡）
        allow_pass_through: True=允许穿越非敌对生物（但不停止）
    """
    if not grid.within_bounds(col, row):
        return False

    terrain = grid[col, row]
    if terrain == Terrain.WALL:
        return False

    # 对角移动：检查两侧是否有墙
    if from_col is not None and from_row is not None:
        dc = col - from_col
        dr = row - from_row
        if abs(dc) == 1 and abs(dr) == 1:  # 对角
            corners = _DIAG_CORNERS[(dc, dr)]
            blocked = all(
                grid[from_col + cc, from_row + cr] == Terrain.WALL
                for cc, cr in corners
            )
            if blocked:
                return False

    # 实体阻挡
    for creature, (ec, er) in entities:
        if (ec, er) == (col, row):
            if creature.faction == "hostile" or not allow_pass_through:
                return False

    return True


def _terrain_cost(terrain: Terrain) -> int:
    """地形移动代价：普通=10, 困难=20（用于 A* 权重）。"""
    if terrain == Terrain.DIFFICULT:
        return 20
    return 10


# ═══════════════════════════════════════════════════
# A* 寻路
# ═══════════════════════════════════════════════════

def find_path(
    grid: Grid[Terrain],
    entities: list[tuple["Creature", tuple[int, int]]],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]] | None:
    """A* 8 方向寻路。

    Returns:
        路径坐标列表（含起点和终点），不可达返回 None。
    """
    if start == goal:
        return [start]

    if not can_enter(*goal, grid, entities):
        return None

    def h(pos):
        """启发函数：切比雪夫距离（允许 8 方向移动）。"""
        return max(abs(pos[0] - goal[0]), abs(pos[1] - goal[1]))

    open_set = []
    heapq.heappush(open_set, (0, start))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}
    f_score: dict[tuple[int, int], int] = {start: h(start)}

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == goal:
            # 重建路径
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        for dc, dr in _DIRS:
            nc, nr = current[0] + dc, current[1] + dr
            if not can_enter(nc, nr, grid, entities, current[0], current[1],
                             allow_pass_through=True):
                continue

            cost = _terrain_cost(grid[nc, nr])
            # 对角线代价 ×1.4
            if dc != 0 and dr != 0:
                cost = int(cost * 1.4)

            tentative_g = g_score[current] + cost
            if tentative_g < g_score.get((nc, nr), float("inf")):
                came_from[(nc, nr)] = current
                g_score[(nc, nr)] = tentative_g
                f_score[(nc, nr)] = tentative_g + h((nc, nr)) * 10
                heapq.heappush(open_set, (f_score[(nc, nr)], (nc, nr)))

    return None  # 不可达
