"""世界地图生成 —— 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。

地图子区域数据（墙壁/NPC/床/门坐标）从 data/maps/*.json 加载，
加载失败时 fallback 到硬编码默认值。
"""

import json
import os
import random
from core.game_state import GameState
from core.grid import Grid
from core.movement import Terrain

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "maps")


def _load_json(filename: str) -> dict:
    """加载地图 JSON 文件，不存在则返回空 dict。"""
    path = os.path.join(_DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _place_zone(state: GameState, data: dict, loader) -> None:
    """根据 JSON 数据放置一个地图子区域。"""
    ox, oy = data.get("offset", [0, 0])

    # 墙壁
    for wx, wy in data.get("walls", []):
        state.map[ox + wx, oy + wy] = Terrain.WALL

    # 困难地形
    for dx, dy in data.get("difficult", []):
        state.map[ox + dx, oy + dy] = Terrain.DIFFICULT

    # 床
    for bx, by in data.get("beds", []):
        state.bed_positions.add((ox + bx, oy + by))

    # 门
    for door in data.get("doors", []):
        dpos = door["pos"]
        key = (ox + dpos[0], oy + dpos[1])
        state.door_states[key] = door.get("open", False)
        if not door.get("open", False):
            state.map[key] = Terrain.WALL

    # 生物
    for ent in data.get("entities", []):
        c = loader.load_creature(ent["key"])
        if c:
            c.template_name = ent["key"]
            state.add_entity(c, (ox + ent["pos"][0], oy + ent["pos"][1]))

    # 位置名
    name = data.get("location_name", "")
    if name and data.get("width") and data.get("height"):
        w = data["width"]
        h = data["height"]
        for x in range(ox, ox + w):
            for y in range(oy, oy + h):
                state.location_map.setdefault((x, y), name)


def build_world(state: GameState, loader) -> None:
    """构建 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。

    子区域数据优先从 data/maps/*.json 读取，加载失败时使用硬编码默认值。
    """
    w, h = 80, 60
    state.current_map = "世界"
    state.map = Grid[Terrain](w, h, Terrain.PASSABLE)
    state.entities = []
    state.bed_positions = set()
    state.door_states = {}
    state.location_map = {}
    random.seed(42)

    # ── 村庄 ──
    village = _load_json("village.json")
    if village:
        _place_zone(state, village, loader)
    else:
        _build_village_fallback(state, loader)

    # ── 树林 ──
    zones_data = _load_json("world_zones.json")
    forest = zones_data.get("forest", {}) if zones_data else {}
    fx, fy = forest.get("offset", [35, 15])
    fw, fh = forest.get("width", 30), forest.get("height", 30)
    tree_count = forest.get("tree_count", 200)
    forest_name = forest.get("name", "树林")

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
    camp = _load_json("goblin_camp.json")
    if camp:
        _place_zone(state, camp, loader)
    else:
        _build_camp_fallback(state, loader)

    # ── 平原游荡生物 ──
    plains = zones_data.get("plains", {}) if zones_data else {}
    creature_keys = plains.get("creatures", ["bird", "squirrel", "cat", "long_ear_dog", "wild_boar"])
    creature_count = plains.get("creature_count", 15)
    bush_count = plains.get("bush_count", 60)

    # 固定区域（村庄 + 树林 + 营地）
    vo = village.get("offset", [3, 20]) if village else [3, 20]
    vw, vh = village.get("width", 21), village.get("height", 16)
    co = camp.get("offset", [68, 10]) if camp else [68, 10]
    cw, ch = camp.get("width", 9), camp.get("height", 15)
    RESERVED_ZONES = [
        (vo[0], vo[1], vw, vh),         # 村庄
        (fx, fy, fw, fh),               # 树林
        (co[0], co[1], cw, ch),         # 营地
    ]

    def _in_reserved(px: int, py: int) -> bool:
        for rx, ry, rw, rh in RESERVED_ZONES:
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return True
        return False

    for _ in range(creature_count):
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


# ── 硬编码 fallback（JSON 加载失败时使用）──

def _build_village_fallback(state: GameState, loader) -> None:
    """村庄 fallback — 直接在 (3,20) 偏移硬编码。"""
    vx, vy = 3, 20
    village_walls = [
        (2,2),(3,2),(4,2),(5,2),(6,2),(2,3),(6,3),(2,4),(6,4),(2,5),(3,5),(4,5),(5,5),(6,5),
        (9,2),(10,2),(11,2),(12,2),(13,2),(9,3),(13,3),(9,4),(13,4),(9,5),(10,5),(11,5),(12,5),(13,5),
        (20,1),(21,1),(22,1),(23,1),(24,1),(20,2),(24,2),(20,3),(24,3),(20,4),(24,4),(20,5),(21,5),(22,5),(23,5),(24,5),
        (25,8),(26,8),(27,8),(28,8),(25,9),(28,9),(25,10),(28,10),(25,11),(26,11),(27,11),(28,11),
    ]
    for wx, wy in village_walls:
        state.map[vx + wx, vy + wy] = Terrain.WALL
    state.map[vx + 18, vy + 10] = Terrain.DIFFICULT

    state.bed_positions = {(vx + 4, vy + 4), (vx + 11, vy + 4), (vx + 22, vy + 3), (vx + 26, vy + 9)}
    state.door_states = {
        (vx + 4, vy + 5): False, (vx + 11, vy + 5): False,
        (vx + 22, vy + 4): False, (vx + 26, vy + 11): False,
    }
    for pos, is_open in state.door_states.items():
        if not is_open:
            state.map[pos] = Terrain.WALL

    village_npcs = [
        ("village_elder", vx + 3, vy + 7), ("merchant", vx + 11, vy + 7),
        ("villager", vx + 7, vy + 8), ("villager", vx + 14, vy + 5),
        ("villager", vx + 4, vy + 10), ("villager", vx + 15, vy + 8),
        ("villager", vx + 22, vy + 7),
    ]
    for key, cx, cy in village_npcs:
        c = loader.load_creature(key)
        if c:
            c.template_name = key
            state.add_entity(c, (cx, cy))

    for x in range(vx, vx + 21):
        for y in range(vy, vy + 16):
            state.location_map[(x, y)] = "小村庄"


def _build_camp_fallback(state: GameState, loader) -> None:
    """地精营地 fallback — 直接在 (68,10) 偏移硬编码。"""
    gx, gy = 68, 10
    camp_walls = [
        (0,0),(1,0),(2,0),(3,0),(4,0),           (6,0),(7,0),
        (7,1),(7,2),
        (0,1),(0,2),(0,3),
        (4,5),(5,5),(7,5),
        (0,4),(1,4),
    ]
    for wx, wy in camp_walls:
        state.map[gx + wx, gy + wy] = Terrain.WALL
    state.map[gx + 3, gy + 3] = Terrain.DIFFICULT

    camp_enemies = [
        ("goblin_brawler", gx + 2, gy + 2), ("goblin_brawler", gx + 5, gy + 1),
        ("goblin_brawler", gx + 6, gy + 3), ("goblin_brawler", gx + 1, gy + 4),
        ("long_ear_dog", gx + 4, gy + 1), ("long_ear_dog", gx + 5, gy + 4),
        ("long_ear_dog", gx + 2, gy + 3),
    ]
    for key, cx, cy in camp_enemies:
        c = loader.load_creature(key)
        if c:
            c.template_name = key
            state.add_entity(c, (cx, cy))

    for x in range(gx, gx + 9):
        for y in range(gy, gy + 15):
            state.location_map[(x, y)] = "营地"
