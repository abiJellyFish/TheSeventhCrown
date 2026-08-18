"""GameState —— 全局游戏状态，持有地图、实体、时间、战斗状态。"""

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

from core.explore import Trap, Clue, _move_ap_cost, ExploreMixin
from core.lighting import LightMixin
from core.ai.npc_runner import NpcBehaviorMixin
from core.actions import ActionResolverMixin
from core.stealth import StealthMixin
from core.element import SurfaceEffectsMixin
from core.world_features import TwigMixin


@dataclass
class GameState(LightMixin, NpcBehaviorMixin, ActionResolverMixin, StealthMixin, ExploreMixin, SurfaceEffectsMixin, TwigMixin):
    """全局游戏状态。"""

    player: Entity | None = None     # Phase 3: property 兼容层（Deprecated: 由 controlled_id 管理）
    map_width: int = 80
    map_height: int = 60
    player_pos: tuple[int, int] = field(default=(0, 0), repr=False)  # Phase 3: property 兼容层（Deprecated）

    # 地图
    map: Grid[Terrain] = field(init=False)
    current_map: str = ""
    map_exits: list[dict] = field(default_factory=list)
    loot_spots: list[dict] = field(default_factory=list)
    harvested_bushes: dict = field(default_factory=dict)  # {(col,row): 重生钟摆数}
    door_states: dict[tuple[int, int], bool] = field(default_factory=dict)
    in_dungeon: bool = False
    chests: dict[tuple[int,int], dict] = field(default_factory=dict)
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

    # 陷阱与线索（阶段5）
    # 发现记忆表 spot_memo（阶段4.6 隐匿检测表同源机制）：{pos → discovered} 发现状态，进入视野被动感知一次性检定后保留
    spot_memo: dict[tuple[int, int], bool] = field(default_factory=dict)
    traps: list = field(default_factory=list)    # list[Trap]
    clues: list = field(default_factory=list)    # list[Clue]

    # 透明网格缓存（性能优化，阶段4.7）：地形版本号 + 缓存网格，仅含 WALL 阻挡信息
    _terrain_version: int = field(default=0, repr=False)
    _transparent_cache: object = field(default=None, repr=False)
    # 地形特征索引（性能优化）：WATER / BUSH 坐标集合，随地形版本一并失效
    _water_tiles_cache: object = field(default=None, repr=False)
    _bush_tiles_cache: object = field(default=None, repr=False)

    # 实体
    entities: list[tuple[Entity, tuple[int, int]]] = field(default_factory=list)

    # 控制组件
    controlled_id: int | None = None
    _controlled_cache: Entity | None = field(default=None, repr=False)

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
    light_sources: dict = field(default_factory=dict)          # {pos: (radius, LightLevel)}
    fov_bright: set = field(default_factory=set)               # 明亮视野格子
    fov_dim: set = field(default_factory=set)                  # 微光视野格子
    fov_cache: set = field(default_factory=set)                # Deprecated: 兼容旧引用，返回 fov_bright | fov_dim
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

    # 物品系统
    ground_items: list = field(default_factory=list)  # list[tuple[Item, tuple[int,int]]]
    item_menu_stack: list[dict] = field(default_factory=list)  # 物品交互菜单栈
    _twig_regrow_at: int = 0               # 下次树枝重生钟摆数

    # NPC 推进回调设置的待开战目标
    pending_combat_target: Entity | None = None
    # 钟摆推进前刷新 FOV 的回调（由 app 注册）
    _pre_tick_fov_cb: Callable[[], None] | None = field(default=None, repr=False)
    # NPC 行为日志回调（由 app 注册，用于野兽进食/攻击等反馈）
    _npc_log_cb: Callable[[str], None] | None = field(default=None, repr=False)
    # AI 决策回调（由 app 注册，避免循环引用）
    _ai_decide_cb: Callable = field(default=None, repr=False)

    def __post_init__(self):
        self.map = Grid[Terrain](self.map_width, self.map_height, Terrain.GRASS)
        self.clock.set_npc_advance_callback(self._advance_npcs)
        # Deprecated Phase 3: 兼容旧 player 参数，从 instance __dict__ 读取（property 可能已拦截）
        _p = self.__dict__.get('_player_backup')
        _pp = self.__dict__.get('_player_pos_backup', (0, 0))
        if _p is not None:
            _p.controlled = True
            self.entities.append((_p, _pp))
            self.set_controlled(_p)
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
            "stand_prone": self._npc_stand_prone,
            "stand_hiding": self._npc_stand_hiding,
        }

    # ---- 控制组件 ----

    def set_controlled(self, creature: Entity | None) -> None:
        """设置当前被玩家控制的生物。挂载控制组件，摘除 AI 组件（被控跳过 AI）。"""
        from core.entity_components import ControlComponent, AIComponent
        from core.ai.components import DEFAULT_BEHAVIOR
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

    # ---- 实体管理 ----

    def add_entity(self, creature: Entity, pos: tuple[int, int]) -> None:
        self.entities.append((creature, pos))
        if self.is_burning(pos):
            self._ignite(creature, 5)

    def remove_entity(self, creature: Entity) -> None:
        self.entities = [(c, p) for c, p in self.entities if c is not creature]
        self._clean_entity_stealth(creature)

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
        for c, (ec, er) in self.entities:
            if (ec, er) == (col, row):
                return c
        return None

    def get_entity_pos(self, target: Entity) -> tuple[int, int] | None:
        """查找生物在地图上的坐标。"""
        for c, (ec, er) in self.entities:
            if c is target:
                return (ec, er)
        return None

    # ---- 移动 ----

    def move_player(self, col: int, row: int) -> bool:
        p = self.player
        if p is None:
            return False
        # 在 entities 中查找当前被控生物的位置并更新
        for i, (c, (ec, er)) in enumerate(self.entities):
            if c is p:
                if can_enter(col, row, self.map, self.entities, ec, er):
                    self.entities[i] = (c, (col, row))
                    self._check_surface_effects(p)
                    self._check_traps(p, (col, row))
                    if not self.in_combat:
                        # 躲藏/倒地移动速度减半（阶段7.5/7.6：速度减半=每格消耗翻倍，
                        # 移动不自动解除躲藏/倒地，起身需独立 _do_stand）
                        halved = p.has_status("prone") or p.has_status("hiding")
                        self.clock.tick_move(p.speed / 2.0 if halved else p.speed)
                    # 移动自动转向（阶段2）
                    if (col - ec, row - er) != (0, 0):
                        p.facing = (col - ec, row - er)
                    return True
        return False

    def move_entity(self, creature: Entity, from_col: int, from_row: int,
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
                    self._check_surface_effects(creature)
                    self._check_traps(creature, (to_col, to_row))
                    # 移动自动转向（阶段2）
                    creature.facing = (to_col - from_col, to_row - from_row)
                    return True
        return False
    def _tick_all_statuses(self) -> None:
        """每钟摆推进所有实体的状态计时。
        被控生物若在 entities 中则随迭代处理，否则单独处理。"""
        for creature, _ in self.entities:
            creature.tick_statuses()
        p = self.player
        if p is not None and not any(c is p for c, _ in self.entities):
            p.tick_statuses()

    def _tick_mp_regen(self) -> None:
        """每钟摆魔法使自然恢复 MP：1d4 + 智力调整值 + 感知调整值。"""
        p = self.player
        if not p or p.mp >= p.max_mp or p.char_class != "mage":
            return
        restore = random.randint(1, 4) + p.stat_adjust("int") + p.stat_adjust("wis")
        p.mp = min(p.max_mp, p.mp + restore)

    def _tick_food(self) -> None:
        """每钟摆所有非 food_locked 生物消耗 1 饮食值，归零后扣 HP。
        被控生物若在 entities 中则随迭代处理，否则单独处理。"""
        # 确保被控生物被处理（build_world 等可能清空 entities）
        all_creatures = list(self.entities)
        p = self.player
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
                        if self._npc_log_cb:
                            self._npc_log_cb(f"{creature.name} 吃掉了背包里的{item.name}")
                        break
            creature.food_value = max(0, creature.food_value - 250)
            # 玩家饥饿/濒死提示
            if creature.controlled and self._npc_log_cb:
                if creature.food_value == 3000:
                    self._npc_log_cb("你感到饥饿，需要进食了")
                elif creature.food_value == 0 and creature.hp > 0:
                    self._npc_log_cb("你快要饿死了！")
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

        p = self.player
        if p is not None and p.is_dead:
            if self._npc_log_cb:
                self._npc_log_cb(f"{p.name} 饿死了……")
# ═══════════════════════════════════════════════════
# player / player_pos 属性（Phase 1：替换 dataclass 字段为 property）
# 猴子补丁方式：dataclass __init__ 已生成但尚未创建实例时替换
# self.player = value → property setter → _player_backup
# __post_init__ 从 _player_backup 读取并加入 entities
# ═══════════════════════════════════════════════════

def _player_getter(self) -> Entity | None:
    """当前被玩家控制的生物（带缓存）。
    Phase 1 兼容：若 entities 中找不到，回退到 _player_backup。"""
    if '_controlled_cache' not in self.__dict__:
        return self.__dict__.get('_player_backup')
    if self._controlled_cache is not None and self._controlled_cache.controlled:
        return self._controlled_cache
    for c, _ in getattr(self, 'entities', []):
        if c.controlled:
            self._controlled_cache = c
            return c
    # 回退到备份（例如 build_world 清空 entities 后）
    self._controlled_cache = None
    return self.__dict__.get('_player_backup')


def _player_setter(self, value: Entity | None) -> None:
    """Phase 1 兼容：存储以便 __post_init__ 处理。"""
    self.__dict__['_player_backup'] = value


def _player_pos_getter(self) -> tuple[int, int] | None:
    """当前被控生物的位置。
    Phase 1 兼容：若 entities 中找不到，回退到 _player_pos_backup。"""
    for c, (ec, er) in getattr(self, 'entities', []):
        if c.controlled:
            return (ec, er)
    return self.__dict__.get('_player_pos_backup')


def _player_pos_setter(self, value: tuple[int, int]) -> None:
    """设置被控生物的位置：若在 entities 中则更新坐标，同时同步备份。"""
    self.__dict__['_player_pos_backup'] = value
    if hasattr(self, 'entities'):
        for i, (c, (ec, er)) in enumerate(self.entities):
            if c.controlled:
                self.entities[i] = (c, value)
                return


# 替换 dataclass 字段为 property（__init__ 已由 @dataclass 生成）
GameState.player = property(_player_getter, _player_setter)
GameState.player_pos = property(_player_pos_getter, _player_pos_setter)
