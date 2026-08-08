"""世界地图生成 —— 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。"""

import random
from core.game_state import GameState
from core.grid import Grid
from core.movement import Terrain


def build_world(state: GameState, loader) -> None:
    """构建 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。"""
    w, h = 80, 60
    state.current_map = "世界"
    state.map = Grid[Terrain](w, h, Terrain.PASSABLE)
    state.entities = []
    random.seed(42)

    # ── 村庄 (20×15, 偏移 3,20) ──
    vx, vy = 3, 20
    village_walls = [
        (2,2),(3,2),(4,2),(5,2),(6,2),(2,3),(6,3),(2,4),(6,4),(2,5),(3,5),(4,5),(5,5),(6,5),
        (9,2),(10,2),(11,2),(12,2),(13,2),(9,3),(13,3),(9,4),(13,4),(9,5),(10,5),(11,5),(12,5),(13,5),
        (20,1),(21,1),(22,1),(23,1),(24,1),(20,2),(24,2),(20,3),(24,3),(20,4),(24,4),(20,5),(21,5),(22,5),(23,5),(24,5),
        (25,8),(26,8),(27,8),(28,8),(25,9),(28,9),(25,10),(28,10),(25,11),(26,11),(27,11),(28,11),
    ]
    for wx, wy in village_walls:
        state.map[vx + wx, vy + wy] = Terrain.WALL
    state.map[vx + 18, vy + 10] = Terrain.DIFFICULT  # 水井

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

    # ── 树林 (30×30, 偏移 35,15, 村庄东 15 格) ──
    fx, fy = 35, 15
    for _ in range(200):
        tx = fx + random.randint(0, 29)
        ty = fy + random.randint(0, 29)
        if 0 <= tx < w and 0 <= ty < h and state.map[tx, ty] == Terrain.PASSABLE:
            state.map[tx, ty] = Terrain.DIFFICULT

    # 地下城入口 > 在树林中
    entrance = (fx + random.randint(5, 25), fy + random.randint(5, 25))
    state.map[entrance] = Terrain.PASSABLE  # 入口可通行
    state.dungeon_entrance = entrance

    # ── 地精营地 (开放式，偏移 68,10, 树林东侧) ──
    gx, gy = 68, 10
    # 断墙/路障 — 不是封闭房子，而是几段不连通的矮墙
    camp_walls = [
        # 北侧路障（有缺口）
        (0,0),(1,0),(2,0),(3,0),(4,0),           (6,0),(7,0),
        # 东侧断墙
        (7,1),(7,2),
        # 西侧路障
        (0,1),(0,2),(0,3),
        # 南侧散落木桩
        (4,5),(5,5),(7,5),
        # 角落杂物堆
        (0,4),(1,4),
    ]
    for wx, wy in camp_walls:
        state.map[gx + wx, gy + wy] = Terrain.WALL
    # 篝火（营地中央）
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

    # ── 平原游荡生物 ──
    # 固定区域：村庄 (3,20)-(23,35) / 树林 (35,15)-(65,45) / 营地 (68,10)-(78,25)
    RESERVED_ZONES = [
        (vx, vy, 21, 16),   # 村庄
        (fx, fy, 30, 30),   # 树林
        (gx, gy, 9, 15),    # 营地
    ]
    def _in_reserved(px: int, py: int) -> bool:
        for rx, ry, rw, rh in RESERVED_ZONES:
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return True
        return False

    creatures = ["bird", "squirrel", "cat", "long_ear_dog", "wild_boar"]
    for _ in range(15):
        key = random.choice(creatures)
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
    for _ in range(60):
        for _ in range(20):
            bx = random.randint(0, w - 1)
            by = random.randint(0, h - 1)
            if state.map[bx, by] == Terrain.PASSABLE and not _in_reserved(bx, by):
                state.map[bx, by] = Terrain.DIFFICULT
                break

    state.map_exits = []
    state.loot_spots = []

    # 位置 → 地名哈希表（O(1) 查询，无分支）
    state.location_map = {}
    for x in range(vx, vx + 21):
        for y in range(vy, vy + 16):
            state.location_map[(x, y)] = "小村庄"
    for x in range(fx, fx + 30):
        for y in range(fy, fy + 30):
            state.location_map.setdefault((x, y), "树林")
    for x in range(gx, gx + 9):
        for y in range(gy, gy + 15):
            state.location_map[(x, y)] = "营地"
