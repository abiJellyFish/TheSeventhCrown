"""NPC 行为执行层 —— 扫描上下文、各类行为实现、行为分派与 NPC 推进。"""
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
from core.explore import _move_ap_cost


class NpcBehaviorMixin:

    # ---- NPC 推进 ----

    def _scan_context(self, creature, ec, er) -> dict:
        """扫描生物周围环境（只报告视野，不验证可达性）。"""
        body_type = getattr(creature, 'body_type', '')
        vr = getattr(creature, 'vision_range', 8)
        # 事件驱动检定：NPC 进入/重算视野时对新进入视野实体被动感知
        self._on_fov_recompute(creature)
        ctx = {"food_adjacent": False, "food_visible": False,
               "prey_nearby": False, "threat_nearby": False,
               "food_tiles": [], "prey_targets": [],
               "nearby_items": [],
               "enemy_adjacent": False, "enemy_visible": False}

        # 预建物品位置索引（O(N) 一次性 → O(1) 查表）
        food_item_positions: set[tuple[int, int]] = set()
        all_item_positions: set[tuple[int, int]] = set()
        for item, (gi, gj) in self.ground_items:
            all_item_positions.add((gi, gj))
            if getattr(item, 'effect', '') == 'restore_food':
                food_item_positions.add((gi, gj))

        def _record_food(dist: int, nc: int, nr: int, kind: str) -> None:
            if dist <= 1:
                ctx["food_adjacent"] = True
            else:
                ctx["food_visible"] = True
            ctx["food_tiles"].append((dist, nc, nr, kind))

        # 灌木食物源（BUSH 地形索引直查，替代逐格扫描视野方形）
        for bc, br in self._get_bush_tiles():
            dc, dr = bc - ec, br - er
            if dc == 0 and dr == 0:
                continue
            if dc * dc + dr * dr > vr * vr:
                continue  # 欧几里得视野半径（圆形）
            dist = max(abs(dc), abs(dr))  # 切比雪夫：相邻判定 + 排序
            regrow_at = self.harvested_bushes.get((bc, br))
            if regrow_at is None or self.clock.pendulum_count >= regrow_at:
                _record_food(dist, bc, br, 'bush')

        # 地上食物（O(1) 查表）
        for fc, fr in food_item_positions:
            dc, dr = fc - ec, fr - er
            if dc == 0 and dr == 0:
                continue
            if dc * dc + dr * dr > vr * vr:
                continue  # 欧几里得视野半径（圆形）
            dist = max(abs(dc), abs(dr))  # 切比雪夫：相邻判定 + 排序
            _record_food(dist, fc, fr, 'item')

        # 猎物（智慧生物扫描视野内带食物战利品的野兽，直接遍历实体）
        if body_type == 'humanoid':
            for ent, (nc, nr) in self.entities:
                if ent is creature or ent.is_dead or getattr(ent, 'body_type', '') != 'beast':
                    continue
                if (nc - ec) ** 2 + (nr - er) ** 2 > vr * vr:
                    continue  # 欧几里得视野半径（圆形）
                dist = max(abs(nc - ec), abs(nr - er))  # 切比雪夫：排序
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

        # 相邻格（含自身格）是否有可捡取物品（O(1) 查表）
        items_nearby = False
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if (ec + dc, er + dr) in all_item_positions:
                    items_nearby = True
                    break
        ctx["items_nearby"] = items_nearby

        # 相邻格门状态
        door_nearby = False
        open_door_nearby = False
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                pos = (ec + dc, er + dr)
                if pos not in self.door_states:
                    continue
                if not self.door_states[pos]:
                    door_nearby = True
                else:
                    # 开启的门：检查是否无生物占据
                    if pos == self.player_pos:
                        continue
                    occupied = any((e2c, e2r) == pos and not c2.is_dead for c2, (e2c, e2r) in self.entities)
                    if not occupied:
                        open_door_nearby = True
        ctx["door_nearby"] = door_nearby
        ctx["open_door_nearby"] = open_door_nearby

        # 相邻格（含自身格）物品对象缓存（供 _npc_pickup 复用，避免重复遍历）
        nearby_items = []
        for item, (ic, ir) in self.ground_items:
            if max(abs(ic - ec), abs(ir - er)) <= 1:
                nearby_items.append((item, (ic, ir)))
        ctx["nearby_items"] = nearby_items

        # 敌人检测（统一走 are_hostile，无特例；身后扇区不感知，阶段2；隐匿过滤，阶段4）
        from core.movement import sector_of
        enemy_adjacent = False
        enemy_visible = False
        for c2, (e2c, e2r) in self.entities:
            if c2.is_dead or c2 is creature:
                continue
            if not are_hostile(creature, c2):
                continue
            if (e2c - ec) ** 2 + (e2r - er) ** 2 > vr * vr:
                continue  # 欧几里得视野半径（圆形）
            dist = max(abs(e2c - ec), abs(e2r - er))  # 切比雪夫：相邻判定
            # 身后 3 方向扇区不纳入视野（相邻一圈豁免：统一视野=相邻一圈∪面前扇形）
            if sector_of(creature.facing, (e2c - ec, e2r - er)) == "back" and dist > 1:
                continue
            # 隐匿过滤：敌方对观察者隐匿 → 不纳入考量
            if self._is_hidden_to(creature, c2, (e2c, e2r)):
                continue
            enemy_visible = True
            if dist <= 1:
                enemy_adjacent = True
                break
        ctx["enemy_adjacent"] = enemy_adjacent
        ctx["enemy_visible"] = enemy_visible

        # 缓存盟友数（供渲染使用，避免 O(N²)）
        ally_count = 0
        for c2, _ in self.entities:
            if is_ally(c2, creature) and not c2.is_dead and c2 is not creature:
                ally_count += 1
        creature._ally_count = ally_count

        return ctx

    def _npc_move_along_path(self, creature, ec, er, path) -> tuple[bool, int]:
        """沿路径走 crossed 格，被挡截断。返回 (是否到达目标, 实际移动格数)。

        速度→tick 统一走 _move_ap_cost：curS_ticks 每钟摆推进 SCALE ticks，
        整除 ticks_per_grid 得 crossed 格，余数留在 curS_ticks。全程整数运算。"""
        SCALE = 10
        halved = creature.has_status("hiding") or creature.has_status("prone")
        ticks_per_grid = _move_ap_cost(creature, halved=halved)

        creature.curS_ticks += SCALE
        crossed = creature.curS_ticks // ticks_per_grid
        creature.curS_ticks %= ticks_per_grid

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
                if (bc, br) == (tx, ty) and not c.is_dead:
                    blocked = True
                    break
            if (tx, ty) == self.player_pos:
                blocked = True
            if blocked:
                # 被挡 → 清缓存 + cost 归零 → 下次立刻重新评估
                creature._action_remaining_cost = 0
                creature._cached_path = None
                creature._path_target = None
                break  # 截断
            if not self.move_entity(creature, nx, ny, tx, ty):
                # 地形变化导致移动失败（如门关闭、生成新障碍）→ 视为中断
                if not arrived:
                    creature._action_remaining_cost = 0
                    creature._cached_path = None
                    creature._path_target = None
                break
            nx, ny = tx, ty
            actual_steps += 1

        # 恰好停在路径终点（path[-1] 即目标）→ 视为到达
        if not arrived and actual_steps > 0 and (nx, ny) == path[-1]:
            arrived = True

        # 记录本 tick 移动距离（charge_bonus 判定用）
        creature._last_move_distance = actual_steps

        # 不是被挡/失败，而是正常走完一部分 → 截断已走格，保持 path[0]==当前位置，
        # 使缓存路径可跨倍浪续走（游标化，方案A/11.1）
        if not arrived and actual_steps >= crossed and actual_steps > 0:
            creature._cached_path = path[actual_steps:]
            creature._path_target = path[-1]

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
                    from core.trade import _build_item_cache
                    berry_data = _build_item_cache().get("浆果", {})
                    berry_amount = int(berry_data.get("amount", 750))
                    b = random.randint(2, 5)
                    creature.food_value = min(max_food, creature.food_value + b * berry_amount)
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
                hunt_target.take_damage(dmg, act.get('damage_type', 'physical'))
                if self._npc_log_cb and in_fov:
                    self._npc_log_cb(f"{creature.name} 攻击了{hunt_target.name}，造成 {dmg} 点伤害")
                # 躲藏中攻击 → 暴露位置（阶段4）
                self._hide_attack_expose(creature, hunt_target)
                if hunt_target.is_dead:
                    self._resolve_hunt_loot(creature, hunt_target, max_food)
            elif self._npc_log_cb and in_fov:
                self._npc_log_cb(f"{creature.name} 攻击{hunt_target.name}未命中")
        else:
            # 无配置动作 → 兜底徒手攻击（1d4 钝击）
            dmg = random.randint(1, 4)
            atk_roll = random.randint(1, 20) + creature.stat_adjust("str")
            if atk_roll >= hunt_target.total_ac('chest'):
                hunt_target.take_damage(dmg, "bludgeoning")
                if self._npc_log_cb and in_fov:
                    self._npc_log_cb(f"{creature.name} 徒手攻击了{hunt_target.name}，造成 {dmg} 点伤害")
                self._hide_attack_expose(creature, hunt_target)
                if hunt_target.is_dead:
                    self._resolve_hunt_loot(creature, hunt_target, max_food)
            elif self._npc_log_cb and in_fov:
                self._npc_log_cb(f"{creature.name} 徒手攻击{hunt_target.name}未命中")

    def _resolve_hunt_loot(self, hunter, hunt_target, max_food) -> None:
        """捕猎击杀后 2d6 搜刮。使用 resolve_items 统一加载物品。货币直接入账。"""
        from core.trade import resolve_items, player_receive, price_to_text
        from core.loot import is_currency_entry
        roll = roll_2d6()
        loot = getattr(hunt_target, 'loot', {}) or {}
        taken = []
        for key, entries in loot.items():
            entries = [e for e in entries if isinstance(e, dict)]
            # 货币条目：直接入账（含 gp/sp/cp 且无 name）
            for e in entries:
                if is_currency_entry(e):
                    player_receive(hunter, e)
                    taken.append(price_to_text(e))
            # 物品条目：resolve_items 加载
            if key == "always":
                refs = [{"name": e["name"], "count": e.get("amount", e.get("count", 1))}
                        for e in entries if not is_currency_entry(e)]
                for item in resolve_items(refs):
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
                refs = [{"name": e["name"], "count": e.get("amount", e.get("count", 1))}
                        for e in entries if roll >= dc and not is_currency_entry(e)]
                for item in resolve_items(refs):
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
        hunt_target.inventory.clear()
        if taken and self._npc_log_cb:
            # 猎人或目标在 FOV 内才记录
            in_fov = False
            for c, (ec2, er2) in self.entities:
                if c is hunter or c is hunt_target:
                    if (ec2, er2) in self.fov_cache:
                        in_fov = True
                        break
            if in_fov:
                items_str = "、".join(taken)
                self._npc_log_cb(f"{hunter.name} 击杀了{hunt_target.name}(2d6={roll})，{items_str}")

    def _npc_collect(self, creature, ec, er, ctx) -> None:
        """采摘相邻格灌木丛或捡地上食物，放入背包。"""
        for _, tx, ty, ftype in ctx["food_tiles"]:
            if max(abs(tx - ec), abs(ty - er)) > 1:
                continue
            if ftype == 'bush':
                b = random.randint(2, 5)
                from core.trade import _load_item_by_key
                berry = _load_item_by_key("浆果")
                if berry:
                    berry.count = b
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

    def _npc_open_door(self, creature, ec, er, ctx) -> None:
        """打开相邻的关闭的门。"""
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                pos = (ec + dc, er + dr)
                if pos in self.door_states and not self.door_states[pos]:
                    self.door_states[pos] = True
                    if self._npc_log_cb and (ec, er) in self.fov_cache:
                        self._npc_log_cb(f"{creature.name} 打开了门")
                    return

    def _npc_close_door(self, creature, ec, er, ctx) -> None:
        """关闭相邻的开启的门（门格无生物时）。"""
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                pos = (ec + dc, er + dr)
                if pos not in self.door_states:
                    continue
                if not self.door_states[pos]:
                    continue
                if pos == self.player_pos:
                    continue
                occupied = any((e2c, e2r) == pos and not c2.is_dead for c2, (e2c, e2r) in self.entities)
                if occupied:
                    continue
                self.door_states[pos] = False
                if self._npc_log_cb and (ec, er) in self.fov_cache:
                    self._npc_log_cb(f"{creature.name} 关上了门")
                return

    def _npc_flee(self, creature, ec, er, ctx) -> None:
        path = getattr(creature, '_cached_path', None)
        if path:
            arrived, _ = self._npc_move_along_path(creature, ec, er, path)
            if arrived:
                creature._cached_path = None
                creature._path_target = None

    def _npc_find_water(self, creature, ec, er, ctx) -> None:
        """灭火自救：沿缓存路径向水源/潮湿地表移动一格。"""
        path = getattr(creature, '_cached_path', None)
        if path:
            arrived, _ = self._npc_move_along_path(creature, ec, er, path)
            if arrived:
                creature._cached_path = None
                creature._path_target = None
            if self._npc_log_cb and (ec, er) in self.fov_cache:
                self._npc_log_cb(f"{creature.name} 向水源移动")

    def _npc_move_away_from_fire(self, creature, ec, er, ctx) -> None:
        """逃离/避火：沿缓存路径远离火源移动。"""
        path = getattr(creature, '_cached_path', None)
        if path:
            arrived, _ = self._npc_move_along_path(creature, ec, er, path)
            if arrived:
                creature._cached_path = None
                creature._path_target = None

    def _npc_roll(self, creature, ec, er, ctx) -> None:
        """打滚灭火：消除灼烧，进入倒地状态（cost 由组件扣费）。"""
        creature.remove_status("灼烧")
        creature.add_status("prone", duration=None)
        if self._npc_log_cb and (ec, er) in self.fov_cache:
            self._npc_log_cb(f"{creature.name} 在地上打滚，扑灭了火焰")

    def _npc_hide(self, creature, ec, er, ctx) -> None:
        """NPC躲藏：有敌对可见且在遮蔽内时尝试躲藏（阶段4）。"""
        pos = (ec, er)
        if self._cover_level(pos) == "none":
            return  # 不在遮蔽内，不尝试
        if creature.has_status("hiding"):
            return  # 已在躲藏中
        self._do_hide(creature)

    def _npc_stand_prone(self, creature, ec, er, ctx) -> None:
        """主动起身（倒地）：解除倒地状态（cost 由 _do_stand 内部计费）。"""
        if creature.has_status("prone"):
            self._do_stand(creature)

    def _npc_stand_hiding(self, creature, ec, er, ctx) -> None:
        """主动起身（躲藏）：解除躲藏状态（cost 由 _do_stand 内部计费）。"""
        if creature.has_status("hiding"):
            self._do_stand(creature)

    def _npc_attack_enemy(self, creature, ec, er, ctx) -> None:
        """攻击相邻敌人。"""
        target = None
        best_dist = 999
        for c2, (e2c, e2r) in self.entities:
            if c2.is_dead or c2 is creature:
                continue
            if not are_hostile(creature, c2):
                continue
            dist = max(abs(e2c - ec), abs(e2r - er))
            if dist <= 1 and dist < best_dist:
                best_dist, target = dist, c2
        if target is None:
            return
        self._npc_attack_prey_impl(creature, target)

    def _npc_approach_enemy(self, creature, ec, er, ctx) -> None:
        """向最近敌人移动。"""
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

    # ═══════════════════════════════════════════════════
    # 通用动作系统（阶段3：动作面板框架 + 控制组件重构）
    # 动作核心 _do_* 全在 GameState（数据+规则层），UI/NPC 只做入口。
    # ═══════════════════════════════════════════════════


    def _npc_pickup(self, creature, ec, er, ctx):
        """捡取相邻及自身格的所有物品（复用 _scan_context 缓存的 nearby_items）。"""
        for item, pos in ctx.get("nearby_items", []):
            if (item, pos) not in self.ground_items:
                continue  # 已被其他生物捡走
            if creature.body_type == "beast":
                if getattr(item, 'effect', '') == 'restore_food':
                    food_val = getattr(item, 'amount', '500')
                    try:
                        val = int(food_val)
                    except (ValueError, TypeError):
                        val = 500
                    creature.food_value = min(15000, creature.food_value + val)
                    self.ground_items.remove((item, pos))
                    if self._npc_log_cb and (ec, er) in self.fov_cache:
                        self._npc_log_cb(f"{creature.name} 吃掉了地上的{item.name}")
            else:
                creature.inventory.append(item)
                self.ground_items.remove((item, pos))
                if self._npc_log_cb and (ec, er) in self.fov_cache:
                    self._npc_log_cb(f"{creature.name} 捡起了{item.name}")
                self._auto_equip_npc(creature, item)

    def _auto_equip_npc(self, creature, item):
        """NPC 拾取武器/护甲后自动装备到空闲槽位。"""
        if item.weapon is not None:
            if creature.equipment.get("right_hand") is None:
                creature.equipment["right_hand"] = item
                creature.inventory.remove(item)
                if self._npc_log_cb:
                    self._npc_log_cb(f"{creature.name} 装备了{item.name}(右手)")
            elif creature.equipment.get("left_hand") is None:
                creature.equipment["left_hand"] = item
                creature.inventory.remove(item)
                if self._npc_log_cb:
                    self._npc_log_cb(f"{creature.name} 装备了{item.name}(左手)")
        elif item.armor is not None:
            slot = getattr(item, 'slot', '')
            if slot and creature.equipment.get(slot) is None:
                creature.equipment[slot] = item
                creature.inventory.remove(item)
                if self._npc_log_cb:
                    self._npc_log_cb(f"{creature.name} 装备了{item.name}")



    def _npc_evaluate_and_dispatch(self, creature, ec, er, ctx: dict = None) -> None:
        """评估并分发一个动作。不可达目标会移除重试（最多3轮）。
        ctx: 可选的预建 _scan_context 结果，传入时跳过重复扫描。"""
        if ctx is None:
            ctx = self._scan_context(creature, ec, er)
        creature._last_move_distance = 0
        move_candidates = None

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
            if ctx.get("items_nearby"):
                extra_keys.add("env:items_nearby")
            for item in creature.inventory:
                if getattr(item, 'effect', '') == 'restore_food':
                    extra_keys.add("env:has_food")
                    break
            if ctx.get("door_nearby"):
                extra_keys.add("env:door_nearby")
            if ctx.get("open_door_nearby"):
                extra_keys.add("env:open_door_nearby")
            if ctx.get("enemy_adjacent"):
                extra_keys.add("env:enemy_adjacent")
            if ctx.get("enemy_visible"):
                extra_keys.add("env:enemy_visible")

            # 灭火自救/避火环境键（阶段 14）
            if self._find_nearest_water(creature, (ec, er)) is not None:
                extra_keys.add("env:water_visible")
            if self.is_burning((ec, er)):
                extra_keys.add("env:on_fire_tile")
            fire_traits = creature.temp_traits.get("fire", {})
            avoid_dist = fire_traits.get("avoid_dist", 0)
            if avoid_dist > 0:
                fire_positions = set(self.burning_surfaces.keys())
                if any(max(abs(f[0] - ec), abs(f[1] - er)) <= avoid_dist for f in fire_positions):
                    extra_keys.add("env:fire_nearby")

            if self._ai_decide_cb:
                candidates = self._ai_decide_cb(creature, extra_keys)
            else:
                candidates = [("idle", 0.0)]

            if not candidates:
                return

            action, _ = candidates[0]
            creature._current_action = action   # 缓存供渲染使用
            comp = COMPONENTS.get(action)
            if comp is None:
                return

            # 统一扣费：参战生物扣 AP（1 钟摆 = 10 AP），非参战扣钟摆
            in_combat_action = self.in_combat and creature in self.combat_initiative
            combat_cost = comp.cost * 10
            if in_combat_action and creature.ap < combat_cost:
                # AP 不足 → 尝试下一个候选动作
                candidates.pop(0)
                if not candidates:
                    break
                continue
            if in_combat_action:
                creature.ap -= combat_cost
            else:
                creature._action_remaining_cost = comp.cost

            # 移动类：验证路径（候选格 → 目标源 大小条件嵌套）
            if action in ("forage", "hunt", "wander", "flee", "approach_enemy",
                          "find_water", "escape_fire", "avoid_fire"):
                # 11.1 方案A：移动执行中复用缓存路径，不重新规划。
                # 缓存非空 = 实体仍在沿某段路径移动（未到达、未被挡）；到达/被挡时
                # handler 会清空 _cached_path，下一个钟摆才重新寻路规划。
                if getattr(creature, '_cached_path', None) is not None:
                    # 动作一致性守卫：缓存路径只被规划它的同一动作消费；
                    # 目标源已切换（wander→forage 等）→ 丢弃缓存重新规划
                    if getattr(creature, '_path_action', None) != action:
                        creature._cached_path = None
                        creature._path_target = None
                    else:
                        handler = self._NPC_ACTIONS.get(action)
                        if handler:
                            handler(creature, ec, er, ctx)
                            # cost 提前归零但路径未走完（如中途躲藏减速）→
                            # 重新覆盖路径时长，恢复"移动期间零评估"（仅非战斗）
                            if not in_combat_action:
                                rest = creature._cached_path
                                if rest:
                                    halved = creature.has_status("hiding") or creature.has_status("prone")
                                    tpg = _move_ap_cost(creature, halved=halved)
                                    creature._action_remaining_cost = max(
                                        comp.cost, -(-(len(rest) - 1) * tpg // 10))
                        return
                # 首次或候选格耗尽时重新获取
                if move_candidates is None:
                    move_candidates = self._npc_get_move_target(action, creature, ec, er, ctx)
                if not move_candidates:
                    move_candidates = None
                    continue
                target = move_candidates[0]
                # 视野内寻路：目标均在视野内选取，A* 限搜索半径 = 视野 + 1（候选格可能落在目标源相邻格）
                vr = getattr(creature, 'vision_range', 8)
                path = find_path(self.map, self.entities, (ec, er), target, self.player_pos,
                                 ground_items=self.ground_items, max_radius=vr + 1,
                                 door_positions=set(self.door_states.keys()))
                if path:
                    creature._cached_path = path
                    creature._path_target = target
                    creature._path_action = action
                    # 6.4：动作时长 = 路径时长（仅非战斗钟摆模型）。战斗走 AP 分支，
                    # 逐轮重评估（接近后切换攻击），不设钟摆 cost。
                    if not in_combat_action:
                        halved = creature.has_status("hiding") or creature.has_status("prone")
                        tpg = _move_ap_cost(creature, halved=halved)
                        path_ticks = -(-(len(path) - 1) * tpg // 10)  # ceil(grids * ticks/grid / 10)
                        creature._action_remaining_cost = max(comp.cost, path_ticks)
                    handler = self._NPC_ACTIONS.get(action)
                    if handler:
                        handler(creature, ec, er, ctx)
                    move_candidates = None
                    return
                else:
                    # 不可达 → 移除该候选格
                    move_candidates.pop(0)
                    if not move_candidates:
                        # 该目标所有候选格都不可达 → 移除整个目标源
                        if action == "forage" and ctx["food_tiles"]:
                            ctx["food_tiles"].pop(0)
                            if not ctx["food_tiles"]:
                                ctx["food_visible"] = False
                        elif action == "hunt" and ctx["prey_targets"]:
                            ctx["prey_targets"].pop(0)
                        move_candidates = None
                    # 继续 retry 循环（candidates 有余 → 用下一个；耗尽 → 重获取）

            # 非移动类：直接执行
            handler = self._NPC_ACTIONS.get(action)
            if handler:
                handler(creature, ec, er, ctx)
            return

    def _npc_get_move_target(self, action, creature, ec, er, ctx):
        """计算移动候选格列表。forage/hunt 返回所有合法相邻格按距离排序，wander/flee 返回单元素列表。"""
        if action == "forage":
            tiles = ctx["food_tiles"]
            if not tiles:
                return None
            _, tx, ty, _ = tiles[0]
            candidates = []
            for adc in (-1, 0, 1):
                for adr in (-1, 0, 1):
                    anc, anr = tx + adc, ty + adr
                    if not self.map.within_bounds(anc, anr):
                        continue
                    if is_full_cover(self.map[anc, anr]):
                        continue
                    d = max(abs(anc - ec), abs(anr - er))
                    candidates.append((d, (anc, anr)))
            candidates.sort(key=lambda x: x[0])
            return [p for _, p in candidates]

        elif action == "hunt":
            targets = ctx["prey_targets"]
            if not targets:
                return None
            _, prey, px, py = targets[0]
            candidates = []
            for adc in (-1, 0, 1):
                for adr in (-1, 0, 1):
                    anc, anr = px + adc, py + adr
                    if not self.map.within_bounds(anc, anr):
                        continue
                    if is_full_cover(self.map[anc, anr]):
                        continue
                    d = max(abs(anc - ec), abs(anr - er))
                    candidates.append((d, (anc, anr)))
            candidates.sort(key=lambda x: x[0])
            return [p for _, p in candidates]

        elif action == "wander":
            vr = getattr(creature, 'vision_range', 8)
            for _ in range(5):
                tx = ec + random.randint(-vr, vr)
                ty = er + random.randint(-vr, vr)
                if self.map.within_bounds(tx, ty) and (tx, ty) != self.player_pos and not is_full_cover(self.map[tx, ty]):
                    return [(tx, ty)]
            return None

        elif action == "flee":
            pc, pr = self.player_pos
            dx = -1 if pc > ec else (1 if pc < ec else random.choice([-1, 1]))
            dy = -1 if pr > er else (1 if pr < er else random.choice([-1, 1]))
            target = (ec + dx * 5, er + dy * 5)
            return [(max(0, min(target[0], self.map_width-1)), max(0, min(target[1], self.map_height-1)))]

        elif action == "approach_enemy":
            best_dist = 999
            best_enemy_pos = None
            for c2, (e2c, e2r) in self.entities:
                if c2.is_dead or c2 is creature:
                    continue
                if not are_hostile(creature, c2):
                    continue
                dist = max(abs(e2c - ec), abs(e2r - er))
                if dist < best_dist:
                    best_dist, best_enemy_pos = dist, (e2c, e2r)
            if best_enemy_pos is None:
                return None
            px, py = best_enemy_pos
            candidates = []
            for adc in (-1, 0, 1):
                for adr in (-1, 0, 1):
                    anc, anr = px + adc, py + adr
                    if not self.map.within_bounds(anc, anr):
                        continue
                    if is_full_cover(self.map[anc, anr]):
                        continue
                    d = max(abs(anc - ec), abs(anr - er))
                    candidates.append((d, (anc, anr)))
            candidates.sort(key=lambda x: x[0])
            return [p for _, p in candidates]

        elif action == "find_water":
            # 灭火自救：向最近水源/潮湿地表移动（候选为水源相邻可入格）
            target = self._find_nearest_water(creature, (ec, er))
            if target is None:
                return None
            candidates = []
            for adc in (-1, 0, 1):
                for adr in (-1, 0, 1):
                    anc, anr = target[0] + adc, target[1] + adr
                    if not self.map.within_bounds(anc, anr):
                        continue
                    if is_full_cover(self.map[anc, anr]):
                        continue
                    d = max(abs(anc - ec), abs(anr - er))
                    candidates.append((d, (anc, anr)))
            candidates.sort(key=lambda x: x[0])
            return [p for _, p in candidates]

        elif action in ("escape_fire", "avoid_fire"):
            # 逃离火源：向远离最近火源的方向移动 5 格
            fire_positions = set(self.burning_surfaces.keys())
            if not fire_positions:
                return None
            nearest = min(fire_positions, key=lambda f: max(abs(f[0] - ec), abs(f[1] - er)))
            dx = ec - nearest[0]
            dy = er - nearest[1]
            step_x = 1 if dx > 0 else (-1 if dx < 0 else random.choice([-1, 1]))
            step_y = 1 if dy > 0 else (-1 if dy < 0 else random.choice([-1, 1]))
            target = (ec + step_x * 5, er + step_y * 5)
            return [(max(0, min(target[0], self.map_width - 1)),
                     max(0, min(target[1], self.map_height - 1)))]

        return None

    def _npc_act(self, creature: Entity) -> None:
        """单个NPC的战斗回合：循环执行动作直到 AP 耗尽或无动作可做。

        受到伤害（_interrupted）时立即清除标记并重新评估，不继续原动作。
        """
        pos = self.get_entity_pos(creature)
        if pos is None:
            return
        ec, er = pos
        while creature.ap > 0:
            # 打断检查：受到伤害 → 清除标记，丢弃缓存动作并重新评估
            if getattr(creature, '_interrupted', False):
                creature._interrupted = False
                creature._cached_path = None
                creature._path_target = None
                creature._action_remaining_cost = 0
            ap_before = creature.ap
            self._npc_evaluate_and_dispatch(creature, ec, er)
            if creature.ap >= ap_before:
                break  # 无动作被执行（AP 未消耗）
            # 刷新位置（移动后）
            pos = self.get_entity_pos(creature)
            if pos is None:
                break
            ec, er = pos

    # ═══════════════════════════════════════════════════
    # 树枝生成（阶段8）
    # ═══════════════════════════════════════════════════


    def _advance_npcs(self, delta: float, combatants: bool = True) -> None:
        """delta 钟摆的 NPC 结算。

        combatants=True（默认）：参战生物仅首轮行动，非参战生物每轮行动。
        combatants=False：仅非参战生物行动（战斗满轮结算时使用）。

        无论是否参战，每个动作都通过 _npc_evaluate_and_dispatch 重新评估行动表，
        只是分配资源不同（参战扣 AP，非参战扣钟摆）。
        """
        self._tick_all_statuses()
        self._tick_mp_regen()
        self._tick_food()
        self._check_surface_effects(self.player)
        # 昏迷自然清醒累积（1500 钟摆，期间持续昏迷；失去昏迷后清零）
        for creature, _ in self.entities:
            creature.accumulate_comatose(delta)
        p = self.player
        if p is not None and not any(c is p for c, _ in self.entities):
            p.accumulate_comatose(delta)
        # 回合推进钩子：身后相邻格隐匿重检
        self._stealth_back_checks()

        # 元素反应引擎：燃烧/潮湿/地表再生
        from core.element import tick_surface_effects
        for msg in tick_surface_effects(self, delta):
            if self._npc_log_cb:
                self._npc_log_cb(msg)

        loops = max(1, int(delta))
        # 预建 _scan_context 缓存（id(creature) → ctx），loop 内复用避免重复扫描
        ctx_cache: dict[int, dict] = {}
        for loop_idx in range(loops):
            # 按 maxS 降序排序，同速按 ID；跳过被控生物
            sorted_entities = sorted(
                [(c, p) for c, p in self.entities if not c.controlled and not c.is_dead and not c.has_status("不可移动")],
                key=lambda x: (-x[0].speed, id(x[0]))
            )

            # 预建 id → pos 映射，避免逐实体 O(N) 线性查找（O(N²)→O(N)）
            pos_map = {id(c): (ec, er) for c, (ec, er) in self.entities}

            for creature, _ in sorted_entities:
                ec, er = pos_map[id(creature)]

                # 参战生物：仅在首轮行动（combatants=True 时），后续轮跳过
                in_initiative = creature in self.combat_initiative
                if in_initiative and loop_idx > 0:
                    continue

                # combatants=False 时跳过参战生物
                if not combatants and in_initiative:
                    continue

                # 濒死：掷死亡豁免，跳过行动（D24）
                if creature.has_status("濒死"):
                    # _roll_death_save 内部已处理 稳定(hp=1+昏迷)/苏醒(hp=1)/死亡
                    self._roll_death_save(creature)
                    continue

                # 忙碌中 → cost 倒计时（受伤害则打断当前动作，立即重新评估）
                if creature._action_remaining_cost > 0:
                    if getattr(creature, '_interrupted', False):
                        creature._interrupted = False
                        creature._action_remaining_cost = 0
                        creature._cached_path = None
                        creature._path_target = None
                    else:
                        creature._action_remaining_cost = max(0, creature._action_remaining_cost - 1.0)
                        # 11.1：忙碌 = 执行中，路径每钟摆续走（不重新评估）
                        path = getattr(creature, '_cached_path', None)
                        if path:
                            arrived, _ = self._npc_move_along_path(creature, ec, er, path)
                            if arrived:
                                creature._cached_path = None
                                creature._path_target = None
                                creature._action_remaining_cost = 0
                            # 移动后刷新 pos_map + 失效该实体 ctx（与评估路径行为一致）
                            new_pos = self.get_entity_pos(creature)
                            if new_pos and new_pos != (ec, er):
                                ctx_cache.pop(id(creature), None)
                                pos_map[id(creature)] = new_pos
                        continue

                # 评估 + 执行：复用缓存 ctx，实体移动后失效
                cid = id(creature)
                ctx = ctx_cache.get(cid)
                if ctx is None:
                    ctx = self._scan_context(creature, ec, er)
                    ctx_cache[cid] = ctx
                self._npc_evaluate_and_dispatch(creature, ec, er, ctx=ctx)
                # 移动后刷新 pos_map，供后续实体读取最新坐标；使该实体 ctx 缓存失效
                new_pos = self.get_entity_pos(creature)
                if new_pos:
                    if new_pos != (ec, er):
                        ctx_cache.pop(cid, None)
                    pos_map[id(creature)] = new_pos

        # 敌对检测：双方互相在视野内才触发战斗（跳过尸体与濒死）
        pc, pr = self.player_pos
        for creature, (ec, er) in self.entities:
            if creature.is_dead or creature.has_status("濒死"):
                continue
            if are_hostile(creature, self.player) and (ec, er) in self.fov_bright:
                vr = getattr(creature, 'vision_range', 0)
                if (ec - pc) ** 2 + (er - pr) ** 2 <= vr * vr:
                    self.pending_combat_target = creature
                    break
        # 灌木丛重生
        for pos, regrow_at in list(self.harvested_bushes.items()):
            if self.clock.pendulum_count >= regrow_at:
                del self.harvested_bushes[pos]
        # 树枝重生（阶段8）
        if self.clock.pendulum_count >= self._twig_regrow_at:
            self._regrow_twigs()
            self._twig_regrow_at = self.clock.pendulum_count + 3000


