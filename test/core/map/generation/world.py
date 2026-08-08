"""世界地图生成 —— 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。

地图子区域数据从 data/maps/*.json 加载。
"""

import json
import os
import random
from core.game_state import GameState
from core.grid import Grid
from core.movement import Terrain

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "maps")


def _load_map_json(filename: str) -> dict:
    """加载地图 JSON 文件。"""
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _place_zone(state: GameState, data: dict, loader) -> None:
    """根据 JSON 数据放置一个地图子区域。"""
    ox, oy = data["offset"]

    # 墙壁
    for wx, wy in data.get("walls", []):
        state.map[ox + wx, oy + wy] = Terrain.WALL

    # 困难地形
    for dx, dy in data.get("difficult", []):
        state.map[ox + dx, oy + dy] = Terrain.DIFFICULT

    # 篝火
    for fx, fy in data.get("campfires", []):
        state.campfire_positions.add((ox + fx, oy + fy))

    # 床
    for bx, by in data.get("beds", []):
        state.bed_positions.add((ox + bx, oy + by))

    # 门
    for door in data.get("doors", []):
        dpos = door["pos"]
        key = (ox + dpos[0], oy + dpos[1])
        state.door_states[key] = door.get("open", False)
        if not door["open"]:
            state.map[key] = Terrain.WALL

    # 生物
    for ent in data.get("entities", []):
        c = loader.load_creature(ent["key"])
        if c:
            c.template_name = ent["key"]
            state.add_entity(c, (ox + ent["pos"][0], oy + ent["pos"][1]))

    # 位置名
    name = data.get("location_name", "")
    w = data.get("width", 0)
    h = data.get("height", 0)
    if name and w and h:
        for x in range(ox, ox + w):
            for y in range(oy, oy + h):
                state.location_map.setdefault((x, y), name)


def build_world(state: GameState, loader) -> None:
    """构建 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。"""
    w, h = 80, 60
    state.current_map = "世界"
    state.map = Grid[Terrain](w, h, Terrain.PASSABLE)
    state.entities = []
    state.bed_positions = set()
    state.campfire_positions = set()
    state.door_states = {}
    state.location_map = {}
    random.seed(42)

    # ── 村庄 ──
    village = _load_map_json("village.json")
    _place_zone(state, village, loader)

    # ── 树林 ──
    zones_data = _load_map_json("world_zones.json")
    forest = zones_data["forest"]
    fx, fy = forest["offset"]
    fw, fh = forest["width"], forest["height"]
    tree_count = forest["tree_count"]
    forest_name = forest["name"]

    for _ in range(tree_count):
        tx = fx + random.randint(0, fw - 1)
        ty = fy + random.randint(0, fh - 1)
        if 0 <= tx < w and 0 <= ty < h and state.map[tx, ty] == Terrain.PASSABLE:
            state.map[tx, ty] = Terrain.DIFFICULT

    # 地下城入口
    entrance = (fx + random.randint(5, fw - 5), fy + random.randint(5, fh - 5))
    state.map[entrance] = Terrain.PASSABLE
    state.dungeon_entrance = entrance

    for x in range(fx, fx + fw):
        for y in range(fy, fy + fh):
            state.location_map.setdefault((x, y), forest_name)

    # ── 地精营地 ──
    camp = _load_map_json("goblin_camp.json")
    _place_zone(state, camp, loader)

    # ── 平原游荡生物 ──
    plains = zones_data["plains"]
    creature_keys = plains["creatures"]
    creature_count = plains["creature_count"]
    bush_count = plains["bush_count"]

    # 固定区域
    vo = village["offset"]
    vw, vh = village.get("width", 21), village.get("height", 16)
    co = camp["offset"]
    cw, ch = camp.get("width", 9), camp.get("height", 15)
    RESERVED_ZONES = [
        (vo[0], vo[1], vw, vh),
        (fx, fy, fw, fh),
        (co[0], co[1], cw, ch),
    ]

    def _in_reserved(px: int, py: int) -> bool:
        for rx, ry, rw, rh in RESERVED_ZONES:
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return True
        return False

    # 实体数量上限（不含玩家），防止地图生物过多
    MAX_ENTITIES = 20
    for _ in range(creature_count):
        if len(state.entities) >= MAX_ENTITIES:
            break
        key = random.choice(creature_keys)
        c = loader.load_creature(key)
        if c:
            c.template_name = key
            for _ in range(20):
                px = random.randint(0, w - 1)
                py = random.randint(0, h - 1)
                if state.map[px, py] == Terrain.PASSABLE and not _in_reserved(px, py):
                    state.add_entity(c, (px, py))
                    break

    # ── 平原灌木 ──
    for _ in range(bush_count):
        for _ in range(20):
            bx = random.randint(0, w - 1)
            by = random.randint(0, h - 1)
            if state.map[bx, by] == Terrain.PASSABLE and not _in_reserved(bx, by):
                state.map[bx, by] = Terrain.DIFFICULT
                break

    state.map_exits = []
    state.loot_spots = []
