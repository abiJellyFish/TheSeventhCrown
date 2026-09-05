"""Textual MVP App — 完整游戏原型。"""

import json
import re
import random
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Input
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from textual.events import Key

from infrastructure.bootstrap import configure as configure_infrastructure
from domain.ports import configure_action_executor
from application.action_executor import ActionExecutor

configure_infrastructure()
configure_action_executor(ActionExecutor)

from domain.game_state import GameState, _move_ap_cost
from domain.entity import Entity, Weapon, are_hostile
import domain.entity as ent
from domain.movement import Terrain
from domain.movement import find_path
from domain.fov import LightLevel, compute_fov
from domain.combat.initiative import roll_initiative
from domain.combat.attack import hit_check, roll_damage, reduce_tenacity, apply_damage_type_modifiers, parse_dice, roll_dice, resolve_attack, miss_message, cover_message, normalize_damage_type
from domain.combat.flow import CombatFlow
from domain.map.generation import build_world
from domain.dice import roll_d20, check_dc, roll_2d6

from domain.rest import short_rest, long_rest
from infrastructure.loader import DataLoader
from infrastructure.save.database import SaveManager
from domain.interact import InteractType, scan_interact_targets
from domain.trade import load_shop, trade_buy, trade_sell, price_to_text, copper_to_currency, shop_gold_text, player_receive, resolve_items, load_item
from domain.item_actions import get_item_actions, find_placeable_tile, place_on_ground, remove_from_inventory as item_remove_from_inventory, copy_item_with_count, get_throw_range, get_throw_max_range, tile_space_used, MAX_TILE_SPACE
from presentation.textual.widgets import (
    TopBar, LeftPanel, MapView, MapLegend, RightPanel, ActionLog, SceneLog,
)
from presentation.textual.screens.title_main import (
    TitleScreen, SaveSlotScreen, JourneyEndScreen,
)
from presentation.textual.screens.char_select import CharSelectScreen, CHARACTERS
import os
from presentation.textual.controllers.inventory import InventoryMixin
from presentation.textual.controllers.interact import InteractMixin


def _is_living_entity_target(target) -> bool:
    """阵营反应只处理实体目标，物品目标不读取 hp。"""
    return isinstance(target, Entity) and target.hp >= 0
from presentation.textual.controllers.targeting import TargetingMixin
from presentation.textual.controllers.npc_runner import NpcRunnerMixin
from presentation.textual.controllers.commands import CommandMixin
from presentation.textual.controllers.keybinds import KeybindMixin
from presentation.textual.controllers.input_gate import InputGate
from application.coordinator import ApplicationCoordinator, UIContext
from presentation.textual.view_models import (
    CookingToolViewModel,
    build_game_view_model,
)
from domain.events import combat_ended, combat_started, turn_changed
from presentation.textual.fov import _update_fov
from domain.loot import _add_to_inventory
from infrastructure.loader import _load_dialogues, _load_scene_actions
from domain.ai.engine import BehaviorEngine

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
SAVE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "saves")
_loader = DataLoader(DATA_DIR)


class GameInput(Input):
    """Input 子类：输入框按键过滤器，拦截不应被输入到框内的特殊键。"""

    async def _on_key(self, event: Key) -> None:
        if event.key == "colon":
            self.screen._close_input()
            event.stop()
            return
        if event.key == "escape":
            screen = self.screen
            screen._close_input()
            event.stop()
            return
        await super()._on_key(event)




# ── JSON 数据加载辅助 ──







# ── 交互分发哈希表（新增交互类型只需加一行）──



# ── 投掷特效 → 处理方法 哈希表（新增投掷物品只需加一行）──


# ── 烹饪食谱（原材料名 → 成品名）──


# ── 「思绪」面板选项（:E序号 → (显示名, 动作)）──





# ═════════════════════════════════ GameScreen ════════════════════════════════════

class GameScreen(InventoryMixin, InteractMixin, TargetingMixin, NpcRunnerMixin, CommandMixin, KeybindMixin, Screen):
    CSS = """
    * { margin: 0; padding: 0; overflow: hidden; }

    #top { height: 3; border: solid #444444; padding: 0 1; }

    #main { height: 3fr; min-height: 0; }
    #left { width: 2fr; min-width: 14; height: 100%; border-right: solid #444444; padding: 0 1; overflow: hidden; }
    #map-column { width: 2fr; min-width: 20; height: 100%; }
    MapView { width: 100%; height: 1fr; content-align: center middle; }
    #map-legend { height: 3; padding: 0 1; }
    #right { width: 2fr; min-width: 18; height: 100%; border-left: solid #444444; padding: 0 1; overflow: hidden; }

    #input-bar { height: 3; border: solid #444444; }

    #log-area { height: 2fr; min-height: 0; border: solid #444444; }
    #action-log { width: 1fr; min-width: 20; height: 100%; border-right: solid #444444; padding: 0 1; content-align: left top; }
    #scene-log { width: 1fr; min-width: 20; height: 100%; padding: 0 1; content-align: left top; }
    """

    BINDINGS = [
        Binding("up", "move_up", "", priority=True),
        Binding("down", "move_down", "", priority=True),
        Binding("left", "move_left", "", priority=True),
        Binding("right", "move_right", "", priority=True),
        Binding("tab", "switch_party", "切换盟友", priority=True),
        Binding("semicolon", "party_select", "选择同行", priority=True),
        Binding("colon", "focus_input", "", priority=True),
        Binding("shift+tab", "end_turn", "结束战斗轮", priority=True),
        Binding("enter", "confirm_attack", "", priority=False),
        Binding("apostrophe", "cancel_ranged_target", "", priority=False),
    ]

    # ── 视图注册表：每个视图声明支持的按键和输入命令 ──

    _EXPLORE_KEYS = {
        "0", "N", "g", "G", "r", "R", "comma", "F", "A", "S", "5", "T", "semicolon", ";",
        "[", "]", "L",
    }

    _RIGHT_DEFAULT_KEYS = {"X", "C", "I", "Q", "B", "E", "Z", "K", "Y", "H", "M"}

    VIEW_DEFS = {
        # ── 左栏 ──
        "explore":                {"keys": _EXPLORE_KEYS, "commands": {"D": "_cmd_facing_input"}},
        "combat_idle":            {"keys": _EXPLORE_KEYS, "commands": {"D": "_cmd_facing_input"}},
        "combat_select_action":   {"keys": set(), "commands": {"A": "_cmd_action_input"}},
        "combat_select_spell":    {"keys": set(), "commands": {"A": "_cmd_spell_input"}},
        "combat_select_cast_attr": {"keys": set(), "commands": {"A": "_cmd_cast_attr_input"}},
        "combat_select_maneuver": {"keys": set(), "commands": {"A": "_cmd_maneuver_input"}},
        "combat_select_special":  {"keys": set(), "commands": {"A": "_cmd_special_input"}},
        "combat_adv_select":      {"keys": set(),
                                   "commands": {"0": "_cmd_adv_select", "1": "_cmd_adv_select",
                                                "2": "_cmd_adv_select", "3": "_cmd_adv_select",
                                                "4": "_cmd_adv_select", "5": "_cmd_adv_select",
                                                "6": "_cmd_adv_select", "7": "_cmd_adv_select",
                                                "8": "_cmd_adv_select", "9": "_cmd_adv_select"}},
        "combat_ranged_target":   {"keys": {"enter", "apostrophe", "[", "]", "1", "2", "3"},
                                   "commands": {"A": "_cmd_target_choice"}},
        "interact_menu":          {"keys": {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}, "commands": {}},
        "item_menu":              {"keys": {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}, "commands": {}},
        "talking":                {"keys": {"t", "Q", "D", "R", "0"}, "commands": {}},
        "trading":                {"keys": {"0"}, "commands": {"B": "_cmd_trade_buy", "S": "_cmd_trade_sell"}},
        "cooking_tools":          {"keys": set(), "commands": {"A": "_interact_cook"}},
        "cooking":                {"keys": set(), "commands": {"A": "_interact_cook"}},
        "chest":                  {"keys": {"0"}, "commands": {"C": "_handle_chest_take", "S": "_handle_chest_store"}},
        "chest_qty":              {"keys": {"0"}, "commands": {"C": "_handle_chest_take_qty", "S": "_handle_chest_store_qty"}},
        "action_menu":            {"keys": {"0"}, "commands": {"N": "_cmd_action_menu_input"}},
        "shove_choice":           {"keys": set(), "commands": {"S": "_cmd_shove_choice"}},
        "corpse":                 {"keys": {"0", "1", "2"}, "commands": {}},
        "reaction":               {"keys": {"escape", "0"}, "commands": {"A": "_cmd_reaction_input"}},
        "stealing":               {"keys": {"0"}, "commands": {"S": "_cmd_steal_input"}},
        "steal_caught":           {"keys": {"0"}, "commands": {"S": "_cmd_steal_caught"}},
        "party_select":           {"keys": {"1", "2", "3", "4", "0", "enter"}, "commands": {}},
        # ── 右栏 ──
        "right_default":          {"keys": _RIGHT_DEFAULT_KEYS, "commands": {}},
        "right_inventory":        {"keys": {"I", "C", "X"}, "commands": {"I": "_use_item", "U": "_handle_unequip", "W": "_swap_hands"}},
        "right_character":        {"keys": {"C", "I", "X"}, "commands": {}},
        "right_system":           {"keys": {"E", "escape"}, "commands": {"E": "_cmd_system_input"}},
        "right_spellbook":        {"keys": {"B"}, "commands": {"I": "_cmd_spellbook_input"}},
        "right_manual":           {"keys": {"E", "escape"}, "commands": {"M": "_cmd_manual_input"}},
        "right_guide":            {"keys": {"E", "escape"}, "commands": {}},
        "right_title":            {"keys": {"E", "escape"}, "commands": {}},
        "right_quests":           {"keys": {"Q", "E", "escape"}, "commands": {"Q": "_cmd_quest_select"}},
        "right_quest_detail":     {"keys": {"E", "escape"}, "commands": {}},
        "right_item_menu":        {"keys": {"I", "escape"}, "commands": {"U": "_cmd_item_action"}},
        "right_observe":          {"keys": {"X"}, "commands": {}},
    }

    # 交互阶段 → 左栏视图名映射（与 LeftPanel.render 分支顺序一致）
    _INTERACT_VIEWS = {
        "menu": "interact_menu", "talking": "talking", "trading": "trading",
        "cooking_tools": "cooking_tools", "cooking": "cooking", "chest": "chest",
        "chest_take_qty": "chest_qty", "chest_store_qty": "chest_qty",
        "action_menu": "action_menu",
        "shove_choice": "shove_choice",
        "corpse": "corpse",
        "reaction": "reaction",
        "stealing": "stealing",
        "steal_caught": "steal_caught",
        "party_select": "party_select",
    }

    def __init__(self, char_key: str = "伊芙琳", domain: str | None = None,
                 load_slot: str | None = None):
        super().__init__()
        self._char_key = char_key
        self._domain = domain
        self._load_slot = load_slot
        self._state: GameState | None = None
        self._act_log: ActionLog | None = None
        self._scene_log: SceneLog | None = None
        self._map_view: MapView | None = None
        self._left_panel: LeftPanel | None = None
        self._right_panel: RightPanel | None = None
        self._input_bar: Input | None = None
        self._top_bar: TopBar | None = None
        self._last_move: tuple[int, int] = (0, 0)
        self._coordinator: ApplicationCoordinator | None = None
        self._journey_end_opened = False
        self._input_gate = InputGate(
            lambda delay, callback: self.set_timer(delay, callback)
        )

    @property
    def _pn(self) -> str:
        """玩家名称快捷访问。后续自定义名称只需改 Entity 构造处。（Phase 3）"""
        return self._state.controlled_entity.name

    def _create_game(self) -> None:
        # 玩家选的角色 key
        char_key = self._char_key

        self._state = GameState(map_width=80, map_height=60)
        self._state.ai_engine = BehaviorEngine()

        # 加载战技数据
        with open(os.path.join(DATA_DIR, "maneuvers.json"), "r", encoding="utf-8") as f:
            mdata = json.load(f)
        self._state.maneuvers = mdata.get("maneuvers", mdata if isinstance(mdata, list) else [])

        self._state.subscribe_events(self._handle_domain_event)

        # build_world 统一加载所有实体（包括 fighter/mage，和其他村民一样）
        build_world(self._state, _loader)

        # 玩家角色不是地图 NPC，必须从角色数据单独创建并加入世界实体集合。
        player = _loader.load_entity(char_key)
        if player is None:
            raise ValueError(f"角色数据不存在: {char_key}")
        self._state.add_entity(player, (0, 0))
        self._state.set_controlled(player)
        companion = next(
            character for character in CHARACTERS if character["key"] != char_key
        )
        ally = _loader.load_entity(companion["key"])
        if ally is None:
            raise ValueError(f"盟友角色数据不存在: {companion['key']}")
        self._state.add_entity(ally, (0, 1))
        if not self._state.add_party_member(ally):
            raise RuntimeError("初始盟友加入小队失败")
        # 法师领域天赋注入（角色选择页的领域选择不是装备法术书）
        if char_key == "伊芙琳" and self._domain and self._domain != "evocation":
            player.domain_talents = [self._domain]
            player.domain_experience = {self._domain: 1}
            player.spell_domains = [self._domain]
            player.memorized_spells = []

        position = self._state.controlled_entity_pos
        if self._state.controlled_entity is None or position is None:
            raise RuntimeError("角色初始化失败：未设置受控实体位置")
        _update_fov(self._state)
        self._save_manager = SaveManager(SAVE_DIR)
        if self._load_slot is not None:
            if not self._save_manager.load(self._state, self._load_slot, _loader):
                raise ValueError(f"存档不存在: {self._load_slot}")
            _update_fov(self._state)
        # 战斗流程状态机（需在 widgets 创建后初始化，使用延迟绑定）
        self._combat_flow: CombatFlow | None = None

    def _init_combat_flow(self) -> None:
        """在 compose 完成后初始化 CombatFlow（依赖已创建的 widgets）。"""
        self._combat_flow = CombatFlow(
            self._state,
            self._pn,
            action_map=self._left_panel._action_map,
            maneuver_map=self._left_panel._maneuver_map,
            special_map=self._left_panel._special_map,
            on_refresh=self.refresh_all,
        )

    def compose(self) -> ComposeResult:
        self._top_bar = TopBar(id="top"); yield self._top_bar
        with Horizontal(id="main"):
            self._left_panel = LeftPanel(id="left"); yield self._left_panel
            with Vertical(id="map-column"):
                self._map_view = MapView(); yield self._map_view
                self._map_legend = MapLegend(id="map-legend"); yield self._map_legend
            self._right_panel = RightPanel(id="right"); yield self._right_panel
        self._input_bar = GameInput(placeholder=": 输入命令(Esc退出) lu/ld左侧栏 ru/rd右侧栏 LU/LD左日志 RU/RD右日志", id="input-bar", disabled=True)
        yield self._input_bar
        with Horizontal(id="log-area"):
            self._act_log = ActionLog(id="action-log"); yield self._act_log
            self._scene_log = SceneLog(id="scene-log"); yield self._scene_log

    def on_mount(self) -> None:
        self._create_game()
        self._coordinator = ApplicationCoordinator(
            UIContext(
                game=self._state,
                log=self._act_log,
                combat_log=self._scene_log,
                input=self._input_bar,
                refresh=self.refresh_all,
            )
        )
        self._init_combat_flow()
        self._refresh_scene()
        self.refresh_all()
        self.call_after_refresh(self.refresh_all)
        self._map_view.focus()

    # 需要输入框获得焦点的战斗阶段
    _COMBAT_INPUT_PHASES = {
        "select_action", "select_maneuver", "select_special",
    }

    # 需要输入框获得焦点的交互阶段
    _INTERACT_INPUT_PHASES = {"trading", "talking"}

    # 需要自动聚焦输入框的右侧面板视图（observe 不在此列）
    _FOCUS_VIEW_MODES = {"inventory", "character"}

    # 需要输入框获得焦点的交互阶段（扩展）
    _FOCUS_INTERACT_PHASES = {"interact_menu", "talking"}

    def _wake_input(self) -> None:
        """唤醒输入框 — 启用并聚焦。"""
        if self._input_bar is None:
            return
        self._input_bar.disabled = False
        self._input_bar.focus()

    def _close_input(self) -> None:
        """关闭输入框 — 禁用，焦点回地图。"""
        if self._input_bar is None:
            return
        self._input_bar.disabled = True
        if self._map_view is not None:
            self._map_view.focus()

    def _sync_input(self) -> None:
        """按当前页面统一决定是否唤起输入框（左栏流程优先，右栏不抢占主面板）。"""
        if self._state is None:
            return
        from presentation.textual.controllers.ui_state import build_ui_state

        right_view = (
            self._right_panel.view_mode
            if self._right_panel is not None
            else "default"
        )
        ui = build_ui_state(self._state, right_view=right_view)
        if ui.input_enabled:
            self._wake_input()
        else:
            self._close_input()

    def refresh_all(self) -> None:
        if self._coordinator is not None:
            self._coordinator.consume_events(notify=False)
        if self._state.is_game_over():
            return
        if self._state.controlled_entity is not None:
            self._state.update_render_chunks()
        if self._state.controlled_entity is not None:
            _update_fov(self._state)
            cooking_tools = tuple(
                CookingToolViewModel(
                    name=tool["name"],
                    tool_type=tool["type"],
                    position=tool["pos"],
                )
                for tool in getattr(self, "_cooking_tools", [])
            )
            selected_tool_data = getattr(self, "_selected_cooking_tool", None)
            selected_tool = (
                CookingToolViewModel(
                    name=selected_tool_data["name"],
                    tool_type=selected_tool_data["type"],
                    position=selected_tool_data["pos"],
                )
                if selected_tool_data is not None
                else None
            )
            view_model = build_game_view_model(
                self._state,
                cooking_tools=cooking_tools,
                selected_cooking_tool=selected_tool,
            )
            for widget in (
                self._left_panel,
                self._map_view,
                self._map_legend,
                self._top_bar,
                self._right_panel,
            ):
                if widget is not None:
                    widget.set_view_model(view_model, refresh=False)
        for w in [self._map_view, self._map_legend, self._left_panel,
                  self._right_panel, self._top_bar, self._act_log, self._scene_log]:
            if w: w.refresh()
        self._sync_input()
        self._sync_carry_status()

    def _add_visible_action_log(self, message: str, position=None) -> None:
        """写入左侧日志；有位置的消息只显示在玩家视野内。"""
        player_pos = self._state.controlled_entity_pos
        if position is None or (player_pos is not None
                                and position[:2] == player_pos[:2]):
            self._act_log.add(message)
            return
        pos3 = (*position[:2], position[2]) if len(position) == 3 else (*position, self._state.active_z)
        if self._state.is_in_fov(pos3):
            self._act_log.add(message)

    def _start_spell_targeting(self, spell: dict, cast_attr: str | None = None) -> None:
        """进入法术瞄准阶段：统一选格子（同远程攻击），范围允许即可选自身/空地。支持多目标。"""
        missiles = spell.get("effect", {}).get("missiles", 1)
        target_mode = spell.get("target_mode")
        if target_mode not in ("target", "area"):
            target_mode = "area" if spell.get("effect", {}).get("area") else "target"
        self._state.observe_mode = False
        self._state.pending_attack = {
            "mode": "spell", "spell": spell,
            "cast_attr": cast_attr,
            "target_mode": target_mode,
            "target_count": missiles if target_mode == "target" else 1,
            "targets": [],
            "max_range": spell.get("range", 1),
            "target_shape": spell.get("target_shape", ""),
            "target_z": self._state.controlled_entity.z,
        }
        self._state.combat_phase = "ranged_target"
        self._state.observe_cursor = self._state.controlled_entity_pos[:2]
        rng = spell.get("range", 1)
        shape_hint = f" 范围:{spell.get('target_shape')}" if spell.get("target_shape") else ""
        if missiles > 1:
            prompt = f"选择 {spell['name']} 目标 (1/{missiles})"
        else:
            prompt = f"选择 {spell['name']} 目标"
        self._act_log.add(f"{prompt} — 射程:{rng}{shape_hint}  移动  确认  取消")
        self._close_input()
        self.refresh_all()

    def _cast_spell(self, spell: dict, target: "Entity | None | list", target_pos: tuple[int, int] | None = None) -> None:
        """执行法术施放：扣 MP + AP/钟摆，结算效果。target 可为单个/None 或多目标列表。"""
        from domain.spell import resolve_spell, spell_mp_cost
        from domain.crops import apply_wet_to_tile
        from domain.element import BurningSurface
        from domain.grid import FLAMMABLE
        from domain.fov import LightLevel
        from domain.combat.target_phase import SurfaceTarget

        caster = self._state.controlled_entity
        pending = self._state.pending_attack or {}
        scroll = pending.get("scroll_item")
        if scroll is not None and pending.get("spell", {}).get("effect", {}).get("type") == "revive":
            if not isinstance(target, Entity) or not target.is_dead:
                self._act_log.add("只能选择相邻的非亡灵尸体")
                return
            target_position = self._state.get_entity_pos(target)
            caster_position = self._state.get_entity_pos(caster)
            if (target_position is None or caster_position is None
                    or max(abs(target_position[0] - caster_position[0]),
                           abs(target_position[1] - caster_position[1])) != 1):
                self._act_log.add("死者复生只能选择相邻尸体")
                return
            if target.body_type == "undead":
                self._act_log.add("亡灵不能复活")
                return
            try:
                self._state._first_free_adjacent(self._state.get_entity_pos(target))
            except RuntimeError:
                self._act_log.add("相邻格没有空位")
                return
        if scroll is None:
            cast_time_ap = spell.get("cast_time_ap", 0)
            if self._state.in_combat and caster.ap < cast_time_ap:
                self._act_log.add("AP 不足")
                return
            mp_cost = spell_mp_cost(caster, spell)
            if caster.mp < mp_cost:
                self._act_log.add("MP 不足")
                return
            caster.mp -= mp_cost
            # 消耗 AP（战斗）或钟摆（探索）
            if self._state.in_combat:
                caster.ap -= cast_time_ap
            else:
                self._state.clock.tick_action(spell.get("cast_time_pendulum", 0))
        else:
            inv_index = pending.get("scroll_inv_index", -1)
            if inv_index < 0 or inv_index >= len(caster.inventory):
                self._act_log.add("卷轴已不在背包中")
                return
            if caster.inventory[inv_index] is not scroll:
                self._act_log.add("卷轴位置已变化，请重新选择")
                return
            self._state.clock.tick_action(spell.get("cast_time_pendulum", 0))
        cast_attr = self._state.pending_attack.get("cast_attr")
        effect_type = spell.get("effect", {}).get("type", "")
        if effect_type == "revive":
            try:
                destination = self._state.revive_entity(target)
            except (ValueError, RuntimeError) as exc:
                self._act_log.add(str(exc))
                return
            self._act_log.add(
                f"{target.name} 复活，恢复 {target.hp} 点生命，移至 {destination}"
            )
            result = {"effect": "revive", "damage": 0}
        elif effect_type == "wet_tile":
            pos = target_pos or self._state.observe_cursor
            apply_wet_to_tile(self._state, pos)
            self._act_log.add(f"{caster.name} 施放了 {spell['name']}，({pos[0]},{pos[1]}) 变得潮湿")
        else:
            effect = spell.get("effect", {})
            surface_damage = 0
            surface_cells = []
            if isinstance(target, list):
                flat_targets = []
                for t in target:
                    if isinstance(t, SurfaceTarget):
                        surface_cells.append(t.position)
                    elif t is not None:
                        flat_targets.append(t)
                target = flat_targets
            elif isinstance(target, SurfaceTarget):
                surface_cells = [target.position]
                target = None
            if (
                effect_type == "damage"
                and spell.get("target_mode") == "area"
                and target_pos is not None
            ):
                shape_spec = spell.get("target_shape") or effect.get("area")
                if shape_spec:
                    target = self._state.damageables_in_shape(
                        (*target_pos, pending.get("target_z", self._state.active_z)),
                        shape_spec,
                        visible_only=True,
                    )
            if effect_type == "damage":
                target_mode = spell.get("target_mode") or (
                    "area" if effect.get("area") else "target"
                )
                if target_mode == "area":
                    area_cells = pending.get("affected_cells")
                    if area_cells is not None:
                        surface_cells = list(area_cells)
                elif target is None and target_pos is not None and not surface_cells:
                    # target 模式选择空气 → 不追加地表
                    surface_cells = []
                count, sides = parse_dice(effect.get("amount", "1d4"))
                for col, row, z in surface_cells:
                    if (
                        self._state.is_in_fov((col, row, z))
                        and self._state.is_exposed_surface((col, row, z))
                        and self._state.surface_at((col, row), z).exists
                    ):
                        damage = roll_dice(count, sides)
                        surface_damage += damage
                        self._state.damage_surface((col, row), damage, z=z)
            result = resolve_spell(caster, target, spell, cast_attr=cast_attr)
            if surface_damage:
                result["damage"] += surface_damage
                result["message"] = (
                    f"{caster.name} 施放 {spell['name']}，地表受到 "
                    f"{surface_damage} 点伤害"
                )
            self._act_log.add(result["message"])
            if spell.get("effect", {}).get("ignite"):
                if isinstance(target, list) and not target and surface_cells:
                    cells = surface_cells
                elif target is None and surface_cells:
                    cells = surface_cells
                else:
                    cells = pending.get("affected_cells") or [target_pos or self._state.observe_cursor]
                for cell in cells:
                    position = cell[:2]
                    cell_z = cell[2] if len(cell) == 3 else pending.get(
                        "target_z", self._state.active_z
                    )
                    terrain = self._state.surface_at(position, cell_z).terrain
                    if terrain in FLAMMABLE:
                        self._state.burning_surfaces[position] = BurningSurface(
                            fuel=FLAMMABLE[terrain]
                        )
                        self._state.register_light((position[0], position[1], cell_z), 1, LightLevel.BRIGHT)
            # 伤害型法术 → 检查态度反应（多目标逐个）
            if result.get("effect") != "heal" and result.get("damage", 0) > 0:
                targets = target if isinstance(target, list) else [target]
                for t in targets:
                    if _is_living_entity_target(t):
                        self._check_faction_reaction(t)
        if scroll is not None:
            from domain.item_actions import remove_from_inventory
            remove_from_inventory(caster, pending["scroll_inv_index"], 1)
            self._act_log.add(f"{scroll.name} 已消散")
        self._begin_input_interval()
        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._state.pending_spells = []
        # 施法 → 破坏隐匿
        self._state._break_stealth_in_view(caster)
        _update_fov(self._state)
        self.refresh_all()

    # ── Combat ──

    def _start_combat(self, target: Entity, ambush: bool = False) -> None:
        """进入战斗。ambush=True 时玩家必定先手（探索模式主动攻击）。"""
        if self._state.is_game_over():
            self._open_journey_end()
            return
        if target.is_dead:
            return
        self._state.in_combat = True
        self._state.emit_event(combat_started())
        self._state._combat_ticked = False
        self._state.controlled_entity.ap = self._state.controlled_entity.max_ap
        combatants = [
            member for member in self._state.party if not member.is_dead
        ]
        pc, pr = self._state.controlled_entity_pos[:2]
        for creature, (ec, er, ez) in self._state.entities:
            if creature.hp > 0 and are_hostile(creature, self._state.controlled_entity) \
               and (ec - pc) ** 2 + (er - pr) ** 2 <= creature.vision_range ** 2:
                if creature not in combatants:
                    combatants.append(creature)
                creature.ap = creature.max_ap
        # 弹药武器：战斗开始时重置为未装填
        for item in self._state.controlled_entity.equipment.values():
            if item is not None:
                props = getattr(item, 'properties', []) or []
                if "ammo" in props:
                    item.loaded = False
        for item in self._state.controlled_entity.inventory:
            props = getattr(item, 'properties', []) or []
            if "ammo" in props:
                item.loaded = False

        self._state.combat_initiative = roll_initiative(combatants)
        self._state.combat_turn_index = 0

        turn = self._state.controlled_entity if ambush else combatants[0]
        self._state.combat_turn_index = self._state.combat_initiative.index(turn)
        self._state.combat_turn_entity = turn
        turn.ap = turn.max_ap
        self._scene_log.add("=== 战斗开始 ===")
        if turn in self._state.party:
            self._state.set_controlled(turn)
            self._act_log.add(f">>> {turn.name}的战斗轮 <<<")
        else:
            self._act_log.add(f">>> {self._pn}的战斗轮 <<<")
            self._state._npc_act(turn)
            if self._state._player_reaction_pending():
                self._maybe_open_reaction_panel()
                self.refresh_all()
                return
            self._next_turn(reset_combat_ticked=False)
            self.refresh_all()
            return

    def _end_combat(self) -> None:
        if self._state.is_game_over():
            self._open_journey_end()
            return
        # 当前轮未完成（敌人死在半轮等场景）→ 补推
        if not getattr(self._state, '_combat_ticked', False):
            self._state.clock.tick_combat_round()
            self._state._advance_npcs(6.0, combatants=False)
        self._state.in_combat = False; self._state.combat_initiative = []
        self._state.combat_turn_entity = None
        self._state.emit_event(combat_ended())
        self._state.controlled_entity.ap = self._state.controlled_entity.max_ap
        self._state._combat_ticked = False
        self._scene_log.add("=== 战斗结束 ===")

    def _require_held_item(self, item):
        """火把等手持物在左或右手，不要求双手。不在手持栏则抛错。"""
        if item is None:
            raise ValueError("手持物品为空")
        equip = self._state.controlled_entity.equipment
        if item is not equip.get("left_hand") and item is not equip.get("right_hand"):
            raise ValueError("物品不在手持装备栏")
        return item

    def _handle_domain_event(self, event) -> None:
        if self._check_game_over_after_death(event):
            return
        if event.name == "LogEvent":
            # LogEvent 统一由 ApplicationCoordinator.consume_events 消费，避免重复写入。
            return
        if event.name == "ReactionRequired":
            self._maybe_open_reaction_panel()
        elif event.name == "TurnChanged" and event.payload.get("entity_id") is None:
            self._next_turn(reset_combat_ticked=False)
        elif event.name == "InputWake":
            self._wake_input()
        elif event.name == "CombatRequested":
            target = next(
                (entity for entity, _ in self._state.entities
                 if id(entity) == event.payload["target_id"]),
                None,
            )
            if target is not None:
                self._start_combat(target, ambush=True)
        elif event.name == "TwoHandRequested":
            self._on_two_hand_equip(
                self._require_held_item(event.payload["item"]),
                hand=event.payload["hand"],
            )
        elif event.name == "TorchActionRequested":
            self._on_torch_action(
                self._require_held_item(event.payload["item"]),
                event.payload["mode"],
            )

    def _check_game_over_after_death(self, event) -> bool:
        """死亡事件确认小队全灭后，只调度一次旅途结束页面。"""
        if event.name != "EntityDied" or getattr(self, "_journey_end_opened", False):
            return False
        party = getattr(self._state, "party", [])
        if not any(id(member) == event.payload.get("entity_id") for member in party):
            return False
        if not self._state.is_game_over():
            return False
        self._open_journey_end()
        return True

    def _open_journey_end(self) -> None:
        """标记并调度旅途结束页面，阻止全灭后的游戏界面继续处理。"""
        if getattr(self, "_journey_end_opened", False):
            return
        self._journey_end_opened = True
        self.call_after_refresh(self.app.show_journey_end)

    def _next_turn(self, *, reset_combat_ticked: bool = True) -> None:
        if not self._state.in_combat: return
        if self._state.is_game_over():
            self._open_journey_end()
            return
        if reset_combat_ticked:
            self._state._combat_ticked = False  # 仅顶层流转重置，递归/续跑不抹掉满轮标记

        # 透明网格（复用缓存，一部构建，参战拉入+脱战共用，阶段2.5）
        from domain.fov import _line_of_sight
        from domain.movement import sector_of
        transparent = self._state._get_transparent_grid()

        # 拉入视野内未参战的敌对生物（朝向+距离+视线，阶段2.5）
        pc, pr = self._state.controlled_entity_pos[:2]
        for creature, (ec, er, ez) in self._state.entities:
            if creature.hp > 0 and are_hostile(creature, self._state.controlled_entity) \
               and (ec - pc) ** 2 + (er - pr) ** 2 <= creature.vision_range ** 2 \
               and sector_of(creature.facing, (pc - ec, pr - er)) != "back" \
               and _line_of_sight(transparent, ec, er, pc, pr) \
               and creature not in self._state.combat_initiative:
                creature.ap = creature.max_ap
                self._state.combat_initiative.append(creature)
                self._add_visible_action_log(
                    f"{creature.name} 加入了战斗!",
                    position=(ec, er),
                )

        if self._state.check_combat_visibility(self._state.controlled_entity):
            self._act_log.add(f"{self._pn} 脱离了敌人的视野，战斗结束")
            self._end_combat()
            self.refresh_all()
            return

        alive = [e for e in self._state.combat_initiative if e is self._state.controlled_entity or not e.is_dead]

        self._state.combat_initiative = alive
        if not alive:
            self.refresh_all()
            return
        idx = (self._state.combat_turn_index + 1) % len(alive)
        # 满轮 → 推进钟摆 6 + 非参战生物结算 6 钟摆
        if idx == 0:
            self._state.clock.tick_combat_round()
            self._state._combat_ticked = True
            self._state._advance_npcs(6.0, combatants=False)
        self._state.combat_turn_index = idx; turn = alive[idx]
        self._state.combat_turn_entity = turn
        if turn in self._state.party:
            self._state.set_controlled(turn)
        self._state.emit_event(turn_changed(id(turn) if turn is not None else None))
        # 回合开始清除撤离/回避状态（至下回合开始失效）
        turn.remove_status("disengaged")
        turn.remove_status("dodge")
        turn.ap = turn.max_ap
        if turn is self._state.controlled_entity:
            self._act_log.add(f">>> {self._pn}的战斗轮 <<<")
        else:
            self._add_visible_action_log(
                f">>> {turn.name}的战斗轮 <<<",
                position=self._state.get_entity_pos(turn),
            )
            self._state._npc_act(turn)
            if self._state._player_reaction_pending():
                self._maybe_open_reaction_panel()
                self.refresh_all()
                return
            self._next_turn(reset_combat_ticked=False)
            self.refresh_all()
            return
        self.refresh_all()

    # ── 攻击流程状态机 ──

    def _handle_action_input(self, cmd: str) -> None:
        """阶段一：选择攻击方式 → 委托 CombatFlow。"""
        self._combat_flow.handle_action_input(cmd)

    def _execute_attack_roll(self) -> None:
        """执行攻击检定 → 委托 CombatFlow。"""
        self._combat_flow.execute_attack_roll()

    def _handle_maneuver_input(self, cmd: str) -> None:
        """阶段三A：命中后选择战技 → 委托 CombatFlow。"""
        self._combat_flow.handle_maneuver_input(cmd)

    def _handle_special_input(self, cmd: str) -> None:
        """阶段三B：未命中后选择特殊行动 → 委托 CombatFlow。"""
        self._combat_flow.handle_special_input(cmd)

    def _check_faction_reaction(self, target: Entity) -> None:
        """玩家攻击非敌对生物后检查阵营反应 → 委托 CombatFlow。"""
        self._combat_flow.check_faction_reaction(target, self._state.controlled_entity)
    def _refresh_scene(self) -> None:
        if self._state.is_game_over():
            return
        pc, pr = self._state.controlled_entity_pos[:2]
        lines = []
        for creature, (ec, er, ez) in self._state.entities:
            if not self._state.is_in_fov((ec, er, ez)) or creature.is_dead: continue
            if creature is self._state.controlled_entity: continue
            desc = self._describe_creature(creature, (ec, er), pc, pr)
            if desc: lines.append(desc)
        if not lines: lines = [""]
        if lines != getattr(self, '_last_scene', None):
            self._last_scene = lines; self._scene_log.set_scene(lines)

    def _describe_creature(self, c: Entity, pos: tuple[int, int],
                            pc: int, pr: int) -> str:
        ec, er = pos
        dist = max(abs(ec - pc), abs(er - pr))
        enemy_count = 1 if dist <= c.vision_range else 0
        ally_count = getattr(c, '_ally_count', 0)
        ratio = c.hp / max(c.max_hp, 1) * (ally_count + 1) / max(enemy_count, 1)
        action = getattr(c, '_current_action', 'idle')

        r = c.hp / max(c.max_hp, 1)
        if r <= 0: hp = "瘫倒在地，"
        elif r < 0.2: hp = "伤痕累累，"
        elif r < 0.5: hp = "身上带伤，"
        else: hp = ""

        act_map = _load_scene_actions()
        desc = act_map.get(action, act_map.get("fallback", "待在原地"))
        if isinstance(desc, dict):
            desc = desc.get("enemy", desc.get("no_enemy", "")) if enemy_count else desc.get("no_enemy", desc.get("enemy", ""))
            desc = desc.replace("{player}", self._pn)
        status_text = ""
        if c.statuses:
            status_text = f" {', '.join(s.name for s in c.statuses)}"
        return f"{c.name}{status_text} {hp}{desc}"
# ═════════════════════════════════════ MVPApp ═══════════════════════════════════════

class MVPApp(App):
    """薄壳 App：只负责标题/游戏两个屏幕之间的切换。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._char_key = "伊芙琳"

    def on_mount(self) -> None:
        self.push_screen(TitleScreen())

    def open_save_slots(self) -> None:
        """兼容旧调用：打开存档页面。"""
        self.push_screen(SaveSlotScreen(mode="save"))

    def open_load_slots(self) -> None:
        """标题页回忆入口：打开读档页面。"""
        self.push_screen(SaveSlotScreen(mode="load"))

    def _game_screen(self):
        return next(
            (screen for screen in reversed(self.screen_stack)
             if isinstance(screen, GameScreen)),
            None,
        )

    def save_to_slot(self, slot: str) -> None:
        game = self._game_screen()
        if game is None or game._state is None:
            self.notify("当前没有可保存的游戏状态")
            return
        SaveManager(SAVE_DIR).save(game._state, slot)
        self.notify(f"已保存到 {slot}")
        self.pop_screen()

    def load_from_slot(self, slot: str) -> None:
        game = self._game_screen()
        save_manager = SaveManager(SAVE_DIR)
        if game is not None and game._state is not None:
            loaded = save_manager.load(game._state, slot, _loader)
            if loaded:
                _update_fov(game._state)
                game.refresh_all()
                self.notify(f"已读取 {slot}")
                self.pop_screen()
                return
            current_screen = self.screen
            if hasattr(current_screen, "show_message"):
                current_screen.show_message("记录为空")
            else:
                self.notify("记录为空")
            return
        slot_data = next(
            item for item in save_manager.list_slots() if item["slot"] == slot
        )
        if slot_data["updated_at"] is None:
            current_screen = self.screen
            if hasattr(current_screen, "show_message"):
                current_screen.show_message("记录为空")
            else:
                self.notify("记录为空")
            return
        self.switch_screen(GameScreen(char_key=self._char_key, load_slot=slot))

    def show_journey_end(self) -> None:
        if any(isinstance(screen, JourneyEndScreen) for screen in self.screen_stack):
            return
        self.push_screen(JourneyEndScreen())

    def start_char_select(self) -> None:
        """唤醒 → 进入角色选择画面。"""
        self.switch_screen(CharSelectScreen())

    def start_game_with(self, char_key: str, domain: str | None = None) -> None:
        """以所选角色启动游戏。mage 需传魔法领域。"""
        self._char_key = char_key
        self.switch_screen(GameScreen(char_key=char_key, domain=domain))

    def back_to_title(self) -> None:
        """返回标题画面（新实例，不预存）。"""
        self.switch_screen(TitleScreen())
