"""树枝生成 —— 落地格、播种、再生。"""
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


class TwigMixin:

    # ═══════════════════════════════════════════════════
    # 树枝生成（阶段8）
    # ═══════════════════════════════════════════════════

    def _twig_landing_spots(self, tree_pos: tuple[int, int]) -> list[tuple[int, int]]:
        """树周围曼哈顿距离≤3的有效落地格（排除全障碍和 BLOCKING_TERRAINS）。"""
        from core.combat.cover import is_full_cover
        tx, ty = tree_pos
        spots = []
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if abs(dx) + abs(dy) > 3:
                    continue
                cx, cy = tx + dx, ty + dy
                if not self.map.within_bounds(cx, cy):
                    continue
                t = self.map[cx, cy]
                if t in BLOCKING_TERRAINS or is_full_cover(t):
                    continue
                spots.append((cx, cy))
        return spots

    def _count_twigs_around(self, tree_pos: tuple[int, int]) -> int:
        """统计树周围 ground_items 中已有树枝数量。"""
        spots = self._twig_landing_spots(tree_pos)
        count = 0
        for item, (ic, ir) in self.ground_items:
            if item.name == "树枝" and (ic, ir) in spots:
                count += item.count
        return count

    def _make_twig(self, pos: tuple[int, int]) -> None:
        """在指定位置生成一个树枝物品。"""
        from core.trade import resolve_items
        try:
            items = resolve_items([{"name": "树枝", "count": 1}])
            if items:
                self.ground_items.append((items[0], pos))
        except ValueError:
            pass

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
        """遍历所有 TREE 格生成初始树枝。"""
        for x in range(self.map.width):
            for y in range(self.map.height):
                if self.map[x, y] == Terrain.TREE:
                    self._seed_twigs_at((x, y))

    def _regrow_twigs(self) -> None:
        """每3000钟摆重生树枝。"""
        self._seed_twigs()

