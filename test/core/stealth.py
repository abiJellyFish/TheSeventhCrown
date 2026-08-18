"""隐匿与视野判定 —— 被动感知、遮蔽判定、FOV 重算、身后周期重检、透明网格缓存。"""
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


class StealthMixin:

    def _cover_level(self, pos: tuple[int, int], observer_pos: tuple[int, int] | None = None) -> str:
        """遮蔽等级："heavy"|"light"|"none"。
        重度遮蔽 = 不在观察者FOV内 或 雾气格 或 被墙体完全阻断。
        轻度遮蔽 = 灌木/矮墙 或 雾气格（雾气轻度遮蔽）。
        """
        from core.combat.cover import COVER_TABLE
        col, row = pos
        t = self.map[col, row]
        # 雾气格 → 轻度遮蔽
        if pos in self.fog_surfaces:
            return "light"
        # 灌木/矮墙/石头 → 轻度遮蔽（半身或四分之三障碍）
        info = COVER_TABLE.get(t)
        if info is not None:
            ac = info[0]
            if 5 <= ac <= 8:
                return "light"
        # 不在观察者FOV内 → 重度遮蔽
        if observer_pos is not None:
            if pos not in self.fov_bright and pos not in self.fov_dim:
                return "heavy"
        return "none"

    def _get_transparent_grid(self) -> "Grid[bool]":
        """返回透明网格（仅 WALL 不可穿透），按 _terrain_version 缓存，避免每次 LOS 全图重建。"""
        if self._transparent_cache is None:
            from core.grid import Grid
            transparent = Grid[bool](self.map.width, self.map.height, True)
            for col in range(self.map.width):
                for row in range(self.map.height):
                    if self.map[col, row] == Terrain.WALL:
                        transparent[col, row] = False
            self._transparent_cache = transparent
        return self._transparent_cache

    def _bump_terrain_version(self) -> None:
        """地图加载 / 门开合 / 燃烧烧尽 / 灌木再生等地形变化后调用，失效透明网格缓存。"""
        self._terrain_version += 1
        self._transparent_cache = None
        self._water_tiles_cache = None
        self._bush_tiles_cache = None

    def _get_water_tiles(self) -> frozenset:
        """WATER 地形坐标索引（按 _terrain_version 缓存）。"""
        if self._water_tiles_cache is None:
            tiles = set()
            for col in range(self.map.width):
                for row in range(self.map.height):
                    if self.map[col, row] == Terrain.WATER:
                        tiles.add((col, row))
            self._water_tiles_cache = frozenset(tiles)
        return self._water_tiles_cache

    def _get_bush_tiles(self) -> frozenset:
        """BUSH 地形坐标索引（按 _terrain_version 缓存）。"""
        if self._bush_tiles_cache is None:
            tiles = set()
            for col in range(self.map.width):
                for row in range(self.map.height):
                    if self.map[col, row] == Terrain.BUSH:
                        tiles.add((col, row))
            self._bush_tiles_cache = frozenset(tiles)
        return self._bush_tiles_cache

    def _observer_can_see(self, observer: Entity, target_pos: tuple[int, int]) -> bool:
        """观察者是否能看见目标位置（vision_range + 非身后扇区 + LOS）。"""
        obs_pos = self.get_entity_pos(observer)
        if obs_pos is None:
            return False
        vr = getattr(observer, 'vision_range', 8)
        if (target_pos[0] - obs_pos[0]) ** 2 + (target_pos[1] - obs_pos[1]) ** 2 > vr * vr:
            return False  # 欧几里得视野半径（圆形）
        from core.movement import sector_of
        if sector_of(observer.facing, (target_pos[0] - obs_pos[0], target_pos[1] - obs_pos[1])) == "back":
            return False
        from core.fov import _line_of_sight
        if not _line_of_sight(self._get_transparent_grid(), obs_pos[0], obs_pos[1], target_pos[0], target_pos[1]):
            return False
        return True

    def _stealth_conditions_met(self, observer_pos: tuple[int, int], target_pos: tuple[int, int]) -> bool:
        """判定目标是否满足隐匿条件（规则2）：轻度遮蔽格 或 视线穿过轻度遮蔽格。"""
        from core.combat.cover import COVER_TABLE
        # 目标在轻度遮蔽格（P3 短路：命中直接返回，跳过射线）
        t = self.map[target_pos[0], target_pos[1]]
        if COVER_TABLE.get(t) and 5 <= COVER_TABLE[t][0] <= 8:
            return True
        if target_pos in self.fog_surfaces:
            return True
        # 观察者→目标视线穿过轻度遮蔽格（排除起终点）
        line = self._ray_cells(self._get_transparent_grid(), observer_pos[0], observer_pos[1],
                               target_pos[0], target_pos[1])
        if len(line) < 3:
            return False
        for (col, row) in line[1:-1]:
            t2 = self.map[col, row]
            if COVER_TABLE.get(t2) and 5 <= COVER_TABLE[t2][0] <= 8:
                return True
            if (col, row) in self.fog_surfaces:
                return True
        return False

    @staticmethod
    def _ray_cells(grid: "Grid[bool]", x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
        """返回从 (x0,y0) 到 (x1,y1) 的格点序列（含起终点），与 _line_of_sight 同口径。"""
        dx = x1 - x0
        dy = y1 - y0
        dist = max(abs(dx), abs(dy))
        cells = [(x0, y0)]
        if dist == 0:
            return cells
        step_x = dx / dist
        step_y = dy / dist
        cx, cy = float(x0) + 0.5, float(y0) + 0.5
        for _ in range(1, dist + 1):
            cx += step_x
            cy += step_y
            cells.append((int(cx), int(cy)))
        return cells

    def _has_stealth_qualification(self, target: Entity) -> bool:
        """目标是否具备隐匿资格：主动躲藏状态，或小型/微型生物自动躲藏。"""
        if target.has_status("hiding"):
            return True
        size = getattr(target, 'size', 'medium')
        return size in ("small", "tiny")

    def _passive_spot(self, observer: Entity, target: Entity) -> bool:
        """被动感知检定：d20+感知调整 vs DC。返回 True=发现（移除隐匿）。"""
        from core.dice import roll_d20
        if target.has_status("hiding"):
            dc = target.temp_traits.get("hide_dc", self.PASSIVE_SPOT_DC)
        else:
            dc = 10 + target.stat_adjust("dex")
        roll = roll_d20() + observer.stat_adjust("wis")
        return roll >= dc

    def _is_hidden_to(self, observer: Entity, target: Entity,
                       target_pos: tuple[int, int]) -> bool:
        """纯查询（不掷骰）：判断 target 是否对 observer 隐匿。"""
        if target.is_dead:
            return False
        obs_id = id(observer)
        target_id = id(target)
        # 目标在观察者身前/身侧相邻 → 自动发现（移除配对）
        obs_pos = self.get_entity_pos(observer)
        if obs_pos is not None:
            dist = max(abs(target_pos[0] - obs_pos[0]), abs(target_pos[1] - obs_pos[1]))
            if dist <= 1:
                from core.movement import sector_of
                sec = sector_of(observer.facing, (target_pos[0] - obs_pos[0], target_pos[1] - obs_pos[1]))
                if sec in ("front", "side"):
                    self.hidden_from.get(target_id, set()).discard(obs_id)
                    return False
        # 配对在隐匿表 → 复检条件
        if target_id in self.hidden_from and obs_id in self.hidden_from[target_id]:
            if self._stealth_conditions_met(obs_pos, target_pos):
                return True
            else:
                self.hidden_from[target_id].discard(obs_id)
                return False
        return False

    def _break_stealth_in_view(self, actor: Entity, force_targets: tuple = ()) -> None:
        """动作/攻击破坏隐匿：遍历自身隐匿表，移除能看见的观察者 ∪ force_targets 的配对。"""
        target_id = id(actor)
        if target_id not in self.hidden_from:
            return
        observers = self.hidden_from[target_id]
        if not observers:
            return
        removed = []
        actor_pos = self.get_entity_pos(actor)
        for obs_id in list(observers):
            obs = next((c for c, _ in self.entities if id(c) == obs_id), None)
            if obs is None:
                continue
            # 能看见 或 在 force_targets 中 → 移除
            if (actor_pos and self._observer_can_see(obs, actor_pos)) or obs_id in force_targets:
                observers.discard(obs_id)
                removed.append(obs.name)
        if not observers:
            self.hidden_from.pop(target_id, None)
            if actor.has_status("hiding"):
                actor.remove_status("hiding")
        if removed and self._npc_log_cb:
            self._npc_log_cb(f"{actor.name} 的动作暴露了自己（{', '.join(removed)} 看见了）")

    def _hide_attack_expose(self, attacker: Entity, target: Entity | None = None) -> None:
        """躲藏中攻击暴露（兼容旧入口，委托 _break_stealth_in_view）。"""
        force_targets = ()
        if target is not None:
            force_targets = (id(target),)
        self._break_stealth_in_view(attacker, force_targets=force_targets)

    def _on_fov_recompute(self, observer: Entity) -> None:
        """事件驱动检定入口：对比视野快照，对新进入视野的实体进行被动检定。"""
        obs_id = id(observer)
        obs_pos = self.get_entity_pos(observer)
        if obs_pos is None:
            # 与原逐实体判定等价：观察者不在场 → 可见集为空并更新快照
            self.seen_snap[obs_id] = set()
            return
        # 预取可复用参数，避免内层循环重复 O(N) get_entity_pos / 重复查缓存（性能）
        vr = getattr(observer, 'vision_range', 8)
        from core.movement import sector_of
        from core.fov import _line_of_sight
        transparent = self._get_transparent_grid()
        entity_by_id = {id(c): c for c, _ in self.entities}
        # 当前可见实体集（内联可视判定，与 _observer_can_see 三条件一致）
        current_visible: set[int] = set()
        for c, (ec, er) in self.entities:
            cid = id(c)
            if c.is_dead or cid == obs_id:
                continue
            # 距离 → 扇区 → LOS
            if (ec - obs_pos[0]) ** 2 + (er - obs_pos[1]) ** 2 > vr * vr:
                continue  # 欧几里得视野半径（圆形）
            if sector_of(observer.facing, (ec - obs_pos[0], er - obs_pos[1])) == "back":
                continue
            if not _line_of_sight(transparent, obs_pos[0], obs_pos[1], ec, er):
                continue
            current_visible.add(cid)
        # 新进入视野实体 = 当前 - 上次快照
        prev = self.seen_snap.get(obs_id, set())
        new_entries = current_visible - prev
        for target_id in new_entries:
            target = entity_by_id.get(target_id)
            if target is None:
                continue
            # 已对该观察者隐匿 → 保持配对，不重掷（规则3：持续被看着不重检）
            if target_id in self.hidden_from and obs_id in self.hidden_from[target_id]:
                continue
            target_pos = self.get_entity_pos(target)
            if target_pos is None:
                continue
            # 检查隐匿资格
            if not self._has_stealth_qualification(target):
                continue
            # 检查隐匿条件
            if not self._stealth_conditions_met(obs_pos, target_pos):
                continue
            # 被动感知检定
            if not self._passive_spot(observer, target):
                if target_id not in self.hidden_from:
                    self.hidden_from[target_id] = set()
                self.hidden_from[target_id].add(obs_id)
                if self._npc_log_cb:
                    self._npc_log_cb(f"{observer.name} 注意到了 {target.name} 的动静")
        # 更新快照
        self.seen_snap[obs_id] = current_visible

    def _stealth_back_checks(self) -> None:
        """回合推进钩子：身后相邻格周期性重检（每6钟摆/1战斗轮）。"""
        clock_count = self.clock.pendulum_count if hasattr(self, 'clock') else 0
        for target_id, observers in list(self.hidden_from.items()):
            target = next((c for c, _ in self.entities if id(c) == target_id), None)
            if target is None or target.is_dead:
                continue
            target_pos = self.get_entity_pos(target)
            if target_pos is None:
                continue
            for obs_id in list(observers):
                obs = next((c for c, _ in self.entities if id(c) == obs_id), None)
                if obs is None:
                    continue
                obs_pos = self.get_entity_pos(obs)
                if obs_pos is None:
                    continue
                # 仅处理身后相邻格
                dist = max(abs(target_pos[0] - obs_pos[0]), abs(target_pos[1] - obs_pos[1]))
                if dist != 1:
                    continue
                from core.movement import sector_of
                if sector_of(obs.facing, (target_pos[0] - obs_pos[0], target_pos[1] - obs_pos[1])) != "back":
                    continue
                # 检查是否到了重检时间
                key = (obs_id, target_id)
                if key not in self.spot_clock or clock_count - self.spot_clock[key] >= 6:
                    self.spot_clock[key] = clock_count
                    if self._passive_spot(obs, target):
                        observers.discard(obs_id)
                        if self._npc_log_cb:
                            self._npc_log_cb(f"{obs.name} 察觉到身后有动静")

