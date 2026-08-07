"""视野（FOV）与光照 —— 射线投射 + 三级光照。

光照等级:
- BRIGHT: 明亮光照，正常视野
- DIM: 微光光照，可见但感知检定劣势
- DARK: 黑暗，无光源/黑暗视觉时不可见
"""

from enum import Enum, auto
import math

from core.grid import Grid


class LightLevel(Enum):
    DARK = auto()
    DIM = auto()
    BRIGHT = auto()


def _line_of_sight(
    grid: Grid[bool], x0: int, y0: int, x1: int, y1: int
) -> bool:
    """射线检测：从 (x0,y0) 到 (x1,y1) 是否有视线。
    终点格始终可见（墙本身可以看到），但沿途有墙则被阻挡。
    """
    dx = x1 - x0
    dy = y1 - y0
    dist = max(abs(dx), abs(dy))
    if dist == 0:
        return True

    step_x = dx / dist
    step_y = dy / dist

    # 从起点出发，每次移动半个格子检测
    cx, cy = float(x0) + 0.5, float(y0) + 0.5
    for i in range(1, dist + 1):
        cx += step_x
        cy += step_y
        col, row = int(cx), int(cy)
        if (col, row) == (x1, y1):
            return True  # 到达终点，始终可见
        if not grid[col, row]:
            return False  # 中途被墙挡住
    return True


def compute_fov(
    grid: Grid[bool],
    origin: tuple[int, int],
    radius: int,
    light_grid: Grid[LightLevel],
    has_darkvision: bool = False,
    darkvision_range: int = 0,
) -> set[tuple[int, int]]:
    """计算视野内可见格子集合。

    Args:
        grid: 透明/不透明网格 (True=透明, False=阻挡视野)
        origin: 观察者坐标
        radius: 视野半径
        light_grid: 光照等级网格
        has_darkvision: 是否有黑暗视觉
        darkvision_range: 黑暗视觉范围

    Returns:
        可见格子坐标集合
    """
    ox, oy = origin
    if not grid.within_bounds(ox, oy):
        return set()

    cell_light = light_grid[ox, oy]

    # 确定有效视野半径
    if cell_light == LightLevel.DARK:
        if not has_darkvision:
            return set()
        use_radius = darkvision_range
    else:
        use_radius = radius  # BRIGHT or DIM

    visible: set[tuple[int, int]] = {(ox, oy)}

    # 遍历圆形范围内的所有格子
    for col in range(ox - use_radius, ox + use_radius + 1):
        for row in range(oy - use_radius, oy + use_radius + 1):
            if (col, row) == (ox, oy):
                continue
            if not grid.within_bounds(col, row):
                continue
            # 切比雪夫距离检查
            if max(abs(col - ox), abs(row - oy)) > use_radius:
                continue
            if _line_of_sight(grid, ox, oy, col, row):
                visible.add((col, row))

    return visible
