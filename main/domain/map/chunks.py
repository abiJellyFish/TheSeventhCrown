"""地图区块坐标与范围计算。

区块只负责空间划分，不持有实体对象。规则状态由 GameState 持有，
表现层可以根据区块集合决定加载哪些视图对象。
"""

from dataclasses import dataclass


DEFAULT_CHUNK_SIZE = 16


@dataclass(frozen=True, slots=True)
class ChunkCoord:
    """不可变区块坐标。"""

    col: int
    row: int


def chunk_for_position(
    position: tuple[int, int],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> ChunkCoord:
    """返回坐标所属区块，支持地图边界外的负坐标。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    col, row = position
    return ChunkCoord(col // chunk_size, row // chunk_size)


def chunks_around(
    position: tuple[int, int],
    radius: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> frozenset[ChunkCoord]:
    """返回以坐标所在区块为中心的方形区块集合。"""
    if radius < 0:
        raise ValueError("radius must be non-negative")
    center = chunk_for_position(position, chunk_size)
    return frozenset(
        ChunkCoord(center.col + dc, center.row + dr)
        for dc in range(-radius, radius + 1)
        for dr in range(-radius, radius + 1)
    )
