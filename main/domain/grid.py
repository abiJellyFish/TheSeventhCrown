"""泛型网格 Grid[T] —— 矩形二维网格，支持存取、边界检查、4 方向邻居。

坐标统一为 (col, row)。col 向右递增，row 向下递增。
索引越界时 get 返回 None，set 静默忽略。
"""

from enum import Enum, auto
from typing import Generic, TypeVar

T = TypeVar("T")


class Terrain(Enum):
    """地块类型。每种地块直接携带元素属性。"""
    # 可通行（地块材质）
    GRASS = auto()       # 草地：可燃
    BARREN = auto()      # 荒地：不可燃，永不自然改变
    PLAIN = auto()       # 平原：烧尽后，可再生
    FLOOR = auto()       # 石材地面：地下城/建筑内
    STAIRS_DOWN = auto() # 楼梯下：交互进入地下城
    STAIRS_UP = auto()   # 楼梯上：交互返回地面（预留）
    # 困难地形（地图元素）
    WATER = auto()       # 水：潮湿，灭火
    # 地表只表达材质、楼梯和水；地图结构统一由 ground_items 表达。


# 通行分类。植被、石头和矮墙已经是对象能力，不再作为地表分类。
PASSABLE_TERRAINS = {Terrain.GRASS, Terrain.BARREN, Terrain.PLAIN, Terrain.FLOOR,
                     Terrain.STAIRS_DOWN, Terrain.STAIRS_UP}
DIFFICULT_TERRAINS = {Terrain.WATER}

# 元素属性
FLAMMABLE: dict[Terrain, int] = {Terrain.GRASS: 40}
FUEL: dict[Terrain, int] = {
    Terrain.GRASS: 8,    # 草地燃烧 8 钟摆
}
# 烧尽后变成的地块
BURN_OUT_RESULT = {
    Terrain.GRASS: Terrain.PLAIN,
}
# 可再生为的目标（平原 → 草地/灌木）
REGENERABLE_FROM = Terrain.PLAIN
# 永久火源（不熄灭，持续点燃相邻可燃物）
FIRE_SOURCES: set[Terrain] = set()
# 交互地块
INTERACTIVE_TERRAINS = {Terrain.STAIRS_DOWN, Terrain.STAIRS_UP}

# 4 方向偏移：(dc, dr)
DIRS_4 = [          (0, -1),
          (-1,  0),          (1,  0),
                    (0,  1)          ]

# 8 方向偏移：(dc, dr)
DIRS_8 = [(-1, -1), (0, -1), (1, -1),
          (-1,  0),          (1,  0),
          (-1,  1), (0,  1), (1,  1)]


class Grid(Generic[T]):
    """泛型二维网格。"""

    def __init__(self, width: int, height: int, default: T):
        self.width = width
        self.height = height
        self._default = default
        self._cells: list[list[T]] = [
            [default for _ in range(width)] for _ in range(height)
        ]

    # ---- 访问 ----

    def __getitem__(self, key: tuple[int, int]) -> T:
        col, row = key
        if not self.within_bounds(col, row):
            return self._default
        return self._cells[row][col]

    def __setitem__(self, key: tuple[int, int], value: T) -> None:
        col, row = key
        if not self.within_bounds(col, row):
            return
        self._cells[row][col] = value

    def get(self, col: int, row: int) -> T | None:
        """带 None 返回的取值（越界返回 None）。"""
        if not self.within_bounds(col, row):
            return None
        return self._cells[row][col]

    # ---- 边界 ----

    def within_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.width and 0 <= row < self.height

    # ---- 邻居 ----

    def neighbors(self, col: int, row: int) -> list[tuple[int, int]]:
        """返回上下左右四方向中在边界内的邻居坐标列表。"""
        return [
            (col + dc, row + dr)
            for dc, dr in DIRS_4
            if self.within_bounds(col + dc, row + dr)
        ]
