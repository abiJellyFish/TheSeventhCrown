"""光照 —— 光源注册与光照网格构建。"""
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from core.entity import Entity, Item, are_hostile, is_ally
from core.grid import Grid, BLOCKING_TERRAINS
from core.dice import roll_2d6
from core.movement import Terrain, can_enter, find_path
from core.combat.cover import is_full_cover
from core.ai.components import COMPONENTS
from core.pendulum import PendulumClock


class LightMixin:

    # ---- 光照注册 ----

    def register_light(self, pos: tuple[int, int], radius: int, level) -> None:
        """注册光源。"""
        from core.fov import LightLevel
        self.light_sources[pos] = (radius, level)

    def unregister_light(self, pos: tuple[int, int]) -> None:
        """注销光源。"""
        self.light_sources.pop(pos, None)

    def _build_light_grid(self):
        """根据光源注册表合成光照等级网格。
        基准: in_dungeon 内为 DARK，否则 BRIGHT。
        光源按 BRIGHT > DIM > DARK 优先级叠加（只在更暗时覆盖）。
        """
        from core.fov import LightLevel
        from core.grid import Grid
        base = LightLevel.BRIGHT if not self.in_dungeon else LightLevel.DARK
        lg = Grid[LightLevel](self.map.width, self.map.height, base)
        for (lx, ly), (radius, level) in self.light_sources.items():
            for dc in range(-radius, radius + 1):
                for dr in range(-radius, radius + 1):
                    if max(abs(dc), abs(dr)) <= radius:
                        nc, nr = lx + dc, ly + dr
                        if lg.within_bounds(nc, nr):
                            current = lg[nc, nr]
                            # BRIGHT > DIM > DARK (higher enum value = brighter)
                            if current.value < level.value:
                                lg[nc, nr] = level
        return lg

    # 战技数据
