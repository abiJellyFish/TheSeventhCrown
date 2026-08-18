"""命令路由 —— _cmd_* 输入命令与 on_input_submitted。"""
import json
import os
import random
from core.game_state import GameState
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
from textual.widgets import Input


_SYSTEM_ACTIONS = {
    1: ("手册",    "stub"),
    2: ("封存记忆", "stub"),
    3: ("回想记忆", "stub"),
    4: ("入眠",    "exit"),
    5: ("主标题",  "title"),
    6: ("设置",    "stub"),
}


class CommandMixin:

    # ── 命令包装器（供 VIEW_DEFS 的 commands 查表调用）──

    def _cmd_trade_buy(self, cmd: str) -> None:
        try:
            self._handle_trade_buy(int(cmd[1:]) - 1)
        except (ValueError, IndexError):
            self._act_log.add("用法: :B序号  如 :B1 购买第1件商品")

    def _cmd_trade_sell(self, cmd: str) -> None:
        try:
            self._handle_trade_sell(int(cmd[1:]) - 1)
        except (ValueError, IndexError):
            self._act_log.add("用法: :S序号  如 :S1 出售第1件物品")

    def _cmd_action_input(self, cmd: str) -> None:
        self._combat_flow.handle_action_input(cmd)

    def _cmd_maneuver_input(self, cmd: str) -> None:
        self._combat_flow.handle_maneuver_input(cmd)

    def _cmd_special_input(self, cmd: str) -> None:
        self._combat_flow.handle_special_input(cmd)

    def _cmd_adv_select(self, cmd: str) -> None:
        """优势面板选择点数：输入纯数字（无冒号前缀，因 GameInput._on_key 拦截冒号）。"""
        self._combat_flow.confirm_adv_choice(cmd)

    def _cmd_action_menu_input(self, cmd: str) -> None:
        """动作面板命令：:N序号 执行动作，:N0 返回。cmd 形如 "N1"（冒号已被 GameInput 拦截）。"""
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            return
        if num == 0:
            self._cancel_interact()
            return
        actions = self._state.player.actions
        if num < 1 or num > len(actions):
            self._act_log.add("序号无效")
            return
        self._execute_action(actions[num - 1])

    def _cmd_shove_choice(self, cmd: str) -> None:
        """推撞二选一命令：:S1 撞倒 :S2 推开 :S0 取消。"""
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            return
        if num == 0:
            self._cancel_shove_choice()
            return
        result = "prone" if num == 1 else ("push" if num == 2 else "")
        if not result:
            self._act_log.add("序号无效")
            return
        target = getattr(self._state, 'shove_target', None)
        if target is None:
            self._cancel_shove_choice()
            return
        target_pos = self._state.get_entity_pos(target)
        # 清状态 + 执行
        self._state.interact_phase = ""
        self._state.shove_target = None
        self._run_action_with_result("shove", target=target, target_pos=target_pos,
                                     result=result)
        self._post_action_update()

    def _cancel_shove_choice(self) -> None:
        """取消推撞选择。"""
        self._state.interact_phase = ""
        self._state.shove_target = None
        self._act_log.add("取消推撞")
        self.refresh_all()

    def _cmd_spell_input(self, cmd: str) -> None:
        """S 键施法：:A序号 选择记忆法术。"""
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            return
        if num == 0:
            self._state.combat_phase = "idle"
            self._state.pending_spells = []
            self._state.pending_attack = {}
            self.refresh_all()
            return
        spells = getattr(self._state, 'pending_spells', [])
        if num < 1 or num > len(spells):
            self._act_log.add("序号无效")
            return
        spell = spells[num - 1]
        self._start_spell_targeting(spell)


    def _cmd_spellbook_input(self, cmd: str) -> None:
        from core.spell import get_known_spells, get_available_slots, memorize_spell, unmemorize_spell
        try:
            idx = int(cmd[1:]) - 1
        except (ValueError, IndexError):
            self._act_log.add("用法: :I序号  如 :I1 选择第1个法术")
            return
        known = get_known_spells(self._state.player)
        if idx < 0 or idx >= len(known):
            self._act_log.add("序号无效")
            return
        p = self._state.player
        spell = known[idx]
        name = spell["name"]
        if name in p.memorized_spells:
            unmemorize_spell(p, name)
            self._act_log.add(f"取消了记忆 {name}")
        elif get_available_slots(p) > 0:
            memorize_spell(p, name)
            self._act_log.add(f"记忆了 {name}")
        else:
            self._act_log.add("法术位已满，请先取消一个已记忆法术")
        self._right_panel.refresh()
        self._wake_input()

    def _cmd_system_input(self, cmd: str) -> None:
        """思绪面板命令：:E1~:E6 按 _SYSTEM_ACTIONS 分发。"""
        try:
            num = int(cmd[1:].upper().replace("E", ""))
        except (ValueError, IndexError):
            self._act_log.add("用法: :E序号  如 :E1 手册")
            return
        entry = _SYSTEM_ACTIONS.get(num)
        if entry is None:
            self._act_log.add(f"无效选项: {cmd}")
            return
        label, action = entry
        if action == "stub":
            self._act_log.add(f"[思绪] {label} 功能待定")
        elif action == "exit":
            self.app.exit()
        elif action == "title":
            self.app.back_to_title()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        self._input_bar.value = ""
        if not cmd:
            self._sync_input()
            return

        # 日志翻页（全局命令，任意视图可用）
        upper = cmd.upper()
        if upper == "LU":
            self._act_log.scroll_up(); self._sync_input(); return
        if upper == "LD":
            self._act_log.scroll_down(); self._sync_input(); return
        if upper == "RU":
            self._scene_log.scroll_up(); self._sync_input(); return
        if upper == "RD":
            self._scene_log.scroll_down(); self._sync_input(); return

        # 合并所有活跃视图的命令表（当前页面显示什么才允许触发什么）
        all_commands = {}
        for view_name in self._get_active_views():
            vdef = self.VIEW_DEFS.get(view_name, {})
            commands = vdef.get("commands", {})
            if isinstance(commands, dict):
                all_commands.update(commands)

        # 按命令前缀查表分发
        prefix = cmd[0].upper() if cmd else ""
        handler_name = all_commands.get(prefix)
        if handler_name:
            handler = getattr(self, handler_name, None)
            if handler:
                self._act_log.add(f"> :{cmd}")
                handler(cmd)
                self._sync_input()
                return

        # 当前页面未显示的命令 → 静默忽略（达成"没反应"）
        self._sync_input()


    def _cmd_facing_input(self, cmd: str) -> None:
        """手动转向：D1-D4 朝向北/东/南/西（阶段4.5，主面板直接输入）。"""
        from core.movement import facing_label
        p = self._state.player
        dir_map = {
            "1": (0, -1), "2": (1, 0), "3": (0, 1), "4": (-1, 0),
        }
        num = cmd[-1] if cmd else ""
        _dir = dir_map.get(num)
        if _dir is None:
            self._act_log.add("用法: :D1~D4  1北 2东 3南 4西")
            return
        p.facing = _dir
        self._act_log.add(f"朝向: {facing_label(p.facing)}")
        _update_fov(self._state)
        self.refresh_all()

