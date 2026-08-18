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

from core.game_state import GameState, _move_ap_cost
from core.entity import Entity, Weapon, are_hostile
import core.entity as ent
from core.movement import Terrain
from core.movement import find_path
from core.fov import LightLevel, compute_fov
from core.combat.initiative import roll_initiative
from core.combat.attack import hit_check, roll_damage, reduce_tenacity, apply_damage_type_modifiers, parse_dice, roll_dice, resolve_attack, miss_message, cover_message, normalize_damage_type
from core.combat.flow import CombatFlow
from core.map.generation import build_world, build_dungeon
from core.dice import roll_d20, check_dc, roll_2d6
from core.ai.engine import BehaviorEngine

from core.rest import short_rest, long_rest
from core.loader import DataLoader
from core.save.database import SaveManager
from core.interact import InteractType, scan_interact_targets
from core.trade import load_shop, trade_buy, trade_sell, price_to_text, copper_to_currency, shop_gold_text, player_receive, _build_item_cache, resolve_items, _load_item_by_key
from core.item_actions import get_item_actions, find_placeable_tile, place_on_ground, remove_from_inventory as item_remove_from_inventory, copy_item_with_count, get_throw_range, get_throw_max_range, tile_space_used, MAX_TILE_SPACE
from render.textual.widgets import (
    TopBar, LeftPanel, MapView, MapLegend, RightPanel, ActionLog, SceneLog,
)
from render.textual.screens.title_main import TitleScreen
from render.textual.screens.char_select import CharSelectScreen
import os
from render.textual.controllers.inventory import InventoryMixin
from render.textual.controllers.interact import InteractMixin
from render.textual.controllers.targeting import TargetingMixin
from render.textual.controllers.npc_runner import NpcRunnerMixin
from render.textual.controllers.commands import CommandMixin
from render.textual.controllers.keybinds import KeybindMixin
from render.textual.fov import _update_fov
from core.loot import _add_to_inventory
from core.loader import _load_dialogues, _load_scene_actions

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
SAVE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "saves")
_loader = DataLoader(DATA_DIR)
_ai_engine = BehaviorEngine()


class GameInput(Input):
    """Input 子类：输入框按键过滤器，拦截不应被输入到框内的特殊键。"""

    def _on_key(self, event: Key) -> None:
        if event.key == "colon":
            self.disabled = True
            event.stop()
            return
        super()._on_key(event)




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

    #main { height: 3fr; min-height: 15; }
    #left { width: 2fr; min-width: 14; height: 100%; border-right: solid #444444; padding: 0 1; }
    #map-column { width: 3fr; min-width: 20; height: 100%; }
    MapView { width: 100%; height: 1fr; content-align: center middle; }
    #map-legend { height: 3; padding: 0 1; }
    #right { width: 2fr; min-width: 18; height: 100%; border-left: solid #444444; padding: 0 1; }

    #input-bar { height: 3; border: solid #444444; }

    #log-area { height: 2fr; min-height: 6; border: solid #444444; }
    #action-log { width: 1fr; min-width: 20; height: 100%; border-right: solid #444444; padding: 0 1; content-align: left top; }
    #scene-log { width: 1fr; min-width: 20; height: 100%; padding: 0 1; content-align: left top; }
    """

    BINDINGS = [
        Binding("up", "move_up", "", priority=True),
        Binding("down", "move_down", "", priority=True),
        Binding("left", "move_left", "", priority=True),
        Binding("right", "move_right", "", priority=True),
        Binding("colon", "focus_input", "", priority=True),
        Binding("shift+tab", "end_turn", "结束战斗轮", priority=True),
        Binding("enter", "confirm_attack", "", priority=False),
        Binding("f5", "quick_save", "存档", priority=True),
        Binding("f9", "quick_load", "读档", priority=True),
        Binding("apostrophe", "cancel_ranged_target", "", priority=False),
    ]

    # ── 视图注册表：每个视图声明支持的按键和输入命令 ──

    _EXPLORE_KEYS = {
        "0", "N", "g", "G", "r", "R", "comma", "F", "A", "S",
    }

    _RIGHT_DEFAULT_KEYS = {"X", "C", "I", "B", "E", "Z", "K", "Y", "H", "M"}

    VIEW_DEFS = {
        # ── 左栏 ──
        "explore":                {"keys": _EXPLORE_KEYS, "commands": {"D": "_cmd_facing_input"}},
        "combat_idle":            {"keys": _EXPLORE_KEYS, "commands": {"D": "_cmd_facing_input"}},
        "combat_select_action":   {"keys": set(), "commands": {"A": "_cmd_action_input"}},
        "combat_select_spell":    {"keys": set(), "commands": {"A": "_cmd_spell_input"}},
        "combat_select_maneuver": {"keys": set(), "commands": {"A": "_cmd_maneuver_input"}},
        "combat_select_special":  {"keys": set(), "commands": {"A": "_cmd_special_input"}},
        "combat_adv_select":      {"keys": set(),
                                   "commands": {"0": "_cmd_adv_select", "1": "_cmd_adv_select",
                                                "2": "_cmd_adv_select", "3": "_cmd_adv_select",
                                                "4": "_cmd_adv_select", "5": "_cmd_adv_select",
                                                "6": "_cmd_adv_select", "7": "_cmd_adv_select",
                                                "8": "_cmd_adv_select", "9": "_cmd_adv_select"}},
        "combat_ranged_target":   {"keys": {"enter", "apostrophe"}, "commands": {}},
        "interact_menu":          {"keys": {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}, "commands": {}},
        "talking":                {"keys": {"T", "0"}, "commands": {}},
        "trading":                {"keys": {"0"}, "commands": {"B": "_cmd_trade_buy", "S": "_cmd_trade_sell"}},
        "cooking_tools":          {"keys": set(), "commands": {"A": "_interact_cook"}},
        "cooking":                {"keys": set(), "commands": {"A": "_interact_cook"}},
        "chest":                  {"keys": {"0"}, "commands": {"C": "_handle_chest_take", "S": "_handle_chest_store"}},
        "chest_qty":              {"keys": {"0"}, "commands": {"C": "_handle_chest_take_qty", "S": "_handle_chest_store_qty"}},
        "action_menu":            {"keys": {"0"}, "commands": {"N": "_cmd_action_menu_input"}},
        "shove_choice":           {"keys": set(), "commands": {"S": "_cmd_shove_choice"}},
        "corpse":                 {"keys": {"0", "1", "2"}, "commands": {}},
        # ── 右栏 ──
        "right_default":          {"keys": _RIGHT_DEFAULT_KEYS, "commands": {}},
        "right_inventory":        {"keys": {"I", "C", "X"}, "commands": {"I": "_use_item", "U": "_handle_unequip", "W": "_swap_hands"}},
        "right_character":        {"keys": {"C", "I", "X"}, "commands": {}},
        "right_system":           {"keys": set(), "commands": {"E": "_cmd_system_input"}},
        "right_spellbook":        {"keys": {"B"}, "commands": {"I": "_cmd_spellbook_input"}},
        "right_item_menu":        {"keys": set(), "commands": {"U": "_cmd_item_action"}},
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
    }

    def __init__(self, char_key: str = "伊芙琳", domain: str | None = None):
        super().__init__()
        self._char_key = char_key
        self._domain = domain
        self._state: GameState | None = None
        self._act_log: ActionLog | None = None
        self._scene_log: SceneLog | None = None
        self._map_view: MapView | None = None
        self._left_panel: LeftPanel | None = None
        self._right_panel: RightPanel | None = None
        self._input_bar: Input | None = None
        self._top_bar: TopBar | None = None
        self._last_move: tuple[int, int] = (0, 0)

    @property
    def _pn(self) -> str:
        """玩家名称快捷访问。后续自定义名称只需改 Entity 构造处。（Phase 3）"""
        return self._state.player.name

    def _create_game(self) -> None:
        # 玩家选的角色 key
        char_key = self._char_key

        self._state = GameState(map_width=80, map_height=60)

        # 加载战技数据
        with open(os.path.join(DATA_DIR, "maneuvers.json"), "r", encoding="utf-8") as f:
            mdata = json.load(f)
        self._state.maneuvers = mdata.get("maneuvers", mdata if isinstance(mdata, list) else [])

        # 钟摆推进前刷新 FOV（确保 NPC 检测用最新位置）
        self._state._pre_tick_fov_cb = lambda: _update_fov(self._state)
        self._state._npc_log_cb = lambda msg: self._act_log.add(msg) if self._act_log else None
        self._state._ai_decide_cb = lambda c, ek: _ai_engine.decide(c, extra_keys=ek)

        # build_world 统一加载所有实体（包括 fighter/mage，和其他村民一样）
        build_world(self._state, _loader)

        # 从已加载的实体中找到玩家选的角色，挂载控制组件
        for c, _ in self._state.entities:
            if c.template_name == char_key:
                self._state.set_controlled(c)
                # 法师 domain 注入（若玩家选了不同 domain）
                if char_key == "伊芙琳" and self._domain and self._domain != "evocation":
                    spells = {"evocation": ["魔法飞弹"], "abjuration": ["护盾术", "疗伤术"]}
                    c.spell_domains = [self._domain]
                    c.memorized_spells = spells.get(self._domain, [])
                break

        _update_fov(self._state)
        self._save_manager = SaveManager(SAVE_DIR)
        # 战斗流程状态机（需在 widgets 创建后初始化，使用延迟绑定）
        self._combat_flow: CombatFlow | None = None

    def _init_combat_flow(self) -> None:
        """在 compose 完成后初始化 CombatFlow（依赖已创建的 widgets）。"""
        self._combat_flow = CombatFlow(
            self._state, self._act_log, self._left_panel,
            self._input_bar, self._map_view, self._pn,
            lambda t: self._start_combat(t, ambush=True), self.refresh_all,
            on_two_hand_cb=self._on_two_hand_equip,
            wake_cb=lambda: self._wake_input(),
            on_torch_action_cb=self._on_torch_action,
        )

    def compose(self) -> ComposeResult:
        self._top_bar = TopBar(id="top"); yield self._top_bar
        with Horizontal(id="main"):
            self._left_panel = LeftPanel(id="left"); yield self._left_panel
            with Vertical(id="map-column"):
                self._map_view = MapView(); yield self._map_view
                self._map_legend = MapLegend(id="map-legend"); yield self._map_legend
            self._right_panel = RightPanel(id="right"); yield self._right_panel
        self._input_bar = GameInput(placeholder=": 输入命令(Esc退出) LU/LD左日志 RU/RD右日志", id="input-bar", disabled=True)
        yield self._input_bar
        with Horizontal(id="log-area"):
            self._act_log = ActionLog(id="action-log"); yield self._act_log
            self._scene_log = SceneLog(id="scene-log"); yield self._scene_log

    def on_mount(self) -> None:
        self._create_game()
        for w in [self._map_view, self._map_legend, self._left_panel, self._right_panel, self._top_bar]:
            w.state = self._state
        self._init_combat_flow()
        self._refresh_scene()
        self.refresh_all()
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
        """完全空闲时关闭输入框，远程瞄准时也关闭（方向键操作，不需要输入）。"""
        if self._state is None:
            return
        phase = self._state.combat_phase
        # 远程瞄准模式用方向键+Enter，不需要输入框
        if phase == "ranged_target":
            self._close_input()
            return
        # 命中/未命中/优势选择面板 → 唤起输入框（与物品栏同理：进入面板即唤）
        if phase in ("select_maneuver", "select_special", "adv_select"):
            self._wake_input()
            return
        if (phase == "idle"
                and not self._state.interact_phase
                and not self._state.item_menu_stack
                and (self._right_panel is None or self._right_panel.view_mode == "default")):
            self._close_input()

    def refresh_all(self) -> None:
        for w in [self._map_view, self._map_legend, self._left_panel,
                  self._right_panel, self._top_bar, self._act_log, self._scene_log]:
            if w: w.refresh()
        self._sync_input()
        self._sync_carry_status()
    def _start_spell_targeting(self, spell: dict) -> None:
        """进入法术瞄准阶段：统一选格子（同远程攻击），范围允许即可选自身/空地。支持多目标。"""
        missiles = spell.get("effect", {}).get("missiles", 1)
        self._state.observe_mode = False
        self._state.pending_attack = {
            "mode": "spell", "spell": spell,
            "target_count": missiles, "targets": [],
            "max_range": spell.get("range", 1),
        }
        self._state.combat_phase = "ranged_target"
        self._state.observe_cursor = self._state.player_pos
        rng = spell.get("range", 1)
        if missiles > 1:
            prompt = f"选择 {spell['name']} 目标 (1/{missiles})"
        else:
            prompt = f"选择 {spell['name']} 目标"
        self._act_log.add(f"{prompt} — 范围:{rng} [方向键]移动 [Enter]确认 [']取消")
        self._close_input()
        self.refresh_all()

    def _cast_spell(self, spell: dict, target: "Entity | None | list") -> None:
        """执行法术施放：扣 MP + AP/钟摆，结算效果。target 可为单个/None 或多目标列表。"""
        from core.spell import resolve_spell
        caster = self._state.player
        mp_cost = spell.get("mp_cost", 0)
        if caster.mp < mp_cost:
            self._act_log.add("MP 不足")
            return
        caster.mp -= mp_cost
        # 消耗 AP（战斗）或钟摆（探索）
        if self._state.in_combat:
            caster.ap -= spell.get("cast_time_ap", 0)
        else:
            self._state.clock.tick_action(spell.get("cast_time_pendulum", 0))
        result = resolve_spell(caster, target, spell)
        self._act_log.add(result["message"])
        # 伤害型法术 → 检查态度反应（多目标逐个）
        if result.get("effect") != "heal" and result.get("damage", 0) > 0:
            targets = target if isinstance(target, list) else [target]
            for t in targets:
                if t is not None and t.hp >= 0:
                    self._check_faction_reaction(t)
        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._state.pending_spells = []
        # 施法 → 破坏隐匿
        self._state._break_stealth_in_view(caster)
        _update_fov(self._state)
        self.refresh_all()
    def _enter_dungeon(self) -> None:
        """保存世界状态，进入地下城。"""
        from core.element import BurningSurface
        self._state.world_state = {
            "map": self._state.map, "entities": self._state.entities,
            "player_pos": self._state.player_pos, "current_map": self._state.current_map,
            "door_states": self._state.door_states,
            "location_map": self._state.location_map,
            "burning_surfaces": {
                k: BurningSurface(v.tier, v.fuel, v.tick)
                for k, v in self._state.burning_surfaces.items()
            },
            "wet_surfaces": dict(self._state.wet_surfaces),
            "regen_candidates": set(self._state.regen_candidates),
        }
        # 地下城为全新地图，清空地表元素状态
        self._state.burning_surfaces = {}
        self._state.wet_surfaces = {}
        self._state.regen_candidates = set()
        build_dungeon(self._state, _loader)
        self._state._bump_terrain_version()
        # 修复：build_dungeon 清空了 entities，需重新加入被控生物
        p = self._state.player
        if not any(c is p for c, _ in self._state.entities):
            self._state.entities.append((p, self._state.player_pos))
        self._state.in_dungeon = True
        self._act_log.add(f"{self._pn} 走入了地下城...")
        self._end_combat(); _update_fov(self._state)
        self._refresh_scene(); self.refresh_all()

    def _exit_dungeon(self) -> None:
        """恢复世界状态，退出地下城。"""
        ws = self._state.world_state
        if ws:
            self._state.map = ws["map"]
            self._state._bump_terrain_version()
            self._state.entities = ws["entities"]
            self._state.player_pos = ws["player_pos"]
            self._state.current_map = ws["current_map"]
            self._state.door_states = ws["door_states"]
            self._state.location_map = ws.get("location_map", {})
            self._state.burning_surfaces = ws.get("burning_surfaces", {})
            self._state.wet_surfaces = ws.get("wet_surfaces", {})
            self._state.regen_candidates = ws.get("regen_candidates", set())
        # 确保被控生物在实体列表中
        p = self._state.player
        if p is not None and not any(c is p for c, _ in self._state.entities):
            self._state.entities.append((p, self._state.player_pos))
        self._state.in_dungeon = False
        self._act_log.add(f"{self._pn} 回到了地面")
        self._end_combat(); _update_fov(self._state)
        self._refresh_scene(); self.refresh_all()

    # ── Combat ──

    def _start_combat(self, target: Entity, ambush: bool = False) -> None:
        """进入战斗。ambush=True 时玩家必定先手（探索模式主动攻击）。"""
        if target.is_dead:
            return
        self._state.in_combat = True
        self._state._combat_ticked = False
        self._state.player.ap = self._state.player.max_ap
        combatants = [self._state.player]
        pc, pr = self._state.player_pos
        for creature, (ec, er) in self._state.entities:
            if creature.hp > 0 and are_hostile(creature, self._state.player) \
               and (ec - pc) ** 2 + (er - pr) ** 2 <= creature.vision_range ** 2:
                combatants.append(creature)
                creature.ap = creature.max_ap
        # 弹药武器：战斗开始时重置为未装填
        for item in self._state.player.equipment.values():
            if item is not None:
                props = getattr(item, 'properties', []) or []
                if "ammo" in props:
                    item.loaded = False
        for item in self._state.player.inventory:
            props = getattr(item, 'properties', []) or []
            if "ammo" in props:
                item.loaded = False

        self._state.combat_initiative = roll_initiative(combatants)
        self._state.combat_turn_index = 0

        turn = self._state.player if ambush else combatants[0]
        self._state.combat_turn_entity = turn
        turn.ap = turn.max_ap
        self._act_log.add("=== 战斗开始 ===")
        if turn is self._state.player:
            self._act_log.add(f">>> {self._pn}的战斗轮 <<<")
        else:
            self._act_log.add(f">>> {turn.name}的战斗轮 <<<")
            self._state._npc_act(turn)
            self._next_turn()
            self.refresh_all()
            return

    def _end_combat(self) -> None:
        # 当前轮未完成（敌人死在半轮等场景）→ 补推
        if not getattr(self._state, '_combat_ticked', False):
            self._state.clock.tick_combat_round()
        self._state.in_combat = False; self._state.combat_initiative = []
        self._state.combat_turn_entity = None
        self._state.player.ap = self._state.player.max_ap
        self._state._combat_ticked = False
        self._act_log.add("=== 战斗结束 ===")

    def _next_turn(self) -> None:
        if not self._state.in_combat: return
        self._state._combat_ticked = False  # 每次进入重置，不跨调用泄漏

        # 透明网格（复用缓存，一部构建，参战拉入+脱战共用，阶段2.5）
        from core.fov import _line_of_sight
        from core.movement import sector_of
        transparent = self._state._get_transparent_grid()

        # 拉入视野内未参战的敌对生物（朝向+距离+视线，阶段2.5）
        pc, pr = self._state.player_pos
        for creature, (ec, er) in self._state.entities:
            if creature.hp > 0 and are_hostile(creature, self._state.player) \
               and (ec - pc) ** 2 + (er - pr) ** 2 <= creature.vision_range ** 2 \
               and sector_of(creature.facing, (pc - ec, pr - er)) != "back" \
               and _line_of_sight(transparent, ec, er, pc, pr) \
               and creature not in self._state.combat_initiative:
                creature.ap = creature.max_ap
                self._state.combat_initiative.append(creature)
                self._act_log.add(f"{creature.name} 加入了战斗!")

        alive = [e for e in self._state.combat_initiative if e is self._state.player or not e.is_dead]
        hostiles = [e for e in alive if are_hostile(e, self._state.player) and not e.is_dead]
        if not hostiles:
            self._end_combat(); self.refresh_all(); return

        # 脱战判定：玩家不在所有敌对生物视野内（朝向+距离+视线，阶段2.5）
        all_out_of_sight = True
        for e in hostiles:
            epos = None
            for c, (ec, er) in self._state.entities:
                if c is e:
                    epos = (ec, er); break
            if epos is None:
                continue
            ec, er = epos
            if (ec - pc) ** 2 + (er - pr) ** 2 <= e.vision_range ** 2 \
               and sector_of(e.facing, (pc - ec, pr - er)) != "back" \
               and _line_of_sight(transparent, ec, er, pc, pr):
                all_out_of_sight = False
                break
        if all_out_of_sight:
            self._act_log.add(f"{self._pn} 脱离了敌人的视野，战斗结束")
            self._end_combat(); self.refresh_all(); return

        self._state.combat_initiative = alive
        idx = (self._state.combat_turn_index + 1) % len(alive)
        # 满轮 → 推进钟摆 6 + 非参战生物结算 6 钟摆
        if idx == 0:
            self._state.clock.tick_combat_round()
            self._state._combat_ticked = True
            self._state._advance_npcs(6.0, combatants=False)
        self._state.combat_turn_index = idx; turn = alive[idx]
        self._state.combat_turn_entity = turn
        # 回合开始清除撤离/回避状态（至下回合开始失效）
        turn.remove_status("disengaged")
        turn.remove_status("dodge")
        turn.ap = turn.max_ap
        if turn is self._state.player:
            self._act_log.add(f">>> {self._pn}的战斗轮 <<<")
            # 玩家濒死 → 掷死亡豁免；死亡/稳定则结束战斗
            if turn.has_status("濒死"):
                result = self._state._roll_death_save(turn)
                if result == "died":
                    self._act_log.add(f"{self._pn} 死了……")
                    self._end_combat(); self.refresh_all(); return
                if result in ("stable", "woke"):
                    self._end_combat(); self.refresh_all(); return
        else:
            self._act_log.add(f">>> {turn.name}的战斗轮 <<<")
            self._state._npc_act(turn)
            self._next_turn()
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
        self._combat_flow.check_faction_reaction(target, self._state.player)
    def _refresh_scene(self) -> None:
        fov = self._state.fov_cache
        pc, pr = self._state.player_pos
        lines = []
        for creature, (ec, er) in self._state.entities:
            if (ec, er) not in fov or creature.is_dead: continue
            if creature is self._state.player: continue
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
            status_text = f" [{', '.join(s.name for s in c.statuses)}]"
        return f"{c.name}{status_text} {hp}{desc}"
    def action_quick_save(self) -> None:
        """快速存档 — 固定使用 quicksave 槽位（持久化到磁盘）。"""
        if self._state is None:
            return
        if self._state.in_combat:
            self._act_log.add("战斗中无法存档")
            return
        self._save_manager.save(self._state, slot="quicksave")
        self._act_log.add("[快速存档] 已保存")

    def action_quick_load(self) -> None:
        """快速读档 — 从 quicksave 槽位恢复。"""
        if self._state is None:
            return
        if self._state.in_combat:
            self._act_log.add("战斗中无法读档")
            return

        # 检查存档是否存在
        path = os.path.join(self._save_manager._dir, "quicksave.json")
        if not os.path.exists(path):
            self._act_log.add("没有快速存档")
            return

        # 获取存档中的地图名，必要时重建地图
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        current_map = meta.get("current_map", "")
        if current_map != self._state.current_map:
            # 需要加载不同地图：重建世界/地下城
            if current_map == "世界":
                build_world(self._state, _loader)
            elif current_map == "地下城":
                build_dungeon(self._state, _loader)

        # 恢复状态
        success = self._save_manager.load(self._state, slot="quicksave", loader=_loader)
        if success:
            self._end_combat()
            _update_fov(self._state)
            self._refresh_scene()
            self._act_log.add("[快速读档] 已恢复")
        else:
            self._act_log.add("[快速读档] 失败")
        self.refresh_all()


# ═════════════════════════════════════ MVPApp ═══════════════════════════════════════

class MVPApp(App):
    """薄壳 App：只负责标题/游戏两个屏幕之间的切换。"""

    def on_mount(self) -> None:
        self.push_screen(TitleScreen())

    def start_char_select(self) -> None:
        """唤醒 → 进入角色选择画面。"""
        self.switch_screen(CharSelectScreen())

    def start_game_with(self, char_key: str, domain: str | None = None) -> None:
        """以所选角色启动游戏。mage 需传魔法领域。"""
        self.switch_screen(GameScreen(char_key=char_key, domain=domain))

    def back_to_title(self) -> None:
        """返回标题画面（新实例，不预存）。"""
        self.switch_screen(TitleScreen())
