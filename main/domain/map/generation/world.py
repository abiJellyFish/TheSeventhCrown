"""世界地图生成 —— 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。

地图子区域数据从 data/maps/*.json 加载。
"""

import json
import os
import random
from domain.game_state import GameState
from domain.entity import Entity
from domain.items.item import Item
from domain.obstacle import ObstacleType
from domain.grid import Grid, PASSABLE_TERRAINS
from domain.fov import LightLevel
from domain.movement import Terrain

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "maps")


def _load_map_json(filename: str) -> dict:
    """加载地图 JSON 文件。"""
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _place_zone(state: GameState, data: dict, loader) -> None:
    """根据 JSON 数据放置一个地图子区域。"""
    ox, oy = data["offset"]

    for item_data in data.get("items", []):
        _place_map_item(state, item_data, ox, oy, loader)

    # 水域（水源）
    for wx, wy in data.get("water", []):
        state.map[ox + wx, oy + wy] = Terrain.WATER

    # 生物
    for ent in data.get("entities", []):
        c = loader.load_entity(ent["key"])
        if c is None:
            raise RuntimeError(f"缺少地图实体：{ent['key']}")
        c.template_name = ent["key"]
        state.add_entity(c, (ox + ent["pos"][0], oy + ent["pos"][1]))

    # 陷阱（阶段5）：布置时同荒地，踩中 1d4 触发一次失效
    for trap in data.get("traps", []):
        tpos = (ox + trap["pos"][0], oy + trap["pos"][1])
        state._add_trap(tpos, trap.get("damage", "1d4"), trap.get("dc", 10))

    # 位置名
    name = data.get("location_name", "")
    w = data.get("width", 0)
    h = data.get("height", 0)
    if name and w and h:
        for x in range(ox, ox + w):
            for y in range(oy, oy + h):
                state.location_map.setdefault((x, y), name)
    _validate_layout(state)


def _place_map_item(state: GameState, data: dict, ox: int, oy: int, loader) -> None:
    """按统一 items 配置放置地图物品。"""
    name = data["name"]
    x, y = ox + data["pos"][0], oy + data["pos"][1]
    if name == "墙壁":
        _place_wall(state, x, y)
        return
    if name == "灌木丛":
        _place_plant(state, x, y, name, '"', ObstacleType.HALF)
        return
    if name == "矮墙":
        _place_plant(state, x, y, name, "=", ObstacleType.THREE_QUARTER)
        return
    if name == "门":
        item_name = "打开的门" if data.get("open", False) else "关闭的门"
        item = loader.load_item(item_name)
        if item is None:
            raise RuntimeError(f"缺少地图物品：{item_name}")
        item.door_id = f"{x},{y}"
    else:
        item = loader.load_item(name)
        if item is None:
            raise RuntimeError(f"缺少地图物品：{name}")
    if name == "木箱":
        from domain.trade import resolve_items
        item.chest_data = {
            "label": data.get("label", "箱子"),
            "gp": data.get("gp", 0),
            "inventory": resolve_items(data.get("inventory", [])),
        }
    from domain.item_actions import place_on_ground
    place_on_ground(state.ground_items, item, x, y)
    if name == "篝火":
        state.register_light((x, y), 3, LightLevel.BRIGHT)


def _place_plant(state: GameState, x: int, y: int, name: str,
                 char: str, obstacle_type: ObstacleType) -> None:
    """在干净地表上放置带障碍组件的地图特征物品。"""
    feature = Item(
        name=name, item_type="obstacle", weight=1.0,
        description=f"{name}。",
        durability=25 if name == "树" else 40 if obstacle_type is ObstacleType.HALF else 80,
        max_durability=25 if name == "树" else 40 if obstacle_type is ObstacleType.HALF else 80,
        flammable=name in ("灌木丛", "树"),
        obstacle_type=obstacle_type,
        block_value=5 if obstacle_type is ObstacleType.HALF else 30,
        stack_limit=1, render_char=char,
        render_color="green" if name == "灌木丛" else "rgb(139,90,43)",
        traits=(
            ["bludgeoning_resist", "piercing_resist",
             "fire_vulnerable", "slashing_vulnerable"]
            if name == "树" else
            ["fire_vulnerable"] if name == "灌木丛" else []
        ),
    )
    from domain.item_actions import place_on_ground
    place_on_ground(state.ground_items, feature, x, y)


def _place_wall(state: GameState, x: int, y: int) -> None:
    """放置全身障碍墙壁物品。"""
    feature = Item(
        name="墙壁", item_type="obstacle", weight=0.0,
        description="全身障碍。",
        durability=80, max_durability=80,
        obstacle_type=ObstacleType.FULL, block_value=30,
        stack_limit=1, can_pickup=False,
        render_char="#", render_color="#808080",
    )
    from domain.item_actions import place_on_ground
    place_on_ground(state.ground_items, feature, x, y)


def _ground_position_available(state: GameState, x: int, y: int) -> bool:
    """判断随机地图特征位置是否尚未放置地面物品。"""
    return (
        not any(position == (x, y) for _, position in state.ground_items)
        and not any(position == (x, y) for _, position in state.entities)
    )


def _validate_layout(state: GameState) -> None:
    """验证地图初始化不产生同格物品或实体。"""
    item_positions = [position for _, position in state.ground_items]
    entity_positions = [position for _, position in state.entities]
    if len(item_positions) != len(set(item_positions)):
        duplicates = {
            position for position in item_positions
            if item_positions.count(position) > 1
        }
        raise RuntimeError(f"地图初始化失败：地面物品坐标重叠 {duplicates}")
    if len(entity_positions) != len(set(entity_positions)):
        duplicates = {
            position for position in entity_positions
            if entity_positions.count(position) > 1
        }
        raise RuntimeError(f"地图初始化失败：实体坐标重叠 {duplicates}")
    conflicts = set(item_positions) & set(entity_positions)
    if conflicts:
        details = [
            (
                position,
                [item.name for item, item_pos in state.ground_items
                 if item_pos == position],
                [entity.name for entity, entity_pos in state.entities
                 if entity_pos == position],
            )
            for position in sorted(conflicts)
        ]
        raise RuntimeError(f"地图初始化失败：物品与实体坐标重叠 {details}")


def build_world(state: GameState, loader) -> None:
    """构建 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。"""
    w, h = 80, 60
    state.current_map = "世界"
    state.map = Grid[Terrain](w, h, Terrain.GRASS)
    state.entities = []
    state.ground_items = []
    state.location_map = {}
    state.burning_surfaces.clear()
    state.wet_surfaces.clear()
    state.light_sources.clear()
    state.invalidate_spatial_cache()
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

    # 树木/灌木：地表保持草地，障碍由实体组件提供。
    forest_positions = [
        (x, y)
        for x in range(fx, fx + fw)
        for y in range(fy, fy + fh)
        if state.map[x, y] == Terrain.GRASS
        and _ground_position_available(state, x, y)
    ]
    for _ in range(tree_count):
        if not forest_positions:
            raise RuntimeError("树林灌木没有找到合法空位")
        tx, ty = forest_positions.pop(random.randrange(len(forest_positions)))
        _place_plant(state, tx, ty, "灌木丛", '"', ObstacleType.HALF)

    forest_positions = [
        (x, y)
        for x in range(fx, fx + fw)
        for y in range(fy, fy + fh)
        if state.map[x, y] == Terrain.GRASS
        and _ground_position_available(state, x, y)
    ]
    for _ in range(max(1, tree_count // 10)):
        if not forest_positions:
            raise RuntimeError("树林树木没有找到合法空位")
        tx, ty = forest_positions.pop(random.randrange(len(forest_positions)))
        _place_plant(state, tx, ty, "树", "T", ObstacleType.FULL)

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
    entity_positions = [
        (x, y)
        for x in range(w)
        for y in range(h)
        if state.map[x, y] in PASSABLE_TERRAINS
        and not _in_reserved(x, y)
        and _ground_position_available(state, x, y)
    ]
    for _ in range(creature_count):
        if len(state.entities) >= MAX_ENTITIES:
            break
        key = random.choice(creature_keys)
        c = loader.load_entity(key)
        if c is None:
            raise RuntimeError(f"缺少地图实体：{key}")
        if not entity_positions:
            raise RuntimeError("平原生物没有找到合法空位")
        c.template_name = key
        px, py = entity_positions.pop(random.randrange(len(entity_positions)))
        state.add_entity(c, (px, py))

    # ── 平原灌木 ──
    plains_positions = [
        (x, y)
        for x in range(w)
        for y in range(h)
        if state.map[x, y] in PASSABLE_TERRAINS
        and not _in_reserved(x, y)
        and _ground_position_available(state, x, y)
    ]
    for _ in range(bush_count):
        if not plains_positions:
            raise RuntimeError("平原灌木没有找到合法空位")
        bx, by = plains_positions.pop(random.randrange(len(plains_positions)))
        _place_plant(state, bx, by, "灌木丛", '"', ObstacleType.HALF)

    # ── 平原随机石头（地面物品，可拾取；数量与树木一致 tree_count//10）──
    stone_count = max(1, tree_count // 10)
    plains_positions = [
        (x, y)
        for x in range(w)
        for y in range(h)
        if state.map[x, y] in PASSABLE_TERRAINS
        and not _in_reserved(x, y)
        and _ground_position_available(state, x, y)
    ]
    for _ in range(stone_count):
        if not plains_positions:
            raise RuntimeError("平原石头没有找到合法空位")
        sx, sy = plains_positions.pop(random.randrange(len(plains_positions)))
        from domain.trade import resolve_items
        items = resolve_items([{"name": "石头", "count": 1}])
        if not items:
            raise RuntimeError("缺少地图物品：石头")
        items[0].obstacle_type = ObstacleType.HALF
        items[0].block_value = 5
        items[0].stack_limit = 1
        from domain.item_actions import place_on_ground
        place_on_ground(state.ground_items, items[0], sx, sy)

    state.map_exits = []
    state.loot_spots = []
    state.seed_campfires()
    state._seed_twigs()
