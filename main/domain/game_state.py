"""GameState —— 全局游戏状态，持有地图、实体、时间、战斗状态。"""

import math
import random
from dataclasses import InitVar, dataclass, field
from typing import Any, Callable

from domain.entity import Entity, Item, are_hostile, is_ally
from domain.grid import Grid
from domain.dice import roll_2d6
from domain.movement import Terrain, can_enter, find_path
from domain.obstacle import is_full_obstacle
from domain.ai.components import COMPONENTS
from domain.pendulum import PendulumClock

from domain.explore import Trap, Clue, _move_ap_cost, ExploreMixin
from domain.lighting import LightMixin
from domain.ai.npc_runner import NpcBehaviorMixin
from domain.actions import ActionResolverMixin
from domain.stealth import StealthMixin
from domain.element import SurfaceEffectsMixin
from domain.world_features import TwigMixin
from domain.action_queue import ActionQueue
from domain.stealth_state import StealthState
from domain.ports import get_action_executor
from domain.events import DomainEvent, log_event, reaction_required, state_changed, turn_changed
from domain.damageable import is_destroyed
from domain.map.chunks import (
    DEFAULT_CHUNK_SIZE,
    ChunkCoord,
    chunk_for_position,
    chunks_around,
)


@dataclass
class GameState(LightMixin, NpcBehaviorMixin, ActionResolverMixin, StealthMixin, ExploreMixin, SurfaceEffectsMixin, TwigMixin):
    """全局游戏状态。"""

    # 仅作为构造迁移参数，不创建 player 属性；新代码应使用 controlled_entity。
    player: InitVar[Entity | None] = None
    map_width: int = 80
    map_height: int = 60
    chunk_size: int = DEFAULT_CHUNK_SIZE
    render_chunk_radius: int = 1

    # 地图
    map: Grid[Terrain] = field(init=False)
    current_map: str = ""
    map_exits: list[dict] = field(default_factory=list)
    loot_spots: list[dict] = field(default_factory=list)
    harvested_bushes: dict = field(default_factory=dict)  # {(col,row): 重生钟摆数}
    crops: dict = field(default_factory=dict)  # {(col,row): CropPlot}
    in_dungeon: bool = False
    world_state: dict | None = None
    location_map: dict[tuple[int, int], str] = field(default_factory=dict)

    # 元素地表状态 {pos: BurningSurface}
    burning_surfaces: dict[tuple[int, int], "BurningSurface"] = field(default_factory=dict)
    wet_surfaces: dict[tuple[int, int], int] = field(default_factory=dict)
    # 烧尽后成为平原、待再生的候选格
    regen_candidates: set[tuple[int, int]] = field(default_factory=set)
    # 雾气地表（§2.7：池塘上方，轻度遮蔽）
    fog_surfaces: set[tuple[int, int]] = field(default_factory=set)
    # 隐匿表（唯一持久游戏状态）{target_id → set[observer_id]}：目标对观察者隐匿，视野外保留
    hidden_from: dict[int, set[int]] = field(default_factory=dict)
    # 身后相邻格上次检定钟摆刻度 {(observer_id, target_id) → pendulum_count}
    spot_clock: dict[tuple[int, int], int] = field(default_factory=dict)
    # 观察者视野快照 {observer_id → set[target_id]}：判定"新进入视野"事件（纯技术字段）
    seen_snap: dict[int, set[int]] = field(default_factory=dict)
    # 隐匿状态的唯一领域容器；旧字段暂作为反序列化兼容别名指向此容器。
    stealth: StealthState = field(default_factory=StealthState, repr=False)

    # 陷阱与线索（阶段5）
    # 发现记忆表 spot_memo（阶段4.6 隐匿检测表同源机制）：{pos → discovered} 发现状态，进入视野被动感知一次性检定后保留
    spot_memo: dict[tuple[int, int], bool] = field(default_factory=dict)
    traps: list = field(default_factory=list)    # list[Trap]
    clues: list = field(default_factory=list)    # list[Clue]

    # 透明网格缓存（性能优化，阶段4.7）：地形版本号 + 缓存网格，仅含结构物品阻挡信息
    _terrain_version: int = field(default=0, repr=False)
    _transparent_cache: object = field(default=None, repr=False)
    # 地形特征索引（性能优化）：WATER / BUSH 坐标集合，随地形版本一并失效
    _water_tiles_cache: object = field(default=None, repr=False)
    _bush_tiles_cache: object = field(default=None, repr=False)

    # 实体
    entities: list[tuple[Entity, tuple[int, int]]] = field(default_factory=list)

    # 控制组件；控制权是实体组件，不是第二套实体存储。
    controlled_id: int | None = None
    _controlled_cache: Entity | None = field(default=None, repr=False)
    _spatial_cache: dict | None = field(default=None, repr=False)
    _render_chunks: frozenset[ChunkCoord] = field(
        default_factory=frozenset, repr=False
    )
    # 每次已提交的状态变化递增；Action 以此检测过期决策。
    state_version: int = 0
    events: list[DomainEvent] = field(default_factory=list, repr=False)
    _event_listeners: list[Callable[[DomainEvent], None]] = field(
        default_factory=list, repr=False
    )
    action_queue: ActionQueue = field(default_factory=ActionQueue, repr=False)
    action_executor: Any = field(default_factory=get_action_executor, repr=False)

    # 时间
    clock: PendulumClock = field(default_factory=PendulumClock)

    # 战斗
    in_combat: bool = False
    combat_initiative: list[Entity] = field(default_factory=list)
    current_turn_index: int = 0
    combat_turn_entity: Entity | None = None
    combat_phase: str = "idle"              # 攻击流程状态机: "idle"|"select_action"|"ranged_target"|"select_maneuver"|"select_special"
    pending_attack: dict | None = None      # 当前攻击上下文 {"mode":..., "weapon":..., "attack_roll":None, "target":None}

    # 光照与视野
    light_map: Grid | None = None
    environment_light: "LightLevel | None" = None  # 全局环境光照覆盖；None=按 in_dungeon（室外明亮/室内黑暗）
    light_sources: dict = field(default_factory=dict)          # {pos: (radius, LightLevel)}
    _light_version: int = field(default=0, repr=False)
    _light_cache_key: tuple | None = field(default=None, repr=False)
    _light_grid_cache: Grid | None = field(default=None, repr=False)
    fov_bright: set = field(default_factory=set)               # 明亮视野格子
    fov_dim: set = field(default_factory=set)                  # 微光视野格子
    fov_cache: set = field(default_factory=set)                # Deprecated: 兼容旧引用，返回 fov_bright | fov_dim
    _fov_cache_key: tuple | None = field(default=None, repr=False)
    maneuvers: list[dict] = field(default_factory=list)

    # 观察模式
    observe_mode: bool = False
    observe_cursor: tuple[int, int] = (0, 0)

    # 慢速模式
    slow_mode: bool = False

    # 击晕/杀害模式（阶段9）：True=击晕（近战致死→HP1+昏迷），False=杀害（默认）
    knockout_mode: bool = False

    # 交互系统
    interact_phase: str = ""              # "" | "menu" | "talking" | "trading"
    interact_targets: list = field(default_factory=list)
    interact_target: object | None = None  # 当前交互目标 (InteractTarget)
    shop_data: dict | None = None         # 当前交易中的商店数据

    # 偷窃系统（P1 3.3）
    steal_target: Entity | None = None    # 当前偷窃目标
    steal_stolen: list = field(default_factory=list)  # 本次会话已偷到物品
    steal_persuade_failures: int = 0       # 游说失败次数（3 次后敌对）
    steal_persuade_bonus: int = 0          # 游说难度累积加成（每次失败 +5）

    # 委托系统（P1 3.4）
    active_quests: list[str] = field(default_factory=list)    # 已接取未完成任务名
    completed_quests: list[str] = field(default_factory=list)  # 已完成（历史）任务名

    # 物品系统
    ground_items: list = field(default_factory=list)  # list[tuple[Item, tuple[int,int]]]
    item_menu_stack: list[dict] = field(default_factory=list)  # 物品交互菜单栈
    _twig_regrow_at: int = 0               # 下次树枝重生钟摆数

    pending_reactions: list = field(default_factory=list)
    oa_resume_npc_turn: Entity | None = None

    # NPC 推进回调设置的待开战目标
    pending_combat_target: Entity | None = None
    # 钟摆推进前刷新 FOV 的回调（由 app 注册）
    _pre_tick_fov_cb: Callable[[], None] | None = field(default=None, repr=False)
    # NPC 行为日志回调（由 app 注册，用于野兽进食/攻击等反馈）
    # AI 决策回调（由 app 注册，避免循环引用）
    _ai_decide_cb: Callable = field(default=None, repr=False)
    ai_engine: object | None = field(default=None, repr=False)

    def __post_init__(self, player: Entity | None = None):
        self.map = Grid[Terrain](self.map_width, self.map_height, Terrain.GRASS)
        # 统一历史字段与领域容器的存储对象，避免两套隐匿状态分叉。
        self.stealth.hidden_from = self.hidden_from
        self.stealth.spot_clock = self.spot_clock
        self.stealth.seen_snap = self.seen_snap
        self.stealth.spot_memo = self.spot_memo
        if player is not None:
            player.controlled = True
            self.add_entity(player, (0, 0))
        self.clock.set_npc_advance_callback(self._advance_npcs)
        self._NPC_ACTIONS = {
            "wander": self._npc_wander,
            "forage": self._npc_move_to_food,
            "eat_food": self._npc_eat_food,
            "pickup": self._npc_pickup,
            "hunt": self._npc_move_to_prey,  # 相邻攻击 + 不邻移动
            "collect": self._npc_collect,
            "eat_inventory": self._npc_eat_from_inventory,
            "open_door": self._npc_open_door,
            "close_door": self._npc_close_door,
            "attack_enemy": self._npc_attack_enemy,
            "approach_enemy": self._npc_approach_enemy,
            "flee": self._npc_flee,
            "rest": self._npc_rest,
            "idle": None,
            # 灭火自救 / 避火（阶段 14）
            "find_water": self._npc_find_water,
            "escape_fire": self._npc_move_away_from_fire,
            "avoid_fire": self._npc_move_away_from_fire,
            "roll": self._npc_roll,
            "hide": self._npc_hide,
            "search": self._npc_search,
            "stand_prone": self._npc_stand_prone,
            "stand_hiding": self._npc_stand_hiding,
        }

    # ---- 控制组件 ----

    def set_controlled(self, creature: Entity | None) -> None:
        """设置当前被玩家控制的生物。挂载控制组件，摘除 AI 组件（被控跳过 AI）。"""
        from domain.entity_components import ControlComponent, AIComponent
        from domain.ai.components import DEFAULT_BEHAVIOR
        if creature is not None and not any(c is creature for c, _ in self.entities):
            creature._control = ControlComponent(controlled=True)
            creature._ai = None
        for c, _ in self.entities:
            if c is creature:
                c._control = ControlComponent(controlled=True)
                c._ai = None  # 被控生物跳过 AI
            else:
                c._control = None
                if c._ai is None:
                    c._ai = AIComponent(
                        behavior_table=list(DEFAULT_BEHAVIOR["components"]),
                        behavior_overrides=dict(DEFAULT_BEHAVIOR["overrides"]),
                    )
        self.controlled_id = id(creature) if creature else None
        self._controlled_cache = creature
        self.state_version += 1

    @property
    def controlled_entity(self) -> Entity | None:
        """返回挂载 ControlComponent 的当前实体。"""
        cached = self._controlled_cache
        if cached is not None and cached.controlled:
            return cached
        for creature, _ in self.entities:
            if creature.controlled:
                self._controlled_cache = creature
                return creature
        return None

    @controlled_entity.setter
    def controlled_entity(self, creature: Entity | None) -> None:
        """设置受控实体；实体加入地图后由 add_entity 完成位置归属。"""
        if creature is not None:
            self.set_controlled(creature)
        else:
            self.set_controlled(None)

    @property
    def controlled_entity_pos(self) -> tuple[int, int] | None:
        """当前受控实体的位置。"""
        controlled = self.controlled_entity
        if controlled is not None:
            position = self.get_entity_pos(controlled)
            if position is not None:
                return position
        return self.__dict__.get("_controlled_pos_pending")

    @controlled_entity_pos.setter
    def controlled_entity_pos(self, value: tuple[int, int]) -> None:
        controlled = self.controlled_entity
        if controlled is None:
            self.__dict__["_controlled_pos_pending"] = tuple(value)
            return
        for index, (creature, _) in enumerate(self.entities):
            if creature is controlled:
                self.entities[index] = (creature, tuple(value))
                self.state_version += 1
                return
        self.__dict__["_controlled_pos_pending"] = tuple(value)

    def submit_action(self, action) -> None:
        """提交行动意图；调用方不得直接修改世界状态。"""
        self.action_queue.append(action)

    def subscribe_events(self, listener: Callable[[DomainEvent], None]) -> None:
        """注册领域事件监听器；保留 events 队列供旧调用方消费。"""
        self._event_listeners.append(listener)

    def unsubscribe_events(self, listener: Callable[[DomainEvent], None]) -> None:
        self._event_listeners.remove(listener)

    def emit_event(self, event: DomainEvent) -> None:
        self.events.append(event)
        for listener in tuple(self._event_listeners):
            try:
                listener(event)
            except Exception:
                continue

    def emit_log(self, message: str, category=None, position=None) -> None:
        """发布结构化日志；未指定分类时归入普通系统日志。"""
        from domain.events import LogCategory
        if category is None:
            combat_terms = ("命中", "未命中", "伤害", "重击", "死亡",
                            "战斗开始", "战斗结束", "获得状态", "失去状态")
            category = (
                LogCategory.COMBAT
                if any(term in message for term in combat_terms)
                else LogCategory.SYSTEM
            )
        if position is None:
            source = getattr(self, "_log_context_entity", None)
            if source is not None:
                position = self.get_entity_pos(source)
        self.emit_event(log_event(message, category, position=position))

    def emit_reaction_required(self) -> None:
        self.emit_event(reaction_required())

    def emit_turn_resume(self) -> None:
        self.emit_event(turn_changed(None))

    def execute_next_action(self) -> bool | None:
        """串行提交一个行动，事件处理器应只向队列追加后续行动。"""
        action = self.action_queue.pop()
        if action is None:
            return None
        result = self.action_executor.execute(self, action)
        self.emit_event(state_changed(self.state_version))
        return result

    def drain_events(self) -> list[DomainEvent]:
        """取出自上次调用后的领域事件，避免 UI 直接观察可变状态。"""
        events = self.events[:]
        self.events.clear()
        return events

    # ---- 实体管理 ----

    def add_entity(self, creature: Entity, pos: tuple[int, int]) -> None:
        # 实体的控制权只由 ControlComponent 决定。通过运行时入口加入的
        # 实体也必须遵守同一规则，避免出现“无控制且无 AI”的悬空实体。
        from domain.entity_components import AIComponent
        from domain.ai.components import DEFAULT_BEHAVIOR
        if creature._control is None and creature._ai is None:
            creature._ai = AIComponent(
                behavior_table=list(DEFAULT_BEHAVIOR["components"]),
                behavior_overrides=dict(DEFAULT_BEHAVIOR["overrides"]),
            )
        self.entities.append((creature, tuple(pos)))
        self.invalidate_spatial_cache()
        self.state_version += 1
        if self.is_burning(pos):
            self._ignite(creature, 5)

    def remove_entity(self, creature: Entity) -> None:
        self.entities = [(c, p) for c, p in self.entities if c is not creature]
        self.invalidate_spatial_cache()
        self._clean_entity_stealth(creature)
        self.state_version += 1

    def _clean_entity_stealth(self, creature: Entity) -> None:
        """实体死亡/移除时清理隐匿相关表条目。"""
        cid = id(creature)
        self.hidden_from.pop(cid, None)
        for obs in self.hidden_from.values():
            obs.discard(cid)
        self.seen_snap.pop(cid, None)
        for key in [k for k in self.spot_clock if cid in k]:
            del self.spot_clock[key]

    def get_entity_at(self, col: int, row: int) -> Entity | None:
        return self.spatial_cache()["entity_by_position"].get((col, row))

    def get_door_at(self, pos: tuple[int, int]):
        """返回指定位置的门物品。"""
        return next(
            (
                item
                for item, _ in self.spatial_cache()["ground_items_by_position"].get(
                    pos, ()
                )
                if item.name in ("打开的门", "关闭的门")
            ),
            None,
        )

    def is_door_open(self, pos: tuple[int, int]) -> bool:
        door = self.get_door_at(pos)
        return door is not None and door.name == "打开的门"

    def full_obstacles(self) -> list[dict]:
        """返回当前地图所有全身障碍，用于视线问题诊断。"""
        from domain.obstacle import is_full_obstacle

        result = []
        for entity, pos in self.entities:
            if not entity.is_dead and is_full_obstacle(entity):
                result.append({
                    "name": entity.name, "position": pos, "source": "entity",
                    "obstacle_type": entity.obstacle_type,
                    "block_value": entity.block_value,
                })
        for item, pos in self.ground_items:
            if is_full_obstacle(item):
                result.append({
                    "name": item.name, "position": pos, "source": "ground_item",
                    "obstacle_type": item.obstacle_type.value,
                    "block_value": item.block_value,
                })
        return result

    def iter_entities(self):
        """返回场上唯一的实体集合；控制组件不创建隐式实体。"""
        yield from self.entities

    def spatial_cache(self) -> dict:
        """返回当前状态的空间索引，状态变化后由移动/物品操作使其失效。"""
        if self._spatial_cache is None:
            entity_by_position = {}
            for creature, position in self.entities:
                entity_by_position.setdefault(position, creature)
            self._spatial_cache = {
                "entity_positions": {id(c): pos for c, pos in self.entities},
                "entity_by_position": entity_by_position,
                "ground_items_by_position": {},
                "item_positions": set(),
                "food_item_positions": set(),
                "bush_positions": set(),
                "entities_by_chunk": {},
                "ground_items_by_chunk": {},
                "alive_positions": {pos for c, pos in self.entities if not c.is_dead},
                "dead_positions": {pos for c, pos in self.entities if c.is_dead},
                "blocking_positions": {
                    pos for item, pos in self.ground_items
                    if is_full_obstacle(item)
                },
            }
            for item, pos in self.ground_items:
                self._spatial_cache["ground_items_by_position"].setdefault(
                    pos, []
                ).append((item, pos))
                self._spatial_cache["item_positions"].add(pos)
                if getattr(item, "effect", "") == "restore_food":
                    self._spatial_cache["food_item_positions"].add(pos)
                if "灌木" in getattr(item, "name", ""):
                    self._spatial_cache["bush_positions"].add(pos)
            for creature, pos in self.entities:
                chunk = chunk_for_position(pos, self.chunk_size)
                self._spatial_cache["entities_by_chunk"].setdefault(
                    chunk, []
                ).append((creature, pos))
            for item, pos in self.ground_items:
                chunk = chunk_for_position(pos, self.chunk_size)
                self._spatial_cache["ground_items_by_chunk"].setdefault(
                    chunk, []
                ).append((item, pos))
        return self._spatial_cache

    def update_render_chunks(
        self,
        center: tuple[int, int] | None = None,
    ) -> tuple[frozenset[ChunkCoord], frozenset[ChunkCoord]]:
        """更新玩家周边表现区块集合，返回进入区块和离开区块。"""
        position = center or self.controlled_entity_pos
        if position is None:
            return frozenset(), frozenset()
        next_chunks = chunks_around(
            position, self.render_chunk_radius, self.chunk_size
        )
        entered = next_chunks - self._render_chunks
        exited = self._render_chunks - next_chunks
        self._render_chunks = next_chunks
        return entered, exited

    def render_chunks(self) -> frozenset[ChunkCoord]:
        """返回当前表现层应加载的区块。"""
        return self._render_chunks

    def invalidate_spatial_cache(self) -> None:
        """地面物品或实体位置变化后失效空间索引及透明度缓存。"""
        self._spatial_cache = None
        self._transparent_cache = None
        self._visibility_cache = {}
        self._fov_cache_key = None

    def get_damageable_at(self, col: int, row: int):
        """兼容旧调用方：返回坐标上的第一个可伤害对象。"""
        return next(iter(self.get_damageables_at(col, row)), None)

    def get_damageables_at(self, col: int, row: int) -> list:
        """返回坐标上的全部可伤害对象，不对实体和物品排序取舍。"""
        result = []
        entity = self.spatial_cache()["entity_by_position"].get((col, row))
        if entity is not None and not entity.is_dead:
            result.append(entity)
        for item, _ in self.spatial_cache()["ground_items_by_position"].get(
            (col, row), ()
        ):
            if not is_destroyed(item) and (
                hasattr(item, "durability") or hasattr(item, "max_durability")
            ):
                result.append(item)
        return result

    def remove_destroyed_ground_items(self) -> list:
        """移除所有耐久归零的地面物品，并使空间缓存失效。"""
        destroyed = [
            item for item, _ in self.ground_items
            if is_destroyed(item)
        ]
        if not destroyed:
            return []
        self.ground_items = [
            entry for entry in self.ground_items
            if entry[0] not in destroyed
        ]
        self.invalidate_spatial_cache()
        return destroyed

    def get_entity_pos(self, target: Entity) -> tuple[int, int] | None:
        """查找生物在地图上的坐标。"""
        position = self.spatial_cache().get("entity_positions", {}).get(id(target))
        return position

    def check_combat_visibility(self, creature: Entity | None = None) -> bool:
        """当前生物脱离所有敌对实体视野时自动退出战斗。"""
        if not self.in_combat:
            return False
        creature = creature or self.controlled_entity
        if creature is None:
            return False
        from domain.visibility import can_see
        enemies = [
            entity for entity, _ in self.iter_entities()
            if entity is not creature
            and not entity.is_dead
            and are_hostile(creature, entity)
        ]
        if enemies and any(can_see(self, enemy, creature) for enemy in enemies):
            return False
        self.in_combat = False
        self.combat_initiative.clear()
        self.current_turn_index = 0
        self.combat_turn_entity = None
        self.pending_reactions.clear()
        self.pending_attack = None
        self.combat_phase = "idle"
        self.interact_phase = ""
        return True

    # ---- 移动 ----

    def move_player(self, col: int, row: int) -> bool:
        p = self.controlled_entity
        if p is None:
            return False
        if not p.meets_condition("can_move"):
            return False
        for i, (c, (ec, er)) in enumerate(self.entities):
            if c is p:
                if can_enter(col, row, self.map, self.entities, ec, er,
                             ground_items=self.ground_items,
                             tile_space_prebuilt=self.spatial_cache()):
                    self.entities[i] = (c, (col, row))
                    self._spatial_cache = None
                    self.state_version += 1
                    self._check_surface_effects(p)
                    self._check_traps(p, (col, row))
                    self.check_combat_visibility(p)
                    if not self.in_combat:
                        # 躲藏/倒地移动速度减半（阶段7.5/7.6：速度减半=每格消耗翻倍，
                        # 移动不自动解除躲藏/倒地，起身需独立 _do_stand）
                        halved = p.has_status("prone") or p.has_status("hiding")
                        speed = p.effective_speed / 2.0 if halved else p.effective_speed
                        self.clock.tick_move(speed)
                    # 移动自动转向（阶段2）
                    if (col - ec, row - er) != (0, 0):
                        p.facing = (col - ec, row - er)
                    self._offer_opportunities(p, (ec, er), (col, row))
                    return True
        return False

    def move_entity(self, creature: Entity, from_col: int, from_row: int,
                    to_col: int, to_row: int,
                    allow_non_adjacent: bool = False) -> bool:
        """移动非玩家实体。不能移动到玩家所在格。"""
        if not creature.meets_condition("can_move"):
            return False
        if can_enter(to_col, to_row, self.map, self.entities,
                     from_col, from_row,
                         allow_non_adjacent=allow_non_adjacent,
                         ground_items=self.ground_items,
                         tile_space_prebuilt=self.spatial_cache()):
            # 更新位置
            for i, (c, (ec, er)) in enumerate(self.entities):
                if c is creature and (ec, er) == (from_col, from_row):
                    self.entities[i] = (c, (to_col, to_row))
                    self._spatial_cache = None
                    self.state_version += 1
                    self._check_surface_effects(creature)
                    self._check_traps(creature, (to_col, to_row))
                    # 移动自动转向（阶段2）
                    creature.facing = (to_col - from_col, to_row - from_row)
                    return True
        return False

    def _player_reaction_pending(self) -> bool:
        return any(e.get("reactor") is not None and getattr(e["reactor"], "controlled", False)
                   for e in self.pending_reactions)

    def _offer_opportunities(self, mover, from_pos, to_pos) -> bool:
        from domain.combat.opportunity import collect_opportunity_reactors
        reactors = collect_opportunity_reactors(self, mover, from_pos, to_pos)
        player_stop = False
        for sequence, r in enumerate(reactors):
            event = {
                "kind": "opportunity_attack", "trigger": "movement",
                "mover": mover, "reactor": r, "registered_at": sequence,
            }
            if r.controlled:
                self.pending_reactions.append(event)
                self.emit_event(reaction_required(event["kind"]))
                player_stop = True
            else:
                self._resolve_npc_opportunity(event)
        return player_stop

    def _resolve_npc_opportunity(self, event: dict) -> None:
        from domain.combat.opportunity import REACTION_DEFS, default_melee_weapon, weapon_ap_cost
        from domain.combat.attack import resolve_attack
        reactor, mover = event["reactor"], event["mover"]
        weapon = default_melee_weapon(reactor)
        cost = weapon_ap_cost(weapon)
        kind = event["kind"]
        spec = REACTION_DEFS[kind]
        apos = self.get_entity_pos(reactor)
        visible = apos is not None and apos in self.fov_cache
        if reactor.ap < cost:
            if self.emit_log and visible:
                self.emit_log(spec["log_npc"].format(reactor=reactor.name, mover=mover.name)
                                 + "（AP 不足）")
            return
        reactor.ap -= cost
        mpos = self.get_entity_pos(mover)
        resolve_attack(reactor, mover, weapon, attacker_pos=apos, target_pos=mpos,
                       grid=self.map, ground_items=getattr(self, "ground_items", []))
        if self.emit_log and visible:
            self.emit_log(spec["log_npc"].format(reactor=reactor.name, mover=mover.name))

    def finish_player_reaction(self, abandoned: bool) -> None:
        if not self.pending_reactions:
            return
        self.pending_reactions.pop()
        self.interact_phase = ""
        if not abandoned:
            pass
        if self._player_reaction_pending():
            self.interact_phase = "reaction"
            self.emit_reaction_required()
            return
        self.resume_npc_advance()

    def resume_npc_advance(self) -> None:
        if self._player_reaction_pending():
            self.emit_reaction_required()
            return
        for creature, pos in list(self.entities):
            if not getattr(creature, "_oa_suspended", False):
                continue
            creature._oa_suspended = False
            path = getattr(creature, "_cached_path", None)
            if pos and path:
                arrived, _ = self._npc_move_along_path(creature, pos[0], pos[1], path)
                if arrived:
                    creature._cached_path = None
                    creature._path_target = None
                    creature._action_remaining_cost = 0
                if self._player_reaction_pending():
                    creature._oa_suspended = True
                    self.emit_reaction_required()
                    return
        npc = self.oa_resume_npc_turn
        if npc is not None:
            self.oa_resume_npc_turn = None
            self._npc_act(npc)
            if self._player_reaction_pending():
                self.emit_reaction_required()
                return
            self.emit_turn_resume()

    def _first_free_adjacent(self, origin: tuple[int, int]) -> tuple[int, int]:
        oc, orow = origin
        for radius in range(1, 32):
            for dc in range(-radius, radius + 1):
                for dr in range(-radius, radius + 1):
                    if max(abs(dc), abs(dr)) != radius:
                        continue
                    col, row = oc + dc, orow + dr
                    if can_enter(col, row, self.map, self.entities, oc, orow):
                        return (col, row)
        raise RuntimeError("无可用邻格复活")

    def extract_corpse_and_place(self, creature: Entity) -> None:
        corpse_name = getattr(creature.corpse, "name", None) if creature.corpse else None
        holder_pos = None
        for ent, pos in self.entities:
            inv = getattr(ent, "inventory", None) or []
            for item in list(inv):
                if corpse_name and item.name == corpse_name:
                    inv.remove(item)
                    holder_pos = pos
                    break
            if holder_pos:
                break
        if holder_pos is None:
            return
        dest = self._first_free_adjacent(holder_pos)
        for i, (c, _) in enumerate(self.entities):
            if c is creature:
                self.entities[i] = (c, dest)
                return
        self.entities.append((creature, dest))

    def _tick_all_statuses(self, delta: float = 1.0) -> None:
        """推进所有实体的状态计时。
        被控生物若在 entities 中则随迭代处理，否则单独处理。"""
        for creature, _ in self.entities:
            creature.tick_statuses(delta)
        p = self.controlled_entity
        if p is not None and not any(c is p for c, _ in self.entities):
            p.tick_statuses(delta)

    def _tick_mp_regen(self) -> None:
        """每钟摆魔法使自然恢复 MP：1d4 + 智力调整值 + 感知调整值。"""
        p = self.controlled_entity
        if not p or p.mp >= p.max_mp or p.char_class != "mage":
            return
        restore = random.randint(1, 4) + p.stat_adjust("int") + p.stat_adjust("wis")
        p.mp = min(p.max_mp, p.mp + restore)

    def _tick_food(self) -> None:
        """每钟摆所有非 food_locked 生物消耗 1 饮食值，归零后扣 HP。
        被控生物若在 entities 中则随迭代处理，否则单独处理。"""
        # 确保被控生物被处理（build_world 等可能清空 entities）
        all_creatures = list(self.entities)
        p = self.controlled_entity
        if p is not None and not any(c is p for c, _ in all_creatures):
            all_creatures.append((p, None))  # pos 占位
        for creature, _ in all_creatures:
            if creature.is_dead:
                continue
            # 临时：被控生物 HP 保底 1（玩家暂不可死亡，接入完整死亡流程后移除）
            if creature.controlled and creature.hp < 1:
                creature.hp = 1
            if creature.food_locked:
                continue
            # NPC 饥饿时优先吃背包食物（玩家手动吃，不自动）
            max_food = 15000
            if not creature.controlled and creature.food_value < max_food * 0.2 and creature.inventory:
                for item in list(creature.inventory):
                    if getattr(item, 'effect', '') == 'restore_food':
                        amt = item.amount
                        try:
                            val = int(amt)
                        except (ValueError, TypeError):
                            val = 2000
                        creature.food_value = min(max_food, creature.food_value + val)
                        # 堆叠食物：消耗 1 个
                        if item.count > 1:
                            unit_weight = item.weight / item.count
                            item.count -= 1
                            item.weight -= unit_weight
                        else:
                            creature.inventory.remove(item)
                        if self.emit_log:
                            self.emit_log(
                                f"{creature.name} 吃掉了背包里的{item.name}",
                                position=self.get_entity_pos(creature),
                            )
                        break
            creature.food_value = max(0, creature.food_value - 250)
            # 玩家饥饿/濒死提示
            if creature.controlled and self.emit_log:
                if creature.food_value == 3000:
                    self.emit_log("你感到饥饿，需要进食了")
                elif creature.food_value == 0 and creature.hp > 0:
                    self.emit_log("你快要饿死了！")
            if creature.food_value == 0:
                creature.take_damage(1, "starvation")
                # 死亡时 inventory + equipment 物品加入掉落（被控生物除外）
                if not creature.controlled and creature.is_dead:
                    loot = getattr(creature, 'loot', {}) or {}
                    always = loot.get('always', [])
                    # 背包物品
                    for item in creature.inventory:
                        always.append({
                            "name": item.name, "item_type": item.item_type,
                            "amount": item.count if hasattr(item, 'count') else 1,
                            "weight": item.weight, "price": item.price,
                            "effect": getattr(item, 'effect', ''),
                            "description": getattr(item, 'description', ''),
                        })
                    # 装备栏物品
                    for slot, item in creature.equipment.items():
                        if item is not None:
                            always.append({
                                "name": item.name, "item_type": item.item_type,
                                "amount": item.count if hasattr(item, 'count') else 1,
                                "weight": item.weight, "price": item.price,
                                "effect": getattr(item, 'effect', ''),
                                "description": getattr(item, 'description', ''),
                                "slot": slot,
                            })
                    if always:  # 只在有物品时更新
                        loot['always'] = always
                        creature.loot = loot

        p = self.controlled_entity
        if p is not None and p.is_dead:
            if self.emit_log:
                self.emit_log(f"{p.name} 饿死了……")
