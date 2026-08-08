"""GameState —— 全局游戏状态，持有地图、实体、时间、战斗状态。"""

import random
from dataclasses import dataclass, field
from typing import Any

from core.entity import Creature, Player
from core.grid import Grid
from core.movement import Terrain, can_enter
from core.pendulum import PendulumClock


@dataclass
class GameState:
    """全局游戏状态。"""

    player: Player
    map_width: int = 80
    map_height: int = 60
    player_pos: tuple[int, int] = (0, 0)

    # 地图
    map: Grid[Terrain] = field(init=False)
    current_map: str = ""
    map_exits: list[dict] = field(default_factory=list)
    loot_spots: list[dict] = field(default_factory=list)
    bed_positions: set[tuple[int, int]] = field(default_factory=set)
    campfire_positions: set[tuple[int, int]] = field(default_factory=set)
    door_states: dict[tuple[int, int], bool] = field(default_factory=dict)
    dungeon_entrance: tuple[int, int] | None = None
    dungeon_exit: tuple[int, int] | None = None
    in_dungeon: bool = False
    world_state: dict | None = None
    location_map: dict[tuple[int, int], str] = field(default_factory=dict)

    # 实体
    entities: list[tuple[Creature, tuple[int, int]]] = field(default_factory=list)

    # 时间
    clock: PendulumClock = field(default_factory=PendulumClock)

    # 战斗
    in_combat: bool = False
    combat_initiative: list[Creature] = field(default_factory=list)
    current_turn_index: int = 0
    combat_turn_entity: Creature | None = None
    combat_phase: str = "idle"              # 攻击流程状态机: "idle"|"select_action"|"select_target"|"select_maneuver"|"select_special"
    pending_attack: dict | None = None      # 当前攻击上下文 {"mode":..., "weapon":..., "attack_roll":None, "target":None}

    # 光照与视野
    light_map: Grid | None = None
    fov_cache: set = field(default_factory=set)       # 当前 FOV 可见格集合

    # 战技数据
    maneuvers: list[dict] = field(default_factory=list)

    # 观察模式
    observe_mode: bool = False
    observe_cursor: tuple[int, int] = (0, 0)

    # 慢速模式
    slow_mode: bool = False

    # 灼烧计时（id(creature) → 剩余钟摆数）
    burn_timers: dict[int, int] = field(default_factory=dict)

    # NPC 推进回调设置的待开战目标
    pending_combat_target: Creature | None = None

    def __post_init__(self):
        self.map = Grid[Terrain](self.map_width, self.map_height, Terrain.PASSABLE)
        self.clock.set_npc_advance_callback(self._advance_npcs)

    # ---- 实体管理 ----

    def add_entity(self, creature: Creature, pos: tuple[int, int]) -> None:
        self.entities.append((creature, pos))
        if pos in self.campfire_positions:
            cid = id(creature)
            self.burn_timers[cid] = 5
            if "灼烧" not in creature.statuses:
                creature.statuses.append("灼烧")

    def remove_entity(self, creature: Creature) -> None:
        self.entities = [(c, p) for c, p in self.entities if c is not creature]

    def get_entity_at(self, col: int, row: int) -> Creature | None:
        for c, (ec, er) in self.entities:
            if (ec, er) == (col, row):
                return c
        return None

    # ---- 移动 ----

    def move_player(self, col: int, row: int) -> bool:
        if can_enter(col, row, self.map, self.entities,
                     self.player_pos[0], self.player_pos[1]):
            self.player_pos = (col, row)
            self._check_campfire_burn(self.player)
            if not self.in_combat:
                self.clock.tick_move(self.player.speed)
            return True
        return False

    def move_entity(self, creature: Creature, from_col: int, from_row: int,
                    to_col: int, to_row: int) -> bool:
        """移动非玩家实体。"""
        if can_enter(to_col, to_row, self.map, self.entities,
                     from_col, from_row):
            # 更新位置
            for i, (c, (ec, er)) in enumerate(self.entities):
                if c is creature and (ec, er) == (from_col, from_row):
                    self.entities[i] = (c, (to_col, to_row))
                    self._check_campfire_burn(creature)
                    return True
        return False

    # ---- NPC 推进 ----

    def _check_campfire_burn(self, creature: Creature) -> None:
        """若生物站在篝火上，施加灼烧状态（5 钟摆）。"""
        pos = None
        if creature is self.player:
            pos = self.player_pos
        else:
            for c, (ec, er) in self.entities:
                if c is creature:
                    pos = (ec, er)
                    break
        if pos and pos in self.campfire_positions:
            cid = id(creature)
            self.burn_timers[cid] = 5
            if "灼烧" not in creature.statuses:
                creature.statuses.append("灼烧")

    def _tick_burn_timers(self) -> None:
        """每钟摆结算灼烧计时，归零时移除状态。"""
        expired = []
        for cid, remaining in list(self.burn_timers.items()):
            new_remaining = remaining - 1
            if new_remaining <= 0:
                expired.append(cid)
            else:
                self.burn_timers[cid] = new_remaining
        for cid in expired:
            del self.burn_timers[cid]
            # 查找对应生物并移除灼烧状态
            if id(self.player) == cid:
                if "灼烧" in self.player.statuses:
                    self.player.statuses.remove("灼烧")
            else:
                for c, _ in self.entities:
                    if id(c) == cid:
                        if "灼烧" in c.statuses:
                            c.statuses.remove("灼烧")
                        break

    def _advance_npcs(self, delta: float) -> None:
        """每钟摆 NPC 行动结算（探索模式）。MVP: 随机游荡 + 记录敌对发现。"""
        if self.in_combat:
            # 战斗中也要结算灼烧计时
            self._tick_burn_timers()
            return
        # 结算灼烧
        self._tick_burn_timers()
        # 玩家站在篝火上（回合开始时已在上面）
        if self.player_pos in self.campfire_positions:
            self._check_campfire_burn(self.player)
        for creature, (ec, er) in list(self.entities):
            if creature is self.player or creature.hp <= 0:
                continue
            # 随机游荡（25% 概率每钟摆移动一格）
            if random.random() < 0.25:
                dx = random.choice([-1, 0, 1])
                dy = random.choice([-1, 0, 1])
                if dx == 0 and dy == 0:
                    continue
                nx, ny = ec + dx, er + dy
                if self.map.within_bounds(nx, ny):
                    self.move_entity(creature, ec, er, nx, ny)
        # 敌对检测：NPC 游荡后可能进入玩家 FOV
        pc, pr = self.player_pos
        for creature, (ec, er) in self.entities:
            if creature.faction == "hostile" and (ec, er) in self.fov_cache:
                self.pending_combat_target = creature
                break
