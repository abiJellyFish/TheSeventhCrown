"""元素反应引擎 —— 燃烧/潮湿/地表再生的钟摆推进。

只在 GameState 上操作，不持有自身状态。返回日志列表，由调用方路由到日志系统。
"""

import random
from dataclasses import dataclass
from core.entity import Entity

from core.fov import LightLevel
from core.grid import (Terrain, DIRS_4, FLAMMABLE, FUEL,
                       BURN_OUT_RESULT, REGENERABLE_FROM)


MAX_TIER = 3           # 燃烧最高档位
TIER_UP_TICKS = 3      # 升一档所需钟摆


@dataclass
class BurningSurface:
    """燃烧地表状态：档位 + 剩余燃料 + 当前档位持续钟摆。"""
    tier: int = 1       # 燃烧档位 1-3，仅 3 档具备传播能力
    fuel: int = 8       # 剩余燃料（钟摆）
    tick: int = 0       # 当前档位已持续钟摆数


def tick_surface_effects(state, delta: float) -> list[str]:
    """每钟摆推进地表元素效果。返回日志列表。

    delta 为钟摆推进数，内部循环 max(1, int(delta)) 次，使燃烧/潮湿按真实钟摆数递减。
    """
    logs: list[str] = []
    for _ in range(max(1, int(delta))):
        logs.extend(_tick_burning(state))
        logs.extend(_tick_wet(state))
        logs.extend(_tick_regeneration(state))
    return logs


def _tick_burning(state) -> list[str]:
    """推进燃烧地表：实体灼烧、点火光、档位提升、3 档传播、燃料耗尽熄灭。

    燃烧分 3 档，每 TIER_UP_TICKS 钟摆升一档，仅 3 档按 FLAMMABLE 概率每钟摆传播。
    fuel=None 表示永久火源（篝火），永不熄灭、不烧尽地形。
    传播目标格潮湿且非水源 → 先移除潮湿再判定点燃。
    """
    logs: list[str] = []
    # 快照遍历，避免迭代中修改 dict
    for pos, bs in list(state.burning_surfaces.items()):
        # 1. 实体效果：站在燃烧格上的实体受灼烧（任何档位）
        ent = state.get_entity_at(pos[0], pos[1])
        if ent:
            state._ignite(ent, 5)

        # 2. 光源：半径随档位 1→2→3
        state.register_light(pos, bs.tier, LightLevel.BRIGHT)

        # 3. 传播（仅 3 档）：目标格潮湿且非水源 → 先移除潮湿，再按概率判定点燃
        if bs.tier >= MAX_TIER:
            for dc, dr in DIRS_4:
                nbr = (pos[0] + dc, pos[1] + dr)
                if not state.map.within_bounds(*nbr):
                    continue
                t = state.map[nbr]
                if nbr in state.wet_surfaces:
                    del state.wet_surfaces[nbr]  # 火烘干潮湿
                if t in FLAMMABLE and nbr not in state.burning_surfaces:
                    if random.randint(1, 100) <= FLAMMABLE[t]:
                        state.burning_surfaces[nbr] = BurningSurface(fuel=FUEL[t])
                        state.register_light(nbr, 1, LightLevel.BRIGHT)

        # 4. 档位推进：每 TIER_UP_TICKS 钟摆升一档，最高 MAX_TIER
        bs.tick += 1
        if bs.tick >= TIER_UP_TICKS and bs.tier < MAX_TIER:
            bs.tier += 1
            bs.tick = 0
            state.register_light(pos, bs.tier, LightLevel.BRIGHT)

        # 5. 燃料消耗：永久火源（fuel=None）永不耗尽；否则耗尽后烧尽成对应地块
        if bs.fuel is None:
            continue
        bs.fuel -= 1
        if bs.fuel <= 0:
            t = state.map[pos]
            if t in BURN_OUT_RESULT:
                state.map[pos] = BURN_OUT_RESULT[t]
                state.regen_candidates.add(pos)
            state.unregister_light(pos)
            del state.burning_surfaces[pos]
            logs.append(f"{pos} 处的火焰熄灭了")
    return logs


def _tick_wet(state) -> list[str]:
    """推进潮湿地表：实体受潮湿、计时递减后消失。"""
    for pos, remaining in list(state.wet_surfaces.items()):
        ent = state.get_entity_at(pos[0], pos[1])
        if ent:
            ent.add_status("潮湿", duration=5)
        new_remaining = remaining - 1
        if new_remaining <= 0:
            del state.wet_surfaces[pos]
        else:
            state.wet_surfaces[pos] = new_remaining
    return []


def _tick_regeneration(state) -> list[str]:
    """地表再生：烧尽的平原概率长回草地/灌木。只检查 regen_candidates。"""
    logs: list[str] = []
    for pos in list(state.regen_candidates):
        if state.map[pos] != REGENERABLE_FROM:
            state.regen_candidates.discard(pos)
            continue
        if random.randint(1, 1000) <= 2:  # 0.2% 每钟摆
            if random.random() < 0.9:
                state.map[pos] = Terrain.GRASS
            else:
                state.map[pos] = Terrain.BUSH
            state.regen_candidates.discard(pos)
            logs.append("荒芜的土地上长出了新的植被")
    return logs


class SurfaceEffectsMixin:

    def _check_surface_effects(self, creature: Entity) -> None:
        """实体移动后检查地表效果：踩水熄灭灼烧、着火格点燃、自燃、潮湿。"""
        pos = self.player_pos if creature.controlled else None
        if pos is None:
            for c, (ec, er) in self.entities:
                if c is creature:
                    pos = (ec, er)
                    break
        if not pos:
            return
        # 灼烧 + 站在水源/潮湿地表 → 熄灭并受潮湿
        if creature.has_status("灼烧"):
            if self.is_wet(pos):
                creature.remove_status("灼烧")
                creature.add_status("潮湿", duration=5)
        # 直接站在火源上 → 点燃
        if self.is_burning(pos):
            self._ignite(creature, 5)
        else:
            # 自燃：距火源 auto_ignite_dist 格内
            fire_traits = creature.temp_traits.get("fire", {})
            ignite_dist = fire_traits.get("auto_ignite_dist", 0)
            if ignite_dist > 0:
                fire_positions = set(self.burning_surfaces.keys())
                for fpos in fire_positions:
                    if max(abs(fpos[0] - pos[0]), abs(fpos[1] - pos[1])) <= ignite_dist:
                        self._ignite(creature, 3)
                        break
        # 潮湿
        if pos in self.wet_surfaces or self.map[pos] == Terrain.WATER:
            creature.add_status("潮湿", duration=5)

    def _ignite(self, creature: Entity, duration: int) -> None:
        """点燃实体：潮湿状态使持续时间减半（并消耗潮湿）。"""
        creature.ignite(duration)

    def is_burning(self, pos: tuple[int, int]) -> bool:
        """该格是否处于燃烧状态（唯一来源：燃烧条目，篝火通过 seed_campfires 注入）。"""
        return pos in self.burning_surfaces

    def is_wet(self, pos: tuple[int, int]) -> bool:
        """该格是否潮湿（潮湿地表或水域）。"""
        return pos in self.wet_surfaces or self.map[pos] == Terrain.WATER

    def seed_campfires(self) -> None:
        """为地图上所有篝火结构（CAMPFIRE）格注入永久燃烧条目（fuel=None, tier=3）。

        篝火并入燃烧系统：加载地图后调用，使篝火与普通燃烧格共用同一套 tick 管线。
        """
        from core.element import BurningSurface
        from core.fov import LightLevel
        for c in range(self.map.width):
            for r in range(self.map.height):
                if self.map[c, r] == Terrain.CAMPFIRE:
                    self.burning_surfaces[(c, r)] = BurningSurface(fuel=None, tier=3)
                    self.register_light((c, r), 3, LightLevel.BRIGHT)

    def _find_nearest_water(self, creature: Entity, pos: tuple[int, int]) -> tuple[int, int] | None:
        """在实体视野内寻找最近的水源（WATER 地形）或潮湿地表。
        通过地形索引 + wet_surfaces 直查，避免逐格扫描视野方形。"""
        vision = getattr(creature, 'vision_range', 8)
        best_pos = None
        best_dist = float('inf')
        for tpos in self._get_water_tiles():
            dist = max(abs(tpos[0] - pos[0]), abs(tpos[1] - pos[1]))
            if dist <= vision and dist < best_dist:
                best_dist, best_pos = dist, tpos
        for tpos in self.wet_surfaces:
            dist = max(abs(tpos[0] - pos[0]), abs(tpos[1] - pos[1]))
            if dist <= vision and dist < best_dist:
                best_dist, best_pos = dist, tpos
        return best_pos

