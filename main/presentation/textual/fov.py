"""FOV 与持有光源同步 —— 玩家视野重算与三维光源同步。"""

from domain.fov import LightLevel, compute_fov
from domain.visibility import visible_cells_3d
from domain.game_state import GameState


def _update_fov(state: GameState) -> None:
    if state.controlled_entity is None:
        return
    _sync_torch_light(state)

    transparent = state._get_transparent_grid()
    player = state.controlled_entity
    members = [
        member for member in getattr(state, "party", [player])
        if member is not None and not member.is_dead
    ]
    if player not in members:
        members.insert(0, player)
    positions = {
        id(member): position for member, position in state.entities
    }
    cache_key = (
        state.state_version,
        state.controlled_entity_pos,
        tuple(
            (id(member), positions.get(id(member)), member.facing,
             member.vision_range, member.darkvision_range)
            for member in members
        ),
        state._terrain_version,
        state._light_version,
    )
    if state._fov_cache_key == cache_key:
        return
    state.light_map = state._build_light_grid(player.z)
    bright: set[tuple[int, int]] = set()
    dim: set[tuple[int, int]] = set()
    fov_3d: set[tuple[int, int, int]] = set()
    fov_by_entity: dict[int, set[tuple[int, int, int]]] = {}
    member_bright: dict[int, set[tuple[int, int]]] = {}
    member_dim: dict[int, set[tuple[int, int]]] = {}
    surface_heights = state._surface_height_grid()
    height_walls = getattr(state, "dungeon_wall_cells", None)
    for member in members:
        position = positions.get(id(member))
        if position is None:
            continue
        slice_light = state._build_light_grid(member.z)
        b, d = compute_fov(
            transparent, position[:2], member.vision_range, slice_light,
            member.darkvision_range > 0, member.darkvision_range,
            facing=member.facing,
            surface_heights=surface_heights,
            origin_z=member.z,
            height_walls=height_walls,
        )
        member_bright[id(member)] = b
        member_dim[id(member)] = d
        fov_by_entity[id(member)] = visible_cells_3d(state, member)

    render_ids = {id(player)}
    player_fov = fov_by_entity.get(id(player), set())
    for member in members:
        if member is player:
            continue
        position = positions.get(id(member))
        if position is not None and position in player_fov:
            render_ids.add(id(member))

    for member in members:
        if id(member) not in render_ids:
            continue
        three_d = fov_by_entity[id(member)]
        bright |= member_bright[id(member)] | {(col, row) for col, row, _ in three_d}
        dim |= member_dim[id(member)]
        fov_3d |= three_d
    dim -= bright
    state.fov_bright = bright
    state.fov_dim = dim
    state.fov_cache = fov_3d
    state.fov_by_entity = fov_by_entity
    _report_visible_holes(state, bright | dim)
    state._on_fov_recompute(state.controlled_entity)
    state._maybe_discover_spots(state.controlled_entity)
    state._fov_cache_key = cache_key


def _report_visible_holes(state: GameState, visible_xy: set[tuple[int, int]]) -> None:
    """首次看到当前层向下贯通的空地表时记录洞口提示。"""
    if state.controlled_entity is None:
        return
    map_key = (state.current_map, state.active_z)
    reported = getattr(state, "_reported_holes", set())
    for col, row in visible_xy:
        if state.surface_at((col, row), state.active_z).exists:
            continue
        if not any(
            z < state.active_z and state.surface_at((col, row), z).exists
            for z in state.world_layers
        ):
            continue
        hole_key = (*map_key, col, row)
        if hole_key in reported:
            continue
        reported.add(hole_key)
        state.emit_log("地上有个洞口", position=(col, row, state.active_z))
    state._reported_holes = reported


def _sync_torch_light(state: GameState) -> None:
    """将当前被控实体持有的已点燃光源同步到其三维坐标。"""
    player = state.controlled_entity
    if player is None:
        return
    pos = state.controlled_entity_pos
    if pos is not None and len(pos) == 2:
        pos = (*pos, player.z)
    lit = None
    for item in list(player.equipment.values()) + list(player.inventory):
        if item is None:
            continue
        ls = item.light
        if ls and ls.condition == "lit":
            lit = ls
            break
    old = getattr(state, "_held_light_pos", None)
    if lit is None:
        if old is not None:
            state.unregister_light(old)
            state._held_light_pos = None
        return
    if pos is None:
        raise ValueError("被控实体没有坐标")
    level = LightLevel.BRIGHT if lit.level == "bright" else LightLevel.DIM
    if old is not None and old != pos:
        state.unregister_light(old)
    state.register_light(pos, lit.radius, level)
    state._held_light_pos = pos
