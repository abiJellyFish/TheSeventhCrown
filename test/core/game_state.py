"""GameState —— 全局游戏状态，持有地图、实体、时间、战斗状态。"""

import random
from dataclasses import dataclass, field
from typing import Any, Callable

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
    stone_positions: set[tuple[int, int]] = field(default_factory=set)
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

    # 交互系统
    interact_phase: str = ""              # "" | "menu" | "talking" | "trading"
    interact_targets: list = field(default_factory=list)
    interact_target: object | None = None  # 当前交互目标 (InteractTarget)
    shop_data: dict | None = None         # 当前交易中的商店数据

    # NPC 推进回调设置的待开战目标
    pending_combat_target: Creature | None = None
    # 钟摆推进前刷新 FOV 的回调（由 app 注册）
    _pre_tick_fov_cb: Callable[[], None] | None = field(default=None, repr=False)

    def __post_init__(self):
        self.map = Grid[Terrain](self.map_width, self.map_height, Terrain.PASSABLE)
        self.clock.set_npc_advance_callback(self._advance_npcs)

    # ---- 实体管理 ----

    def add_entity(self, creature: Creature, pos: tuple[int, int]) -> None:
        self.entities.append((creature, pos))
        if pos in self.campfire_positions:
            creature.add_status("灼烧", duration=5)

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
                # 推进钟摆前刷新 FOV（确保 NPC 检测用新位置）
                if self._pre_tick_fov_cb:
                    self._pre_tick_fov_cb()
                self.clock.tick_move(self.player.speed)
            return True
        return False

    def move_entity(self, creature: Creature, from_col: int, from_row: int,
                    to_col: int, to_row: int) -> bool:
        """移动非玩家实体。不能移动到玩家所在格。"""
        if (to_col, to_row) == self.player_pos:
            return False
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
        """若生物站在篝火上，施加灼烧状态（5 钟摆，自动刷新）。"""
        pos = self.player_pos if creature is self.player else None
        if pos is None:
            for c, (ec, er) in self.entities:
                if c is creature:
                    pos = (ec, er)
                    break
        if pos and pos in self.campfire_positions:
            creature.add_status("灼烧", duration=5)

    def _tick_all_statuses(self) -> None:
        """每钟摆推进玩家和所有实体的状态计时。"""
        self.player.tick_statuses()
        for creature, _ in self.entities:
            creature.tick_statuses()

    def _advance_npcs(self, delta: float) -> None:
        """每钟摆 NPC 行动结算（探索模式）。MVP: 随机游荡 + 记录敌对发现。"""
        # 统一状态计时（探索 + 战斗均需）
        self._tick_all_statuses()
        if self.in_combat:
            return
        # 玩家站在篝火上（持续烧伤）
        if self.player_pos in self.campfire_positions:
            self._check_campfire_burn(self.player)
        for creature, (ec, er) in list(self.entities):
            if creature is self.player or creature.hp <= 0:
                continue
            if creature.has_status("不可移动"):
                continue
            # 随机游荡（25% 概率每钟摆移动一格）
            if random.random() < 0.25:
                dx = random.choice([-1, 0, 1])
                dy = random.choice([-1, 0, 1])
                if dx == 0 and dy == 0:
                    continue
                nx, ny = ec + dx, er + dy
                if (nx, ny) == self.player_pos:
                    continue  # 不能走到玩家所在格
                if self.map.within_bounds(nx, ny):
                    self.move_entity(creature, ec, er, nx, ny)
        # 敌对检测：双方互相在视野内才触发战斗（跳过尸体）
        pc, pr = self.player_pos
        for creature, (ec, er) in self.entities:
            if creature.hp <= 0:
                continue
            if creature.faction == "hostile" and (ec, er) in self.fov_cache:
                dist = max(abs(ec - pc), abs(er - pr))
                if dist <= getattr(creature, 'vision_range', 0):
                    self.pending_combat_target = creature
                    break
