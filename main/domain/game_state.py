"""GameState —— 全局游戏状态，持有地图、实体、时间、战斗状态。"""

import math
import random
from dataclasses import InitVar, dataclass, field
from typing import Any, Callable

from domain.entity import Entity, Item, are_hostile, is_ally
from domain.grid import Grid, DIRS_8
from domain.layers import LayerMap, SurfaceCell
from domain.dice import roll_2d6
from domain.movement import Terrain, can_enter, find_path, higher_surface_fills_volume
from domain.obstacle import is_full_obstacle
from domain.ai.components import COMPONENTS
from domain.pendulum import PendulumClock
from domain.death import DeathSystem

from domain.explore import Trap, Clue, _move_ap_cost, ExploreMixin
from domain.entity.status import movement_speed_halved
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
from domain.damageable import is_destroyed, purge_container, purge_equipment, purge_item_list
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
    world_layers: dict[int, LayerMap] = field(default_factory=dict)
    active_z: int = 0
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
    entities: list[tuple[Entity, tuple[int, int, int]]] = field(default_factory=list)
    party: list[Entity] = field(default_factory=list)
    max_party_size: int = 4

    # 多选小队成员移动（按 id 存储的选中集合）
    selected_party_members: set[int] = field(default_factory=set, repr=False)
    _party_move_curS: dict[int, int] = field(default_factory=dict, repr=False)

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
    death_system: DeathSystem = field(default_factory=DeathSystem, repr=False)

    # 战斗
    in_combat: bool = False
    combat_initiative: list[Entity] = field(default_factory=list)
    current_turn_index: int = 0
    combat_turn_entity: Entity | None = None
    combat_phase: str = "idle"              # 攻击流程状态机: "idle"|"select_action"|"ranged_target"|"select_maneuver"|"select_special"
    pending_attack: dict | None = None      # 当前攻击上下文 {"mode":..., "weapon":..., "attack_roll":None, "target":None}
    pending_rest_kind: str = ""
    selected_rest_members: set[int] = field(default_factory=set, repr=False)
    selected_dismiss_members: set[int] = field(default_factory=set, repr=False)

    # 光照与视野
    light_map: Grid | None = None
    environment_light: "LightLevel | None" = None  # 全局环境光照覆盖；None=按钟摆推导天光
    light_sources: dict = field(default_factory=dict)          # {(x,y,z): (radius, LightLevel)}
    _light_version: int = field(default=0, repr=False)
    _light_cache_key: tuple | None = field(default=None, repr=False)
    _light_grid_cache: Grid | None = field(default=None, repr=False)
    fov_bright: set = field(default_factory=set)               # 明亮视野格子
    fov_dim: set = field(default_factory=set)                  # 微光视野格子
    fov_cache: set = field(default_factory=set)                # Deprecated: 兼容旧引用，返回 fov_bright | fov_dim
    fov_by_entity: dict = field(default_factory=dict, repr=False)
    _fov_cache_key: tuple | None = field(default=None, repr=False)
    maneuvers: list[dict] = field(default_factory=list)

    # 观察模式
    observe_mode: bool = False
    observe_cursor: tuple[int, int] = (0, 0)
    observe_z: int | None = None
    observe_log_id: int | None = None
    entity_logs: dict[int, list[str]] = field(default_factory=dict, repr=False)
    height_view: bool = False

    # 慢速模式
    slow_mode: bool = False

    # 击晕/杀害模式（阶段9）：True=击晕（近战致死→HP1+昏迷），False=杀害（默认）
    knockout_mode: bool = False

    # 交互系统
    interact_phase: str = ""              # "" | "menu" | "target" | "trading"
    interact_targets: list = field(default_factory=list)
    interact_target: object | None = None  # 当前交互目标 (InteractTarget)
    shop_data: dict | None = None         # 当前交易中的商店数据

    # 偷窃系统（P1 3.3）
    steal_target: Entity | None = None    # 当前偷窃目标
    steal_stolen: list = field(default_factory=list)  # 本次会话已偷到物品
    steal_persuade_failures: int = 0       # 游说失败次数（3 次后敌对）
    steal_persuade_bonus: int = 0          # 游说难度累积加成（每次失败 +5）
    loot_selected: set = field(default_factory=set)
    loot_return_phase: str = ""

    # 委托系统（P1 3.4）
    active_quests: list[str] = field(default_factory=list)    # 已接取未完成任务名
    completed_quests: list[str] = field(default_factory=list)  # 已完成（历史）任务名

    # 物品系统
    ground_items: list = field(default_factory=list)  # list[tuple[Item, tuple[int,int,int]]]
    item_menu_stack: list[dict] = field(default_factory=list)  # 物品交互菜单栈
    pending_craft: dict = field(default_factory=dict)
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
        if not self.world_layers:
            self.world_layers = {
                0: LayerMap(self.map_width, self.map_height, Terrain.GRASS)
            }
        elif self.active_z not in self.world_layers:
            self.world_layers[self.active_z] = LayerMap(
                self.map_width, self.map_height, Terrain.GRASS,
                exists=self.active_z == 0,
            )
        # 统一历史字段与领域容器的存储对象，避免两套隐匿状态分叉。
        self.stealth.hidden_from = self.hidden_from
        self.stealth.spot_clock = self.spot_clock
        self.stealth.seen_snap = self.seen_snap
        self.stealth.spot_memo = self.spot_memo
        self._death_events_emitted: set[int] = set()
        self.death_system.bind(self)
        if player is not None:
            player.controlled = True
            self.add_entity(player, (0, 0))
            self.party = [player]
            player.party_member = True
            player.z = self.active_z
        self.clock.set_npc_advance_callback(self._advance_npcs)
        self._NPC_ACTIONS = {
            "wander": self._npc_wander,
            "forage": self._npc_move_to_food,
            "eat_food": self._npc_eat_food,
            "pickup": self._npc_pickup,
            "pickup_misc": self._npc_pickup_misc,
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
        """设置当前被玩家控制的生物。挂载控制组件，摘除 AI 组件（被控跳过 AI）。

        若传入成员已死亡，自动切换到小队中下一个存活成员；全灭则置空。
        """
        from domain.entity_components import ControlComponent, AIComponent
        from domain.ai.components import DEFAULT_BEHAVIOR
        if creature is not None and not self.party:
            self.party = [creature]
            creature.party_member = True
            creature.ally = False
        if creature is not None and self.party and creature not in self.party:
            raise ValueError("只能控制当前小队成员")
        if creature is not None and creature.is_dead:
            alive = [member for member in self.party if not member.is_dead]
            creature = alive[0] if alive else None
        if creature is not None and not any(c is creature for c, _ in self.entities):
            creature._control = ControlComponent(controlled=True)
            creature._ai = None
        for c, _ in self.entities:
            if c is creature:
                c._control = ControlComponent(controlled=True)
                c._ai = None  # 被控生物跳过 AI
            elif any(member is c for member in self.party):
                c._control = None
                c._ai = None  # 盟友由玩家依次控制，不进入 NPC 行动表
            else:
                c._control = None
                if c._ai is None:
                    c._ai = AIComponent(
                        behavior_table=list(DEFAULT_BEHAVIOR["components"]),
                        behavior_overrides=dict(DEFAULT_BEHAVIOR["overrides"]),
                    )
        self.controlled_id = id(creature) if creature else None
        self._controlled_cache = creature
        self.selected_party_members = {self.controlled_id} if self.controlled_id else set()
        self.state_version += 1

    def clear_group_move(self) -> None:
        """解除多选同行，恢复单独移动。"""
        self.selected_party_members = (
            {self.controlled_id} if self.controlled_id else set()
        )
        self._party_move_curS.clear()

    def add_party_member(self, creature: Entity) -> bool:
        """将场上实体加入小队；小队最多包含四名成员。"""
        if creature in self.party:
            return True
        if len(self.party) >= self.max_party_size or creature.is_dead:
            return False
        if not any(c is creature for c, _ in self.entities):
            raise ValueError("盟友必须先加入地图")
        self.party.append(creature)
        creature.party_member = True
        creature.ally = True
        creature._control = None
        creature._ai = None
        self.state_version += 1
        return True

    def remove_party_member(self, creature: Entity) -> bool:
        """遣散小队成员；当前受控者不能移出队伍。"""
        if creature not in self.party or creature is self.controlled_entity:
            return False
        self.party.remove(creature)
        creature.party_member = False
        creature.ally = False
        from domain.entity_components import AIComponent
        from domain.ai.components import DEFAULT_BEHAVIOR
        creature._control = None
        creature._ai = AIComponent(
            behavior_table=list(DEFAULT_BEHAVIOR["components"]),
            behavior_overrides=dict(DEFAULT_BEHAVIOR["overrides"]),
        )
        entity_id = id(creature)
        self.selected_party_members.discard(entity_id)
        self._party_move_curS.pop(entity_id, None)
        self.selected_dismiss_members.discard(entity_id)
        self.state_version += 1
        return True

    def next_controlled(self) -> Entity | None:
        """循环切换到下一名存活小队成员。"""
        alive = [member for member in self.party if not member.is_dead]
        if not alive:
            self.set_controlled(None)
            return None
        current = self.controlled_entity
        if current in alive:
            index = alive.index(current)
            target = alive[(index + 1) % len(alive)]
        else:
            start = self.party.index(current) if current in self.party else -1
            target = next(
                member for member in self.party[start + 1:] + self.party[:start + 1]
                if not member.is_dead
            )
        self.set_controlled(target)
        return target

    def is_game_over(self) -> bool:
        """所有当前小队成员死亡时结束旅途。"""
        return bool(self.party) and all(member.is_dead for member in self.party)

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
            if self.party and creature not in self.party:
                if any(member is creature for member, _ in self.entities):
                    if not self.add_party_member(creature):
                        raise ValueError("只能控制当前小队成员")
                else:
                    raise ValueError("只能控制当前小队成员")
            self.set_controlled(creature)
        else:
            self.set_controlled(None)

    @property
    def controlled_entity_pos(self) -> tuple[int, int, int] | None:
        """当前受控实体的三维位置。"""
        controlled = self.controlled_entity
        if controlled is not None:
            position = self.get_entity_pos(controlled)
            if position is not None:
                return position
        pending = self.__dict__.get("_controlled_pos_pending")
        if pending is not None and len(pending) == 2:
            return (pending[0], pending[1], 0)
        return pending

    @controlled_entity_pos.setter
    def controlled_entity_pos(self, value: tuple[int, int] | tuple[int, int, int]) -> None:
        controlled = self.controlled_entity
        if controlled is None:
            self.__dict__["_controlled_pos_pending"] = tuple(value)
            return
        for index, (creature, pos) in enumerate(self.entities):
            if creature is controlled:
                if len(value) == 2:
                    new_pos = (value[0], value[1], pos[2])
                else:
                    new_pos = tuple(value)
                self.entities[index] = (creature, new_pos)
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

    def emit_log(self, message: str, category=None, position=None,
                 related_ids=None) -> None:
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
        related: set[int] = set(related_ids or ())
        source = getattr(self, "_log_context_entity", None)
        if source is not None:
            related.add(id(source))
            if position is None:
                position = self.get_entity_pos(source)
        for creature, pos in self.entities:
            if message.startswith(creature.name):
                related.add(id(creature))
                if position is None:
                    position = pos
        self._record_entity_logs(message, position, related)
        self.emit_event(log_event(message, category, position=position))

    def _record_entity_logs(self, message: str, position, related: set[int]) -> None:
        pos3 = None
        if position is not None:
            pos3 = position if len(position) == 3 else (*position, self.active_z)
            occupant = self.get_entity_at(pos3[0], pos3[1], z=pos3[2])
            if occupant is not None:
                related.add(id(occupant))
            for entity_id, cells in self.fov_by_entity.items():
                if pos3 in cells:
                    related.add(entity_id)
        for entity_id in related:
            bucket = self.entity_logs.setdefault(entity_id, [])
            bucket.append(message)
            if len(bucket) > 500:
                self.entity_logs[entity_id] = bucket[-500:]

    def party_log_fov(self) -> set[tuple[int, int, int]]:
        """存活小队成员个人视野的并集；未计算时回退到渲染 fov_cache。"""
        members = [member for member in self.party if member is not None and not member.is_dead]
        cells: set[tuple[int, int, int]] = set()
        for member in members:
            for cell in self.fov_by_entity.get(id(member), ()):
                cells.add(cell if len(cell) == 3 else (*cell[:2], self.active_z))
        if cells:
            return cells
        fallback: set[tuple[int, int, int]] = set()
        for cell in self.fov_cache:
            fallback.add(cell if len(cell) == 3 else (*cell[:2], self.active_z))
        return fallback

    def notify_entity_death(self, creature: Entity) -> None:
        """发布实体首次真正死亡的事件和日志。"""
        entity_id = id(creature)
        if entity_id in self._death_events_emitted:
            return
        self._death_events_emitted.add(entity_id)
        from domain.events import entity_died
        self.emit_event(entity_died(entity_id, creature.name))
        self.emit_log(f"{creature.name}死亡")
        self.selected_party_members.discard(entity_id)
        self._party_move_curS.pop(entity_id, None)
        if self.controlled_entity is creature:
            self.next_controlled()

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

    def add_entity(self, creature: Entity, pos: tuple[int, int] | tuple[int, int, int]) -> None:
        # 实体的控制权只由 ControlComponent 决定。通过运行时入口加入的
        # 实体也必须遵守同一规则，避免出现“无控制且无 AI”的悬空实体。
        from domain.entity_components import AIComponent
        from domain.ai.components import DEFAULT_BEHAVIOR
        creature._death_callback = self.notify_entity_death
        creature._death_save_callback = self.death_system.on_enter_dying
        if creature._control is None and creature._ai is None:
            creature._ai = AIComponent(
                behavior_table=list(DEFAULT_BEHAVIOR["components"]),
                behavior_overrides=dict(DEFAULT_BEHAVIOR["overrides"]),
            )
        if len(pos) == 2:
            pos3 = (pos[0], pos[1], getattr(creature, "z", 0))
        else:
            pos3 = tuple(pos)
            creature.z = pos3[2]
        self.entities.append((creature, pos3))
        self.invalidate_spatial_cache()
        self.state_version += 1
        if self.is_burning(pos3[:2]):
            self._ignite(creature, 5)

    def advance_death_saves(self, delta: float) -> None:
        """推进所有濒死实体的独立死亡豁免计时。"""
        self.death_system.advance(delta)

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

    def get_entity_at(self, col: int, row: int, z: int | None = None) -> Entity | None:
        """返回指定高度层实体；省略高度时使用当前活动层。"""
        layer_z = self.active_z if z is None else int(z)
        if layer_z == self.active_z:
            return self.spatial_cache()["entity_by_position"].get((col, row))
        return next(
            (
                creature for creature, position in self.entities
                if position[2] == layer_z and position[:2] == (col, row)
            ),
            None,
        )

    def layer(self, z: int | None = None, create: bool = True) -> LayerMap:
        """返回指定高度层；create=False 时不创建空层，避免污染 world_layers。"""
        level = self.active_z if z is None else int(z)
        if level not in self.world_layers:
            if not create:
                return LayerMap(
                    self.map_width, self.map_height, Terrain.BARREN,
                    exists=False,
                )
            self.world_layers[level] = LayerMap(
                self.map_width, self.map_height, Terrain.BARREN,
                exists=level == 0,
            )
        return self.world_layers[level]

    def surface_at(self, position: tuple[int, int] | tuple[int, int, int],
                   z: int | None = None, create: bool = True) -> SurfaceCell:
        return self.layer(z, create=create).surface(tuple(position[:2]))

    def visible_surface_levels(self, position: tuple[int, int]) -> list[int]:
        """返回该坐标存在且可切片查看的高度层，最高层优先。"""
        col, row = position
        levels = [
            z for z, layer in self.world_layers.items()
            if layer.grid.within_bounds(col, row) and layer.surface(position).exists
        ]
        return sorted(levels, reverse=True)

    def surface_height_at(self, position: tuple[int, int]) -> int:
        """返回坐标上仍存在地表的最高绝对高度。"""
        levels = self.visible_surface_levels(position)
        return levels[0] if levels else self.active_z

    def _surface_height_grid(self) -> Grid[int]:
        grid = Grid[int](self.map_width, self.map_height, self.active_z)
        for row in range(self.map_height):
            for col in range(self.map_width):
                grid[col, row] = self.surface_height_at((col, row))
        return grid

    def observation_surface(self, position: tuple[int, int]) -> tuple[int, SurfaceCell]:
        """返回观察光标当前选中的绝对高度与地表。"""
        levels = self.visible_surface_levels_in_fov(position)
        # 纯面板测试/初始化阶段尚未计算 FOV；真实观察状态有非空缓存时不允许回退。
        if not levels and not self.fov_cache:
            levels = self.visible_surface_levels(position)[:1]
        z = self.observe_z if self.observe_z in levels else (
            levels[0] if levels else self.active_z
        )
        if not levels:
            return z, SurfaceCell(exists=False)
        return z, self.surface_at(position, z)

    def exposed_surface(self, position: tuple[int, int], visible=None):
        """返回视野中该坐标最高的露出地表。"""
        visible = self.fov_cache if visible is None else visible
        candidates = [
            z for z in self.visible_surface_levels(position)
            if (position[0], position[1], z) in visible
        ]
        if not candidates:
            return None
        z = candidates[0]
        return z, self.surface_at(position, z)

    def is_exposed_surface(self, position: tuple[int, int, int]) -> bool:
        """判断三维地表是否是当前视野内该坐标的最高露出层。"""
        exposed = self.exposed_surface(position[:2])
        return exposed is not None and exposed[0] == position[2]

    def is_column_in_fov(self, position: tuple[int, int]) -> bool:
        """该列是否有任一格进入三维视野。"""
        col, row = position
        return any(x == col and y == row for x, y, _ in self.fov_cache)

    def is_targetable_cell(self, cell: tuple[int, int, int]) -> bool:
        """瞄准光标可停留的三维格：视野内地表，或视野内球形视距中的空气。"""
        if cell in self.fov_cache:
            return True
        observer = self.controlled_entity
        if observer is None or not self.is_column_in_fov(cell[:2]):
            return False
        origin = self.get_entity_pos(observer) or (*self.observe_cursor, self.active_z)
        dx, dy, dz = (cell[0] - origin[0], cell[1] - origin[1],
                      cell[2] - getattr(observer, "z", self.active_z))
        return dx * dx + dy * dy + dz * dz <= observer.vision_range ** 2

    def visible_surface_levels_in_fov(self, position: tuple[int, int]) -> list[int]:
        """返回该坐标实际进入三维视野的地表层，最高层优先。"""
        levels = [
            z for z in self.visible_surface_levels(position)
            if (position[0], position[1], z) in self.fov_cache
        ]
        return levels[:1]

    def target_surface_levels_in_fov(self, position: tuple[int, int]) -> list[int]:
        """返回瞄准可选的所有视野内地表层，最高层优先。"""
        return [
            z for z in self.visible_surface_levels(position)
            if (position[0], position[1], z) in self.fov_cache
        ]

    def is_height_wall(self, position: tuple[int, int], z: int) -> bool:
        """该格是否是实心体积：本层登记为高度墙，或被更高地表填实（空洞除外）。"""
        layer = int(z)
        walls = getattr(self, "dungeon_wall_cells", set()) or set()
        if (*position, layer) in walls:
            return True
        return higher_surface_fills_volume(
            position[0], position[1], layer, self.world_layers, walls
        )

    def is_surface_edge(self, position: tuple[int, int], z: int) -> bool:
        """判断地表是否是高层地表与低层地表的边缘。"""
        if not self.surface_at(position, z).exists:
            return False
        col, row = position
        for dx, dy in DIRS_8:
            neighbor = (col + dx, row + dy)
            if not self.map.within_bounds(*neighbor):
                continue
            if self.surface_height_at(neighbor) < z:
                return True
        return False

    def is_xy_in_fov(self, position: tuple[int, int]) -> bool:
        """判断二维坐标是否有任一高度层进入视野。"""
        col, row = position
        return any(x == col and y == row for x, y, _ in self.fov_cache)

    def damageables_in_shape(
        self, anchor: tuple[int, int, int], shape: str,
        visible_only: bool = False,
    ) -> list:
        """收集三维形状内露出的实体与地面物品。"""
        from domain.combat.shape import shape_cells
        from domain.combat.shape import parse_shape
        cells = set(shape_cells(anchor, parse_shape(shape)))
        result = []
        if visible_only:
            cells = {
                cell for cell in cells
                if cell in self.fov_cache
                and self.surface_at(cell[:2], cell[2]).exists
                and self.is_exposed_surface(cell)
            }
        for creature, position in self.entities:
            if position in cells and self.surface_at(position[:2], position[2]).exists:
                result.append(creature)
        for item, position in self.ground_items:
            if position in cells and self.surface_at(position[:2], position[2]).exists:
                result.append(item)
        return result

    def damage_surface(self, position: tuple[int, int], amount: int,
                       z: int | None = None) -> int:
        layer_z = self.active_z if z is None else int(z)
        cell = self.surface_at(position, layer_z)
        was_exists = cell.exists
        remaining = self.layer(layer_z).damage_surface(position, amount)
        self._terrain_version += 1
        self.invalidate_spatial_cache()
        if was_exists and not cell.exists:
            self._relocate_objects_after_surface_loss(position, layer_z)
        return remaining

    def _relocate_objects_after_surface_loss(
        self, position: tuple[int, int], lost_z: int
    ) -> None:
        """地表消失后，将该层对象下沉到最近存在的地表。"""
        from domain.item_actions import find_placeable_position, place_on_ground
        col, row = position
        lowered_entities = []
        for creature, pos in self.entities:
            if pos == (col, row, lost_z):
                lowered = self._lowered_position(pos)
                creature.z = lowered[2]
                lowered_entities.append((creature, lowered))
            else:
                lowered_entities.append((creature, pos))
        self.entities = lowered_entities
        remaining_items = [
            entry for entry in self.ground_items
            if entry[1] != (col, row, lost_z)
        ]
        for item, _ in [
            entry for entry in self.ground_items
            if entry[1] == (col, row, lost_z)
        ]:
            target = find_placeable_position(
                remaining_items,
                self._lowered_position((col, row, lost_z)),
                item,
                self.world_layers,
            )
            if target is None:
                raise RuntimeError(f"地表下沉后没有物品可用位置: {(col, row, lost_z)}")
            place_on_ground(remaining_items, item, *target)
        self.ground_items = remaining_items
        self.invalidate_spatial_cache()

    def _lowered_position(self, position: tuple[int, int, int]) -> tuple[int, int, int]:
        """返回坐标下方最近存在的地表位置。"""
        col, row, z = position
        for lower_z in sorted((level for level in self.world_layers if level < z), reverse=True):
            if self.surface_at((col, row), lower_z).exists:
                return col, row, lower_z
        raise RuntimeError(f"对象下方没有存在地表: {position}")

    def set_active_z(self, z: int) -> None:
        """切换兼容二维地图入口，不移动实体。"""
        self.active_z = int(z)
        layer = self.layer(self.active_z)
        self.map = Grid(layer.width, layer.height, Terrain.BARREN)
        for row in range(layer.height):
            for col in range(layer.width):
                cell = layer.surface((col, row))
                if cell.exists:
                    self.map[col, row] = cell.terrain
        self.invalidate_spatial_cache()

    def climb_player(self, direction: int) -> bool:
        """按朝向逐层攀爬；direction=1 向高处，-1 向低处。"""
        creature = self.controlled_entity
        if creature is None or not creature.meets_condition("can_move"):
            return False
        position = self.get_entity_pos(creature)
        if position is None:
            return False
        target_z = creature.z + (1 if direction > 0 else -1)
        dx, dy = creature.facing
        flying = creature.fly_speed > 0
        hovering = creature.is_hovering and not flying
        if hovering and direction > 0:
            return False
        if flying or hovering:
            if target_z not in self.world_layers or target_z < 0:
                return False
            climb_cells = [position[:2]]
        elif direction < 0:
            climb_cells = [position[:2]] + [
                (position[0] + offset_x, position[1] + offset_y)
                for offset_x, offset_y in DIRS_8
                if self.map.within_bounds(
                    position[0] + offset_x, position[1] + offset_y
                )
            ]
        else:
            if (dx, dy) == (0, 0):
                return False
            climb_cells = [
                (position[0] + offset_x, position[1] + offset_y)
                for offset_x, offset_y in DIRS_8
                if dx * offset_x + dy * offset_y > 0
                and self.map.within_bounds(
                    position[0] + offset_x, position[1] + offset_y
                )
            ]
            climb_cells.sort(
                key=lambda cell: (
                    cell != (position[0] + dx, position[1] + dy),
                    abs(cell[0] - position[0]) + abs(cell[1] - position[1]),
                )
            )
        flying = creature.is_hovering or creature.fly_speed > 0
        if not can_enter(
            position[0], position[1], self.map, self.entities,
            allow_non_adjacent=True,
            ground_items=self.ground_items,
            surface_layers=self.world_layers,
            actor_z=target_z,
            can_fly=flying,
            height_walls=getattr(self, "dungeon_wall_cells", None),
        ):
            return False
        has_target_surface = any(
            self.surface_at(cell, target_z).exists for cell in climb_cells
        )
        has_vertical_hole = (
            direction < 0
            and not self.surface_at(position[:2], target_z).exists
            and any(
                self.surface_at(position[:2], z).exists
                for z in self.world_layers
                if z < target_z
            )
        )
        if not flying and not has_target_surface and not has_vertical_hole:
            return False
        if self.is_height_wall(position[:2], target_z):
            return False
        for index, (entity, entity_position) in enumerate(self.entities):
            if entity is creature:
                self.entities[index] = (entity, (*entity_position[:2], target_z))
                break
        creature.z = target_z
        self.active_z = target_z
        self.set_active_z(target_z)
        self.state_version += 1
        speed = creature.climb_speed or creature.effective_speed / 2
        self.clock.tick_move(speed)
        return True

    def release_player(self) -> bool:
        """解除攀附并逐层下降至可站立地表。已在实心地表上则不下降。"""
        creature = self.controlled_entity
        if creature is None or creature.is_hovering or creature.fly_speed > 0:
            return False
        position = next(
            (entity_position for entity, entity_position in self.entities
             if entity is creature),
            None,
        )
        if position is None:
            return False
        if self.surface_at(position[:2], creature.z, create=False).exists:
            return False
        return self.fall_player()

    def fall_player(self, save_ability: str | None = None) -> bool:
        """逐层检查坠落，落地后按最终高度差统一结算伤害。"""
        creature = self.controlled_entity
        if creature is None:
            return False
        # 坠落中的实体可能不在 active_z；空间缓存只索引当前切片，
        # 因此这里直接从实体容器读取二维位置。
        position = next(
            (entity_position for entity, entity_position in self.entities
             if entity is creature),
            None,
        )
        if position is None:
            return False
        start_z = creature.z
        landing_z = start_z
        landing = None
        while landing_z > -2:
            landing_z -= 1
            candidate = self.surface_at(position, landing_z)
            supported = candidate.exists
            if not supported and creature.meets_condition("can_move"):
                for dx, dy in DIRS_8:
                    neighbor = (position[0] + dx, position[1] + dy)
                    if (self.map.within_bounds(*neighbor)
                            and self.surface_at(neighbor, landing_z).exists):
                        supported = True
                        break
            if supported:
                landing = candidate
                break
        if landing is None:
            return False
        creature.z = landing_z
        for index, (entity, entity_position) in enumerate(self.entities):
            if entity is creature:
                self.entities[index] = (entity, (*entity_position[:2], landing_z))
                break
        distance = start_z - landing_z
        if distance > 1:
            from domain.combat.attack import roll_dice
            damage = roll_dice(distance - 1, 6)
            if landing.terrain is Terrain.WATER:
                from domain.checks import saving_throw
                if save_ability not in {"str", "dex"}:
                    save_ability = "str" if creature.stat("str") >= creature.stat("dex") else "dex"
                _, total = saving_throw(creature, save_ability)
                if total >= 15:
                    damage //= 2
            creature.take_damage(damage, "bludgeoning")
            creature.add_status("prone")
        self.active_z = landing_z
        self.set_active_z(landing_z)
        self.state_version += 1
        return True

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
                if position[2] == self.active_z:
                    entity_by_position.setdefault(position[:2], creature)
            self._spatial_cache = {
                "active_z": self.active_z,
                "entity_positions": {
                    id(c): pos for c, pos in self.entities
                    if pos[2] == self.active_z
                },
                "entity_by_position": entity_by_position,
                "ground_items_by_position": {},
                "item_positions": set(),
                "food_item_positions": set(),
                "bush_positions": set(),
                "entities_by_chunk": {},
                "ground_items_by_chunk": {},
                "alive_positions": {
                    pos[:2] for c, pos in self.entities
                    if not c.is_dead and pos[2] == self.active_z
                },
                "dead_positions": {
                    pos[:2] for c, pos in self.entities
                    if c.is_dead and pos[2] == self.active_z
                },
                "blocking_positions": set(),
            }
            for item, pos in self.ground_items:
                if pos[2] != self.active_z:
                    continue
                self._spatial_cache["ground_items_by_position"].setdefault(
                    pos[:2], []
                ).append((item, pos))
                self._spatial_cache["item_positions"].add(pos[:2])
                if getattr(item, "effect", "") == "restore_food":
                    self._spatial_cache["food_item_positions"].add(pos[:2])
                if "灌木" in getattr(item, "name", ""):
                    self._spatial_cache["bush_positions"].add(pos[:2])
            for creature, pos in self.entities:
                if pos[2] != self.active_z:
                    continue
                chunk = chunk_for_position(pos[:2], self.chunk_size)
                self._spatial_cache["entities_by_chunk"].setdefault(
                    chunk, []
                ).append((creature, pos))
            for item, pos in self.ground_items:
                if pos[2] != self.active_z:
                    continue
                chunk = chunk_for_position(pos[:2], self.chunk_size)
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

    def is_in_fov(self, position: tuple[int, int] | tuple[int, int, int]) -> bool:
        """检查位置是否在视野内。支持二维或三维坐标。
        
        二维坐标检查该坐标在当前活动层是否在视野内；三维坐标检查精确位置。
        """
        if len(position) == 3:
            return position in self.fov_cache
        col, row = position
        return (col, row, self.active_z) in self.fov_cache

    def get_damageable_at(self, col: int, row: int):
        """兼容旧调用方：返回坐标上的第一个可伤害对象。"""
        return next(iter(self.get_damageables_at(col, row)), None)

    def get_damageables_at(
        self, col: int, row: int, z: int | None = None,
        include_dead: bool = False,
    ) -> list:
        """返回指定高度层全部可伤害对象，不对实体和物品排序取舍。
        include_dead=True 时包含死亡实体（用于复活等瞄准面板）。"""
        layer_z = self.active_z if z is None else int(z)
        if layer_z != self.active_z:
            entity = self.get_entity_at(col, row, layer_z)
            result = [entity] if entity is not None and (include_dead or not entity.is_dead) else []
            for item, position in self.ground_items:
                if position[2] != layer_z or position[:2] != (col, row):
                    continue
                if not is_destroyed(item) and (
                    hasattr(item, "durability") or hasattr(item, "max_durability")
                ):
                    result.append(item)
            return result
        result = []
        entity = self.spatial_cache()["entity_by_position"].get((col, row))
        if entity is not None and (include_dead or not entity.is_dead):
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
        """移除耐久归零的地面/背包/装备/箱内物品，并使空间缓存失效。"""
        destroyed: list = []
        kept_ground = []
        for item, pos in self.ground_items:
            destroyed.extend(purge_container(item))
            if is_destroyed(item):
                destroyed.append(item)
            else:
                kept_ground.append((item, pos))
        self.ground_items = kept_ground
        for creature in self._iter_item_holders():
            destroyed.extend(purge_item_list(creature.inventory))
            destroyed.extend(purge_item_list(creature.accessories))
            destroyed.extend(purge_equipment(creature))
        if destroyed:
            self.invalidate_spatial_cache()
        return destroyed

    def _iter_item_holders(self):
        seen: set[int] = set()
        for creature, _pos in self.entities:
            cid = id(creature)
            if cid in seen:
                continue
            seen.add(cid)
            if getattr(creature, "_inventory", None) is None:
                continue
            yield creature

    def get_entity_pos(self, target: Entity) -> tuple[int, int, int] | None:
        """查找生物在地图上的三维坐标（含非当前活动层）。"""
        position = self.spatial_cache().get("entity_positions", {}).get(id(target))
        if position is not None:
            return position
        return next((pos for c, pos in self.entities if c is target), None)

    def check_combat_visibility(self, creature: Entity | None = None) -> bool:
        """参战敌对实体均看不见该生物时返回 True，表示应脱战。

        先攻没有存活敌对时返回 False。只检查 combat_initiative，不修改状态。
        """
        if not self.in_combat:
            return False
        creature = creature or self.controlled_entity
        if creature is None:
            return False
        from domain.visibility import can_see
        hostiles = [
            entity for entity in self.combat_initiative
            if entity is not creature
            and not entity.is_dead
            and are_hostile(creature, entity)
        ]
        if not hostiles:
            return False
        if any(can_see(self, enemy, creature) for enemy in hostiles):
            return False
        return True

    def is_engaged(self, creature: Entity | None = None) -> bool:
        """参战：该实体在先攻中，且先攻里有与其敌对的存活生物。"""
        creature = creature or self.controlled_entity
        if creature is None:
            return False
        if not any(participant is creature for participant in self.combat_initiative):
            return False
        return any(
            other is not creature
            and not other.is_dead
            and are_hostile(creature, other)
            for other in self.combat_initiative
        )

    def party_any_engaged(self) -> bool:
        """小队是否有人参战。"""
        return any(
            self.is_engaged(member)
            for member in self.party
            if not member.is_dead
        )

    # ---- 移动 ----

    def move_player(self, col: int, row: int) -> bool:
        p = self.controlled_entity
        if p is None:
            return False
        if not p.meets_condition("can_move"):
            return False
        for i, (c, (ec, er, ez)) in enumerate(self.entities):
            if c is p:
                target_z = p.z
                if (col - ec, row - er) != (0, 0):
                    p.facing = (col - ec, row - er)
                if can_enter(col, row, self.map, self.entities, ec, er,
                             ground_items=self.ground_items,
                             tile_space_prebuilt=self.spatial_cache(),
                             surface_layers=self.world_layers,
                             actor_z=target_z,
                             can_fly=p.is_hovering or p.fly_speed > 0,
                             height_walls=getattr(self, "dungeon_wall_cells", None)):
                    self.entities[i] = (c, (col, row, target_z))
                    self._spatial_cache = None
                    p.z = target_z
                    if target_z != self.active_z:
                        self.active_z = target_z
                        self.set_active_z(target_z)
                    self.state_version += 1
                    self._check_surface_effects(p)
                    self._check_traps(p, (col, row))
                    self._check_wall_support_or_fall(p)
                    if not self.in_combat:
                        halved = movement_speed_halved(p)
                        speed = p.effective_speed / 2.0 if halved else p.effective_speed
                        self.clock.tick_move(speed)
                    self._offer_opportunities(p, (ec, er), (col, row))
                    return True
        return False

    def _check_wall_support_or_fall(self, creature) -> None:
        """墙面上的横向移动后，失去同高度支撑时触发坠落。"""
        if creature.is_hovering or creature.fly_speed > 0:
            return
        position = self.get_entity_pos(creature)
        if position is None or self.surface_at(position[:2], creature.z).exists:
            return
        for dx, dy in DIRS_8:
            neighbor = (position[0] + dx, position[1] + dy)
            if (self.map.within_bounds(*neighbor)
                    and self.surface_at(neighbor, creature.z).exists):
                return
        if creature is self.controlled_entity:
            self.fall_player()

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
                         tile_space_prebuilt=self.spatial_cache(),
                         surface_layers=self.world_layers,
                         actor_z=creature.z,
                         can_fly=creature.is_hovering or creature.fly_speed > 0,
                         height_walls=getattr(self, "dungeon_wall_cells", None)):
            # 更新位置
            for i, (c, (ec, er, ez)) in enumerate(self.entities):
                if c is creature and (ec, er) == (from_col, from_row):
                    self.entities[i] = (c, (to_col, to_row, ez))
                    self._spatial_cache = None
                    self.state_version += 1
                    self._check_surface_effects(creature)
                    self._check_traps(creature, (to_col, to_row))
                    # 移动自动转向（阶段2）
                    creature.facing = (to_col - from_col, to_row - from_row)
                    return True
        return False

    def move_selected_followers(self, actor: Entity, delta: float) -> None:
        """根据当前受控者移动推进的钟摆数，移动所有被选中的跟随者。"""
        if delta <= 0:
            return
        actor_pos = self.get_entity_pos(actor)
        if actor_pos is None:
            return
        SCALE = 10
        for member in list(self.party):
            if member is actor or member.is_dead or id(member) not in self.selected_party_members:
                continue
            member_pos = self.get_entity_pos(member)
            if member_pos is None:
                continue
            target = self._party_follower_target(member_pos, actor_pos, member)
            if target is None:
                continue
            path = find_path(
                self.map, self.entities, member_pos, target,
                ground_items=self.ground_items,
                surface_layers=self.world_layers,
                actor_z=member.z,
                can_fly=member.is_hovering or member.fly_speed > 0,
            )
            if not path or len(path) < 2:
                continue
            halved = movement_speed_halved(member)
            ticks_per_grid = _move_ap_cost(member, halved=halved)
            curS = self._party_move_curS.get(id(member), 0)
            curS += int(SCALE * delta)
            steps = curS // ticks_per_grid
            self._party_move_curS[id(member)] = curS % ticks_per_grid
            from_pos = member_pos
            for i in range(min(steps, len(path) - 1)):
                next_pos = path[i + 1]
                if not self.move_entity(member, from_pos[0], from_pos[1], next_pos[0], next_pos[1]):
                    break
                from_pos = next_pos

    def _party_follower_target(
        self, follower_pos: tuple[int, int], actor_pos: tuple[int, int], follower: Entity
    ) -> tuple[int, int] | None:
        """为跟随者选取当前受控者相邻的可用目标格。"""
        candidates = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                pos = (actor_pos[0] + dc, actor_pos[1] + dr)
                if not self.map.within_bounds(pos[0], pos[1]):
                    continue
                if pos == follower_pos:
                    return pos
                if can_enter(
                    pos[0], pos[1], self.map, self.entities,
                    allow_non_adjacent=True,
                    ground_items=self.ground_items,
                    tile_space_prebuilt=self.spatial_cache(),
                    surface_layers=self.world_layers,
                    actor_z=follower.z,
                    can_fly=follower.is_hovering or follower.fly_speed > 0,
                    height_walls=getattr(self, "dungeon_wall_cells", None),
                ):
                    distance = max(abs(pos[0] - follower_pos[0]), abs(pos[1] - follower_pos[1]))
                    candidates.append((distance, pos))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _player_reaction_pending(self) -> bool:
        return any(e.get("reactor") is not None and getattr(e["reactor"], "controlled", False)
                   for e in self.pending_reactions)

    def _offer_opportunities(self, mover, from_pos, to_pos) -> bool:
        from domain.combat.opportunity import collect_opportunity_reactors, reaction_can_fire
        reactors = collect_opportunity_reactors(self, mover, from_pos, to_pos)
        player_stop = False
        for sequence, r in enumerate(reactors):
            event = {
                "kind": "opportunity_attack", "trigger": "movement",
                "mover": mover, "reactor": r, "registered_at": sequence,
            }
            if not r.controlled:
                self._resolve_npc_opportunity(event)
                continue
            if not reaction_can_fire(r, event):
                self.emit_log("AP 不足，无法借机")
                continue
            self.pending_reactions.append(event)
            self.emit_event(reaction_required(event["kind"]))
            player_stop = True
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
        visible = apos is not None and self.is_in_fov(apos)
        if reactor.ap < cost:
            if self.emit_log and visible:
                self.emit_log(spec["log_npc"].format(reactor=reactor.name, mover=mover.name)
                                 + "（AP 不足）")
            return
        reactor.ap -= cost
        mpos = self.get_entity_pos(mover)
        result = resolve_attack(reactor, mover, weapon, attacker_pos=apos, target_pos=mpos,
                       grid=self.map, ground_items=getattr(self, "ground_items", []))
        from domain.classes import available_abilities
        from domain.combat.tenacity import settle_attack_tenacity
        tenacity_action = (not result["hit"]) and "削韧" in available_abilities(reactor)
        settle_attack_tenacity(
            reactor, mover, weapon, result["roll"],
            tenacity_action=tenacity_action,
            combat_state=self,
            consume_extra=False,
            note_combo=False,
        )
        if self.emit_log and visible:
            self.emit_log(spec["log_npc"].format(reactor=reactor.name, mover=mover.name))

    def finish_player_reaction(self, abandoned: bool) -> None:
        if not self.pending_reactions:
            return
        self.pending_reactions.pop()
        self.interact_phase = ""
        from domain.combat.opportunity import reaction_can_fire
        while self._player_reaction_pending():
            event = self.pending_reactions[-1]
            if reaction_can_fire(event.get("reactor"), event):
                self.interact_phase = "reaction"
                self.emit_reaction_required()
                return
            self.pending_reactions.pop()
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

    def _first_free_adjacent(self, origin: tuple[int, int] | tuple[int, int, int]) -> tuple[int, int]:
        oc, orow = origin[0], origin[1]
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
        corpse = getattr(creature, "corpse", None)
        holder_pos = None
        for ent, pos in self.entities:
            inv = getattr(ent, "inventory", None) or []
            for item in list(inv):
                if corpse is not None and item is corpse:
                    holder_pos = pos
                    break
            if holder_pos:
                break
        if holder_pos is None:
            return
        dest = self._first_free_adjacent(holder_pos)
        for ent, _ in self.entities:
            if ent is creature:
                break
        else:
            raise ValueError("尸体实体不在地图上")
        # 先确认目标格，再变更背包，保证无空位时完整回滚。
        for ent, _ in self.entities:
            inv = getattr(ent, "inventory", None) or []
            if corpse in inv:
                inv.remove(corpse)
                break
        for i, (c, pos) in enumerate(self.entities):
            if c is creature:
                if len(dest) == 2:
                    dest3 = (dest[0], dest[1], pos[2])
                else:
                    dest3 = tuple(dest)
                self.entities[i] = (c, dest3)
                return
        self.entities.append((creature, dest3))

    def revive_entity(self, creature: Entity) -> tuple[int, int]:
        """原子复活实体并移至相邻空格，失败时不改变尸体或状态。"""
        if not creature.is_dead or creature.body_type == "undead":
            raise ValueError("目标不是可复活的非亡灵尸体")
        current_pos = self.get_entity_pos(creature)
        if current_pos is None:
            raise ValueError("尸体不在地图上")
        holder_pos = current_pos
        corpse = getattr(creature, "corpse", None)
        holder = None
        for ent, pos in self.entities:
            if corpse is not None and any(item is corpse for item in ent.inventory):
                holder, holder_pos = ent, pos
                break
        destination = self._first_free_adjacent(holder_pos)
        if holder is not None and corpse is not None:
            holder.inventory.remove(corpse)
        creature.revive()
        for index, (entity, pos) in enumerate(self.entities):
            if entity is creature:
                if len(destination) == 2:
                    dest3 = (destination[0], destination[1], pos[2])
                else:
                    dest3 = tuple(destination)
                self.entities[index] = (entity, dest3)
                self.invalidate_spatial_cache()
                return dest3
        raise ValueError("尸体实体不在地图上")

    def _tick_all_statuses(self, delta: float = 1.0) -> None:
        """推进所有实体的状态计时。
        被控生物若在 entities 中则随迭代处理，否则单独处理。"""
        for creature, _ in self.entities:
            creature.tick_statuses(delta)
        p = self.controlled_entity
        if p is not None and not any(c is p for c, _ in self.entities):
            p.tick_statuses(delta)

    def _tick_mp_regen(self, delta: float = 1.0) -> None:
        """每钟摆魔法使自然恢复 MP：1d4 + 智力调整值 + 感知调整值。"""
        p = self.controlled_entity
        if not p or p.mp >= p.max_mp or p.char_class != "mage":
            return
        base = p.stat_adjust("int") + p.stat_adjust("wis")
        restore = 0
        for _ in range(int(delta)):
            restore += random.randint(1, 4) + base
        p.mp = min(p.max_mp, p.mp + restore)

    def _tick_food(self, delta: float = 1.0) -> None:
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
            if creature.food_locked or getattr(creature, "_resting", False):
                continue
            # NPC 饥饿时优先吃背包食物（玩家手动吃，不自动）
            max_food = 15000
            if (
                not creature.controlled
                and not creature.party_member
                and creature.food_value < max_food * 0.2
                and creature.inventory
            ):
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
            spent = int(delta)
            old_food = creature.food_value
            creature.food_value = max(0, creature.food_value - spent)
            if creature.food_value > 0:
                creature.starve_pendulums = 0.0
            else:
                starved = spent - min(old_food, spent)
                creature.starve_pendulums += starved
                from domain.entity.status import STARVE_PENDULUMS, raise_exhaustion
                while creature.starve_pendulums >= STARVE_PENDULUMS:
                    creature.starve_pendulums -= STARVE_PENDULUMS
                    raise_exhaustion(creature, 1)
            # 玩家饥饿提示
            if creature.controlled and self.emit_log:
                if creature.food_value == 3000:
                    self.emit_log("你感到饥饿，需要进食了")
                elif creature.food_value == 0 and old_food > 0:
                    self.emit_log("你开始挨饿")
