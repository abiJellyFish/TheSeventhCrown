"""光照 —— 天光遮挡缓存、三维立方体光源、二维切片。"""

from domain.grid import Grid

_SKY_EMPTY = -10 ** 9


def _require_xyz(pos) -> tuple[int, int, int]:
    if len(pos) != 3:
        raise ValueError("光源坐标必须是三维")
    return int(pos[0]), int(pos[1]), int(pos[2])


def effect_light_pos(state, pos) -> tuple[int, int, int]:
    """地表效应的光源坐标。已是三维则原样；二维落到当前操作层。"""
    if len(pos) == 3:
        return _require_xyz(pos)
    if len(pos) != 2:
        raise ValueError("光源坐标必须是三维")
    return int(pos[0]), int(pos[1]), int(getattr(state, "active_z", 0))


class LightMixin:

    def register_light(self, pos: tuple[int, int, int], radius: int, level) -> None:
        """注册三维光源。范围是切比雪夫立方体。"""
        pos = _require_xyz(pos)
        value = (radius, level)
        if self.light_sources.get(pos) == value:
            return
        self.light_sources[pos] = value
        self._light_version = getattr(self, "_light_version", 0) + 1
        self._light_cache_key = None
        self._light_grid_cache = None

    def unregister_light(self, pos: tuple[int, int, int]) -> None:
        """注销三维光源。"""
        pos = _require_xyz(pos)
        if pos not in self.light_sources:
            return
        self.light_sources.pop(pos, None)
        self._light_version = getattr(self, "_light_version", 0) + 1
        self._light_cache_key = None
        self._light_grid_cache = None

    def _ensure_sky_cache(self) -> None:
        version = getattr(self, "_terrain_version", 0)
        if (
            getattr(self, "_sky_cache_version", None) == version
            and getattr(self, "_sky_block_z", None) is not None
        ):
            return
        grid = Grid[int](self.map.width, self.map.height, _SKY_EMPTY)
        for z, layer in self.world_layers.items():
            for row in range(layer.height):
                for col in range(layer.width):
                    if layer.surface((col, row)).exists and z > grid[col, row]:
                        grid[col, row] = z
        self._sky_block_z = grid
        self._sky_cache_version = version

    def _effective_sky(self):
        """覆盖值优先；否则按钟摆推导天光。"""
        from domain.calendar import sky_light

        env = getattr(self, "environment_light", None)
        if env is not None:
            return env
        clock = getattr(self, "clock", None)
        pendulum_count = getattr(clock, "pendulum_count", 0) if clock is not None else 0
        return sky_light(pendulum_count)

    def light_at(self, col: int, row: int, z: int):
        """(x,y,z) 的合成光照：天光（被更高实心地表挡住则无）叠三维立方体光源。"""
        from domain.combat.shape import is_in_reach
        from domain.fov import LightLevel

        self._ensure_sky_cache()
        if self._sky_block_z[col, row] <= z:
            level = self._effective_sky()
        else:
            level = LightLevel.DARK
        cell = (col, row, z)
        for pos, (radius, src_level) in self.light_sources.items():
            if is_in_reach(pos, cell, radius) and level.value < src_level.value:
                level = src_level
        return level

    def _observer_light_z(self) -> int:
        actor = getattr(self, "controlled_entity", None)
        if actor is not None:
            return actor.z
        return getattr(self, "active_z", 0)

    def _build_light_grid(self, z: int | None = None):
        """观察高度 z 的二维光照切片。供 compute_fov / 隐匿使用。"""
        from domain.combat.shape import cells_in_range_3d
        from domain.fov import LightLevel

        if z is None:
            z = self._observer_light_z()
        sky = self._effective_sky()
        key = (
            self.map.width,
            self.map.height,
            z,
            sky,
            getattr(self, "_light_version", 0),
            getattr(self, "_terrain_version", 0),
        )
        if getattr(self, "_light_cache_key", None) == key:
            return self._light_grid_cache
        self._ensure_sky_cache()
        lg = Grid[LightLevel](self.map.width, self.map.height, LightLevel.DARK)
        block = self._sky_block_z
        for row in range(self.map.height):
            for col in range(self.map.width):
                if block[col, row] <= z:
                    lg[col, row] = sky
        for pos, (radius, level) in self.light_sources.items():
            for cell in cells_in_range_3d(pos, radius):
                if cell[2] != z:
                    continue
                nc, nr = cell[0], cell[1]
                if lg.within_bounds(nc, nr) and lg[nc, nr].value < level.value:
                    lg[nc, nr] = level
        walls = getattr(self, "dungeon_wall_cells", None) or set()
        for row in range(self.map.height):
            for col in range(self.map.width):
                peak = block[col, row]
                if peak <= z:
                    continue
                cavity = any(
                    (col, row, mid) in walls
                    for mid in range(z + 1, peak + 1)
                )
                if cavity:
                    continue
                peak_level = self.light_at(col, row, peak)
                if lg[col, row].value < peak_level.value:
                    lg[col, row] = peak_level
        self._light_cache_key = key
        self._light_grid_cache = lg
        return lg
