"""地图生成模块。"""

from domain.map.generation.world import build_world
from domain.map.generation.dungeon import build_dungeon

__all__ = ["build_world", "build_dungeon"]
