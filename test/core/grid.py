"""泛型网格 Grid[T] —— 矩形二维网格，支持存取、边界检查、8 方向邻居。

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
    BED = auto()         # 床铺：交互休息
    STAIRS_DOWN = auto() # 楼梯下：交互进入地下城
    STAIRS_UP = auto()   # 楼梯上：交互返回地面（预留）
    # 困难地形（地图元素）
    WATER = auto()       # 水：潮湿，灭火
    BUSH = auto()        # 灌木丛：可燃，半身掩体，交互采摘
    STONE = auto()       # 石头：半身掩体
    LOW_WALL = auto()    # 矮墙：3/4掩体
    TREE = auto()        # 树：全身掩体，可燃，阻塞
    # 阻塞
    CAMPFIRE = auto()    # 篝火结构：加载时 seed_campfires 注入燃烧条目（fuel=None），熄灭后保留结构可再点燃，可通行
    DOOR = auto()        # 门：开关切换，关闭时阻塞（关闭时以 WALL 表示）
    WALL = auto()        # 墙壁：全身掩体


# 通行分类
PASSABLE_TERRAINS = {Terrain.GRASS, Terrain.BARREN, Terrain.PLAIN, Terrain.FLOOR,
                     Terrain.BED, Terrain.STAIRS_DOWN, Terrain.STAIRS_UP}
DIFFICULT_TERRAINS = {Terrain.WATER, Terrain.BUSH, Terrain.STONE, Terrain.LOW_WALL}
BLOCKING_TERRAINS = {Terrain.WALL, Terrain.TREE}

# 元素属性
FLAMMABLE: dict[Terrain, int] = {
    Terrain.GRASS: 40,   # 草地蔓延概率 40%
    Terrain.BUSH: 30,    # 灌木蔓延概率 30%
    Terrain.TREE: 3,     # 树蔓延概率 3%（灌木的1/10）
}
FUEL: dict[Terrain, int] = {
    Terrain.GRASS: 8,    # 草地燃烧 8 钟摆
    Terrain.BUSH: 18,    # 灌木燃烧 18 钟摆
    Terrain.TREE: 30,    # 树燃烧 30 钟摆（更持久）
}
# 烧尽后变成的地块
BURN_OUT_RESULT = {
    Terrain.GRASS: Terrain.PLAIN,
    Terrain.BUSH: Terrain.PLAIN,
    Terrain.TREE: Terrain.PLAIN,  # 树烧尽后变平原
}
# 可再生为的目标（平原 → 草地/灌木）
REGENERABLE_FROM = Terrain.PLAIN
# 永久火源（不熄灭，持续点燃相邻可燃物）
FIRE_SOURCES = {Terrain.CAMPFIRE}
# 交互地块
INTERACTIVE_TERRAINS = {Terrain.BUSH, Terrain.BED, Terrain.DOOR,
                        Terrain.STAIRS_DOWN, Terrain.STAIRS_UP}

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
        """返回 8 方向中在边界内的邻居坐标列表。"""
        return [
            (col + dc, row + dr)
            for dc, dr in DIRS_8
            if self.within_bounds(col + dc, row + dr)
        ]
