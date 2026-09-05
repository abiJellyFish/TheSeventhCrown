"""按键分发 —— on_key、_dispatch_key、action_* 行动方法。"""
import json
import os
import random
from domain.game_state import GameState, _move_ap_cost
from domain.entity import Entity, Weapon, are_hostile
import domain.entity as ent
from domain.movement import find_path
from domain.fov import LightLevel, compute_fov
from domain.combat.initiative import roll_initiative
from domain.combat.attack import (hit_check, roll_damage, reduce_tenacity,
    apply_damage_type_modifiers, parse_dice, roll_dice, resolve_attack,
    miss_message, cover_message, normalize_damage_type)
from domain.combat.flow import CombatFlow
from domain.map.generation import build_world, build_dungeon
from domain.dice import roll_d20, check_dc, roll_2d6
from domain.ai.engine import BehaviorEngine
from domain.rest import short_rest, long_rest
from infrastructure.loader import DataLoader, _load_dialogues, _load_scene_actions
from infrastructure.save.database import SaveManager
from domain.interact import InteractType, scan_interact_targets
from domain.trade import (load_shop, trade_buy, trade_sell, price_to_text,
    copper_to_currency, shop_gold_text, player_receive,
    resolve_items, load_item)
from domain.item_actions import (get_item_actions, find_placeable_tile,
    place_on_ground, remove_from_inventory as item_remove_from_inventory,
    copy_item_with_count, get_throw_range, get_throw_max_range,
    tile_space_used, MAX_TILE_SPACE)
from domain.loot import _add_to_inventory
from presentation.textual.fov import _update_fov


from textual.events import Key


class KeybindMixin:

    def on_key(self, event) -> None:
        """上下文感知的按键分发：只有当前面板显示的键才触发。"""
        key = {
            "left_square_bracket": "[",
            "right_square_bracket": "]",
            "bracketleft": "[",
            "bracketright": "]",
        }.get(event.key, event.key)
        state = self._state

        # ── 0. Escape：输入框唤醒时关闭它；瞄准阶段取消瞄准；否则无操作 ──
        if key == "escape":
            if state and self._right_panel and self._right_panel.view_mode != "default":
                self._right_view_back()
                event.stop()
                return
            if state and state.item_menu_stack:
                state.item_menu_stack.pop()
                self._sync_input()
                self.refresh_all()
                event.stop()
                return
            if self._input_bar and not self._input_bar.disabled:
                self._close_input()
                event.stop()
                return
            if state and state.combat_phase == "ranged_target":
                self.action_cancel_ranged_target()
                event.stop()
                return
            if state and state.interact_phase == "reaction":
                self._cmd_reaction_input("A0")
                event.stop()
                return
            return

        # ── 1. 输入栏聚焦时，所有按键均作为输入内容 ──
        if self._input_bar and self._input_bar.has_focus:
            return

        if key == "T" and state and not state.interact_phase:
            self.action_toggle_combat_mode()
            event.stop()
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
            "tab": self.action_switch_party,
            "semicolon": self.action_party_select,
            ";": self.action_party_select,
            "T": self.action_toggle_combat_mode,
            "0": self.action_interact,
            "5": self.action_5,
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
            "Q": self.action_quest_panel,
            "B": self.action_spellbook,
            "Z": self.action_crafting,
            "K": self.action_cooking,
            "Y": self.action_alchemy,
            "H": self.action_height_view,
            "]": self.action_climb_up,
            "[": self.action_climb_down,
            "L": self.action_release,
            "M": self.action_map_overview,
            "E": self.action_system_menu,
            "enter": self._confirm_ranged_target,
            "apostrophe": self.action_cancel_ranged_target,
            "1": lambda: self.action_rotate_target("XY"),
            "2": lambda: self.action_rotate_target("XZ"),
            "3": lambda: self.action_rotate_target("YZ"),
        }
        handler = actions.get(key)
        if handler:
            handler()
        else:
            self._act_log.add(f" {key} 功能待定")

    def action_switch_party(self) -> None:
        """Tab：切换到下一名存活小队成员。"""
        target = self._state.next_controlled()
        if target is None:
            self._act_log.add("小队没有存活成员")
            return
        self._act_log.add(f"现在控制 {target.name}")
        self.refresh_all()

    def action_party_select(self) -> None:
        """;：打开多选小队成员移动界面。"""
        if self._state is None or self._state.interact_phase:
            return
        self._state.interact_phase = "party_select"
        self.refresh_all()

    def action_toggle_combat_mode(self) -> None:
        """T：由玩家手动切换探索模式与轮转模式。"""
        if self._state.combat_phase != "idle":
            return
        self._state.in_combat = not self._state.in_combat
        if self._state.in_combat:
            for member in self._state.party:
                if not member.is_dead and not any(
                    participant is member
                    for participant in self._state.combat_initiative
                ):
                    self._state.combat_initiative.append(member)
            controlled = self._state.controlled_entity
            if controlled is not None:
                self._state.combat_turn_index = (
                    self._state.combat_initiative.index(controlled)
                )
            self._state.combat_turn_entity = self._state.controlled_entity
            self._act_log.add("进入轮转模式")
        else:
            status = (
                "参战中"
                if any(
                    not any(member is participant for member in self._state.party)
                    for participant in self._state.combat_initiative
                )
                else "未参战"
            )
            self._state.combat_turn_entity = None
            self._act_log.add(f"进入探索模式（{status}）")
        self.refresh_all()

    def action_roll_extinguish(self) -> None:
        """打滚：消耗20AP，进入倒地；若灼烧则一并扑灭火焰。随时可发动。"""
        p = self._state.controlled_entity
        if not p:
            return
        if self._state.in_combat and p.ap < 20:
            self._act_log.add("AP 不足")
            return
        def execute():
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
            return True
        if self._run_game_action(execute):
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
        if ip == "item_menu" and key.isdigit():
            self._handle_ground_item_menu(int(key))
            return True
        if ip == "talking":
            if key == "t":
                target = getattr(self._state, 'interact_target', None)
                c = target.creature if target else None
                if c and not are_hostile(c, self._state.controlled_entity) \
                        and c.body_type != "beast":
                    self._interact_trade_start()
                else:
                    self._act_log.add("对方不愿意与你交易")
                return True
            if key == "Q":
                self._interact_ask_quest()
                return True
            if key == "R":
                target = getattr(self._state, "interact_target", None)
                creature = target.creature if target else None
                if creature is not None:
                    from domain.recruitment import attempt_recruit
                    from domain.faction import get_attitude
                    attitude = get_attitude(creature, self._state.controlled_entity)
                    cost = 5 if creature.name == "商人" or creature.shop_id else 0
                    result = attempt_recruit(self._state, creature,
                                             attitude=attitude, cost=cost)
                    self._act_log.add(result.message)
                    if result.success:
                        self._state.interact_phase = ""
                    self.refresh_all()
                return True
            if key == "D":
                self._interact_deliver_quest()
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
        if ip == "reaction" and key in ("0", "escape"):
            self._cmd_reaction_input("A0")
            return True
        if ip == "stealing" and key == "0":
            self._cancel_interact(); return True
        if ip == "steal_caught" and key == "0":
            self._handle_steal_caught(0); return True
        if ip == "party_select":
            if key == "0":
                self._cancel_interact()
                return True
            if key == "enter":
                self._state.interact_phase = ""
                count = len(self._state.selected_party_members)
                if count > 1:
                    self._act_log.add(f"已选择 {count} 名成员共同移动")
                self.refresh_all()
                return True
            if key in ("1", "2", "3", "4"):
                idx = int(key) - 1
                members = [m for m in self._state.party if not m.is_dead]
                if idx >= len(members):
                    return True
                member = members[idx]
                if member is self._state.controlled_entity:
                    return True
                member_id = id(member)
                if member_id in self._state.selected_party_members:
                    self._state.selected_party_members.discard(member_id)
                else:
                    self._state.selected_party_members.add(member_id)
                self.refresh_all()
                return True
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
                    from domain.combat.shape import weapon_melee_reach
                    max_range = weapon_melee_reach(weapon, self._state.controlled_entity)
            pc, pr = self._state.controlled_entity_pos[:2]
            oc, oro = self._state.observe_cursor
            nc, nr = oc + dc, oro + dr
            if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                from domain.combat.shape import shape_from_pending_attack
                from domain.combat.target_phase import aim_position_allowed
                shape = shape_from_pending_attack(pa)
                target_z = int(pa.get("target_z", self._state.active_z))
                anchor = (nc, nr, target_z)
                if aim_position_allowed(self._state, anchor, shape, max_range):
                    self._state.observe_cursor = (nc, nr)
                    self.refresh_all()
            return
        if self._state.observe_mode:
            oc, oro = self._state.observe_cursor
            nc, nr = oc + dc, oro + dr
            if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                if self._state.is_xy_in_fov((nc, nr)):
                    self._state.observe_cursor = (nc, nr)
                    self.refresh_all()
            return
        input_gate = getattr(self, "_input_gate", None)
        if input_gate is not None and input_gate.locked:
            return
        # 交互流程中允许方向键移动，移动后复用当前交互目标的范围检查
        if self._state.interact_phase:
            ip = self._state.interact_phase
            col, row = self._state.controlled_entity_pos[:2][:2]
            nc, nr = col + dc, row + dr
            if self._state.in_combat:
                halved = self._state.controlled_entity.has_status("prone") or self._state.controlled_entity.has_status("hiding")
                move_cost = _move_ap_cost(self._state.controlled_entity, halved=halved)
                if self._state.controlled_entity.ap < move_cost:
                    self._act_log.add("AP 不足")
                    return
            else:
                move_cost = 0
            moved = (
                self._coordinator.move((nc, nr))
                if self._coordinator is not None
                else self._state.move_player(nc, nr)
            )
            if moved:
                if self._state.in_combat:
                    self._state.controlled_entity.ap -= move_cost
                elif self._state.slow_mode:
                    self._state.clock.tick_action(1.0)
                self._last_move = (dc, dr)
                if input_gate is not None:
                    input_gate.begin()
                if ip == "menu":
                    targets = scan_interact_targets(self._state)
                    if targets:
                        self._state.interact_targets = targets
                        self._left_panel.refresh()
                        self._map_view.refresh()
                    else:
                        self._cancel_interact()
                        self._act_log.add("离开了交互范围")
                else:
                    target = getattr(self._state, "interact_target", None)
                    if ip == "stealing":
                        target_pos = self._state.get_entity_pos(self._state.steal_target)
                    else:
                        target_pos = getattr(target, "pos", None)
                    px, py = self._state.controlled_entity_pos[:2]
                    target_still_valid = True
                    if target is not None and ip != "stealing":
                        target_still_valid = any(
                            candidate.interact_type == target.interact_type
                            and candidate.pos == target.pos
                            and candidate.creature is target.creature
                            for candidate in scan_interact_targets(self._state)
                        )
                    if (
                        not target_still_valid
                        or target_pos is None
                        or max(abs(px - target_pos[0]), abs(py - target_pos[1])) > 1
                    ):
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
        if self._state.in_combat:
            halved = self._state.controlled_entity.has_status("prone") or self._state.controlled_entity.has_status("hiding")
            move_cost = _move_ap_cost(self._state.controlled_entity, halved=halved)
            if self._state.controlled_entity.ap < move_cost:
                self._act_log.add("AP 不足")
                return
        else:
            move_cost = 0
        col, row = self._state.controlled_entity_pos[:2]
        nc, nr = col + dc, row + dr
        leader = self._state.controlled_entity
        is_group = (
            not self._state.in_combat
            and self._state.interact_phase == ""
            and leader is not None
            and len(self._state.selected_party_members) > 1
        )
        old_time = None
        if is_group:
            old_time = self._state.clock.pendulum_count + self._state.clock.pendulum_acc_ticks / self._state.clock.scale
        moved = (
            self._coordinator.move((nc, nr))
            if self._coordinator is not None
            else self._state.move_player(nc, nr)
        )
        if moved:
            if is_group:
                new_time = self._state.clock.pendulum_count + self._state.clock.pendulum_acc_ticks / self._state.clock.scale
                delta = new_time - old_time
                if delta > 0:
                    self._state.move_selected_followers(leader, delta)
            if self._state.in_combat:
                self._state.controlled_entity.ap -= move_cost
            elif self._state.slow_mode:
                self._state.clock.tick_action(1.0)
            self._last_move = (dc, dr)
            if input_gate is not None:
                input_gate.begin()
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

    def action_rotate_target(self, plane: str | None = None) -> None:
        """旋转多格光标；1/2/3 分别选择 XY/XZ/YZ 平面。"""
        st = self._state
        if not st or st.combat_phase != "ranged_target":
            return
        pa = st.pending_attack or {}
        from domain.combat.shape import (
            is_contiguous_shape, rotate_shape_3d, shape_cells,
            shape_from_pending_attack,
        )
        shape = shape_from_pending_attack(pa)
        if shape.is_single:
            return
        selected_plane = plane or pa.get("target_rotation_plane", "XY")
        new_shape = rotate_shape_3d(shape, selected_plane)
        if not is_contiguous_shape(new_shape):
            self._act_log.add("旋转后范围不连续，无法旋转")
            self.refresh_all()
            return
        shift = (0, 0, 0)
        ac, ar = st.observe_cursor
        new_anchor = (ac + shift[0], ar + shift[1])
        target_z = pa.get("target_z", st.active_z)
        anchor = (new_anchor[0], new_anchor[1], target_z)
        cells = shape_cells(anchor, new_shape)
        max_range = pa.get("max_range", 1)
        pc, pr = st.controlled_entity_pos[:2]
        for c, r, *_ in cells:
            if not (0 <= c < st.map.width and 0 <= r < st.map.height):
                self._act_log.add("旋转后超出地图边界，无法旋转")
                self.refresh_all()
                return
            if max(abs(c - pc), abs(r - pr)) > max_range:
                self._act_log.add("旋转后超出射程，无法旋转")
                self.refresh_all()
                return
        pa["target_offsets"] = list(new_shape.offsets)
        pa["target_rotation"] = new_shape.rotation_steps
        pa["target_rotation_plane"] = selected_plane
        st.observe_cursor = new_anchor
        self._act_log.add(f"旋转平面: {selected_plane}，方向: {new_shape.rotation_steps}/8")
        self.refresh_all()

    def action_cancel_ranged_target(self) -> None:
        """' 键取消远程瞄准。法术模式回到法术选择，投掷模式直接取消，远程攻击回到攻击选择。"""
        if self._state and self._state.combat_phase == "ranged_target":
            if (self._state.pending_attack or {}).get("target_choice_active"):
                self.cancel_target_choice()
                return
            if self._state.pending_attack and self._state.pending_attack.get("mode") == "throw":
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self._act_log.add("取消投掷")
            elif self._state.pending_attack and self._state.pending_attack.get("mode") == "spell":
                self._state.combat_phase = "select_spell"
                self._state.pending_attack = {"mode": "spell"}
                self._act_log.add("法术：选择要施放的法术 — 输入 :A序号 确认, :A0 取消")
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
        if self._state.in_combat and self._state.combat_turn_entity is self._state.controlled_entity:
            def end_turn():
                self._state.controlled_entity.ap = 0
                self._next_turn()
            if self._coordinator is not None:
                self._coordinator.execute_operation(end_turn)
            else:
                end_turn()
        else:
            self._act_log.add("现在不是你的战斗轮")

    # ── 后处理 ──

    def _post_action_update(self) -> None:
        """玩家行动后统一处理：检查待开战目标、刷新 UI。"""
        p = self._state.controlled_entity
        if p is not None:
            p._interrupted = False
        # 处理 clock 回调设置的待开战目标
        if self._state.pending_combat_target and not self._state.in_combat:
            target = self._state.pending_combat_target
            self._state.pending_combat_target = None
            self._act_log.add(f"{target.name} 发现了{self._pn}!")
            self._start_combat(target)
        self._maybe_open_reaction_panel()
        # 刷新场景和地图
        _update_fov(self._state)
        self._refresh_scene()
        self.refresh_all()

    def _begin_input_interval(self) -> None:
        """在已接受游戏行动后启动固定输入间隔。"""
        input_gate = getattr(self, "_input_gate", None)
        if input_gate is not None:
            input_gate.begin()

    def _run_game_action(self, operation) -> bool:
        """执行会推进游戏的操作；成功后统一启动输入间隔。"""
        input_gate = getattr(self, "_input_gate", None)
        if input_gate is not None and input_gate.locked:
            return False
        result = operation()
        if result is False:
            return False
        self._begin_input_interval()
        return True

    # ── Observe ──

    def action_climb_up(self) -> None:
        if self._state.combat_phase == "ranged_target":
            self._switch_target_height(1)
            return
        if self._state.observe_mode:
            self._switch_observe_height(1)
            return
        if self._run_game_action(lambda: self._state.climb_player(1)):
            self._act_log.add("向高处攀爬一层")
        else:
            self._act_log.add("没有符合条件的高处地表")
        self.refresh_all()

    def action_climb_down(self) -> None:
        if self._state.combat_phase == "ranged_target":
            self._switch_target_height(-1)
            return
        if self._state.observe_mode:
            self._switch_observe_height(-1)
            return
        if self._run_game_action(lambda: self._state.climb_player(-1)):
            self._act_log.add("向低处攀爬一层")
        else:
            self._act_log.add("没有符合条件的低处地表")
        self.refresh_all()

    def action_release(self) -> None:
        if self._run_game_action(self._state.release_player):
            self._act_log.add("松手")
        else:
            self._act_log.add("无法松手")
        self.refresh_all()

    def _switch_observe_height(self, direction: int) -> None:
        levels = self._state.target_surface_levels_in_fov(
            self._state.observe_cursor
        )
        if not levels:
            return
        current = self._state.observe_z
        if current is None:
            current = levels[0]
        candidates = [z for z in levels if z > current] if direction > 0 else [
            z for z in levels if z < current
        ]
        if candidates:
            self._state.observe_z = min(candidates) if direction > 0 else max(candidates)
            self.refresh_all()

    def _switch_target_height(self, direction: int) -> None:
        """在瞄准阶段切换当前光标坐标的目标高度：自由 ±1 并统一校验。"""
        pa = self._state.pending_attack or {}
        if not pa:
            return
        from domain.combat.shape import shape_from_pending_attack
        from domain.combat.target_phase import aim_position_allowed
        shape = shape_from_pending_attack(pa)
        current = int(pa.get("target_z", self._state.active_z))
        candidate = current + direction
        anchor = (*self._state.observe_cursor, candidate)
        max_range = pa.get("max_range", 1)
        if aim_position_allowed(self._state, anchor, shape, max_range):
            pa["target_z"] = candidate
            self.refresh_all()

    def action_toggle_observe(self) -> None:
        self._state.observe_mode = not self._state.observe_mode
        if self._state.observe_mode:
            self._state.observe_cursor = self._state.controlled_entity_pos[:2]
            self._state.observe_z = None
            self._act_log.add("观察模式 — 方向键移动光标, X退出, [/]切换高度层")
        else:
            self._state.observe_z = None
            player = self._state.controlled_entity
            if player is not None:
                self._state.active_z = player.z
                self._state.set_active_z(player.z)
            self._act_log.add("退出观察模式")
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
        def do_rest():
            return long_rest(self._state.controlled_entity, self._state.clock,
                             self._state.map, self._state.controlled_entity_pos,
                             self._state.ground_items)
        result = {}
        def execute():
            result.update(
                self._coordinator.execute_operation(do_rest)
                if self._coordinator is not None
                else do_rest()
            )
            comfort = "，睡得很舒适" if result.get("comfort") else ""
            self._act_log.add(
                f"{self._pn} 长休 (HP+{result['hp_restored']} "
                f"MP+{result['mp_restored']}){comfort}"
            )
            return True
        if self._run_game_action(execute):
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

    # ── Wait ──

    def action_wait(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法消磨时间"); return
        def wait():
            accepted = (
                self._coordinator.wait()
                if self._coordinator is not None
                else True
            )
            if accepted:
                self._state.clock.tick_action(1.0)
            return accepted
        if self._run_game_action(wait):
            self._act_log.add("时间流逝...")
            self._post_action_update()

    def action_toggle_knockout(self):
        """F 键切换击晕/杀害模式（阶段9）。"""
        if self._state is None:
            return
        self._state.knockout_mode = not self._state.knockout_mode
        if self._state.knockout_mode:
            self._act_log.add("切换为击晕模式 — 近战致死将改为击倒昏迷")
        else:
            self._act_log.add("切换为杀害模式")
        self.refresh_all()
    def action_show_actions(self):
        """按 A 键 → 委托 CombatFlow 进入攻击方式选择阶段。"""
        self._combat_flow.start_action_phase()
    def action_show_spells(self):
        """S 键：显示已记忆法术列表，进入施法流程。"""
        from domain.spell import get_memorized_spells
        p = self._state.controlled_entity
        spells = get_memorized_spells(p)
        if not spells:
            self._act_log.add("没有记忆任何法术 (B 键打开法术书记忆)")
            return
        if self._state.combat_phase != "idle":
            return
        self._state.pending_spells = spells
        self._state.combat_phase = "select_spell"
        self._state.pending_attack = {"mode": "spell"}
        self._act_log.add("法术：选择要施放的法术 — 输入 :A序号 确认, :A0 取消")
        self._wake_input()
        self.refresh_all()

    # ── 动作面板（阶段3：D5/D22 动作菜单框架）──

    def action_show_actions_menu(self) -> None:
        """按 N 打开动作面板（interact_phase="action_menu"），唤起输入框。"""
        if not self._state.controlled_entity.actions:
            self._act_log.add("没有任何可用动作")
            return
        self._state.interact_phase = "action_menu"
        self._act_log.add("动作：输入 :N序号 执行, :N0 返回")
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
        p = self._state.controlled_entity
        action_key = action.get("key", "")
        max_range = action.get("max_range", 1)
        # 跳跃距离 = 速度等级 + 力量调整值
        if action_key in ("jump", "high_jump"):
            if (p.has_status("prone") or p.has_status("hiding")
                    or p.has_status("incapacitated")):
                self._act_log.add("倒地/躲藏/失能状态下无法跳跃")
                self.refresh_all()
                return
            if action_key == "jump":
                max_range = p.effective_speed + p.stat_adjust("str")
        self._state.observe_mode = False
        self._state.interact_phase = ""
        self._state.pending_attack = {
            "mode": "action", "action": action_key,
            "action_name": action.get("name", "动作"),
            "max_range": max_range,
            "target_z": self._state.controlled_entity.z,
        }
        self._state.combat_phase = "ranged_target"
        self._state.observe_cursor = self._state.controlled_entity_pos[:2]
        self._act_log.add(f"选择 {action.get('name', '动作')} 目标 — 范围:{max_range}  移动  确认  取消")
        self._close_input()
        self.refresh_all()

    def _run_action(self, action_key, target, target_pos) -> None:
        """统一动作执行：调 GameState._do_action + 失败日志。"""
        status = None
        def execute():
            nonlocal status
            status = self._state._do_action(
                self._state.controlled_entity,
                action_key,
                target=target,
                target_pos=target_pos,
            )
            if status == "no_ap":
                self._act_log.add("AP 不足")
            elif status == "no_action":
                self._act_log.add("没有该动作")
            elif status == "invalid":
                self._act_log.add("无法对该目标使用此动作")
            return status not in {"no_ap", "no_action", "invalid"}
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is not None:
            original_execute = execute
            def execute():
                nonlocal status
                status = coordinator.execute_operation(original_execute)
                return status not in {"no_ap", "no_action", "invalid"}
        if self._run_game_action(execute):
            self._post_action_update()

    def _run_action_with_result(self, action_key, target, target_pos, result: str) -> None:
        """带 result 参数的动作执行（当前仅推撞二选一）。
        判定已在瞄准确认阶段完成，此处仅施加结果（_apply_shove）+ 破坏隐匿 + 扣费，不重复判定/掷骰。"""
        def execute():
            actor = self._state.controlled_entity
            action = self._state._find_action(actor, action_key)
            cost_ap = action.get("cost_ap", 0) if action else 0
            if self._state.in_combat and actor.ap < cost_ap:
                self._act_log.add("AP 不足")
                return
            if action_key == "shove":
                self._state._apply_shove(actor, target, target_pos, result)
            self._state._break_stealth_in_view(actor)
            self._state._spend_action(actor, action_key)
        def run():
            if self._coordinator is not None:
                self._coordinator.execute_operation(execute)
            else:
                execute()
            return True
        if self._run_game_action(run):
            self._post_action_update()


    def _confirm_action_target(self, pa: dict) -> None:
        """Enter 确认动作瞄准目标：范围允许即可选自身/空地（目标合法性由 _do_* 校验）。
        推撞（shove）特殊处理：先进入二选一面板（撞倒 / 推开），由用户选定后再执行。"""
        oc, orow = self._state.observe_cursor
        pc, pr = self._state.controlled_entity_pos[:2]
        rng = pa.get("max_range", 1)
        if max(abs(oc - pc), abs(orow - pr)) > rng:
            self._act_log.add("目标超出了范围")
            self.refresh_all()
            return
        action_key = pa.get("action")
        target = self._state.get_entity_at(oc, orow)
        # 推撞 → 先判定，胜出才弹二选一面板（体型差超限自动失败；对抗失败不弹面板仅扣费）
        if action_key == "shove":
            if target is None or target is self._state.controlled_entity or target.is_dead:
                self._act_log.add("需要选择一个有效目标")
                self.refresh_all()
                return
            outcome = self._state._shove_check(self._state.controlled_entity, target,
                                               (oc, orow))
            if outcome == "too_big":
                self._act_log.add("目标体型太大，无法推撞")
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self.refresh_all()
                return
            if outcome == "fail":
                action = self._state._find_action(self._state.controlled_entity, "shove")
                cost_ap = action.get("cost_ap", 0) if action else 0
                if self._state.in_combat and self._state.controlled_entity.ap < cost_ap:
                    self._act_log.add("AP 不足")
                    self._state.combat_phase = "idle"
                    self._state.pending_attack = {}
                    self.refresh_all()
                    return
                self._state._break_stealth_in_view(self._state.controlled_entity)
                self._state._spend_action(self._state.controlled_entity, "shove")
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
        # 偷窃 → 进入偷窃物品选择面板（P1 3.3）
        if action_key == "steal":
            st = self._state
            if target is None or target is st.controlled_entity or target.is_dead:
                self._act_log.add("需要选择一个有效目标")
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self.refresh_all()
                return
            if not target.inventory:
                self._act_log.add(f"{target.name} 身上没有可偷的东西")
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self.refresh_all()
                return
            st.combat_phase = "idle"
            st.pending_attack = {}
            st.steal_target = target
            st.steal_stolen = []
            st.steal_persuade_failures = 0
            st.steal_persuade_bonus = 0
            st.interact_phase = "stealing"
            self._act_log.add(f"偷窃 {target.name} — 选择要偷窃的物品 (:S序号)，:S0 放弃")
            self._wake_input()
            self.refresh_all()
            return
        self._state.combat_phase = "idle"
        target_z = int(pa.get("target_z", self._state.active_z))
        self._state.pending_attack = {}
        self._run_action(action_key, target=target, target_pos=(oc, orow, target_z))

    def action_char_panel(self):
        if self._right_panel.view_mode == "character":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "character"
        self.refresh_all()

    def action_inventory(self):
        if self._right_panel.view_mode == "inventory":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "inventory"
        self.refresh_all()

    def action_quest_panel(self):
        """Q 键：切换「任务」面板（P1 3.4）；从默认面板进入，返回目标为 default。"""
        if self._right_panel.view_mode == "quests":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "quests"
            self._right_panel._quests_back = "default"
        self.refresh_all()

    def _right_view_back(self) -> None:
        """右栏视图返回链（E / escape 通用）：
        system→default、manual→system、title→manual、quest_detail→quests、
        quests→进入来源（default 快捷 / manual 手册进入）、inventory/character/spellbook→default。"""
        if self._right_panel is None:
            return
        vm = self._right_panel.view_mode
        if vm == "quests":
            # quests 返回目标由进入来源决定（default 快捷 / manual 手册进入）
            target = getattr(self._right_panel, "_quests_back", "default")
        else:
            target = {
                "system": "default",
                "manual": "system",
                "title": "manual",
                "guide": "manual",
                "quest_detail": "quests",
                "inventory": "default",
                "character": "default",
                "spellbook": "default",
            }.get(vm)
        if target is None:
            return
        self._right_panel.view_mode = target
        self.refresh_all()

    def action_spellbook(self):
        """B 键：切换「法术书」面板。"""
        if self._right_panel.view_mode == "spellbook":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "spellbook"
        self.refresh_all()
    def action_5(self):
        self._run_action("disengage", target=None, target_pos=None)

    def _maybe_open_reaction_panel(self) -> None:
        st = self._state
        if not st or not st.pending_reactions:
            return
        ev = st.pending_reactions[-1]
        if not getattr(ev.get("reactor"), "controlled", False):
            return
        from domain.combat.opportunity import REACTION_DEFS
        if st.interact_phase != "reaction":
            st.interact_phase = "reaction"
            spec = REACTION_DEFS.get(ev["kind"], REACTION_DEFS["opportunity_attack"])
            if self._act_log:
                self._act_log.add(spec["log_player"])
            self._wake_input()

    def action_crafting(self): self._act_log.add("制作 功能待定")
    def action_cooking(self):
        """按 K 键进入烹饪：检测厨具 → 选择厨具 → 选择原材料。"""
        tools = self._detect_cooking_tools()
        has_campfire = any(t['type'] == 'campfire' for t in tools)
        if not has_campfire and len(tools) == 1:
            self._act_log.add("附近没有厨具，但你可以徒手处理食材")
        self._cooking_tools = tools
        self._state.interact_phase = "cooking_tools"
        self.refresh_all()
        self._wake_input()

    def action_alchemy(self): self._act_log.add("炼药 功能待定")
    def action_height_view(self):
        self._state.height_view = not getattr(self._state, "height_view", False)
        label = "开启" if self._state.height_view else "关闭"
        self._act_log.add(f"{label}高度显示")
        self.refresh_all()
    def action_map_overview(self): self._act_log.add("地图 功能待定")
    def action_system_menu(self):
        """E 键：默认面板 ↔ 思绪面板；其余视图走返回链。"""
        if self._right_panel.view_mode == "default":
            self._right_panel.view_mode = "system"
            self.refresh_all()
        else:
            self._right_view_back()

    # ── Scene ──


    # ── Rest ──

    def action_short_rest(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法休息"); return
        def do_rest():
            return short_rest(self._state.controlled_entity, self._state.clock,
                              self._state.map, self._state.controlled_entity_pos,
                              self._state.ground_items)
        result = {}
        def execute():
            result.update(
                self._coordinator.execute_operation(do_rest)
                if self._coordinator is not None
                else do_rest()
            )
            comfort = "，睡得很舒适" if result.get("comfort") else ""
            self._act_log.add(
                f"{self._pn} 短休 (HP+{result['hp_restored']} "
                f"MP+{result['mp_restored']}){comfort}"
            )
            return True
        if self._run_game_action(execute):
            self._post_action_update()

    # ── Save ──

