"""地下城分层生成 —— 作为世界地图的负高度层。"""

import random

from domain.game_state import GameState
from domain.item_actions import place_on_ground
from domain.layers import LayerMap, SurfaceCell
from domain.movement import Terrain
from domain.trade import load_item


def build_dungeon_layers(
    state: GameState, loader, entrance: tuple[int, int]
) -> None:
    """在现有世界地图下生成地下城，不切换地图容器。"""
    width, height = state.map.width, state.map.height
    state.world_layers[-1] = LayerMap(
        width, height, Terrain.BARREN, exists=True
    )
    # -2 层初始为空心，只在地牢房间/走廊处创建地表。
    state.world_layers[-2] = LayerMap(
        width, height, Terrain.BARREN, exists=False
    )
    state.world_layers[-1].surface(entrance).exists = False

    dungeon_width = min(30, width - 2)
    dungeon_height = min(20, height - 2)
    origin_x = max(1, min(entrance[0] - dungeon_width // 2, width - dungeon_width - 1))
    origin_y = max(1, min(entrance[1] - dungeon_height // 2, height - dungeon_height - 1))
    bounds = (origin_x, origin_y, dungeon_width, dungeon_height)
    rooms = _carve_rooms(state, bounds, entrance)
    _carve_entrance(state, entrance)
    state.dungeon_wall_cells = {
        (col, row, -1)
        for col in range(state.map.width)
        for row in range(state.map.height)
        if (col, row) != entrance
    } | {
        (col, row, -2)
        for col in range(width)
        for row in range(height)
        if state.world_layers[-2].surface((col, row)).terrain is not Terrain.FLOOR
    }
    _place_dungeon_contents(state, loader, rooms, entrance)


def build_dungeon(state: GameState, loader) -> None:
    """兼容旧调用方：以当前玩家坐标作为地下城入口生成分层区域。"""
    position = state.controlled_entity_pos or (0, 0, 0)
    build_dungeon_layers(state, loader, position[:2])


def _carve_rooms(state: GameState, bounds: tuple[int, int, int, int],
                 entrance: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    ox, oy, width, height = bounds
    rooms: list[tuple[int, int, int, int]] = []
    # 第一个房间以入口为中心，确保从入口下来后落在地下城空间内。
    first_width = min(6, width - 2)
    first_height = min(5, height - 2)
    first_x = max(ox + 1, min(entrance[0] - first_width // 2,
                               ox + width - first_width - 1))
    first_y = max(oy + 1, min(entrance[1] - first_height // 2,
                               oy + height - first_height - 1))
    first_room = (first_x, first_y, first_width, first_height)
    rooms.append(first_room)
    _fill_floor(state, first_x, first_y, first_width, first_height)

    for _ in range(random.randint(3, 5)):
        room_width = random.randint(4, 8)
        room_height = random.randint(3, 6)
        room_x = random.randint(ox, ox + width - room_width)
        room_y = random.randint(oy, oy + height - room_height)
        room = (room_x, room_y, room_width, room_height)
        rooms.append(room)
        _fill_floor(state, room_x, room_y, room_width, room_height)

    for first, second in zip(rooms, rooms[1:]):
        x1 = first[0] + first[2] // 2
        y1 = first[1] + first[3] // 2
        x2 = second[0] + second[2] // 2
        y2 = second[1] + second[3] // 2
        for x in range(min(x1, x2), max(x1, x2) + 1):
            _set_floor(state, x, y1)
        for y in range(min(y1, y2), max(y1, y2) + 1):
            _set_floor(state, x2, y)
    return rooms


def _fill_wall_layers(
    state: GameState,
    bounds: tuple[int, int, int, int],
    entrance: tuple[int, int],
) -> None:
    """建立负一、负二层实心墙层，后续再挖出负二层地下城区域。"""
    state.dungeon_bounds = bounds


def _fill_floor(state: GameState, x: int, y: int, width: int, height: int) -> None:
    for col in range(x, x + width):
        for row in range(y, y + height):
            _set_floor(state, col, row)


def _set_floor(state: GameState, col: int, row: int) -> None:
    state.world_layers[-2].set_surface(
        (col, row), SurfaceCell(Terrain.FLOOR)
    )


def _carve_entrance(state: GameState, entrance: tuple[int, int]) -> None:
    """让两个入口层保持同一垂直洞口，确保可连续向下攀爬。"""
    col, row = entrance
    state.world_layers[0].surface((col, row)).exists = False
    state.world_layers[-1].surface((col, row)).exists = False
    _set_floor(state, col, row)


def _place_dungeon_contents(
    state: GameState,
    loader,
    rooms: list[tuple[int, int, int, int]],
    entrance: tuple[int, int],
) -> None:
    if not rooms:
        return
    used_positions: set[tuple[int, int]] = set()
    for _ in range(4):
        for _ in range(200):
            room = random.choice(rooms)
            position = (
                random.randint(room[0], room[0] + room[2] - 1),
                random.randint(room[1], room[1] + room[3] - 1),
            )
            if position != entrance and position not in used_positions:
                break
        else:
            continue
        used_positions.add(position)
        skeleton = loader.load_entity("骷髅")
        if skeleton is not None:
            skeleton.template_name = "骷髅"
            state.add_entity(skeleton, (*position, -2))

    room = rooms[-1]
    candidates = [
        (col, row)
        for col in range(room[0], room[0] + room[2])
        for row in range(room[1], room[1] + room[3])
        if (col, row) != entrance and (col, row) not in used_positions
    ]
    ruby = load_item("麦斯神像的红宝石")
    if ruby is not None and candidates:
        ruby_position = random.choice(candidates)
        used_positions.add(ruby_position)
        place_on_ground(state.ground_items, ruby, *ruby_position, -2)
