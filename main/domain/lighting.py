"""光照 —— 光源注册与光照网格构建。"""
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from domain.entity import Entity, Item, are_hostile, is_ally
from domain.grid import Grid
from domain.dice import roll_2d6
from domain.movement import Terrain, can_enter, find_path
from domain.combat.cover import is_full_cover
from domain.ai.components import COMPONENTS
from domain.pendulum import PendulumClock


class LightMixin:

    # ---- 光照注册 ----

    def register_light(self, pos: tuple[int, int], radius: int, level) -> None:
        """注册光源。"""
        from domain.fov import LightLevel
        value = (radius, level)
        if self.light_sources.get(pos) == value:
            return
        self.light_sources[pos] = value
        self._light_version = getattr(self, "_light_version", 0) + 1
        self._light_cache_key = None
        self._light_grid_cache = None

    def unregister_light(self, pos: tuple[int, int]) -> None:
        """注销光源。"""
        if pos not in self.light_sources:
            return
        self.light_sources.pop(pos, None)
        self._light_version = getattr(self, "_light_version", 0) + 1
        self._light_cache_key = None
        self._light_grid_cache = None

    def _build_light_grid(self):
        """根据光源注册表合成光照等级网格。
        基准: in_dungeon 内为 DARK，否则 BRIGHT。
        光源按 BRIGHT > DIM > DARK 优先级叠加（只在更暗时覆盖）。
        """
        from domain.fov import LightLevel
        from domain.grid import Grid
        key = (
            self.map.width,
            self.map.height,
            self.in_dungeon,
            getattr(self, "environment_light", None),
            self._light_version,
        )
        if getattr(self, "_light_cache_key", None) == key:
            return self._light_grid_cache
        # 环境光照覆盖优先；否则按室内/室外基准（室外明亮、室内黑暗）
        env = getattr(self, 'environment_light', None)
        base = env if env is not None else (LightLevel.BRIGHT if not self.in_dungeon else LightLevel.DARK)
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
        self._light_cache_key = key
        self._light_grid_cache = lg
        return lg

    # 战技数据
