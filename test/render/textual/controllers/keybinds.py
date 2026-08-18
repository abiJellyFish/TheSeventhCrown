"""按键分发 —— on_key、_dispatch_key、action_* 行动方法。"""
import json
import os
import random
from core.game_state import GameState, _move_ap_cost
from core.entity import Entity, Weapon, are_hostile
import core.entity as ent
from core.movement import Terrain, find_path
from core.fov import LightLevel, compute_fov
from core.combat.initiative import roll_initiative
from core.combat.attack import (hit_check, roll_damage, reduce_tenacity,
    apply_damage_type_modifiers, parse_dice, roll_dice, resolve_attack,
    miss_message, cover_message, normalize_damage_type)
from core.combat.flow import CombatFlow
from core.map.generation import build_world, build_dungeon
from core.dice import roll_d20, check_dc, roll_2d6
from core.ai.engine import BehaviorEngine
from core.rest import short_rest, long_rest
from core.loader import DataLoader, _load_dialogues, _load_scene_actions
from core.save.database import SaveManager
from core.interact import InteractType, scan_interact_targets
from core.trade import (load_shop, trade_buy, trade_sell, price_to_text,
    copper_to_currency, shop_gold_text, player_receive, _build_item_cache,
    resolve_items, _load_item_by_key)
from core.item_actions import (get_item_actions, find_placeable_tile,
    place_on_ground, remove_from_inventory as item_remove_from_inventory,
    copy_item_with_count, get_throw_range, get_throw_max_range,
    tile_space_used, MAX_TILE_SPACE)
from core.loot import _add_to_inventory
from render.textual.fov import _update_fov


from textual.events import Key


class KeybindMixin:

    def on_key(self, event) -> None:
        """上下文感知的按键分发：只有当前面板显示的键才触发。"""
        key = event.key
        state = self._state

        # ── 0. Escape：输入框唤醒时关闭它；瞄准阶段取消瞄准；否则无操作 ──
        if key == "escape":
            if self._input_bar and not self._input_bar.disabled:
                self._close_input()
                event.stop()
                return
            if state and state.combat_phase == "ranged_target":
                self.action_cancel_ranged_target()
                event.stop()
                return
            return

        # ── 1. 输入栏聚焦时 → 不响应任何快捷键 ──
        if self._input_bar and self._input_bar.has_focus:
            return

        # ── 2. 合并活跃视图的按键集（当前页面显示什么才允许触发什么）──
        if state is None:
            return
        allowed = set()
        for view_name in self._get_active_views():
            vdef = self.VIEW_DEFS.get(view_name, {})
            keys = vdef.get("keys", set())
            if not isinstance(keys, set):
                keys = set()
            allowed |= keys

        if key not in allowed:
            return

        # ── 3. 分发：交互阶段优先；否则走通用分发 ──
        if state.interact_phase:
            if self._try_interact_key(key):
                event.stop()
                return
        self._dispatch_key(key)
        event.stop()

    def _dispatch_key(self, key: str) -> None:
        """根据按键分发到对应的 action 方法。"""
        actions = {
            "0": self.action_interact,
            "N": self.action_show_actions_menu,
            "F": self.action_toggle_knockout,
            "g": self.action_slow_speed,
            "G": self.action_dash,
            "r": self.action_short_rest,
            "R": self.action_long_rest,
            "comma": self.action_wait,
            "X": self.action_toggle_observe,
            "A": self.action_show_actions,
            "S": self.action_show_spells,
            "C": self.action_char_panel,
            "I": self.action_inventory,
            "B": self.action_spellbook,
            "Z": self.action_crafting,
            "K": self.action_cooking,
            "Y": self.action_alchemy,
            "H": self.action_height_view,
            "M": self.action_map_overview,
            "E": self.action_system_menu,
            "enter": self._confirm_ranged_target,
            "apostrophe": self.action_cancel_ranged_target,
        }
        handler = actions.get(key)
        if handler:
            handler()
        else:
            self._act_log.add(f"[{key}] 功能待定")

    def action_roll_extinguish(self) -> None:
        """打滚：消耗20AP，进入倒地；若灼烧则一并扑灭火焰。随时可发动。"""
        p = self._state.player
        if not p:
            return
        if self._state.in_combat and p.ap < 20:
            self._act_log.add("AP 不足")
            return
        if self._state.in_combat:
            p.ap -= 20
        else:
            self._state.clock.tick_action(2.0)
        if p.has_status("灼烧"):
            p.remove_status("灼烧")
            self._act_log.add(f"{self._pn} 在地上打滚，扑灭了身上的火焰")
        else:
            self._act_log.add(f"{self._pn} 在地上打了个滚")
        p.add_status("prone", duration=None)
        self.refresh_all()

    # ── Input ──

    def action_focus_input(self) -> None:
        self._wake_input()

    def _get_active_views(self) -> list[str]:
        """返回当前活跃视图列表（左栏、右栏各一），与各自 render() 分支严格一致。

        「当前页面显示什么就允许触发什么」：允许键/命令 = 左栏视图 ∪ 右栏视图。
        """
        state = self._state
        views = []
        # 左栏：交互覆盖 → 战斗子阶段 → 默认面板
        ip = state.interact_phase
        if ip:
            views.append(self._INTERACT_VIEWS.get(ip, ip))
        else:
            cp = state.combat_phase
            if cp != "idle":
                views.append("combat_" + cp)
            else:
                views.append("combat_idle" if state.in_combat else "explore")
        # 右栏：物品菜单 → 观察 → view_mode → 默认
        if state.item_menu_stack:
            views.append("right_item_menu")
        elif state.observe_mode:
            views.append("right_observe")
        else:
            rv = self._right_panel.view_mode if self._right_panel else "default"
            if rv != "default":
                views.append("right_" + rv)
            else:
                views.append("right_default")
        return views

    def _try_interact_key(self, key: str) -> bool:
        """处理交互阶段专用按键。返回 True 表示已处理。"""
        ip = self._state.interact_phase
        if ip == "menu" and key.isdigit():
            self._handle_interact_menu_select(int(key))
            return True
        if ip == "talking":
            if key == "T":
                target = getattr(self._state, 'interact_target', None)
                if target and target.extra.get("can_trade"):
                    self._interact_trade_start()
                return True
            if key == "0":
                self._cancel_interact(); return True
        if ip == "trading" and key == "0":
            self._cancel_interact(); return True
        if ip == "action_menu" and key == "0":
            self._cancel_interact(); return True
        if ip == "shove_choice" and key == "0":
            self._cancel_shove_choice(); return True
        if ip == "corpse":
            if key == "1":
                self._corpse_loot(); return True
            if key == "2":
                self._corpse_pickup(); return True
            if key == "0":
                self._cancel_interact(); return True
        return False

    # ── 命令包装器（供 VIEW_DEFS 的 commands 查表调用）──


    # ── Movement ──

    def _move_player(self, dc: int, dr: int) -> None:
        if self._state is None:
            return
        # 瞄准/观察模式：方向键移动光标（瞄准优先于观察，杜绝光标冲突）
        if self._state.combat_phase == "ranged_target":
            pa = self._state.pending_attack or {}
            max_range = pa.get("max_range")
            if max_range is None:
                weapon = pa.get("weapon")
                if pa.get("mode") == "throw":
                    max_range = pa.get("throw_max_range", pa.get("throw_range", 3))
                elif weapon and getattr(weapon, 'weapon_type', '') == "ranged":
                    max_range = getattr(weapon, 'range_max', 8)
                else:
                    max_range = weapon.reach if weapon and hasattr(weapon, 'reach') and weapon.reach else 1
            pc, pr = self._state.player_pos
            oc, oro = self._state.observe_cursor
            nc, nr = oc + dc, oro + dr
            if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                if max(abs(nc - pc), abs(nr - pr)) <= max_range:
                    self._state.observe_cursor = (nc, nr)
                    self._left_panel.refresh()
                    self._map_view.refresh()
            return
        if self._state.observe_mode:
            oc, oro = self._state.observe_cursor
            nc, nr = oc + dc, oro + dr
            if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                if (nc, nr) in self._state.fov_cache:
                    self._state.observe_cursor = (nc, nr)
                    self._right_panel.refresh()
                    self._map_view.refresh()
            return
        # 交互流程中：menu/talking 阶段允许方向键移动
        if self._state.interact_phase:
            ip = self._state.interact_phase
            if ip in ("menu", "talking"):
                col, row = self._state.player_pos
                nc, nr = col + dc, row + dr
                if self._state.move_player(nc, nr):
                    if self._state.in_combat:
                        halved = self._state.player.has_status("prone") or self._state.player.has_status("hiding")
                        self._state.player.ap -= _move_ap_cost(self._state.player, halved=halved)
                    elif self._state.slow_mode:
                        self._state.clock.tick_action(1.0)
                    self._last_move = (dc, dr)
                    if ip == "menu":
                        targets = scan_interact_targets(self._state)
                        if targets:
                            self._state.interact_targets = targets
                            self._left_panel.refresh()
                            self._map_view.refresh()
                        else:
                            self._cancel_interact()
                            self._act_log.add("离开了交互范围")
                    elif ip == "talking":
                        target = getattr(self._state, 'interact_target', None)
                        if target is not None:
                            tx, ty = target.pos
                            px, py = self._state.player_pos
                            if max(abs(px - tx), abs(py - ty)) > 1:
                                self._cancel_interact()
                                self._act_log.add("离开了交互范围")
                            else:
                                self._left_panel.refresh()
                                self._map_view.refresh()
            return
        # 攻击流程（非瞄准）中：不能移动，日志提示
        if self._state.combat_phase != "idle":
            self._act_log.add("当前无法移动")
            return
        if self._state.in_combat and self._state.player.ap <= 0:
            self._act_log.add("AP 不足"); return
        col, row = self._state.player_pos
        nc, nr = col + dc, row + dr
        if self._state.move_player(nc, nr):
            if self._state.in_combat:
                halved = self._state.player.has_status("prone") or self._state.player.has_status("hiding")
                self._state.player.ap -= _move_ap_cost(self._state.player, halved=halved)
            elif self._state.slow_mode:
                self._state.clock.tick_action(1.0)
            self._last_move = (dc, dr)
            # 统一后处理：NPC 行为 + 战斗检测 + UI 刷新
            self._post_action_update()

    def action_move_up(self):
        self._move_player(0, -1)

    def action_move_down(self):
        self._move_player(0, 1)

    def action_move_left(self): self._move_player(-1, 0)
    def action_move_right(self): self._move_player(1, 0)

    def action_confirm_attack(self) -> None:
        """Enter 键确认远程目标（Binding 路径）。"""
        if self._state and self._state.combat_phase == "ranged_target":
            self._confirm_ranged_target()
            self.refresh_all()

    def action_cancel_ranged_target(self) -> None:
        """' 键取消远程瞄准。法术模式回到法术选择，投掷模式直接取消，远程攻击回到攻击选择。"""
        if self._state and self._state.combat_phase == "ranged_target":
            if self._state.pending_attack and self._state.pending_attack.get("mode") == "throw":
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self._act_log.add("取消投掷")
            elif self._state.pending_attack and self._state.pending_attack.get("mode") == "spell":
                self._state.combat_phase = "select_spell"
                self._state.pending_attack = {"mode": "spell"}
                self._act_log.add("[法术] 选择要施放的法术 — 输入 :A序号 确认, :A0 取消")
                self._wake_input()
            elif self._state.pending_attack and self._state.pending_attack.get("mode") in ("torch_ignite_surface", "ignite_surface"):
                mode = self._state.pending_attack.get("mode")
                self._state.combat_phase = "select_action" if mode == "torch_ignite_surface" else "idle"
                self._state.pending_attack = {}
                self._act_log.add("取消点火" if mode == "torch_ignite_surface" else "取消生火")
            else:
                self._combat_flow.cancel_ranged_target()
            self.refresh_all()

    def action_end_turn(self) -> None:
        """手动结束当前回合（Shift+Tab）。"""
        if self._state is None:
            return
        if self._state.combat_phase != "idle":
            return  # 战斗子面板中不响应
        if self._state.in_combat and self._state.combat_turn_entity is self._state.player:
            self._state.player.ap = 0
            self._next_turn()
        else:
            self._act_log.add("现在不是你的战斗轮")

    # ── 后处理 ──

    def _post_action_update(self) -> None:
        """玩家行动后统一处理：检查待开战目标、刷新 UI。"""
        # 处理 clock 回调设置的待开战目标
        if self._state.pending_combat_target and not self._state.in_combat:
            target = self._state.pending_combat_target
            self._state.pending_combat_target = None
            self._act_log.add(f"{target.name} 发现了{self._pn}!")
            self._start_combat(target)
        # 刷新场景和地图
        _update_fov(self._state)
        self._refresh_scene()
        self.refresh_all()

    # ── Observe ──

    def action_toggle_observe(self) -> None:
        self._state.observe_mode = not self._state.observe_mode
        if self._state.observe_mode:
            self._state.observe_cursor = self._state.player_pos
            self._act_log.add("观察模式 — 方向键移动光标, X退出")
        else: self._act_log.add("退出观察模式")
        self.refresh_all()

    # ── Interact（重构）──


    def action_interact(self) -> None:
        """按 0 交互：扫描可交互目标 → 单目标直接触发，多目标弹菜单。"""
        # 已在交互阶段 → 按 0 离开
        if self._state.interact_phase:
            self._cancel_interact()
            return
        targets = scan_interact_targets(self._state)
        if not targets:
            self._act_log.add(f"{self._pn} 环顾四周，这里没什么特别的")
            return
        # 统一弹出交互目标选择菜单
        self._state.interact_targets = targets
        self._state.interact_phase = "menu"
        self.refresh_all()


    # ── Long Rest ──

    def action_long_rest(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法长休"); return
        r = long_rest(self._state.player, self._state.clock,
                      self._state.map, self._state.player_pos)
        comfort = "，睡得很舒适" if r.get("comfort") else ""
        self._act_log.add(f"{self._pn} 长休 (HP+{r['hp_restored']} MP+{r['mp_restored']}){comfort}")
        self._post_action_update()

    # ── Speed modes ──

    def action_slow_speed(self) -> None:
        self._state.slow_mode = not self._state.slow_mode
        if self._state.slow_mode:
            self._act_log.add("慢速模式 — 每一步更为谨慎，消耗更多时间")
        else:
            self._act_log.add("恢复正常速度")
        self.refresh_all()

    def action_dash(self) -> None:
        if self._state.in_combat:
            self._act_log.add("战斗中无法疾走")
            return
        dc, dr = self._last_move
        if dc == 0 and dr == 0:
            self._act_log.add(f"{self._pn} 原地踱步")
            return
        self._move_player(dc, dr)

    # ── Search ──

    def action_1(self) -> None:
        """探查相邻格。"""
        if self._state.in_combat: self._act_log.add("战斗中无法探查"); return
        pc, pr = self._state.player_pos
        found = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0: continue
                nc, nr = pc + dc, pr + dr
                if not (0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height): continue
                if (nc, nr) not in self._state.fov_cache: continue
                ent = self._state.get_entity_at(nc, nr)
                if ent and ent is not self._state.player:
                    found.append(ent.name)
                elif self._state.map[nc, nr] == Terrain.BUSH:
                    found.append("灌木丛")
                elif self._state.map[nc, nr] == Terrain.WALL:
                    found.append("墙壁")
        if found:
            self._act_log.add(f"{self._pn} 环顾四周: {', '.join(found)}")
        else:
            self._act_log.add(f"{self._pn} 环顾四周，没有特别的东西")
        self.refresh_all()

    # ── Wait ──

    def action_wait(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法消磨时间"); return
        self._state.clock.tick_action(1.0)
        self._act_log.add("时间流逝...")
        self._post_action_update()

    # ── Stub actions (待实现) ──

    def action_0(self): self.action_interact()
    def action_2(self): self._act_log.add("[躲藏] 功能待定")
    def action_3(self): self._act_log.add("[协助] 功能待定")
    def action_4(self): self._act_log.add("[跳跃] 功能待定")
    def action_5(self): self._act_log.add("[撤离] 功能待定")
    def action_6(self): self._act_log.add("[回避] 功能待定")
    def action_7(self): self._act_log.add("[推撞] 功能待定")
    def action_8(self): self._act_log.add("[擒抱] 功能待定")
    def action_toggle_knockout(self):
        """F 键切换击晕/杀害模式（阶段9）。"""
        if self._state is None:
            return
        self._state.knockout_mode = not self._state.knockout_mode
        if self._state.knockout_mode:
            self._act_log.add("切换为[击晕]模式 — 近战致死将改为击倒昏迷")
        else:
            self._act_log.add("切换为[杀害]模式")
        self.refresh_all()
    def action_show_actions(self):
        """按 A 键 → 委托 CombatFlow 进入攻击方式选择阶段。"""
        self._combat_flow.start_action_phase()
    def action_show_spells(self):
        """S 键：显示已记忆法术列表，进入施法流程。"""
        from core.spell import get_memorized_spells
        p = self._state.player
        spells = get_memorized_spells(p)
        if not spells:
            self._act_log.add("没有记忆任何法术 (B 键打开法术书记忆)")
            return
        if self._state.combat_phase != "idle":
            return
        self._state.pending_spells = spells
        self._state.combat_phase = "select_spell"
        self._state.pending_attack = {"mode": "spell"}
        self._act_log.add("[法术] 选择要施放的法术 — 输入 :A序号 确认, :A0 取消")
        self._wake_input()
        self.refresh_all()

    # ── 动作面板（阶段3：D5/D22 动作菜单框架）──

    def action_show_actions_menu(self) -> None:
        """按 N 打开动作面板（interact_phase="action_menu"），唤起输入框。"""
        if not self._state.player.actions:
            self._act_log.add("没有任何可用动作")
            return
        self._state.interact_phase = "action_menu"
        self._act_log.add("[动作] 输入 :N序号 执行, :N0 返回")
        self._wake_input()
        self.refresh_all()

    def _execute_action(self, action: dict) -> None:
        """执行动作入口：aim 类复用以统一瞄准面板，self 类直接执行。"""
        if action.get("target") == "aim":
            self._start_action_targeting(action)
            return
        self._run_action(action.get("key"), target=None, target_pos=None)

    def _start_action_targeting(self, action: dict) -> None:
        """aim 类动作：进入统一瞄准面板（复用 ranged_target）。"""
        p = self._state.player
        action_key = action.get("key", "")
        max_range = action.get("max_range", 1)
        # 跳跃距离 = (速度等级 + 力量调整值) × 2（D19，阶段7 完整规则）
        if action_key == "jump":
            if (p.has_status("prone") or p.has_status("hiding")
                    or p.has_status("incapacitated")):
                self._act_log.add("倒地/躲藏/失能状态下无法跳跃")
                self.refresh_all()
                return
            max_range = (p.speed + p.stat_adjust("str")) * 2
        self._state.observe_mode = False
        self._state.interact_phase = ""
        self._state.pending_attack = {
            "mode": "action", "action": action_key,
            "action_name": action.get("name", "动作"),
            "max_range": max_range,
        }
        self._state.combat_phase = "ranged_target"
        self._state.observe_cursor = self._state.player_pos
        self._act_log.add(f"选择 {action.get('name', '动作')} 目标 — 范围:{max_range} [方向键]移动 [Enter]确认 [']取消")
        self._close_input()
        self.refresh_all()

    def _run_action(self, action_key, target, target_pos) -> None:
        """统一动作执行：调 GameState._do_action + 失败日志。"""
        status = self._state._do_action(self._state.player, action_key,
                                        target=target, target_pos=target_pos)
        if status == "no_ap":
            self._act_log.add("AP 不足")
        elif status == "no_action":
            self._act_log.add("没有该动作")
        elif status == "invalid":
            self._act_log.add("无法对该目标使用此动作")
        self._post_action_update()

    def _run_action_with_result(self, action_key, target, target_pos, result: str) -> None:
        """带 result 参数的动作执行（当前仅推撞二选一）。
        判定已在瞄准确认阶段完成，此处仅施加结果（_apply_shove）+ 破坏隐匿 + 扣费，不重复判定/掷骰。"""
        actor = self._state.player
        if action_key == "shove":
            self._state._apply_shove(actor, target, target_pos, result)
        self._state._break_stealth_in_view(actor)
        self._state._spend_action(actor, action_key)
        self._post_action_update()


    def _confirm_action_target(self, pa: dict) -> None:
        """Enter 确认动作瞄准目标：范围允许即可选自身/空地（目标合法性由 _do_* 校验）。
        推撞（shove）特殊处理：先进入二选一面板（撞倒 / 推开），由用户选定后再执行。"""
        oc, orow = self._state.observe_cursor
        pc, pr = self._state.player_pos
        rng = pa.get("max_range", 1)
        if max(abs(oc - pc), abs(orow - pr)) > rng:
            self._act_log.add("目标超出了范围")
            self.refresh_all()
            return
        action_key = pa.get("action")
        target = self._state.get_entity_at(oc, orow)
        # 推撞 → 先判定，胜出才弹二选一面板（体型差超限自动失败；对抗失败不弹面板仅扣费）
        if action_key == "shove":
            if target is None or target is self._state.player or target.is_dead:
                self._act_log.add("需要选择一个有效目标")
                self.refresh_all()
                return
            outcome = self._state._shove_check(self._state.player, target,
                                               (oc, orow))
            if outcome == "too_big":
                self._act_log.add("目标体型太大，无法推撞")
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self.refresh_all()
                return
            if outcome == "fail":
                self._state._break_stealth_in_view(self._state.player)
                self._state._spend_action(self._state.player, "shove")
                self._act_log.add("推搡失败，没能撼动对方")
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self._post_action_update()
                self.refresh_all()
                return
            # 胜出（含失能自动成功）→ 弹二选一面板
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self._state.shove_target = target
            self._state.interact_phase = "shove_choice"
            self._act_log.add("推撞成功 — :S1 撞倒 :S2 推开 :S0 取消")
            self._wake_input()
            self.refresh_all()
            return
        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._run_action(action_key, target=target, target_pos=(oc, orow))

    def action_char_panel(self):
        if self._right_panel.view_mode == "character":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "character"
        self._right_panel.refresh()
        if self._right_panel.view_mode == "character":
            self._wake_input()
        else:
            self._sync_input()

    def action_inventory(self):
        if self._right_panel.view_mode == "inventory":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "inventory"
        self._right_panel.refresh()
        if self._right_panel.view_mode == "inventory":
            self._wake_input()
        else:
            self._sync_input()
    def action_spellbook(self):
        """B 键：切换「法术书」面板。"""
        if self._right_panel.view_mode == "spellbook":
            self._right_panel.view_mode = "default"
            self._sync_input()
        else:
            self._right_panel.view_mode = "spellbook"
            self._wake_input()
        self._right_panel.refresh()
    def action_crafting(self): self._act_log.add("[制作] 功能待定")
    def action_cooking(self):
        """按 K 键进入烹饪：检测厨具 → 选择厨具 → 选择原材料。"""
        tools = self._detect_cooking_tools()
        has_campfire = any(t['type'] == 'campfire' for t in tools)
        if not has_campfire and len(tools) == 1:
            self._act_log.add("附近没有厨具，但你可以徒手处理食材")
        self._cooking_tools = tools
        self._state.interact_phase = "cooking_tools"
        self._left_panel.refresh()
        self._wake_input()

    def action_alchemy(self): self._act_log.add("[炼药] 功能待定")
    def action_height_view(self): self._act_log.add("[高度] 功能待定")
    def action_map_overview(self): self._act_log.add("[地图] 功能待定")
    def action_system_menu(self):
        """E 键：切换「- 思绪 -」面板。"""
        if self._right_panel.view_mode == "system":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "system"
        self._right_panel.refresh()
        if self._right_panel.view_mode == "system":
            self._wake_input()
        else:
            self._sync_input()

    # ── Scene ──


    # ── Rest ──

    def action_short_rest(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法休息"); return
        r = short_rest(self._state.player, self._state.clock,
                       self._state.map, self._state.player_pos)
        comfort = "，睡得很舒适" if r.get("comfort") else ""
        self._act_log.add(f"{self._pn} 短休 (HP+{r['hp_restored']} MP+{r['mp_restored']}){comfort}")
        self._post_action_update()

    # ── Save ──

