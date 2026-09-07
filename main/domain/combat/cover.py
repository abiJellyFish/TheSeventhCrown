"""掩体结算 —— 远程直线攻击沿弹道逐个检查掩体。

掩体 AC: 半身=5, 四分之三=8(预留), 全身=30。
投掷武器走抛物线，无视同高度掩体。
暂定掩体不被破坏、弹药不弹射，命中掩体即终止。

新增掩体类型只需修改 COVER_TABLE，无需改动其他文件。
"""

from domain.grid import Grid, Terrain
from domain.fov import LightLevel
from domain.obstacle import obstacle_info

# 掩体唯一数据源：(AC, 中文标签)。None = 不提供掩体。
COVER_TABLE: dict[Terrain, tuple[int, str] | None] = {
    # 墙壁和关闭的门均为 ground_items，不再由地形提供掩体。
    # 以下无掩体
    Terrain.GRASS:     None,
    Terrain.BARREN:    None,
    Terrain.PLAIN:     None,
    Terrain.FLOOR:     None,
    Terrain.WATER:     None,
    Terrain.STAIRS_DOWN: None,
    Terrain.STAIRS_UP: None,
}


def terrain_cover_info(terrain: Terrain) -> tuple[int, str] | None:
    """查询地形掩体：(AC, 中文标签)，无掩体返回 None。"""
    return COVER_TABLE.get(terrain)


def _terrain_cover_ac(terrain: Terrain) -> int | None:
    """获取地形的掩体 AC。None = 不提供掩体。"""
    info = COVER_TABLE.get(terrain)
    return info[0] if info else None


def resolve_cover_line(
    attack_roll: int,
    attacker: tuple[int, int],
    target: tuple[int, int],
    grid: Grid[Terrain],
    weapon_type: str = "ranged",
    ground_items: list | None = None,
    entities: list | None = None,
) -> tuple[bool, tuple[int, int] | None]:
    """沿弹道逐个结算掩体。

    Args:
        attack_roll: 攻击骰结果
        attacker: 攻击者坐标
        target: 目标坐标
        grid: 地形网格
        weapon_type: "ranged" | "thrown" | "melee"
        ground_items: 地上物品列表，space >= 10 格提供半身掩体

    Returns:
        (是否被掩体阻挡, 阻挡掩体的坐标或 None)
    """
    # 投掷武器无视同高度掩体
    if weapon_type == "thrown":
        return False, None

    # 近战不管掩体
    if weapon_type == "melee":
        return False, None

    # Bresenham 线（掩体弹道当前按二维地表结算）
    x0, y0 = attacker[:2]
    x1, y1 = target[:2]
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    # Bresenham 线标准实现：用 for 循环替代 while True，自然防止死循环。
    # 先移动再检查，避免检查起点自身。
    cx, cy = x0, y0
    steps = max(dx, dy)
    first = True  # 攻击者相邻格豁免（阶段4.5）

    for _ in range(steps):
        # 计算下一个像素
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy

        # 到达目标
        if (cx, cy) == (x1, y1):
            return False, None

        # 攻击者相邻格（弹道第一个格）默认不参与掩体判定，但全身掩体（AC≥30）不豁免
        if first:
            first = False
            if not is_full_cover(grid[cx, cy]) and not _has_full_obstacle(
                    (cx, cy), entities, ground_items):
                continue

        # 物品障碍按物品自身覆盖能力结算
        if ground_items:
            for item, item_pos in ground_items:
                if item_pos[:2] == (cx, cy) and getattr(item, "is_obstacle", False):
                    if attack_roll <= getattr(item, "block_value", 0):
                        return True, (cx, cy)

        if entities:
            for entity, entity_pos in entities:
                if entity_pos[:2] == (cx, cy) and not getattr(entity, "is_dead", False):
                    info = obstacle_info(entity)
                    if info is not None and attack_roll <= info[0]:
                        return True, (cx, cy)

        # 检查当前格掩体
        cover_ac = _terrain_cover_ac(grid[cx, cy])
        if cover_ac is not None:
            if attack_roll <= cover_ac:
                return True, (cx, cy)  # 掩体阻挡（命中骰低于掩体AC）

    return False, None


def is_full_cover(terrain: Terrain) -> bool:
    """地形不再提供全身障碍；全身障碍统一查询对象能力。"""
    return False


def _has_full_obstacle(pos, entities=None, ground_items=None) -> bool:
    for collection in (entities or (), ground_items or ()):
        for obstacle, obstacle_pos in collection:
            if obstacle_pos[:2] == pos:
                from domain.obstacle import is_full_obstacle
                if is_full_obstacle(obstacle):
                    return True
    return False


def is_light_cover(state, pos: tuple[int, int], excluded=None) -> bool:
    """该格是否轻度遮蔽（满足隐匿条件并带来远程命中劣势）：
    半身/四分之三掩体（灌木/石头/矮墙）、雾气格、或微光（DIM）光照格。
    统一供隐匿条件与远程命中劣势判定复用。
    """
    pos = tuple(pos[:2])
    info = COVER_TABLE.get(state.map[pos[0], pos[1]])
    if info is not None and 5 <= info[0] <= 8:
        return True
    for collection in (getattr(state, "entities", ()), state.ground_items):
        for obstacle, obstacle_pos in collection:
            if obstacle is excluded:
                continue
            if obstacle_pos[:2] == pos and not getattr(obstacle, "is_dead", False):
                obstacle_data = obstacle_info(obstacle)
                if obstacle_data is not None and 5 <= obstacle_data[0] <= 10:
                    return True
    if pos in state.fog_surfaces:
        return True
    lm = state.light_map
    if lm is not None and lm[pos] == LightLevel.DIM:
        return True
    return False


HEIGHT_WALL = object()


def _xyz(position) -> tuple[int, int, int]:
    if len(position) == 3:
        return int(position[0]), int(position[1]), int(position[2])
    return int(position[0]), int(position[1]), 0


def line_cells_between(origin, dest) -> list[tuple[int, int, int]]:
    """从 origin 走到 dest 的中间格，不含两端。"""
    x0, y0, z0 = _xyz(origin)
    x1, y1, z1 = _xyz(dest)
    if (x0, y0, z0) == (x1, y1, z1):
        return []
    dx, dy, dz = abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)
    sx = 1 if x1 >= x0 else -1
    sy = 1 if y1 >= y0 else -1
    sz = 1 if z1 >= z0 else -1
    cells = []
    if dx >= dy and dx >= dz:
        err_y = err_z = dx // 2
        x, y, z = x0, y0, z0
        while x != x1:
            x += sx
            err_y += dy
            err_z += dz
            if err_y >= dx:
                y += sy
                err_y -= dx
            if err_z >= dx:
                z += sz
                err_z -= dx
            if (x, y, z) != (x1, y1, z1):
                cells.append((x, y, z))
        return cells
    if dy >= dz:
        err_x = err_z = dy // 2
        x, y, z = x0, y0, z0
        while y != y1:
            y += sy
            err_x += dx
            err_z += dz
            if err_x >= dy:
                x += sx
                err_x -= dy
            if err_z >= dy:
                z += sz
                err_z -= dy
            if (x, y, z) != (x1, y1, z1):
                cells.append((x, y, z))
        return cells
    err_x = err_y = dz // 2
    x, y, z = x0, y0, z0
    while z != z1:
        z += sz
        err_x += dx
        err_y += dy
        if err_x >= dz:
            x += sx
            err_x -= dz
        if err_y >= dz:
            y += sy
            err_y -= dz
        if (x, y, z) != (x1, y1, z1):
            cells.append((x, y, z))
    return cells


def _is_ignored(creature, ignore) -> bool:
    return any(creature is skipped for skipped in ignore)


def hard_blocker_at(state, cell, ignore=()) -> object | None:
    """活体实体或高度墙。全身障碍不当硬挡。"""
    col, row, layer = _xyz(cell)
    for creature, position in getattr(state, "entities", ()):
        if _is_ignored(creature, ignore) or getattr(creature, "is_dead", False):
            continue
        pos = _xyz(position)
        if pos == (col, row, layer):
            return creature
    if state.is_height_wall((col, row), layer):
        return HEIGHT_WALL
    return None


def existing_surface_cell(state, cell) -> tuple[int, int, int] | None:
    """该三维格是否有真实存在的地表。"""
    if cell is None:
        return None
    col, row, layer = _xyz(cell)
    if state.surface_at((col, row), layer, create=False).exists:
        return (col, row, layer)
    return None


def surface_for_height_wall(state, wall_cell) -> tuple[int, int, int]:
    """高度墙只是体积概念，伤害落到挡住该体积的真实地表。正负层同一规则。

    本层登记为实心则优先本层；被更高地表填实则落到更高层。
    """
    col, row, layer = _xyz(wall_cell)
    walls = getattr(state, "dungeon_wall_cells", set()) or set()
    higher = sorted(level for level in state.world_layers if level > layer)
    lower = sorted(
        (level for level in state.world_layers if level < layer), reverse=True
    )

    def first_existing(levels):
        for level in levels:
            if state.surface_at((col, row), level, create=False).exists:
                return (col, row, level)
        return None

    if (col, row, layer) in walls:
        found = existing_surface_cell(state, (col, row, layer))
        if found is not None:
            return found
        found = first_existing(higher) or first_existing(lower)
    else:
        found = (
            first_existing(higher)
            or existing_surface_cell(state, (col, row, layer))
            or first_existing(lower)
        )
    if found is not None:
        return found
    raise RuntimeError(f"高度墙没有对应地表: {(col, row, layer)}")


def attack_surface_cell(state, cell) -> tuple[int, int, int] | None:
    """攻击该格时真正扣耐久的地表；高度墙落到阻挡源。"""
    if cell is None:
        return None
    col, row, layer = _xyz(cell)
    if state.is_height_wall((col, row), layer):
        return surface_for_height_wall(state, (col, row, layer))
    return existing_surface_cell(state, cell)


def first_hard_blocker(state, origin, dest, ignore=()):
    """弹道中间第一块硬挡：(坐标, 实体或 HEIGHT_WALL)。无则 None。"""
    for cell in line_cells_between(origin, dest):
        found = hard_blocker_at(state, cell, ignore)
        if found is not None:
            return cell, found
    dest_xyz = _xyz(dest)
    if state.is_height_wall(dest_xyz[:2], dest_xyz[2]):
        return dest_xyz, HEIGHT_WALL
    return None


def redirect_blocked_shape(state, origin, cells, shape, ignore=()):
    """任意格被硬挡则整块改打最近阻挡物及原形状周边。未被挡则原样返回。"""
    from domain.combat.shape import shape_cells
    ox, oy, oz = _xyz(origin)
    nearest = None
    nearest_pos = None
    nearest_dist = None
    for cell in cells:
        found = first_hard_blocker(state, origin, cell, ignore)
        if found is None:
            continue
        pos, blocker = found
        dist = max(abs(pos[0] - ox), abs(pos[1] - oy), abs(pos[2] - oz))
        if nearest_dist is None or dist < nearest_dist:
            nearest, nearest_pos, nearest_dist = blocker, pos, dist
    if nearest is None:
        return list(cells), None, None
    if nearest is HEIGHT_WALL:
        nearest_pos = surface_for_height_wall(state, nearest_pos)
    return shape_cells(nearest_pos, shape), nearest, nearest_pos

