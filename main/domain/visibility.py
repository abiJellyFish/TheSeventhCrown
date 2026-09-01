"""统一实体可见性规则。

玩家渲染和 AI 感知都通过这里获取观察者视野；区别仅在调用方如何使用结果。
"""

from dataclasses import dataclass

from domain.fov import LightLevel, compute_fov
from domain.grid import Grid
from domain.obstacle import is_full_obstacle


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
    light_map = state.light_map
    if light_map is None:
        # 纯规则/测试状态可能尚未初始化光照；可见性仍应由
        # 距离、朝向和阻挡决定，而不是因缺少渲染缓存全部不可见。
        light_map = Grid[LightLevel](
            state.map.width, state.map.height, LightLevel.BRIGHT
        )
    transparent = Grid[bool](state.map.width, state.map.height, True)
    blocking_positions = set(state.spatial_cache()["blocking_positions"])
    blocking_positions |= {
        position for entity, position in state.iter_entities()
        if not entity.is_dead and is_full_obstacle(entity)
    }
    for col in range(state.map.width):
        for row in range(state.map.height):
            transparent[col, row] = (
                (col, row) not in blocking_positions
            )
    bright, dim = compute_fov(
        transparent,
        origin,
        effective_range,
        light_map,
        observer.darkvision_range > 0,
        observer.darkvision_range,
        facing=observer.facing,
    )
    result = VisibilityResult(frozenset(bright), frozenset(dim))
    if len(cache) >= 64:
        cache.clear()
    cache[cache_key] = result
    return result


def can_see(state, observer, target) -> bool:
    """判断目标所在格是否在观察者视野内。"""
    target_pos = state.get_entity_pos(target)
    return target_pos is not None and target_pos in visible_cells(state, observer).visible
