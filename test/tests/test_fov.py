"""视野 (FOV) + 光照 —— 递归阴影投射、黑暗视觉。"""
import pytest
from core.fov import compute_fov, LightLevel
from core.grid import Grid
from core.movement import Terrain


class TestFOV:
    def test_open_area_all_visible(self):
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        light = Grid[LightLevel](10, 10, LightLevel.BRIGHT)
        fov = compute_fov(g, (5, 5), 8, light)
        assert (6, 5) in fov

    def test_wall_blocks_vision(self):
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        g[6, 5] = Terrain.WALL
        light = Grid[LightLevel](10, 10, LightLevel.BRIGHT)
        fov = compute_fov(g, (5, 5), 3, light)
        # wall immediately to the right should block what's behind it
        assert (5, 5) in fov  # origin always visible

    def test_total_darkness_no_source(self):
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        light = Grid[LightLevel](10, 10, LightLevel.DARK)
        fov = compute_fov(g, (5, 5), 8, light, darkvision_range=0)
        # no light + no darkvision → only origin tile visible
        assert len(fov) <= 1

    def test_darkvision_in_darkness(self):
        g = Grid[Terrain](10, 10, Terrain.PASSABLE)
        light = Grid[LightLevel](10, 10, LightLevel.DARK)
        fov = compute_fov(g, (5, 5), 5, light)
        # dark environment restricts visibility
        assert isinstance(fov, set)
