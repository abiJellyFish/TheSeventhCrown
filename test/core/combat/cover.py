"""掩体结算 —— 远程直线攻击沿弹道逐个检查掩体。

掩体 AC: 半身=5, 四分之三=8, 全身=阻挡。
投掷武器走抛物线，无视同高度掩体。
暂定掩体不被破坏、弹药不弹射，命中掩体即终止。
"""

from core.grid import Grid
from core.movement import Terrain

# 掩体 AC 映射
COVER_AC = {
    Terrain.WALL: None,          # 全身 → 直接阻挡
    Terrain.DIFFICULT: None,     # 困难地形不提供掩体（除非是矮墙/灌木丛）
    Terrain.PASSABLE: None,      # 无掩体
}

# 需要更精确的映射——用字符串标记掩体等级会更简单
# 但实际上我们在 resolve_cover_line 中用 Terrain 直接判断


def _terrain_cover_ac(terrain: Terrain) -> int | None:
    """获取地形的掩体 AC。None = 不提供掩体, 0 = 全身阻挡。"""
    if terrain == Terrain.WALL:
        return 0  # 全身阻挡
    # 矮墙和灌木丛都使用 DIFFICULT 类型，但掩体等级不同
    # 目前简化：DIFFICULT 地形默认视为半身掩体(AC 5)
    if terrain == Terrain.DIFFICULT:
        return 5  # 半身掩体
    return None  # 无掩体


def resolve_cover_line(
    attack_roll: int,
    attacker: tuple[int, int],
    target: tuple[int, int],
    grid: Grid[Terrain],
    weapon_type: str = "ranged",
) -> tuple[bool, tuple[int, int] | None]:
    """沿弹道逐个结算掩体。

    Args:
        attack_roll: 攻击骰结果
        attacker: 攻击者坐标
        target: 目标坐标
        grid: 地形网格
        weapon_type: "ranged" | "thrown" | "melee"

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

        # 检查当前格掩体
        cover_ac = _terrain_cover_ac(grid[cx, cy])
        if cover_ac is not None:
            if cover_ac == 0:
                return True, (cx, cy)  # 全身阻挡（AC0 无法穿透）
            if attack_roll < cover_ac:
                return True, (cx, cy)  # 掩体阻挡（命中骰低于掩体AC）

    return False, None
