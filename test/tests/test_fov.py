"""FOV + light tests."""

import pytest
from core.grid import Grid
from core.fov import LightLevel, compute_fov


def make_grid(w, h, transparent=True):
    g = Grid[bool](width=w, height=h, default=transparent)
    return g


class TestFOV:
    def test_open_area_all_visible(self):
        g = make_grid(10, 10, True)
        light = Grid[LightLevel](10, 10, LightLevel.BRIGHT)
        visible = compute_fov(g, (5, 5), 8, light, has_darkvision=False)
        assert (5, 5) in visible
        assert (5, 4) in visible
        assert (6, 5) in visible

    def test_wall_blocks_vision(self):
        g = make_grid(10, 10, True)
        g[6, 5] = False
        light = Grid[LightLevel](10, 10, LightLevel.BRIGHT)
        visible = compute_fov(g, (5, 5), 8, light, has_darkvision=False)
        assert (6, 5) in visible      # wall visible
        assert (7, 5) not in visible  # behind wall

    def test_diagonal_wall_doesnt_block(self):
        g = make_grid(10, 10, True)
        g[6, 4] = False
        light = Grid[LightLevel](10, 10, LightLevel.BRIGHT)
        visible = compute_fov(g, (5, 5), 8, light, has_darkvision=False)
        assert (6, 5) in visible


class TestLightLevels:
    def test_bright_light_full_visibility(self):
        g = make_grid(10, 10, True)
        light = Grid[LightLevel](10, 10, LightLevel.DARK)
        light[5, 5] = LightLevel.BRIGHT
        visible = compute_fov(g, (5, 5), 8, light, has_darkvision=False)
        assert len(visible) > 0

    def test_total_darkness_no_source(self):
        g = make_grid(10, 10, True)
        light = Grid[LightLevel](10, 10, LightLevel.DARK)
        visible = compute_fov(g, (5, 5), 8, light, has_darkvision=False)
        assert len(visible) == 0

    def test_darkvision_in_darkness(self):
        g = make_grid(10, 10, True)
        light = Grid[LightLevel](10, 10, LightLevel.DARK)
        visible = compute_fov(g, (5, 5), 5, light, has_darkvision=True,
                              darkvision_range=5)
        assert len(visible) > 0
        assert (5, 4) in visible
        assert (5, -1) not in visible  # >5 away, out of range

    def test_dim_light_no_darkvision_visible(self):
        g = make_grid(10, 10, True)
        light = Grid[LightLevel](10, 10, LightLevel.DIM)
        visible = compute_fov(g, (5, 5), 8, light, has_darkvision=False)
        assert len(visible) > 0
