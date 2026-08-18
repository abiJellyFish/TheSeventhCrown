"""移动与碰撞 —— 通行判断、实体碰撞、A* 寻路。

坐标统一为 (col, row)。
"""

import heapq

import math

from core.grid import Grid, DIRS_4, DIRS_8, Terrain, DIFFICULT_TERRAINS, BLOCKING_TERRAINS
from core.item_actions import tile_space_used
from core.combat.cover import is_full_cover


# ═══════════════════════════════════════════════════
# 朝向扇区判定（阶段2：朝向系统）
# ═══════════════════════════════════════════════════

# DIRS_8 各方向索引对应的方位角（atan2(-dy,dx) 归一化到 0-360）
_DIR_SECTOR_ANGLES = [135, 90, 45, 180, 0, 225, 270, 315]
_DIR_LABELS = ["西北", "北", "东北", "西", "东", "西南", "南", "东南"]


def _octant_index(dx: int, dy: int) -> int:
    """把任意方向向量归约到最近 8 方向，返回 DIRS_8 索引。"""
    if dx == 0 and dy == 0:
        return 0
    ang = math.degrees(math.atan2(-dy, dx)) % 360
    best, best_d = 0, 1e9
    for i, a in enumerate(_DIR_SECTOR_ANGLES):
        d = abs((ang - a + 180) % 360 - 180)
        if d < best_d:
            best_d, best = d, i
    return best


def sector_of(facing: tuple[int, int], delta: tuple[int, int]) -> str:
    """delta=(dx,dy) 相对 facing 的扇区: "front"|"side"|"back"。

    前方 3 格扇形=身前（±45°），后方 3 格=身后（135°~225°），
    左右各 1 格=身侧（45°~135° 与 225°~315°）。
    """
    fx, fy = facing
    if fx == 0 and fy == 0:
        return "front"
    fang = math.degrees(math.atan2(-fy, fx)) % 360
    dx, dy = delta
    if dx == 0 and dy == 0:
        return "front"  # 自身格
    dang = math.degrees(math.atan2(-dy, dx)) % 360
    diff = (dang - fang) % 360
    if diff <= 45 or diff >= 315:
        return "front"
    if 135 <= diff <= 225:
        return "back"
    return "side"


def facing_label(facing: tuple[int, int]) -> str:
    """朝向方向中文名（北/东北/东/…）。"""
    return _DIR_LABELS[_octant_index(facing[0], facing[1])]


# ═══════════════════════════════════════════════════
# sector_of 背向扇区缓存（避免每次 atan2）
# ═══════════════════════════════════════════════════

_BACK_SECTOR_CACHE: dict[tuple[int, int], frozenset] = {}


def _init_back_sector_cache(max_r: int = 30) -> None:
    """预计算 8 方向各自的身后扇区偏移集合。"""
    for facing in DIRS_8:
        back = set()
        for dx in range(-max_r, max_r + 1):
            for dy in range(-max_r, max_r + 1):
                if dx == 0 and dy == 0:
                    continue
                if sector_of(facing, (dx, dy)) == "back":
                    back.add((dx, dy))
        _BACK_SECTOR_CACHE[facing] = frozenset(back)


def is_back_sector(facing: tuple[int, int], dx: int, dy: int) -> bool:
    """O(1) 查表判断 (dx,dy) 是否在 facing 的身后扇区。"""
    return (dx, dy) in _BACK_SECTOR_CACHE.get(facing, frozenset())


_init_back_sector_cache()


# ═══════════════════════════════════════════════════
# 通行判断
# ═══════════════════════════════════════════════════

def can_enter(
    col: int, row: int,
    grid: Grid[Terrain],
    entities: list[tuple["Entity", tuple[int, int]]],
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
    # 阻塞地形（篝火/墙壁/树）不可通行；全身掩体（闭合门为 WALL）也不可通行
    if terrain in BLOCKING_TERRAINS or is_full_cover(terrain):
        return False

    # 实体阻挡（尸体不阻挡，濒死仍阻挡）
    for creature, (ec, er) in entities:
        if (ec, er) == (col, row):
            if creature.is_dead:
                continue
            # 混乱阵营阻挡，守序/中立不阻挡
            if creature.faction == "混乱" or not allow_pass_through:
                return False

    return True


def _terrain_cost(terrain: Terrain) -> int:
    """地形移动代价：普通=10, 困难=20（用于 A* 权重）。"""
    if terrain in DIFFICULT_TERRAINS:
        return 20
    return 10


def _step_cost(
    grid: Grid[Terrain],
    entities: list[tuple["Entity", tuple[int, int]]],
    pos: tuple[int, int],
    player_pos: tuple[int, int] | None = None,
    ground_items: list | None = None,
    occupied_alive: set | None = None,
    dead_positions: set | None = None,
    tile_space_prebuilt: dict | None = None,
    door_positions: set | None = None,
) -> int | None:
    """返回经过该格的代价，None 表示不可达。

    occupied_alive / dead_positions 为预建的坐标集合（find_path 一次预建），
    传入时 O(1) 判断占据，避免逐实体 O(N) 遍历。
    door_positions: 门坐标集合。门是「可被打开」的障碍——寻路时一律视为
    可通行（代价 1），使 A* 能规划穿门路线（走到关闭的门时被自然打断）。
    """
    t = grid[pos[0], pos[1]]
    # 门位置跳过地形阻塞判定（不论 WALL/DOOR 都视作可通行）
    is_door = door_positions is not None and pos in door_positions
    if not is_door and (t in BLOCKING_TERRAINS or is_full_cover(t)):
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
                if c.is_dead:
                    return 3  # 尸体：可通过，代价 3
                else:
                    return None  # 活物（含濒死）：不可达
    if t in DIFFICULT_TERRAINS:
        return 3
    # 物品堆积格（space >= 10）-> 困难地形代价
    # tile_space_prebuilt: find_path 预建的 位置→占用空间 dict（O(1)）；
    # 未预建时回退到逐物品扫描（兼容旧调用方）
    if tile_space_prebuilt is not None:
        if tile_space_prebuilt.get(pos, 0) >= 10:
            return 3
    elif ground_items and tile_space_used(ground_items, pos[0], pos[1]) >= 10:
        return 3
    return 1


# ═══════════════════════════════════════════════════
# A* 寻路
# ═══════════════════════════════════════════════════

def find_path(
    grid: Grid[Terrain],
    entities: list[tuple["Entity", tuple[int, int]]],
    start: tuple[int, int],
    goal: tuple[int, int],
    player_pos: tuple[int, int] | None = None,
    dirs: list[tuple[int, int]] = None,
    ground_items: list | None = None,
    max_radius: int | None = None,
    door_positions: set | None = None,
) -> list[tuple[int, int]] | None:
    """A* 寻路。

    Args:
        player_pos: 玩家位置，NPC 寻路时避免走入该格。
        dirs: 移动方向列表，默认 4 方向。
        ground_items: 地上物品列表，用于判断拥挤格代价。
        max_radius: 搜索半径上限（切比雪夫距离，相对起点）。非 None 时：
            先做连通性预检（半径内 BFS），不可达直接返回 None；
            A* 也不会扩展超出该半径的格子，避免全图搜索。
        door_positions: 门坐标集合。门在寻路中视作可通行（可被打开），
            使 A* 能规划穿门路线；走到关闭的门时被 move_entity 自然打断。

    Returns:
        路径坐标列表（含起点和终点），不可达返回 None。
    """
    if dirs is None:
        dirs = DIRS_4

    _INF = float("inf")

    if start == goal:
        return [start]

    # 预建占据集合，A* 每步 O(1) 判断（O(N) → O(1)）
    occupied_alive = {pos for c, pos in entities if not c.is_dead}
    dead_positions = {pos for c, pos in entities if c.is_dead}
    # 预建物品占用空间索引（位置 → 总占用），A* 每步 O(1) 查表
    tile_space_prebuilt: dict | None = None
    if ground_items:
        tile_space_prebuilt = {}
        for item, gpos in ground_items:
            tile_space_prebuilt[gpos] = tile_space_prebuilt.get(gpos, 0) + item.space * item.count

    def _cost(npos: tuple[int, int]):
        return _step_cost(grid, entities, npos, player_pos, ground_items,
                          occupied_alive, dead_positions, tile_space_prebuilt,
                          door_positions)

    if _cost(goal) is None:
        return None

    w, h = grid.width, grid.height
    sx, sy = start

    # 连通性预检：半径内 BFS 不可达 → 直接返回 None，避免 A* 全图搜索
    if max_radius is not None:
        if not _reachable(grid, entities, start, goal, max_radius, player_pos,
                          dirs, ground_items, occupied_alive, dead_positions,
                          tile_space_prebuilt, door_positions):
            return None

    open_set = []
    heapq.heappush(open_set, (0, start))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}

    # 每格代价缓存：同一格被 4 个邻居方向重复评估时只算一次
    cost_cache: dict[tuple[int, int], int | None] = {}

    def _cached_cost(npos: tuple[int, int]):
        if npos in cost_cache:
            return cost_cache[npos]
        c = _step_cost(grid, entities, npos, player_pos, ground_items,
                       occupied_alive, dead_positions, tile_space_prebuilt,
                       door_positions)
        cost_cache[npos] = c
        return c

    # 热点循环局部绑定（每步万次调用级优化）
    _push, _pop = heapq.heappush, heapq.heappop
    _cost = _cached_cost
    g_get = g_score.get
    gx, gy = goal

    while open_set:
        _, current = _pop(open_set)

        if current == goal:
            # 重建路径
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        cc, cr_ = current
        cur_g = g_score[current]
        for dc, dr in dirs:
            nc, nr = cc + dc, cr_ + dr
            if nc < 0 or nc >= w or nr < 0 or nr >= h:
                continue
            if max_radius is not None and max(abs(nc - sx), abs(nr - sy)) > max_radius:
                continue
            npos = (nc, nr)
            cost = _cost(npos)
            if cost is None:
                continue
            tentative_g = cur_g + cost
            if tentative_g < g_get(npos, _INF):
                came_from[npos] = current
                g_score[npos] = tentative_g
                _push(open_set, (tentative_g + max(abs(gx - nc), abs(gy - nr)), npos))

    return None  # 不可达


def _reachable(
    grid: Grid[Terrain],
    entities: list[tuple["Entity", tuple[int, int]]],
    start: tuple[int, int],
    goal: tuple[int, int],
    max_radius: int,
    player_pos: tuple[int, int] | None,
    dirs: list[tuple[int, int]],
    ground_items: list | None,
    occupied_alive: set,
    dead_positions: set,
    tile_space_prebuilt: dict | None,
    door_positions: set | None = None,
) -> bool:
    """连通性预检：从 start 出发，在 max_radius（切比雪夫）内的 BFS 能否到达 goal。

    复用 find_path 预建的占据/物品集合，逐格调用 _step_cost 判断通行性。
    只回答可达性（bool），不重建路径，避免不可达目标触发全图 A*。
    door_positions: 门坐标集合，传入门格视作可通行（与 _step_cost 一致）。
    """
    from collections import deque

    w, h = grid.width, grid.height
    sx, sy = start
    seen = {start}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        if (cx, cy) == goal:
            return True
        # 到达半径边界：不再向外扩展（goal 本身已在上方判等）
        if max(abs(cx - sx), abs(cy - sy)) >= max_radius:
            continue
        for dc, dr in dirs:
            nx, ny = cx + dc, cy + dr
            if nx < 0 or nx >= w or ny < 0 or ny >= h:
                continue
            npos = (nx, ny)
            if npos in seen:
                continue
            if max(abs(nx - sx), abs(ny - sy)) > max_radius:
                continue
            if _step_cost(grid, entities, npos, player_pos, ground_items,
                          occupied_alive, dead_positions, tile_space_prebuilt,
                          door_positions) is None:
                continue
            seen.add(npos)
            q.append(npos)
    return False
