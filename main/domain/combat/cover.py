"""掩体结算 —— 远程直线攻击沿弹道逐个检查掩体。

掩体 AC: 半身=5, 四分之三=8(预留), 全身=30。
投掷武器走抛物线，无视同高度掩体。
暂定掩体不被破坏、弹药不弹射，命中掩体即终止。

新增掩体类型只需修改 COVER_TABLE，无需改动其他文件。
"""

from domain.grid import Grid, Terrain
from domain.fov import LightLevel
from domain.obstacle import obstacle_info

# 掩体唯一数据源：(AC, 中文标签)。None = 不提供掩体。
COVER_TABLE: dict[Terrain, tuple[int, str] | None] = {
    # 墙壁和关闭的门均为 ground_items，不再由地形提供掩体。
    # 以下无掩体
    Terrain.GRASS:     None,
    Terrain.BARREN:    None,
    Terrain.PLAIN:     None,
    Terrain.FLOOR:     None,
    Terrain.WATER:     None,
    Terrain.STAIRS_DOWN: None,
    Terrain.STAIRS_UP: None,
}


def terrain_cover_info(terrain: Terrain) -> tuple[int, str] | None:
    """查询地形掩体：(AC, 中文标签)，无掩体返回 None。"""
    return COVER_TABLE.get(terrain)


def _terrain_cover_ac(terrain: Terrain) -> int | None:
    """获取地形的掩体 AC。None = 不提供掩体。"""
    info = COVER_TABLE.get(terrain)
    return info[0] if info else None


def resolve_cover_line(
    attack_roll: int,
    attacker: tuple[int, int],
    target: tuple[int, int],
    grid: Grid[Terrain],
    weapon_type: str = "ranged",
    ground_items: list | None = None,
    entities: list | None = None,
) -> tuple[bool, tuple[int, int] | None]:
    """沿弹道逐个结算掩体。

    Args:
        attack_roll: 攻击骰结果
        attacker: 攻击者坐标
        target: 目标坐标
        grid: 地形网格
        weapon_type: "ranged" | "thrown" | "melee"
        ground_items: 地上物品列表，space >= 10 格提供半身掩体

    Returns:
        (是否被掩体阻挡, 阻挡掩体的坐标或 None)
    """
    # 投掷武器无视同高度掩体
    if weapon_type == "thrown":
        return False, None

    # 近战不管掩体
    if weapon_type == "melee":
        return False, None

    # Bresenham 线
    x0, y0 = attacker
    x1, y1 = target
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    # Bresenham 线标准实现：用 for 循环替代 while True，自然防止死循环。
    # 先移动再检查，避免检查起点自身。
    cx, cy = x0, y0
    steps = max(dx, dy)
    first = True  # 攻击者相邻格豁免（阶段4.5）

    for _ in range(steps):
        # 计算下一个像素
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy

        # 到达目标
        if (cx, cy) == (x1, y1):
            return False, None

        # 攻击者相邻格（弹道第一个格）默认不参与掩体判定，但全身掩体（AC≥30）不豁免
        if first:
            first = False
            if not is_full_cover(grid[cx, cy]) and not _has_full_obstacle(
                    (cx, cy), entities, ground_items):
                continue

        # 物品障碍按物品自身覆盖能力结算
        if ground_items:
            for item, item_pos in ground_items:
                if item_pos == (cx, cy) and getattr(item, "is_obstacle", False):
                    if attack_roll <= getattr(item, "block_value", 0):
                        return True, (cx, cy)

        if entities:
            for entity, entity_pos in entities:
                if entity_pos == (cx, cy) and not getattr(entity, "is_dead", False):
                    info = obstacle_info(entity)
                    if info is not None and attack_roll <= info[0]:
                        return True, (cx, cy)

        # 检查当前格掩体
        cover_ac = _terrain_cover_ac(grid[cx, cy])
        if cover_ac is not None:
            if attack_roll <= cover_ac:
                return True, (cx, cy)  # 掩体阻挡（命中骰低于掩体AC）

    return False, None


def is_full_cover(terrain: Terrain) -> bool:
    """地形不再提供全身障碍；全身障碍统一查询对象能力。"""
    return False


def _has_full_obstacle(pos, entities=None, ground_items=None) -> bool:
    for collection in (entities or (), ground_items or ()):
        for obstacle, obstacle_pos in collection:
            if obstacle_pos == pos:
                from domain.obstacle import is_full_obstacle
                if is_full_obstacle(obstacle):
                    return True
    return False


def is_light_cover(state, pos: tuple[int, int], excluded=None) -> bool:
    """该格是否轻度遮蔽（满足隐匿条件并带来远程命中劣势）：
    半身/四分之三掩体（灌木/石头/矮墙）、雾气格、或微光（DIM）光照格。
    统一供隐匿条件与远程命中劣势判定复用。
    """
    info = COVER_TABLE.get(state.map[pos[0], pos[1]])
    if info is not None and 5 <= info[0] <= 8:
        return True
    for collection in (getattr(state, "entities", ()), state.ground_items):
        for obstacle, obstacle_pos in collection:
            if obstacle is excluded:
                continue
            if obstacle_pos == pos and not getattr(obstacle, "is_dead", False):
                obstacle_data = obstacle_info(obstacle)
                if obstacle_data is not None and 5 <= obstacle_data[0] <= 10:
                    return True
    if pos in state.fog_surfaces:
        return True
    lm = state.light_map
    if lm is not None and lm[pos] == LightLevel.DIM:
        return True
    return False
