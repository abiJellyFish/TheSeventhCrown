"""树枝生成 —— 落地格、播种、再生。"""
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from domain.entity import Entity, Item, are_hostile, is_ally
from domain.grid import Grid
from domain.dice import roll_2d6
from domain.movement import Terrain, can_enter, find_path
from domain.obstacle import obstacle_at
from domain.ai.components import COMPONENTS
from domain.pendulum import PendulumClock


class TwigMixin:

    # ═══════════════════════════════════════════════════
    # 树枝生成（阶段8）
    # ═══════════════════════════════════════════════════

    def _twig_landing_spots(self, tree_pos: tuple[int, int] | tuple[int, int, int]) -> list[tuple[int, int]]:
        """树周围曼哈顿距离≤3的有效落地格。"""
        tx, ty = tree_pos[:2]
        spots = []
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if abs(dx) + abs(dy) > 3:
                    continue
                cx, cy = tx + dx, ty + dy
                if not self.map.within_bounds(cx, cy):
                    continue
                if obstacle_at((cx, cy), self.entities, self.ground_items) is not None:
                    continue
                spots.append((cx, cy))
        return spots

    def _count_twigs_around(self, tree_pos: tuple[int, int]) -> int:
        """统计树周围 ground_items 中已有树枝数量。"""
        spots = self._twig_landing_spots(tree_pos)
        count = 0
        for item, (ic, ir, iz) in self.ground_items:
            if item.name == "树枝" and (ic, ir) in spots:
                count += item.count
        return count

    def _make_twig(self, pos: tuple[int, int]) -> None:
        """在指定位置生成一个树枝物品。"""
        from domain.trade import resolve_items
        items = resolve_items([{"name": "树枝", "count": 1}])
        if items:
            from domain.item_actions import place_on_ground
            place_on_ground(
                self.ground_items, items[0], pos[0], pos[1],
                self.surface_height_at(pos),
            )
            self.invalidate_spatial_cache()

    def _seed_twigs_at(self, tree_pos: tuple[int, int]) -> None:
        """对单棵树生成初始树枝。"""
        count = self._count_twigs_around(tree_pos)
        if count >= 3:
            return
        spots = self._twig_landing_spots(tree_pos)
        if not spots:
            return
        import random
        n = random.randint(1, 3)
        for _ in range(n):
            pos = random.choice(spots)
            self._make_twig(pos)

    def _seed_twigs(self) -> None:
        """遍历树物品生成初始树枝。"""
        for item, pos in self.ground_items:
            if "树" in item.name:
                self._seed_twigs_at(pos)

    def _regrow_twigs(self) -> None:
        """每3000钟摆重生树枝。"""
        self._seed_twigs()
