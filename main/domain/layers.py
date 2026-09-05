"""分层二维地表模型。"""

from dataclasses import dataclass

from domain.grid import Grid, Terrain


@dataclass
class SurfaceCell:
    """单个高度层地表；不存在状态与荒地材质明确分离。"""

    terrain: Terrain = Terrain.BARREN
    exists: bool = True
    durability: int = 300
    max_durability: int = 300

    def apply_damage(self, amount: int) -> int:
        self.durability = max(0, self.durability - max(0, int(amount)))
        if self.durability == 0:
            self.exists = False
        return self.durability

    def current_durability(self) -> int:
        return self.durability

    def is_destroyed(self) -> bool:
        return not self.exists


class LayerMap:
    """固定尺寸的二维地表层。"""

    def __init__(
        self, width: int, height: int, terrain: Terrain = Terrain.BARREN,
        exists: bool = True,
    ):
        self.width = width
        self.height = height
        self.grid = Grid[SurfaceCell](
            width, height, SurfaceCell(terrain=terrain, exists=exists)
        )
        for row in range(height):
            for col in range(width):
                self.grid[col, row] = SurfaceCell(terrain=terrain, exists=exists)
        self.version = 0

    def surface(
        self, position: tuple[int, int] | int, row: int | None = None
    ) -> SurfaceCell:
        """返回地表，兼容 surface((col, row)) 与 surface(col, row)。"""
        if row is None:
            if not isinstance(position, tuple):
                raise TypeError("缺少行坐标")
            col, row = position
        else:
            col = position
        if not self.grid.within_bounds(col, row):
            raise IndexError("地表坐标越界")
        return self.grid[col, row]

    def set_surface(self, position: tuple[int, int], cell: SurfaceCell) -> None:
        self.grid[position] = cell
        self.version += 1

    def damage_surface(self, position: tuple[int, int], amount: int) -> int:
        remaining = self.surface(position).apply_damage(amount)
        self.version += 1
        return remaining

    def destroy_surface(self, position: tuple[int, int]) -> None:
        self.damage_surface(position, self.surface(position).durability)

    def has_surface(self, position: tuple[int, int]) -> bool:
        return self.surface(position).exists
