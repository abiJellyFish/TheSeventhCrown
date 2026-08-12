"""地下城地图生成 —— BSP 算法生成房间 + 走廊。"""

import random
from core.game_state import GameState
from core.grid import Grid
from core.movement import Terrain


def build_dungeon(state: GameState, loader) -> None:
    """BSP 生成地下城 (30×20)。"""
    w, h = 30, 20
    state.current_map = "地下城"
    state.in_dungeon = True
    state.map = Grid[Terrain](w, h, Terrain.WALL)
    state.entities = []
    state.bed_positions = set()
    state.door_states = {}
    state.map_exits = []
    state.location_map = {}  # 地下城全部标记为地下城1层

    # 挖掘 3-5 个房间 + 走廊
    rooms = []
    for _ in range(random.randint(3, 5)):
        rw, rh = random.randint(4, 8), random.randint(3, 6)
        rx = random.randint(1, w - rw - 1)
        ry = random.randint(1, h - rh - 1)
        rooms.append((rx, ry, rw, rh))
        for x in range(rx, rx + rw):
            for y in range(ry, ry + rh):
                state.map[x, y] = Terrain.PASSABLE

    # 连接走廊
    for i in range(len(rooms) - 1):
        x1 = rooms[i][0] + rooms[i][2] // 2
        y1 = rooms[i][1] + rooms[i][3] // 2
        x2 = rooms[i + 1][0] + rooms[i + 1][2] // 2
        y2 = rooms[i + 1][1] + rooms[i + 1][3] // 2
        for x in range(min(x1, x2), max(x1, x2) + 1):
            state.map[x, y1] = Terrain.PASSABLE
        for y in range(min(y1, y2), max(y1, y2) + 1):
            state.map[x2, y] = Terrain.PASSABLE

    # 入口和出口
    first_room = rooms[0]
    state.map[first_room[0] + 1, first_room[1]] = Terrain.PASSABLE  # 入口标记
    state.dungeon_entrance = (first_room[0] + 1, first_room[1])
    state.dungeon_exit = (first_room[0] + 1, first_room[1])
    state.player_pos = (first_room[0] + 2, first_room[1] + 1)

    # 红宝石在最后一个房间
    last_room = rooms[-1]
    state.map[last_room[0] + last_room[2] // 2, last_room[1] + last_room[3] // 2] = Terrain.DIFFICULT

    # 骷髅兵
    skeleton_positions = []
    for _ in range(4):
        r = random.choice(rooms[1:])
        sx = r[0] + random.randint(1, r[2] - 1)
        sy = r[1] + random.randint(1, r[3] - 1)
        if (sx, sy) not in skeleton_positions:
            skeleton_positions.append((sx, sy))
            sk = loader.load_creature("skeleton")
            if sk:
                sk.template_name = "skeleton"
                state.add_entity(sk, (sx, sy))
