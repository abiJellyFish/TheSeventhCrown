"""GameState —— 全局游戏状态，持有地图、实体、时间、战斗状态。"""

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from core.entity import Creature, Item, Player
from core.grid import Grid
from core.dice import roll_2d6
from core.movement import Terrain, can_enter, find_path
from core.ai.components import COMPONENTS
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
    harvested_bushes: dict = field(default_factory=dict)  # {(col,row): 重生钟摆数}
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

    # 物品系统
    ground_items: list = field(default_factory=list)  # list[tuple[Item, tuple[int,int]]]
    item_menu_stack: list[dict] = field(default_factory=list)  # 物品交互菜单栈

    # NPC 推进回调设置的待开战目标
    pending_combat_target: Creature | None = None
    # 钟摆推进前刷新 FOV 的回调（由 app 注册）
    _pre_tick_fov_cb: Callable[[], None] | None = field(default=None, repr=False)
    # NPC 行为日志回调（由 app 注册，用于野兽进食/攻击等反馈）
    _npc_log_cb: Callable[[str], None] | None = field(default=None, repr=False)
    # AI 决策回调（由 app 注册，避免循环引用）
    _ai_decide_cb: Callable = field(default=None, repr=False)

    def __post_init__(self):
        self.map = Grid[Terrain](self.map_width, self.map_height, Terrain.PASSABLE)
        self.clock.set_npc_advance_callback(self._advance_npcs)
        self._NPC_ACTIONS = {
            "wander": self._npc_wander,
            "forage": self._npc_move_to_food,
            "eat_food": self._npc_eat_food,
            "hunt": self._npc_move_to_prey,  # 相邻攻击 + 不邻移动
            "collect": self._npc_collect,
            "eat_inventory": self._npc_eat_from_inventory,
            "flee": self._npc_flee,
            "rest": self._npc_rest,
            "idle": None,
        }

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

    def _scan_context(self, creature, ec, er) -> dict:
        """扫描生物周围环境（只报告视野，不验证可达性）。"""
        body_type = getattr(creature, 'body_type', '')
        vr = getattr(creature, 'vision_range', 8)
        ctx = {"food_adjacent": False, "food_visible": False,
               "prey_nearby": False, "threat_nearby": False,
               "food_tiles": [], "prey_targets": []}

        for dc in range(-vr, vr + 1):
            for dr in range(-vr, vr + 1):
                if dc == 0 and dr == 0:
                    continue
                nc, nr = ec + dc, er + dr
                if not self.map.within_bounds(nc, nr):
                    continue
                dist = max(abs(dc), abs(dr))
                # 食物源
                if self.map[nc, nr] == Terrain.DIFFICULT and (nc, nr) not in self.stone_positions:
                    regrow_at = self.harvested_bushes.get((nc, nr))
                    if regrow_at is None or self.clock.pendulum_count >= regrow_at:
                        if dist <= 1:
                            ctx["food_adjacent"] = True
                        else:
                            ctx["food_visible"] = True
                        ctx["food_tiles"].append((dist, nc, nr, 'bush'))
                for item, (gi, gj) in self.ground_items:
                    if (gi, gj) == (nc, nr) and getattr(item, 'effect', '') == 'restore_food':
                        if dist <= 1:
                            ctx["food_adjacent"] = True
                        else:
                            ctx["food_visible"] = True
                        ctx["food_tiles"].append((dist, nc, nr, 'item'))
                # 猎物（智慧生物扫描）
                if body_type == 'humanoid':
                    ent = self.get_entity_at(nc, nr)
                    if ent and ent.hp > 0 and getattr(ent, 'body_type', '') == 'beast':
                        beast_loot = getattr(ent, 'loot', {}) or {}
                        has_food = False
                        for entries in beast_loot.values():
                            if isinstance(entries, list):
                                for e in entries:
                                    if isinstance(e, dict) and e.get('effect') == 'restore_food':
                                        has_food = True; break
                            if has_food: break
                        if has_food:
                            ctx["prey_nearby"] = True
                            ctx["prey_targets"].append((dist, ent, nc, nr))

        ctx["food_tiles"].sort(key=lambda x: x[0])
        ctx["prey_targets"].sort(key=lambda x: x[0])
        return ctx

    def _npc_move_along_path(self, creature, ec, er, path) -> tuple[bool, int]:
        """沿路径走 crossed 格，被挡截断。返回 (是否到达目标, 实际移动格数)。"""
        SCALE = 10
        maxS = creature.speed
        delta = 1.0  # 每钟摆
        potential = maxS * delta
        old_tiles = creature.curS_ticks // SCALE
        creature.curS_ticks += int(potential * SCALE)
        new_tiles = creature.curS_ticks // SCALE
        crossed = new_tiles - old_tiles
        creature.curS_ticks %= maxS * SCALE

        arrived = False
        actual_steps = 0
        nx, ny = ec, er
        for step in range(1, crossed + 1):
            if step >= len(path):
                arrived = True
                break
            tx, ty = path[step]
            # 检查是否被占
            blocked = False
            for c, (bc, br) in self.entities:
                if (bc, br) == (tx, ty) and c.hp > 0:
                    blocked = True
                    break
            if (tx, ty) == self.player_pos:
                blocked = True
            if blocked:
                creature._action_remaining_cost = 0  # 中断 → 下次立刻重新评估
                creature._cached_path = None
                creature._path_target = None
                break  # 截断
            self.move_entity(creature, nx, ny, tx, ty)
            nx, ny = tx, ty
            actual_steps += 1

        # 记录本 tick 移动距离（charge_bonus 判定用）
        creature._last_move_distance = actual_steps

        # 被挡 → 中断
        if not arrived and actual_steps < crossed:
            creature._action_remaining_cost = 0

        return arrived, actual_steps

    def _npc_wander(self, creature, ec, er, ctx) -> None:
        path = getattr(creature, '_cached_path', None)
        if path:
            arrived, _ = self._npc_move_along_path(creature, ec, er, path)
            if arrived:
                creature._cached_path = None
                creature._path_target = None

    def _npc_move_to_food(self, creature, ec, er, ctx) -> None:
        path = getattr(creature, '_cached_path', None)
        if path:
            arrived, _ = self._npc_move_along_path(creature, ec, er, path)
            if arrived:
                creature._cached_path = None
                creature._path_target = None
            if self._npc_log_cb and (ec, er) in self.fov_cache:
                self._npc_log_cb(f"{creature.name} 向食物移动")

    def _npc_eat_food(self, creature, ec, er, ctx) -> None:
        """相邻格有食物 -> 吃掉。"""
        max_food = 15000
        for _, tx, ty, ftype in ctx["food_tiles"]:
            if max(abs(tx - ec), abs(ty - er)) <= 1:
                if ftype == 'bush':
                    b = random.randint(2, 5)
                    creature.food_value = min(max_food, creature.food_value + b * 2000 // 5)
                    self.harvested_bushes[(tx, ty)] = self.clock.pendulum_count + 6
                    if self._npc_log_cb and (ec, er) in self.fov_cache:
                        self._npc_log_cb(f"{creature.name} 吃掉了灌木丛的浆果")
                    return
                elif ftype == 'item':
                    for item, (gi, gj) in list(self.ground_items):
                        if (gi, gj) == (tx, ty) and getattr(item, 'effect', '') == 'restore_food':
                            amt = item.amount
                            try:
                                val = int(amt)
                            except (ValueError, TypeError):
                                val = 2000
                            creature.food_value = min(max_food, creature.food_value + val)
                            self.ground_items.remove((item, (gi, gj)))
                            if self._npc_log_cb and (ec, er) in self.fov_cache:
                                self._npc_log_cb(f"{creature.name} 吃掉了地上的{item.name}")
                            return

    def _npc_move_to_prey(self, creature, ec, er, ctx) -> None:
        """hunt: 相邻→攻击，不邻→向猎物相邻格移动。"""
        targets = ctx["prey_targets"]
        if not targets:
            return
        _, prey, px, py = targets[0]

        # 相邻 → 攻击
        if max(abs(px - ec), abs(py - er)) <= 1:
            self._npc_attack_prey_impl(creature, prey)
            return

        # 不邻 → 沿路径移动
        path = getattr(creature, '_cached_path', None)
        if path:
            arrived, _ = self._npc_move_along_path(creature, ec, er, path)
            if arrived:
                creature._cached_path = None
                creature._path_target = None
            if self._npc_log_cb and (ec, er) in self.fov_cache:
                self._npc_log_cb(f"{creature.name} 向{prey.name}移动")

    def _npc_attack_prey_impl(self, creature, hunt_target) -> None:
        """攻击相邻猎物（含 charge_bonus）。"""
        # 查找 creature 位置用于 FOV 守卫
        pos = None
        for c, (ec_ent, er_ent) in self.entities:
            if c is creature:
                pos = (ec_ent, er_ent)
                break
        in_fov = pos is not None and pos in self.fov_cache
        max_food = 15000
        actions = getattr(creature, 'actions', []) or []
        if actions:
            act = actions[0]
            dmg_str = act.get('damage', '1d4')
            atk_stat = act.get('attack_stat', 'str')
            try:
                parts = dmg_str.split('d')
                dmg = sum(random.randint(1, int(parts[1])) for _ in range(int(parts[0])))
            except (ValueError, IndexError):
                dmg = random.randint(1, 4)
            # charge_bonus：按本 tick 移动距离判定（>=3 格触发）
            charge_str = act.get('charge_bonus', '')
            if charge_str:
                last_dist = getattr(creature, '_last_move_distance', 0)
                if last_dist >= 3:
                    try:
                        charge_parts = charge_str.split('d')
                        charge_dmg = sum(random.randint(1, int(charge_parts[1])) for _ in range(int(charge_parts[0])))
                    except (ValueError, IndexError):
                        charge_dmg = 0
                    dmg += charge_dmg
                    if self._npc_log_cb and in_fov:
                        self._npc_log_cb(f"{creature.name} 冲锋! 额外造成 {charge_dmg} 点伤害")
            atk_roll = random.randint(1, 20) + hunt_target.stat_adjust(atk_stat)
            if atk_roll >= hunt_target.total_ac('chest'):
                hunt_target.hp = max(0, hunt_target.hp - dmg)
                if self._npc_log_cb and in_fov:
                    self._npc_log_cb(f"{creature.name} 攻击了{hunt_target.name}，造成 {dmg} 点伤害")
                if hunt_target.hp <= 0:
                    self._resolve_hunt_loot(creature, hunt_target, max_food)
            elif self._npc_log_cb and in_fov:
                self._npc_log_cb(f"{creature.name} 攻击{hunt_target.name}未命中")

    def _resolve_hunt_loot(self, hunter, hunt_target, max_food) -> None:
        """捕猎击杀后 2d6 搜刮。"""
        roll = roll_2d6()
        loot = getattr(hunt_target, 'loot', {}) or {}
        taken = []
        remaining = {}
        for key, entries in loot.items():
            if key == "always":
                for e in entries:
                    if not isinstance(e, dict):
                        remaining.setdefault("always", []).append(e)
                        continue
                    item = Item.from_dict({**e, "count": e.get("amount", 1)})
                    if getattr(item, 'effect', '') == 'restore_food':
                        amt = item.amount
                        try:
                            val = int(amt)
                        except (ValueError, TypeError):
                            val = 2000
                        hunter.food_value = min(max_food, hunter.food_value + val)
                        taken.append(f"{item.name}(食用)")
                    else:
                        hunter.inventory.append(item)
                        taken.append(f"{item.name} x{item.count}")
            elif key.startswith("dc_"):
                dc = int(key.split("_")[1])
                for e in entries:
                    if isinstance(e, dict) and roll >= dc:
                        item = Item.from_dict({**e, "count": e.get("amount", 1)})
                        if getattr(item, 'effect', '') == 'restore_food':
                            amt = item.amount
                            try:
                                val = int(amt)
                            except (ValueError, TypeError):
                                val = 2000
                            hunter.food_value = min(max_food, hunter.food_value + val)
                            taken.append(f"{item.name}(食用)")
                        else:
                            hunter.inventory.append(item)
                            taken.append(f"{item.name} x{item.count}")
                    else:
                        remaining.setdefault(key, []).append(e)
        hunt_target.loot = remaining if remaining else {}
        hunt_target.inventory.clear()
        if self._npc_log_cb:
            items_str = "、".join(taken) if taken else "未获得物品"
            self._npc_log_cb(f"{hunter.name} 击杀了{hunt_target.name}(2d6={roll})，{items_str}")

    def _npc_collect(self, creature, ec, er, ctx) -> None:
        """采摘相邻格灌木丛或捡地上食物，放入背包。"""
        for _, tx, ty, ftype in ctx["food_tiles"]:
            if max(abs(tx - ec), abs(ty - er)) > 1:
                continue
            if ftype == 'bush':
                b = random.randint(2, 5)
                berry = Item.from_dict({
                    "name": "浆果", "type": "consumable",
                    "effect": "restore_food", "amount": "2000",
                    "ap_cost": 1, "weight": 0.1,
                    "price": {"cp": 2}, "description": "多汁的浆果",
                    "count": b,
                })
                creature.inventory.append(berry)
                self.harvested_bushes[(tx, ty)] = self.clock.pendulum_count + 6
                if self._npc_log_cb and (ec, er) in self.fov_cache:
                    self._npc_log_cb(f"{creature.name} 摘了一些浆果")
                return
            elif ftype == 'item':
                for item, (gi, gj) in list(self.ground_items):
                    if (gi, gj) == (tx, ty) and getattr(item, 'effect', '') == 'restore_food':
                        creature.inventory.append(item)
                        self.ground_items.remove((item, (gi, gj)))
                        if self._npc_log_cb and (ec, er) in self.fov_cache:
                            self._npc_log_cb(f"{creature.name} 捡起了地上的{item.name}")
                        return

    def _npc_eat_from_inventory(self, creature, ec, er, ctx) -> None:
        """吃背包里的食物。"""
        max_food = 15000
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
                if self._npc_log_cb and (ec, er) in self.fov_cache:
                    self._npc_log_cb(f"{creature.name} 吃掉了背包里的{item.name}")
                return

    def _npc_flee(self, creature, ec, er, ctx) -> None:
        path = getattr(creature, '_cached_path', None)
        if path:
            arrived, _ = self._npc_move_along_path(creature, ec, er, path)
            if arrived:
                creature._cached_path = None
                creature._path_target = None

    def _npc_idle(self, creature, ec, er, ctx) -> None:
        pass

    def _npc_rest(self, creature, ec, er, ctx) -> None:
        pass  # 原地不动，cost 由 _action_remaining_cost 消耗

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

    def _tick_food(self) -> None:
        """每钟摆所有非 food_locked 生物消耗 1 饮食值，归零后扣 HP。"""
        for creature in [self.player] + [c for c, _ in self.entities]:
            if creature.food_locked:
                continue
            # NPC 饥饿时优先吃背包食物（玩家手动吃，不自动）
            max_food = 15000
            if creature is not self.player and creature.food_value < max_food * 0.2 and creature.inventory:
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
            if creature.food_value == 0:
                creature.hp = max(0, creature.hp - 1)
                # 死亡时 inventory 物品加入掉落
                if creature.hp <= 0 and creature.inventory:
                    loot = getattr(creature, 'loot', {}) or {}
                    always = loot.get('always', [])
                    for item in creature.inventory:
                        always.append({
                            "name": item.name, "item_type": item.item_type,
                            "amount": item.count if hasattr(item, 'count') else 1,
                            "weight": item.weight, "price": item.price,
                            "effect": getattr(item, 'effect', ''),
                            "description": getattr(item, 'description', ''),
                        })
                    loot['always'] = always
                    creature.loot = loot
                    creature.inventory.clear()


    def _npc_evaluate_and_dispatch(self, creature, ec, er) -> None:
        """评估并分发一个动作。不可达目标会移除重试（最多3轮）。"""
        ctx = self._scan_context(creature, ec, er)
        creature._last_move_distance = 0

        for retry in range(3):
            extra_keys = set()
            if ctx["food_adjacent"]:
                extra_keys.add("env:food_adjacent")
            if ctx["food_visible"]:
                extra_keys.add("env:food_visible")
            if ctx["prey_nearby"]:
                extra_keys.add("env:prey_nearby")
            if ctx["threat_nearby"]:
                extra_keys.add("env:threat_nearby")
            for item in creature.inventory:
                if getattr(item, 'effect', '') == 'restore_food':
                    extra_keys.add("env:has_food")
                    break

            if self._ai_decide_cb:
                candidates = self._ai_decide_cb(creature, extra_keys)
            else:
                candidates = [("idle", 0.0)]

            if not candidates:
                return

            action, _ = candidates[0]
            comp = COMPONENTS.get(action)
            if comp is None:
                return

            creature._action_remaining_cost = comp.cost

            # 移动类：验证路径
            if action in ("forage", "hunt", "wander", "flee"):
                target = self._npc_get_move_target(action, creature, ec, er, ctx)
                if target is None:
                    return
                path = find_path(self.map, self.entities, (ec, er), target, self.player_pos)
                if path:
                    creature._cached_path = path
                    handler = self._NPC_ACTIONS.get(action)
                    if handler:
                        handler(creature, ec, er, ctx)
                    return
                else:
                    # 不可达 → 移除目标 → 重试
                    if action == "forage" and ctx["food_tiles"]:
                        ctx["food_tiles"].pop(0)
                        if not ctx["food_tiles"]:
                            ctx["food_visible"] = False
                    elif action == "hunt" and ctx["prey_targets"]:
                        ctx["prey_targets"].pop(0)
                        if not ctx["prey_targets"]:
                            ctx["prey_nearby"] = False
                    elif action in ("wander", "flee"):
                        return  # 不重试
                    continue

            # 非移动类：直接执行
            handler = self._NPC_ACTIONS.get(action)
            if handler:
                handler(creature, ec, er, ctx)
            return

    def _npc_get_move_target(self, action, creature, ec, er, ctx):
        """计算移动目标格。"""
        if action == "forage":
            tiles = ctx["food_tiles"]
            if not tiles:
                return None
            _, tx, ty, _ = tiles[0]
            best_adj, best_d = None, 999
            for adc in (-1, 0, 1):
                for adr in (-1, 0, 1):
                    anc, anr = tx + adc, ty + adr
                    if not self.map.within_bounds(anc, anr): continue
                    d = max(abs(anc - ec), abs(anr - er))
                    if d < best_d:
                        best_d, best_adj = d, (anc, anr)
            return best_adj or (tx, ty)
        elif action == "hunt":
            targets = ctx["prey_targets"]
            if not targets:
                return None
            _, prey, px, py = targets[0]
            best_adj, best_d = None, 999
            for adc in (-1, 0, 1):
                for adr in (-1, 0, 1):
                    anc, anr = px + adc, py + adr
                    if not self.map.within_bounds(anc, anr): continue
                    d = max(abs(anc - ec), abs(anr - er))
                    if d < best_d:
                        best_d, best_adj = d, (anc, anr)
            return best_adj or (px, py)
        elif action == "wander":
            vr = getattr(creature, 'vision_range', 8)
            for _ in range(5):
                tx = ec + random.randint(-vr, vr)
                ty = er + random.randint(-vr, vr)
                if self.map.within_bounds(tx, ty) and (tx, ty) != self.player_pos and self.map[tx, ty] != Terrain.WALL:
                    return (tx, ty)
            return None
        elif action == "flee":
            pc, pr = self.player_pos
            dx = -1 if pc > ec else (1 if pc < ec else random.choice([-1, 1]))
            dy = -1 if pr > er else (1 if pr < er else random.choice([-1, 1]))
            target = (ec + dx * 5, er + dy * 5)
            return (max(0, min(target[0], self.map_width-1)), max(0, min(target[1], self.map_height-1)))
        return None

    def _advance_npcs(self, delta: float) -> None:
        """delta 钟摆的 NPC 结算。"""
        self._tick_all_statuses()
        self._tick_food()
        if self.in_combat:
            return
        if self.player_pos in self.campfire_positions:
            self._check_campfire_burn(self.player)


        # 按 maxS 降序排序，同速按 ID
        sorted_entities = sorted(
            [(c, p) for c, p in self.entities if c is not self.player and c.hp > 0 and not c.has_status("不可移动")],
            key=lambda x: (-x[0].speed, id(x[0]))
        )

        for creature, (ec, er) in sorted_entities:
            # 刷新位置
            for _c, (_ec, _er) in self.entities:
                if _c is creature:
                    ec, er = _ec, _er
                    break

            # 忙碌中 → cost 倒计时
            if creature._action_remaining_cost > 0:
                creature._action_remaining_cost -= 1.0
                continue

            # 评估 + 执行
            self._npc_evaluate_and_dispatch(creature, ec, er)

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
        # 灌木丛重生
        for pos, regrow_at in list(self.harvested_bushes.items()):
            if self.clock.pendulum_count >= regrow_at:
                del self.harvested_bushes[pos]
