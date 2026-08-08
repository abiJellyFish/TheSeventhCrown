"""GameState —— 全局游戏状态，持有地图、实体、时间、战斗状态。"""

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

    # 观察模式
    observe_mode: bool = False
    observe_cursor: tuple[int, int] = (0, 0)

    # 慢速模式
    slow_mode: bool = False

    def __post_init__(self):
        self.map = Grid[Terrain](self.map_width, self.map_height, Terrain.PASSABLE)
        self.clock.set_npc_advance_callback(self._advance_npcs)

    # ---- 实体管理 ----

    def add_entity(self, creature: Creature, pos: tuple[int, int]) -> None:
        self.entities.append((creature, pos))

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
                    return True
        return False

    # ---- NPC 推进 ----

    def _advance_npcs(self, delta: float) -> None:
        """每钟摆 NPC 行动结算（探索模式）。MVP: 只随机游荡，不做复杂 AI。"""
        pass
