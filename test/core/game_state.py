"""GameState —— 全局游戏状态，持有地图、实体、时间、战斗状态。"""

from dataclasses import dataclass, field

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

    # 实体
    entities: list[tuple[Creature, tuple[int, int]]] = field(default_factory=list)

    # 时间
    clock: PendulumClock = field(default_factory=PendulumClock)

    # 战斗
    in_combat: bool = False
    combat_initiative: list[Creature] = field(default_factory=list)
    current_turn_index: int = 0

    # 光照
    light_map: Grid | None = None

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

    # ---- NPC 推进 ----

    def _advance_npcs(self, delta: float) -> None:
        """每钟摆 NPC 行动结算（探索模式）。MVP: 只随机游荡，不做复杂 AI。"""
        pass  # 在渲染层/主循环中实现具体移动逻辑
