"""统一实体可见性规则。

玩家渲染和 AI 感知都通过这里获取观察者视野；区别仅在调用方如何使用结果。
"""

from dataclasses import dataclass

from domain.fov import compute_fov, compute_fov_3d
from domain.grid import Grid


@dataclass(frozen=True)
class VisibilityResult:
    bright: frozenset[tuple[int, int]]
    dim: frozenset[tuple[int, int]]

    @property
    def visible(self) -> frozenset[tuple[int, int]]:
        return self.bright | self.dim


def visible_cells(state, observer) -> VisibilityResult:
    """按实体自身视觉属性计算视野。"""
    origin = state.get_entity_pos(observer)
    if origin is None:
        return VisibilityResult(frozenset(), frozenset())
    effective_range = getattr(observer, "effective_vision_range", observer.vision_range)
    cache_key = (
        id(observer),
        origin,
        observer.facing,
        effective_range,
        observer.darkvision_range,
        getattr(state, "_terrain_version", 0),
        getattr(state, "_light_version", 0),
        getattr(state, "active_z", 0),
    )
    # 先刷新空间索引；地面物品列表可能由旧调用方直接修改，
    # 不能在命中旧可见性缓存后才发现障碍坐标已经变化。
    state.spatial_cache()
    cache = getattr(state, "_visibility_cache", None)
    if cache is None:
        cache = {}
        state._visibility_cache = cache
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    light_map = state._build_light_grid(origin[2])
    transparent = Grid[bool](state.map.width, state.map.height, True)
    blocking_positions = set()
    for col in range(state.map.width):
        for row in range(state.map.height):
            transparent[col, row] = (
                (col, row) not in blocking_positions
            )
    bright, dim = compute_fov(
        transparent,
        origin[:2],
        effective_range,
        light_map,
        observer.darkvision_range > 0,
        observer.darkvision_range,
        facing=observer.facing,
        surface_heights=state._surface_height_grid(),
        origin_z=observer.z,
        height_walls=getattr(state, "dungeon_wall_cells", None),
    )
    result = VisibilityResult(frozenset(bright), frozenset(dim))
    if len(cache) >= 64:
        cache.clear()
    cache[cache_key] = result
    return result


def visible_cells_3d(state, observer) -> set[tuple[int, int, int]]:
    """返回带高度的可见格，并只暴露每个坐标的最高地表。"""
    position = state.get_entity_pos(observer)
    if position is None:
        return set()
    origin = position
    if not getattr(state, "world_layers", None):
        return {(*pos[:2], origin[2]) for pos in visible_cells(state, observer).visible}
    grids = {}
    for z, layer in state.world_layers.items():
        grid = Grid[bool](layer.width, layer.height, False)
        for col in range(layer.width):
            for row in range(layer.height):
                cell = layer.surface((col, row))
                grid[col, row] = cell.exists
        grids[z] = grid
    visible = compute_fov_3d(
        grids, origin, observer.vision_range, facing=observer.facing
    )
    visible_xy = visible_cells(state, observer).visible
    origin_z = origin[2]
    height_walls = getattr(state, "dungeon_wall_cells", None) or set()
    visible = {
        cell for cell in visible
        if cell[:2] in visible_xy
        and not _height_wall_occludes(origin_z, cell[0], cell[1], cell[2], height_walls)
    }
    # 二维视线确认坐标露出后，展开该坐标在球形范围内的阶梯地表。
    # 高度墙本身不进入视野；同一列被高度墙隔开的另一侧也不进入。
    for col, row in visible_xy:
        for z, grid in grids.items():
            if not grid[col, row]:
                continue
            if _height_wall_occludes(origin_z, col, row, z, height_walls):
                continue
            dx, dy, dz = col - origin[0], row - origin[1], z - origin[2]
            if dx * dx + dy * dy + dz * dz <= observer.vision_range ** 2:
                visible.add((col, row, z))
    return visible | {origin}


def _height_wall_occludes(
    origin_z: int, col: int, row: int, z: int,
    height_walls: set[tuple[int, int, int]],
) -> bool:
    if (col, row, z) in height_walls:
        return True
    if origin_z == z:
        return False
    low, high = (origin_z, z) if origin_z <= z else (z, origin_z)
    # 含较高端、不含目标本身：往下看时目标列观察高度上的天花/地表也挡住。
    return any(
        mid != z and (col, row, mid) in height_walls
        for mid in range(low + 1, high + 1)
    )


def can_see(state, observer, target) -> bool:
    """判断目标所在格是否在观察者伪三维视野内。

    与 visible_cells_3d 的成员判定对齐：二维视野（距离/朝向/光照）
    确认坐标露出后，目标高度在球形范围内、该层有地表、且未被高度墙隔开。
    禁止为单点重算完整三维视野。
    """
    observer_pos = state.get_entity_pos(observer)
    target_pos = state.get_entity_pos(target)
    if observer_pos is None or target_pos is None:
        return False
    if len(observer_pos) != 3 or len(target_pos) != 3:
        raise ValueError("实体坐标必须是三维")
    origin = observer_pos
    cell = target_pos
    dx, dy, dz = cell[0] - origin[0], cell[1] - origin[1], cell[2] - origin[2]
    if dx * dx + dy * dy + dz * dz > observer.vision_range * observer.vision_range:
        return False
    if cell[:2] not in visible_cells(state, observer).visible:
        return False
    if not getattr(state, "world_layers", None):
        return cell[2] == origin[2]
    if not state.surface_at(cell[:2], cell[2], create=False).exists:
        return False
    height_walls = getattr(state, "dungeon_wall_cells", None) or set()
    return not _height_wall_occludes(
        origin[2], cell[0], cell[1], cell[2], height_walls
    )
