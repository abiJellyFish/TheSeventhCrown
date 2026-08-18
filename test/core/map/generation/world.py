"""世界地图生成 —— 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。

地图子区域数据从 data/maps/*.json 加载。
"""

import json
import os
import random
from core.game_state import GameState
from core.grid import Grid, PASSABLE_TERRAINS
from core.fov import LightLevel
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

    # 灌木丛（原困难地形）
    for dx, dy in data.get("difficult", []):
        state.map[ox + dx, oy + dy] = Terrain.BUSH

    # 篝火（永久火源，注册光源）
    for fx, fy in data.get("campfires", []):
        pos = (ox + fx, oy + fy)
        state.map[pos] = Terrain.CAMPFIRE
        state.register_light(pos, 3, LightLevel.BRIGHT)

    # 石头（地面物品，可拾取，`o` 渲染）
    for sx, sy in data.get("stones", []):
        pos = (ox + sx, oy + sy)
        from core.trade import resolve_items
        try:
            items = resolve_items([{"name": "石头", "count": 1}])
            if items:
                state.ground_items.append((items[0], pos))
        except ValueError:
            pass

    # 床
    for bx, by in data.get("beds", []):
        state.map[ox + bx, oy + by] = Terrain.BED

    # 椅子（阶段8：每房1个，地面物品）
    for cx, cy in data.get("chairs", []):
        from core.trade import resolve_items
        try:
            items = resolve_items([{"name": "椅子", "count": 1}])
            if items:
                state.ground_items.append((items[0], (ox + cx, oy + cy)))
        except ValueError:
            pass

    # 门（关闭时设为 WALL，开启时设回 DOOR，door_states 记录开关状态）
    for door in data.get("doors", []):
        dpos = door["pos"]
        key = (ox + dpos[0], oy + dpos[1])
        state.door_states[key] = door.get("open", False)
        state.map[key] = Terrain.DOOR if door["open"] else Terrain.WALL

    # 水域（水源）
    for wx, wy in data.get("water", []):
        state.map[ox + wx, oy + wy] = Terrain.WATER

    # 矮墙（3/4掩体）
    for lx, ly in data.get("low_walls", []):
        state.map[ox + lx, oy + ly] = Terrain.LOW_WALL

    # 生物
    for ent in data.get("entities", []):
        c = loader.load_entity(ent["key"])
        if c:
            c.template_name = ent["key"]
            state.add_entity(c, (ox + ent["pos"][0], oy + ent["pos"][1]))

    # 陷阱（阶段5）：布置时同荒地，踩中 1d4 触发一次失效
    for trap in data.get("traps", []):
        tpos = (ox + trap["pos"][0], oy + trap["pos"][1])
        state._add_trap(tpos, trap.get("damage", "1d4"), trap.get("dc", 10))

    # 箱子
    for chest in data.get("chests", []):
        cx = ox + chest["pos"][0]
        cy = oy + chest["pos"][1]
        # 解析箱子内物品（名称引用 → 统一从 data/items 加载）
        from core.trade import resolve_items
        inv = resolve_items(chest.get("inventory", []))
        state.chests[(cx, cy)] = {
            "label": chest.get("label", "箱子"),
            "gp": chest.get("gp", 0),
            "inventory": inv,
        }

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
    state.map = Grid[Terrain](w, h, Terrain.GRASS)
    state.entities = []
    state.door_states = {}
    state.location_map = {}
    random.seed(42)

    # ── 村庄 ──
    village = _load_map_json("village.json")
    _place_zone(state, village, loader)

    # 村庄范围内地面改为荒地（BARREN），永不自然改变
    vo = village["offset"]
    vw, vh = village.get("width", 21), village.get("height", 16)
    for x in range(vo[0], vo[0] + vw):
        for y in range(vo[1], vo[1] + vh):
            if state.map[x, y] in PASSABLE_TERRAINS:
                state.map[x, y] = Terrain.BARREN

    # ── 树林 ──
    zones_data = _load_map_json("world_zones.json")
    forest = zones_data["forest"]
    fx, fy = forest["offset"]
    fw, fh = forest["width"], forest["height"]
    tree_count = forest["tree_count"]
    forest_name = forest["name"]

    # 树木：灌木保持原密度（原 DIFFICULT 数量），树为灌木的 1/10
    for _ in range(tree_count):
        tx = fx + random.randint(0, fw - 1)
        ty = fy + random.randint(0, fh - 1)
        if 0 <= tx < w and 0 <= ty < h and state.map[tx, ty] == Terrain.GRASS:
            state.map[tx, ty] = Terrain.BUSH
    for _ in range(max(1, tree_count // 10)):
        tx = fx + random.randint(0, fw - 1)
        ty = fy + random.randint(0, fh - 1)
        if 0 <= tx < w and 0 <= ty < h and state.map[tx, ty] == Terrain.GRASS:
            state.map[tx, ty] = Terrain.TREE

    # 地下城入口
    entrance = (fx + random.randint(5, fw - 5), fy + random.randint(5, fh - 5))
    state.map[entrance] = Terrain.STAIRS_DOWN

    # 风干的骨头线索（阶段5，D10）：洞口上方 3 格
    clue_pos = (entrance[0], entrance[1] - 3)
    state._add_clue(
        clue_pos,
        label="风干的骨头",
        sight_log="一块风干的骨头。",
        egg_text="骨头散发着幽幽的黑影，似乎想回到它的主人身上",
    )

    for x in range(fx, fx + fw):
        for y in range(fy, fy + fh):
            state.location_map.setdefault((x, y), forest_name)

    # ── 池塘（水源，村庄与树林之间）──
    pond_offset = (35, 25)
    pond_w, pond_h = 4, 3
    for px in range(pond_offset[0], pond_offset[0] + pond_w):
        for py in range(pond_offset[1], pond_offset[1] + pond_h):
            state.map[px, py] = Terrain.WATER

    # 池塘雾气（阶段4：池塘上方 + 邻域，轻度遮蔽；随机稀疏化到约一半）
    for fx in range(pond_offset[0] - 1, pond_offset[0] + pond_w + 1):
        for fy in range(pond_offset[1] - 1, pond_offset[1] + pond_h + 1):
            if 0 <= fx < state.map.width and 0 <= fy < state.map.height:
                if random.random() < 0.5:
                    state.fog_surfaces.add((fx, fy))

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
    MAX_ENTITIES = 30
    for _ in range(creature_count):
        if len(state.entities) >= MAX_ENTITIES:
            break
        key = random.choice(creature_keys)
        c = loader.load_entity(key)
        if c:
            c.template_name = key
            for _ in range(20):
                px = random.randint(0, w - 1)
                py = random.randint(0, h - 1)
                if state.map[px, py] in PASSABLE_TERRAINS and not _in_reserved(px, py):
                    state.add_entity(c, (px, py))
                    break

    # ── 平原灌木 ──
    for _ in range(bush_count):
        for _ in range(20):
            bx = random.randint(0, w - 1)
            by = random.randint(0, h - 1)
            if state.map[bx, by] in PASSABLE_TERRAINS and not _in_reserved(bx, by):
                state.map[bx, by] = Terrain.BUSH
                break

    # ── 平原随机石头（地面物品，可拾取；数量与树木一致 tree_count//10）──
    stone_count = max(1, tree_count // 10)
    for _ in range(stone_count):
        for _ in range(20):
            sx = random.randint(0, w - 1)
            sy = random.randint(0, h - 1)
            if state.map[sx, sy] in PASSABLE_TERRAINS and not _in_reserved(sx, sy):
                from core.trade import resolve_items
                try:
                    items = resolve_items([{"name": "石头", "count": 1}])
                    if items:
                        state.ground_items.append((items[0], (sx, sy)))
                except ValueError:
                    pass
                break

    state.map_exits = []
    state.loot_spots = []
    state.seed_campfires()
    state._seed_twigs()
