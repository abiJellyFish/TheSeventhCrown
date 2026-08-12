"""泛型网格 Grid[T] —— 矩形二维网格，支持存取、边界检查、8 方向邻居。

坐标统一为 (col, row)。col 向右递增，row 向下递增。
索引越界时 get 返回 None，set 静默忽略。
"""

from enum import Enum, auto
from typing import Generic, TypeVar

T = TypeVar("T")


class Terrain(Enum):
    """地形类型。"""
    PASSABLE = auto()
    DIFFICULT = auto()
    WALL = auto()

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
