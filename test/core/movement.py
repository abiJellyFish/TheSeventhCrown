"""移动与碰撞 —— 通行判断、实体碰撞、A* 寻路。

坐标统一为 (col, row)。
"""

import heapq

from core.grid import Grid, DIRS_4, Terrain
from core.item_actions import tile_space_used
from core.combat.cover import is_full_cover


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
    if is_full_cover(terrain):
        return False

    # 实体阻挡（尸体不阻挡）
    for creature, (ec, er) in entities:
        if (ec, er) == (col, row):
            if creature.hp <= 0:
                continue
            # 混乱阵营阻挡，守序/中立不阻挡
            if creature.faction == "混乱" or not allow_pass_through:
                return False

    return True


def _terrain_cost(terrain: Terrain) -> int:
    """地形移动代价：普通=10, 困难=20（用于 A* 权重）。"""
    if terrain == Terrain.DIFFICULT:
        return 20
    return 10


def _step_cost(
    grid: Grid[Terrain],
    entities: list[tuple["Creature", tuple[int, int]]],
    pos: tuple[int, int],
    player_pos: tuple[int, int] | None = None,
    ground_items: list | None = None,
    occupied_alive: set | None = None,
    dead_positions: set | None = None,
) -> int | None:
    """返回经过该格的代价，None 表示不可达。

    occupied_alive / dead_positions 为预建的坐标集合（find_path 一次预建），
    传入时 O(1) 判断占据，避免逐实体 O(N) 遍历。
    """
    t = grid[pos[0], pos[1]]
    if is_full_cover(t):
        return None
    if player_pos and pos == player_pos:
        return None  # 不能走到玩家格
    if occupied_alive is not None and dead_positions is not None:
        if pos in occupied_alive:
            return None  # 活物：不可达
        if pos in dead_positions:
            return 3  # 尸体：可通过，代价 3
    else:
        for c, (ec, er) in entities:
            if (ec, er) == pos:
                if c.hp <= 0:
                    return 3  # 尸体：可通过，代价 3
                else:
                    return None  # 活物：不可达
    if t == Terrain.DIFFICULT:
        return 3
    # 物品堆积格（space >= 10）-> 困难地形代价
    if ground_items and tile_space_used(ground_items, pos[0], pos[1]) >= 10:
        return 3
    return 1


# ═══════════════════════════════════════════════════
# A* 寻路
# ═══════════════════════════════════════════════════

def find_path(
    grid: Grid[Terrain],
    entities: list[tuple["Creature", tuple[int, int]]],
    start: tuple[int, int],
    goal: tuple[int, int],
    player_pos: tuple[int, int] | None = None,
    dirs: list[tuple[int, int]] = None,
    ground_items: list | None = None,
) -> list[tuple[int, int]] | None:
    """A* 寻路。

    Args:
        player_pos: 玩家位置，NPC 寻路时避免走入该格。
        dirs: 移动方向列表，默认 4 方向。
        ground_items: 地上物品列表，用于判断拥挤格代价。

    Returns:
        路径坐标列表（含起点和终点），不可达返回 None。
    """
    if dirs is None:
        dirs = DIRS_4

    if start == goal:
        return [start]

    # 预建占据集合，A* 每步 O(1) 判断（O(N) → O(1)）
    occupied_alive = {pos for c, pos in entities if c.hp > 0}
    dead_positions = {pos for c, pos in entities if c.hp <= 0}

    if _step_cost(grid, entities, goal, player_pos, ground_items,
                  occupied_alive, dead_positions) is None:
        return None

    def h(pos):
        """启发函数：切比雪夫距离（允许 8 方向移动时最优）。"""
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

        for dc, dr in dirs:
            nc, nr = current[0] + dc, current[1] + dr
            if not grid.within_bounds(nc, nr):
                continue
            cost = _step_cost(grid, entities, (nc, nr), player_pos, ground_items,
                              occupied_alive, dead_positions)
            if cost is None:
                continue
            tentative_g = g_score[current] + cost
            if tentative_g < g_score.get((nc, nr), float("inf")):
                came_from[(nc, nr)] = current
                g_score[(nc, nr)] = tentative_g
                f_score[(nc, nr)] = tentative_g + h((nc, nr))
                heapq.heappush(open_set, (f_score[(nc, nr)], (nc, nr)))

    return None  # 不可达
