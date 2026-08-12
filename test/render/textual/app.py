"""Textual MVP App — 完整游戏原型。"""

import json
import random
from textual.app import App, ComposeResult
from textual.widgets import Input
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from textual.events import Key

from core.game_state import GameState
from core.entity import Player, Creature, Weapon
import core.entity as ent
from core.movement import Terrain
from core.grid import Grid
from core.movement import find_path
from core.fov import LightLevel, compute_fov
from core.combat.initiative import roll_initiative
from core.combat.attack import hit_check, roll_damage, reduce_tenacity, apply_damage_type_modifiers, parse_dice, roll_dice, resolve_attack, miss_message, cover_message
from core.combat.flow import CombatFlow
from core.map.generation import build_world, build_dungeon
from core.dice import roll_d20
from core.ai.engine import BehaviorEngine
from core.rest import short_rest, long_rest
from core.loader import DataLoader
from core.save.database import SaveManager
from core.interact import InteractType, scan_interact_targets
from core.trade import load_shop, trade_buy, trade_sell, price_to_text, copper_to_currency, shop_gold_text
from render.textual.widgets import (
    TopBar, LeftPanel, MapView, MapLegend, RightPanel, ActionLog, SceneLog,
)
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
SAVE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "saves")
_loader = DataLoader(DATA_DIR)
_ai_engine = BehaviorEngine({
    "goblin_brawler": _loader.load_json("ai/goblin_brawler"),
    "skeleton": _loader.load_json("ai/skeleton"),
})


class GameInput(Input):
    """Input 子类：X 键不消费，阻止输入模式下触发观察模式。"""

    def _on_key(self, event: Key) -> None:
        if event.key == "X":
            event.stop()
            return
        super()._on_key(event)


def _add_to_inventory(player, item) -> None:
    """添加物品到背包，同名称同类型物品堆叠计数。"""
    for existing in player.inventory:
        if existing.name == item.name and existing.item_type == item.item_type:
            existing.count += item.count
            existing.weight += item.weight
            return
    player.inventory.append(item)


# ── JSON 数据加载辅助 ──

_DIALOGUES_CACHE: dict | None = None
_SCENE_ACTIONS_CACHE: dict | None = None


def _load_dialogues() -> dict:
    """加载 NPC 对话数据。"""
    global _DIALOGUES_CACHE
    if _DIALOGUES_CACHE is not None:
        return _DIALOGUES_CACHE
    path = os.path.join(DATA_DIR, "dialogues.json")
    with open(path, "r", encoding="utf-8") as f:
        _DIALOGUES_CACHE = json.load(f)
    return _DIALOGUES_CACHE


def _load_scene_actions() -> dict:
    """加载场景描述文本。"""
    global _SCENE_ACTIONS_CACHE
    if _SCENE_ACTIONS_CACHE is not None:
        return _SCENE_ACTIONS_CACHE
    path = os.path.join(DATA_DIR, "scene_actions.json")
    with open(path, "r", encoding="utf-8") as f:
        _SCENE_ACTIONS_CACHE = json.load(f)
    return _SCENE_ACTIONS_CACHE


# ── 交互分发哈希表（新增交互类型只需加一行）──

_INTERACT_DISPATCH = {
    InteractType.TALK: "_interact_talk",
    InteractType.LOOT: "_interact_loot",
    InteractType.PICK: "_interact_pick",
    InteractType.REST: "_interact_rest",
    InteractType.OPEN: "_interact_door",
    InteractType.ENTER: "_interact_entrance",
}


def _update_fov(state: GameState) -> None:
    ox, oy = state.player_pos
    transparent = Grid[bool](state.map.width, state.map.height, True)
    for col in range(state.map.width):
        for row in range(state.map.height):
            if state.map[col, row] == Terrain.WALL:
                transparent[col, row] = False
    light = Grid[LightLevel](state.map.width, state.map.height,
                             LightLevel.BRIGHT if not state.in_dungeon else LightLevel.DARK)
    state.fov_cache = compute_fov(transparent, (ox, oy), state.player.vision_range,
                                  light, state.player.darkvision_range > 0,
                                  state.player.darkvision_range)


# ═══════════════════════════════════════ App ═══════════════════════════════════════

class MVPApp(App):
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
    ]

    # ── 视图注册表：每个视图声明支持的按键和输入命令 ──

    _EXPLORE_KEYS = {
        "0", "1", "2", "3", "4", "5", "6", "7", "8",
        "slash", "g", "G", "r", "R", "comma", "A", "S", "Q",
        "X", "C", "I", "B", "Z", "K", "Y", "H", "M", "E",
    }

    VIEW_DEFS = {
        "explore":                {"keys": _EXPLORE_KEYS, "commands": {}},
        "combat_idle":            {"keys": _EXPLORE_KEYS, "commands": {}},
        "inventory":              {"keys": _EXPLORE_KEYS, "commands": {"I": "_use_item", "U": "_handle_unequip", "W": "_swap_hands"}},
        "character":              {"keys": _EXPLORE_KEYS, "commands": {}},
        "observe":                {"keys": {"X", "escape"}, "commands": {}},
        "trading":                {"keys": _EXPLORE_KEYS, "commands": {"B": "_cmd_trade_buy", "S": "_cmd_trade_sell"}},
        "talking":                {"keys": _EXPLORE_KEYS, "commands": {}},
        "interact_menu":          {"keys": _EXPLORE_KEYS, "commands": {}},
        "combat_select_action":   {"keys": {"X", "C", "I", "enter"}, "commands": {"A": "_cmd_action_input"}},
        "combat_select_target":   {"keys": {"X", "C", "I", "enter"}, "commands": {"T": "_cmd_target_input"}},
        "combat_select_maneuver": {"keys": {"X", "C", "I", "enter"}, "commands": {"A": "_cmd_maneuver_input"}},
        "combat_select_special":  {"keys": {"X", "C", "I", "enter"}, "commands": {"A": "_cmd_special_input"}},
        "combat_ranged_target":   {"keys": set(), "commands": {}},
    }

    def __init__(self):
        super().__init__()
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
        """玩家名称快捷访问。后续自定义名称只需改 Player 构造处。"""
        return self._state.player.name

    def _create_game(self) -> None:
        import json

        # 加载玩家初始数据
        with open(os.path.join(DATA_DIR, "player_start.json"), "r", encoding="utf-8") as f:
            ps_data = json.load(f)

        stats = dict(ps_data["stats"])
        boosted = random.sample(["str", "dex", "con", "int", "wis", "cha"], ps_data["boosted_stats"])
        for s in boosted:
            stats[s] += 2

        if ps_data["class"] == "fighter":
            player = Player.create_fighter(name=ps_data["name"], stats=stats)
        else:
            player = Player.create_fighter(name=ps_data["name"], stats=stats)

        self._state = GameState(player=player, map_width=80, map_height=60)

        # 加载战技数据
        with open(os.path.join(DATA_DIR, "maneuvers.json"), "r", encoding="utf-8") as f:
            mdata = json.load(f)
        self._state.maneuvers = mdata.get("maneuvers", mdata if isinstance(mdata, list) else [])

        # 钟摆推进前刷新 FOV（确保 NPC 检测用最新位置）
        self._state._pre_tick_fov_cb = lambda: _update_fov(self._state)
        build_world(self._state, _loader)
        self._state.player_pos = tuple(ps_data["start_pos"])

        # 初始装备
        for slot, item_data in ps_data.get("equipment", {}).items():
            if item_data and slot in self._state.player.equipment:
                self._state.player.equipment[slot] = ent.Weapon.from_dict(item_data)
        # 预置初始物品
        for item_data in ps_data.get("inventory", []):
            if item_data.get("item_type") == "weapon":
                _add_to_inventory(self._state.player, ent.Weapon.from_dict(item_data))
            else:
                _add_to_inventory(self._state.player, ent.Item.from_dict(item_data))

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
        )

    def compose(self) -> ComposeResult:
        self._create_game()
        self._top_bar = TopBar(id="top"); yield self._top_bar
        with Horizontal(id="main"):
            self._left_panel = LeftPanel(id="left"); yield self._left_panel
            with Vertical(id="map-column"):
                self._map_view = MapView(); yield self._map_view
                self._map_legend = MapLegend(id="map-legend"); yield self._map_legend
            self._right_panel = RightPanel(id="right"); yield self._right_panel
        self._input_bar = GameInput(placeholder=": 输入命令 (按 Esc 退出输入)", id="input-bar", disabled=True)
        yield self._input_bar
        with Horizontal(id="log-area"):
            self._act_log = ActionLog(id="action-log"); yield self._act_log
            self._scene_log = SceneLog(id="scene-log"); yield self._scene_log

    def on_mount(self) -> None:
        for w in [self._map_view, self._map_legend, self._left_panel, self._right_panel, self._top_bar]:
            w.state = self._state
        self._init_combat_flow()
        self._refresh_scene()
        self.refresh_all()
        self._map_view.focus()

    # 需要输入框获得焦点的战斗阶段
    _COMBAT_INPUT_PHASES = {
        "select_action", "select_target", "select_maneuver", "select_special",
    }

    # 需要输入框获得焦点的交互阶段
    _INTERACT_INPUT_PHASES = {"trading"}

    def _sync_input_focus(self) -> None:
        """根据当前视图状态同步输入框焦点。"""
        phase = self._state.combat_phase
        if phase in self._COMBAT_INPUT_PHASES:
            self._input_bar.disabled = False
            self._input_bar.focus()
        elif phase == "ranged_target":
            self._input_bar.disabled = True
            self._map_view.focus()
        elif self._state.interact_phase in self._INTERACT_INPUT_PHASES:
            self._input_bar.disabled = False
            self._input_bar.focus()
        else:
            self._input_bar.disabled = True

    def refresh_all(self) -> None:
        for w in [self._map_view, self._map_legend, self._left_panel,
                  self._right_panel, self._top_bar, self._act_log, self._scene_log]:
            if w: w.refresh()
        self._sync_input_focus()
        self._sync_carry_status()

    def on_key(self, event) -> None:
        """上下文感知的按键分发：只有当前面板显示的键才触发。"""
        key = event.key
        state = self._state

        # ── 0. Escape（全局：取消交互 / 取消远程瞄准 / 退出输入栏 / 退出右侧栏视图）──
        if key == "escape":
            # 交互阶段：输入框活跃 → 只退出输入模式，保留交互状态
            if state and state.interact_phase:
                if self._input_bar and not self._input_bar.disabled:
                    self._input_bar.disabled = True
                    event.stop()
                    return
                self._cancel_interact()
                event.stop()
                return
            if state and state.combat_phase == "ranged_target":
                self._combat_flow.cancel_ranged_target()
                event.stop()
                return
            # 输入栏活跃 → 只退出输入模式（战斗子阶段需额外回退）
            if self._input_bar and not self._input_bar.disabled:
                cp = state.combat_phase
                if cp in ("select_target", "select_maneuver", "select_special"):
                    state.combat_phase = "select_action"
                elif cp == "select_action":
                    state.combat_phase = "idle"
                    state.pending_attack = {}
                self._input_bar.disabled = True
                event.stop()
                return
            # 右侧栏视图退出
            view = self._right_panel.view_mode if self._right_panel else "default"
            if view != "default":
                self._right_panel.view_mode = "default"
                self._right_panel.refresh()
                event.stop()
            return

        # ── 1. 输入栏聚焦时 → 不响应任何快捷键 ──
        if self._input_bar and self._input_bar.has_focus:
            return

        # ── 1.5. 交互阶段专用按键 ──
        if state and state.interact_phase:
            if self._try_interact_key(key):
                event.stop()
                return

        # ── 2. 合并活跃视图的按键集 ──
        if state is None:
            return
        allowed = set()
        for view_name in self._get_active_views():
            vdef = self.VIEW_DEFS.get(view_name, {})
            keys = vdef.get("keys", set())
            if not isinstance(keys, set):
                keys = set()
            allowed |= keys

        if key not in allowed and key != "enter":
            return

        # ── 3. 分发 ──
        self._dispatch_key(key)
        event.stop()

    def _dispatch_key(self, key: str) -> None:
        """根据按键分发到对应的 action 方法。"""
        actions = {
            "0": self.action_interact,
            "1": self.action_1,
            "2": self.action_2,
            "3": self.action_3,
            "4": self.action_4,
            "5": self.action_5,
            "6": self.action_6,
            "7": self.action_7,
            "8": self.action_8,
            "slash": self.action_toggle_knockout,
            "g": self.action_slow_speed,
            "G": self.action_dash,
            "r": self.action_short_rest,
            "R": self.action_long_rest,
            "comma": self.action_wait,
            "X": self.action_toggle_observe,
            "A": self.action_show_actions,
            "S": self.action_show_spells,
            "Q": self._quit_game,
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
        }
        handler = actions.get(key)
        if handler:
            handler()
        else:
            self._act_log.add(f"[{key}] 功能待定")

    def _quit_game(self) -> None:
        self.exit()

    # ── Input ──

    def action_focus_input(self) -> None:
        self._input_bar.disabled = False
        self._input_bar.focus()

    def _get_active_views(self) -> list[str]:
        """返回当前活跃视图列表。多个视图可同时活跃（如 trading + inventory）。"""
        views = []
        state = self._state
        # 交互覆盖层
        ip = state.interact_phase
        if ip:
            views.append(ip)
        # 战斗子阶段
        cp = state.combat_phase
        if cp != "idle":
            views.append("combat_" + cp)
        # 右侧面板（观察模式下仅展示，不参与按键分发）
        if state.observe_mode:
            views.append("observe")
        else:
            rv = self._right_panel.view_mode if self._right_panel else "default"
            if rv != "default":
                views.append(rv)
        # 基础视图
        if not views:
            views.append("combat_idle" if state.in_combat else "explore")
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
        return False

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

    def _cmd_target_input(self, cmd: str) -> None:
        self._combat_flow.handle_target_input(cmd)

    def _cmd_maneuver_input(self, cmd: str) -> None:
        self._combat_flow.handle_maneuver_input(cmd)

    def _cmd_special_input(self, cmd: str) -> None:
        self._combat_flow.handle_special_input(cmd)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        self._input_bar.value = ""
        if not cmd:
            self._sync_input_focus()
            return

        # 合并所有活跃视图的命令表
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
                self._sync_input_focus()
                return

        self._act_log.add(f"> :{cmd}")
        self._act_log.add("功能待定")
        self._sync_input_focus()

    def _use_item(self, cmd: str) -> None:
        """使用物品：I + 序号，如 I1 使用第 1 个物品。"""
        try:
            idx = int(cmd[1:]) - 1
            inv = self._state.player.inventory
            if 0 <= idx < len(inv):
                item = inv[idx]
                if isinstance(item, ent.Weapon):
                    single = self._take_one_from_stack(item, inv, idx)
                    if single:
                        self._equip_to_hand(single)
                    self._right_panel.refresh()
                    return
                if isinstance(item, ent.Armor):
                    single = self._take_one_from_stack(item, inv, idx)
                    if single:
                        self._equip_armor_from_inventory(single)
                    self._right_panel.refresh()
                    return
                # 消耗品
                cost = item.ap_cost
                if self._state.in_combat and self._state.player.ap < cost:
                    self._act_log.add("AP 不足，无法使用物品")
                    self._right_panel.refresh()
                    return
                if item.count > 1:
                    item.count -= 1
                else:
                    inv.pop(idx)
                if self._state.in_combat:
                    self._state.player.ap -= cost
                self._act_log.add(f"{self._pn} 使用了 {item.name}")
                self._apply_item_effect(item)
            else:
                self._act_log.add("物品序号无效")
        except (ValueError, IndexError):
            self._act_log.add("用法: :I序号  如 :I1 使用第1个物品")
        self._right_panel.refresh()

    def _take_one_from_stack(self, item, inv, idx):
        """从堆叠物品中取出一件。count>1 则减 count 退回单件；count==1 则 pop。
        返回单件物品，失败返回 None。"""
        if item.count > 1:
            unit_weight = item.weight / item.count
            item.count -= 1
            item.weight -= unit_weight
            # 创建单件副本
            if isinstance(item, ent.Weapon):
                return ent.Weapon(
                    name=item.name, weapon_type=item.weapon_type,
                    category=item.category, damage=item.damage,
                    damage_type=item.damage_type, attack_stat=item.attack_stat,
                    ap_cost=item.ap_cost, range_normal=item.range_normal,
                    range_max=item.range_max,
                    properties=list(item.properties) if item.properties else [],
                    weight=unit_weight, price=dict(item.price),
                    description=item.description, count=1,
                    loaded=getattr(item, 'loaded', True),
                )
            elif isinstance(item, ent.Armor):
                return ent.Armor(
                    name=item.name, armor_type=item.armor_type,
                    slot=item.slot, ac_bonus=item.ac_bonus,
                    tenacity_bonus=item.tenacity_bonus,
                    str_requirement=item.str_requirement,
                    weight=unit_weight, price=dict(item.price),
                    description=item.description, count=1,
                )
            else:
                return None
        else:
            return inv.pop(idx)

    # ── 装备/卸除/互换 ──

    def _equip_to_hand(self, item) -> None:
        """装备单手武器/盾牌到手部。先试左手，被占试右手，都被占则与左手互换。"""
        equip = self._state.player.equipment

        # 双手武器：先装到空闲手，另一手自动卸除
        props = getattr(item, 'properties', []) or []
        is_two_handed = 'two_handed' in props

        if is_two_handed:
            # 两手全部卸除，武器放到右手；逐手日志
            for hand in ("left_hand", "right_hand"):
                old = equip.get(hand)
                if old is not None:
                    equip[hand] = None
                    _add_to_inventory(self._state.player, old)
                    hand_name = "左手" if hand == "left_hand" else "右手"
                    self._act_log.add(f"{self._pn} 卸下了{hand_name}的{old.name}")
            equip["right_hand"] = item
            self._act_log.add(f"{self._pn} 双手握持了 {item.name}")
            return

        # 单手：左 → 右 顺序。先检查另一只手是否有双手武器
        for hand in ("left_hand", "right_hand"):
            if equip.get(hand) is None:
                other_hand = "right_hand" if hand == "left_hand" else "left_hand"
                other = equip.get(other_hand)
                if other is not None:
                    other_props = getattr(other, 'properties', []) or []
                    if 'two_handed' in other_props:
                        # 另一只手是双手武器 → 卸除它
                        equip[other_hand] = None
                        _add_to_inventory(self._state.player, other)
                        self._act_log.add(f"{self._pn} 收起了{other.name}（双手），装备了 {item.name}")
                        equip[hand] = item
                        return
                equip[hand] = item
                hand_name = "左手" if hand == "left_hand" else "右手"
                self._act_log.add(f"{self._pn} 装备了 {item.name}（{hand_name}）")
                return

        # 都占，与左手互换
        old = equip["left_hand"]
        equip["left_hand"] = item
        _add_to_inventory(self._state.player, old)
        self._act_log.add(f"{self._pn} 收起了{old.name}，装备了{item.name}（左手）")

    def _equip_armor_from_inventory(self, armor: "ent.Armor") -> None:
        """从物品栏装备护甲到对应部位。"""
        equip = self._state.player.equipment
        p = self._state.player

        slot = armor.slot
        # 盾牌视作单手装备
        if armor.armor_type == "shield":
            self._equip_shield(armor)
            return
        # 全身服饰 → 胸甲位
        if slot == "full_body":
            slot = "chest"
        old = equip.get(slot)
        if old is not None:
            _add_to_inventory(self._state.player, old)

        equip[slot] = armor
        # 更新 AC
        ac_field = {"head": "ac_head", "chest": "ac_chest", "arms": "ac_arms", "legs": "ac_legs"}.get(slot)
        if ac_field:
            setattr(p, ac_field, getattr(p, ac_field) + armor.ac_bonus)
        self._act_log.add(f"{self._pn} 装备了 {armor.name}")

    def _equip_shield(self, shield) -> None:
        """装备盾牌：先试左手，被占试右手，都被占则与左手互换（与单手武器规则一致）。"""
        equip = self._state.player.equipment
        p = self._state.player

        for hand in ("left_hand", "right_hand"):
            if equip.get(hand) is None:
                equip[hand] = shield
                p.ac_shield += shield.ac_bonus
                hand_name = "左手" if hand == "left_hand" else "右手"
                self._act_log.add(f"{self._pn} 装备了 {shield.name}（{hand_name}）")
                return

        # 都占，与左手互换
        old = equip["left_hand"]
        equip["left_hand"] = shield
        _add_to_inventory(self._state.player, old)
        # AC：去除旧物品的 shield AC（如果是盾牌），添加新盾牌 AC
        if isinstance(old, ent.Armor) and old.armor_type == "shield":
            p.ac_shield = max(0, p.ac_shield - old.ac_bonus)
        p.ac_shield += shield.ac_bonus
        self._act_log.add(f"{self._pn} 收起了{old.name}，装备了 {shield.name}（左手）")

    def _unequip_slot(self, slot: str) -> None:
        """卸除指定部位的装备，放入背包。双手武器从任一手卸除均可。"""
        p = self._state.player
        equip = p.equipment
        item = equip.get(slot)
        if item is None and slot in ("left_hand", "right_hand"):
            # 空手但另一只手有双手武器 → 卸除双手武器
            other_slot = "right_hand" if slot == "left_hand" else "left_hand"
            other = equip.get(other_slot)
            if other is not None:
                other_props = getattr(other, 'properties', []) or []
                if 'two_handed' in other_props:
                    item = other
                    slot = other_slot
        if item is None:
            self._act_log.add(f"该部位没有装备")
            return

        equip[slot] = None
        _add_to_inventory(self._state.player, item)

        # 重算对应 AC
        if slot in ("left_hand", "right_hand"):
            if isinstance(item, ent.Armor) and item.armor_type == "shield":
                p.ac_shield = max(0, p.ac_shield - item.ac_bonus)
        else:
            ac_field = {"head": "ac_head", "chest": "ac_chest", "arms": "ac_arms", "legs": "ac_legs"}.get(slot)
            if ac_field and isinstance(item, ent.Armor):
                setattr(p, ac_field, max(0, getattr(p, ac_field) - item.ac_bonus))

        slot_names = {"left_hand": "左手", "right_hand": "右手", "head": "头部",
                      "chest": "躯干", "arms": "双臂", "legs": "双腿"}
        slot_name = slot_names.get(slot, slot)
        self._act_log.add(f"{self._pn} 卸下了 {item.name}（{slot_name}）")
        self._right_panel.refresh()

    UNEQUIP_SLOTS = {
        1: "left_hand", 2: "right_hand",
        3: "head", 4: "chest", 5: "arms", 6: "legs",
    }

    def _handle_unequip(self, cmd: str) -> None:
        """处理卸除命令：:U1~:U6。"""
        try:
            idx = int(cmd[1:])
            slot = self.UNEQUIP_SLOTS.get(idx)
            if slot is None:
                self._act_log.add("用法: :U1 左手 :U2 右手 :U3 头部 :U4 躯干 :U5 双臂 :U6 双腿")
                return
            self._unequip_slot(slot)
        except (ValueError, IndexError):
            self._act_log.add("用法: :U1 左手 :U2 右手 :U3 头部 :U4 躯干 :U5 双臂 :U6 双腿")
        self._right_panel.refresh()

    def _swap_hands(self, cmd: str = "") -> None:
        """交换左右手装备。"""
        equip = self._state.player.equipment
        left = equip.get("left_hand")
        right = equip.get("right_hand")

        # 检查双手武器
        for item in (left, right):
            if item is not None and hasattr(item, 'properties') and item.properties:
                if 'two_handed' in item.properties:
                    self._act_log.add("双手武器不能交换")
                    return

        equip["left_hand"], equip["right_hand"] = right, left
        self._act_log.add(f"{self._pn} 交换了左右手装备")
        self._right_panel.refresh()

    def _on_two_hand_equip(self, weapon, hand: str = "right") -> None:
        """双手并用时卸除另一只手的武器。hand 为武器所在手。"""
        equip = self._state.player.equipment
        other_hand = "right_hand" if hand == "left" else "left_hand"
        other = equip.get(other_hand)
        if other is not None:
            equip[other_hand] = None
            _add_to_inventory(self._state.player, other)
        self._act_log.add(f"{self._pn} 双手握持了 {weapon.name}")
        self._sync_carry_status()

    def _sync_carry_status(self) -> None:
        """同步负重状态到 creature.statuses。"""
        p = self._state.player
        status = p.carry_status()
        # 移除旧负重状态
        for old in ("轻便", "负重", "超重"):
            p.remove_status(old)
        # 始终显示负重状态
        p.add_status(status["label"])

    def _apply_item_effect(self, item) -> None:
        """根据物品 effect 字段应用效果，支持数值和骰子字符串。"""
        eff = item.effect
        amt = item.amount
        p = self._state.player

        # 解析数值或骰子字符串
        try:
            val = int(amt)
        except (ValueError, TypeError):
            if isinstance(amt, str) and "d" in amt:
                count, sides = parse_dice(amt)
                val = roll_dice(count, sides)
            else:
                val = 0

        if eff == "heal" and val > 0:
            p.hp = min(p.max_hp, p.hp + val)
            self._act_log.add(f"  恢复了 {val} 点生命")
        elif eff == "restore_mp" and val > 0:
            p.mp = min(p.max_mp, p.mp + val)
            self._act_log.add(f"  恢复了 {val} 点精神")
        elif eff == "restore_food":
            if val > 0:
                p.food_value = min(15000, p.food_value + val)
            self._act_log.add(f"  恢复了 {val or '一定'} 饮食值")

    # ── Movement ──

    def _move_player(self, dc: int, dr: int) -> None:
        if self._state.observe_mode:
            oc, oro = self._state.observe_cursor
            nc, nr = oc + dc, oro + dr
            if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                if (nc, nr) in self._state.fov_cache:
                    self._state.observe_cursor = (nc, nr)
                    self._right_panel.refresh()
                    self._map_view.refresh()
            return
        # 远程目标选择模式：方向键移动瞄准光标
        if self._state.combat_phase == "ranged_target":
            weapon = None
            if self._state.pending_attack:
                weapon = self._state.pending_attack.get("weapon")
            max_range = weapon.range_max if weapon and weapon.weapon_type == "ranged" else 8
            pc, pr = self._state.player_pos
            oc, oro = self._state.observe_cursor
            nc, nr = oc + dc, oro + dr
            if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                if (nc, nr) in self._state.fov_cache:
                    if max(abs(nc - pc), abs(nr - pr)) <= max_range:
                        self._state.observe_cursor = (nc, nr)
                        self._left_panel.refresh()
                        self._map_view.refresh()
            return
        # 动作/攻击流程中：方向键无反应，不扣 AP
        if self._state.in_combat and self._state.combat_phase != "idle":
            return
        if self._state.in_combat and self._state.player.ap <= 0:
            self._act_log.add("AP 不足"); return
        col, row = self._state.player_pos
        nc, nr = col + dc, row + dr
        if self._state.move_player(nc, nr):
            if self._state.in_combat: self._state.player.ap -= 1
            elif self._state.slow_mode:
                self._state.clock.tick_action(1.0)
            _update_fov(self._state); self._refresh_scene(); self.refresh_all()
            self._last_move = (dc, dr)
            # 统一后处理：NPC 行为 + 战斗检测 + UI 刷新
            self._post_action_update()
            # 交互阶段：移动离开交互范围则自动退出
            if self._state.interact_phase:
                target = getattr(self._state, 'interact_target', None)
                if target is not None:
                    tx, ty = target.pos
                    px, py = self._state.player_pos
                    if max(abs(px - tx), abs(py - ty)) > 1:
                        self._cancel_interact()
                        self._act_log.add("离开了交互范围")
            # 走进地下城入口
            if (not self._state.in_dungeon and self._state.dungeon_entrance
                    and self._state.player_pos == self._state.dungeon_entrance):
                self._enter_dungeon()

    def action_move_up(self): self._move_player(0, -1)
    def action_move_down(self): self._move_player(0, 1)
    def action_move_left(self): self._move_player(-1, 0)
    def action_move_right(self): self._move_player(1, 0)

    def action_confirm_attack(self) -> None:
        """Enter 键确认远程目标（Binding 路径）。"""
        if self._state and self._state.combat_phase == "ranged_target":
            self._combat_flow.confirm_ranged_target()
            self.refresh_all()

    def action_end_turn(self) -> None:
        """手动结束当前回合（Shift+Tab）。"""
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

    def _cancel_interact(self) -> None:
        """取消交互，恢复默认状态。"""
        self._state.interact_phase = ""
        self._state.interact_targets = []
        self._state.interact_target = None
        self._state.shop_data = None
        self.refresh_all()

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
        if len(targets) == 1:
            self._dispatch_interact(targets[0])
            return
        # 多个目标 → 弹菜单
        self._state.interact_targets = targets
        self._state.interact_phase = "menu"
        self.refresh_all()

    def _dispatch_interact(self, target) -> None:
        """哈希表分发交互。"""
        method_name = _INTERACT_DISPATCH.get(target.interact_type)
        if method_name:
            getattr(self, method_name)(target)

    def _handle_interact_menu_select(self, num: int) -> None:
        """交互菜单选择（数字 0~N）。"""
        targets = self._state.interact_targets
        if num == 0:
            self._state.interact_phase = ""
            self._state.interact_targets = []
            self._state.interact_target = None
            self.refresh_all()
            return
        if 1 <= num <= len(targets):
            self._state.interact_phase = ""
            self._dispatch_interact(targets[num - 1])

    # ── 各交互类型处理方法 ──

    def _interact_talk(self, target) -> None:
        """与生物交谈。敌对生物直接开战。"""
        c = target.creature
        if c is None:
            return
        if c.faction == "hostile":
            self._act_log.add(f"{self._pn} 拔剑冲向 {c.name}!")
            self._start_combat(c)
            return
        self._state.interact_target = target
        self._state.interact_phase = "talking"
        self._act_log.add(f"{self._pn} 向 {c.name} 搭话")
        self._act_log.add(self._get_npc_dialogue(c))
        self.refresh_all()

    def _interact_loot(self, target) -> None:
        """搜刮尸体。"""
        c = target.creature
        if c is None:
            return
        if getattr(c, '_looted', False):
            self._act_log.add("已经搜刮过了")
            return
        c._looted = True
        self._act_log.add(f"[搜刮] {c.name}: 获得了一些物品")
        self.refresh_all()

    def _interact_pick(self, target) -> None:
        """采摘灌木丛。"""
        tc, tr = target.pos
        b = random.randint(1, 4)
        berry = ent.Item.from_dict({
            "name": "浆果", "item_type": "consumable",
            "effect": "restore_food", "amount": "500",
            "ap_cost": 1, "weight": 0.1,
            "price": {"cp": 2},
            "description": "多汁的浆果",
            "count": b,
        })
        _add_to_inventory(self._state.player, berry)
        self._act_log.add(f"{self._pn} 从灌木丛摘到 {b} 个浆果")
        self.refresh_all()

    def _interact_rest(self, target) -> None:
        """床铺休息。"""
        self._act_log.add("不妨在床上度过舒适的一晚")
        self.refresh_all()

    def _interact_door(self, target) -> None:
        """开关门。"""
        pos = target.pos
        if pos not in self._state.door_states:
            return
        is_open = self._state.door_states[pos]
        if is_open:
            self._state.door_states[pos] = False
            self._state.map[pos] = Terrain.WALL
            self._act_log.add("门关上了")
        else:
            self._state.door_states[pos] = True
            self._state.map[pos] = Terrain.PASSABLE
            self._act_log.add("门打开了")
        _update_fov(self._state)
        self.refresh_all()

    def _interact_entrance(self, target) -> None:
        """进入/离开地下城。"""
        direction = target.extra.get("direction", "enter")
        if direction == "exit":
            self._exit_dungeon()
        else:
            self._enter_dungeon()
        self.refresh_all()

    # ── 交易流程 ──

    def _interact_trade_start(self) -> None:
        """从交谈界面进入交易。"""
        target = getattr(self._state, 'interact_target', None)
        if target is None or target.creature is None:
            return
        shop_id = getattr(target.creature, 'template_name', '')
        if not shop_id:
            self._act_log.add("商店数据异常")
            return
        shop = load_shop(shop_id)
        if shop is None:
            self._act_log.add(f"商店 '{shop_id}' 数据不存在")
            return
        self._state.shop_data = shop
        self._state.interact_phase = "trading"
        self._act_log.add(f"可以 :B序号 购买商品，:S序号 出售物品")
        self.refresh_all()

    def _handle_trade_buy(self, index: int) -> None:
        """购买商店商品。"""
        shop = self._state.shop_data
        if shop is None:
            return
        ok, msg = trade_buy(self._state.player, shop, index)
        self._act_log.add(msg)
        self.refresh_all()

    def _handle_trade_sell(self, index: int) -> None:
        """出售背包物品给商店。"""
        shop = self._state.shop_data
        if shop is None:
            return
        ok, msg = trade_sell(self._state.player, shop, index)
        self._act_log.add(msg)
        self.refresh_all()

    # ── NPC 对话 ──

    def _get_npc_dialogue(self, c: Creature) -> str:
        """基于 AI 状态生成 NPC 对话，从 dialogues.json 加载文本。"""
        enemy_count = 0
        ally_count = sum(1 for o, _ in self._state.entities
                         if o.faction == c.faction and o.hp > 0 and o is not c)
        ratio = c.hp / max(c.max_hp, 1) * (ally_count + 1)
        try:
            action, _ = _ai_engine.decide(c, enemy_count, ally_count, ratio)
        except Exception:
            action = "idle"

        brave = getattr(c, "bravery_tier", "medium") or "medium"

        dialogue = _load_dialogues()
        tier = brave if brave in ("low", "medium", "high") else "medium"
        action_dialogues = dialogue.get(action, dialogue.get("idle", {}))
        return f"{c.name}: {action_dialogues.get(tier, action_dialogues.get('medium', '...'))}"

    def _enter_dungeon(self) -> None:
        """保存世界状态，进入地下城。"""
        self._state.world_state = {
            "map": self._state.map, "entities": self._state.entities,
            "player_pos": self._state.player_pos, "current_map": self._state.current_map,
            "bed_positions": self._state.bed_positions, "door_states": self._state.door_states,
            "location_map": self._state.location_map,
        }
        build_dungeon(self._state, _loader)
        self._state.in_dungeon = True
        self._act_log.add(f"{self._pn} 走入了地下城...")
        self._end_combat(); _update_fov(self._state)
        self._refresh_scene(); self.refresh_all()

    def _exit_dungeon(self) -> None:
        """恢复世界状态，退出地下城。"""
        ws = self._state.world_state
        if ws:
            self._state.map = ws["map"]
            self._state.entities = ws["entities"]
            self._state.player_pos = ws["player_pos"]
            self._state.current_map = ws["current_map"]
            self._state.bed_positions = ws["bed_positions"]
            self._state.door_states = ws["door_states"]
            self._state.location_map = ws.get("location_map", {})
        self._state.in_dungeon = False
        self._act_log.add(f"{self._pn} 回到了地面")
        self._end_combat(); _update_fov(self._state)
        self._refresh_scene(); self.refresh_all()

    # ── Combat ──

    def _start_combat(self, target: Creature, ambush: bool = False) -> None:
        """进入战斗。ambush=True 时玩家必定先手（探索模式主动攻击）。"""
        if target.hp <= 0:
            return
        self._state.in_combat = True
        self._state._combat_ticked = False
        self._state.player.ap = self._state.player.max_ap
        combatants = [self._state.player]
        pc, pr = self._state.player_pos
        for creature, (ec, er) in self._state.entities:
            if creature.hp > 0 and creature.faction == "hostile" \
               and max(abs(ec - pc), abs(er - pr)) <= creature.vision_range:
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
            self._npc_turn(turn)

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

        # 拉入范围内未参战的敌对生物（基于生物自身视野检测玩家）
        pc, pr = self._state.player_pos
        for creature, (ec, er) in self._state.entities:
            if creature.hp > 0 and creature.faction == "hostile" \
               and max(abs(ec - pc), abs(er - pr)) <= creature.vision_range \
               and creature not in self._state.combat_initiative:
                creature.ap = creature.max_ap
                self._state.combat_initiative.append(creature)
                self._act_log.add(f"{creature.name} 加入了战斗!")

        alive = [e for e in self._state.combat_initiative if e is self._state.player or e.hp > 0]
        hostiles = [e for e in alive if e.faction == "hostile" and e.hp > 0]
        if not hostiles:
            self._end_combat(); self.refresh_all(); return

        # 距离脱战：玩家离开所有敌对生物的视野范围
        pc, pr = self._state.player_pos
        all_out_of_sight = True
        for e in hostiles:
            epos = None
            for c, (ec, er) in self._state.entities:
                if c is e:
                    epos = (ec, er); break
            if epos is None:
                continue
            dist = max(abs(epos[0] - pc), abs(epos[1] - pr))
            if dist <= e.vision_range:
                all_out_of_sight = False
                break
        if all_out_of_sight:
            self._act_log.add(f"{self._pn} 脱离了敌人的视野，战斗结束")
            self._end_combat(); self.refresh_all(); return

        self._state.combat_initiative = alive
        idx = (self._state.combat_turn_index + 1) % len(alive)
        # 满轮 → 推进钟摆 6
        if idx == 0:
            self._state.clock.tick_combat_round()
            self._state._combat_ticked = True
        self._state.combat_turn_index = idx; turn = alive[idx]
        self._state.combat_turn_entity = turn; turn.ap = turn.max_ap
        if turn is self._state.player:
            self._act_log.add(f">>> {self._pn}的战斗轮 <<<")
        else:
            self._act_log.add(f">>> {turn.name}的战斗轮 <<<")
            self._npc_turn(turn)
        self.refresh_all()

    def _player_attack(self) -> None:
        pc, pr = self._state.player_pos
        weapon = self._state.player.equipment.get("right_hand")
        if weapon is None:
            self._act_log.add(f"{self._pn} 赤手空拳!"); return
        if self._state.player.ap < weapon.ap_cost: self._act_log.add("AP 不足"); return

        # 确定有效攻击范围
        if weapon.weapon_type == "ranged":
            reach = max(weapon.range_max, 1)
        else:
            reach = 1

        target = None
        for creature, (ec, er) in self._state.entities:
            if (creature is not self._state.player and creature.hp > 0
                    and abs(ec - pc) <= reach and abs(er - pr) <= reach):
                target = creature; break
        if target is None: self._act_log.add(f"{self._pn} 环顾四周，没有目标"); return
        self._state.player.ap -= weapon.ap_cost
        result = resolve_attack(
            self._state.player, target, weapon,
            attacker_pos=(pc, pr),
            target_pos=self._find_entity_pos(target),
            grid=self._state.map,
        )
        if result["hit"]:
            self._check_faction_reaction(target)
            self._act_log.add(f"{self._pn} 击中了 {target.name}，{target.name} 发出一声惨叫")
            if target.hp <= 0: self._act_log.add(f"{target.name} 倒在地上，不再动弹")
        else:
            dmg_type = result.get("damage_type", "bludgeoning")
            if result.get("blocked_by_cover"):
                self._act_log.add(f"{self._pn} 的{cover_message(dmg_type)}")
            else:
                self._act_log.add(miss_message(self._pn, target.name, dmg_type))
        self.refresh_all()

    # ── 攻击流程状态机 ──

    def _resolve_melee_attack(self, attacker, target, weapon,
                               hit_bonus=0, damage_bonus=0) -> dict:
        """委托 CombatFlow 执行近战攻击检定。"""
        return self._combat_flow.resolve_melee_attack(
            attacker, target, weapon, hit_bonus, damage_bonus)

    def _handle_action_input(self, cmd: str) -> None:
        """阶段一：选择攻击方式 → 委托 CombatFlow。"""
        self._combat_flow.handle_action_input(cmd)

    def _handle_target_input(self, cmd: str) -> None:
        """阶段二：选择目标 → 委托 CombatFlow。"""
        self._combat_flow.handle_target_input(cmd)

    def _execute_attack_roll(self) -> None:
        """执行攻击检定 → 委托 CombatFlow。"""
        self._combat_flow.execute_attack_roll()

    def _handle_maneuver_input(self, cmd: str) -> None:
        """阶段三A：命中后选择战技 → 委托 CombatFlow。"""
        self._combat_flow.handle_maneuver_input(cmd)

    def _handle_special_input(self, cmd: str) -> None:
        """阶段三B：未命中后选择特殊行动 → 委托 CombatFlow。"""
        self._combat_flow.handle_special_input(cmd)

    def _check_faction_reaction(self, target: Creature) -> None:
        """玩家攻击非敌对生物后检查阵营反应 → 委托 CombatFlow。"""
        self._combat_flow.check_faction_reaction(target)

    def _confirm_ranged_target(self) -> None:
        """Enter 键确认远程目标选择。"""
        if self._state.combat_phase != "ranged_target":
            return
        self._combat_flow.confirm_ranged_target()
        self.refresh_all()

    def _find_entity_pos(self, target: Creature) -> tuple[int, int] | None:
        """查找生物在地图上的坐标。"""
        for c, (ec, er) in self._state.entities:
            if c is target:
                return (ec, er)
        return None

    def _move_npc_toward(self, npc: Creature, nc: int, nr: int,
                         tc: int, tr: int) -> bool:
        """NPC 向目标坐标移动一格（A* 寻路 + 简单 fallback）。"""
        # 尝试 A* 寻路
        path = find_path(self._state.map, self._state.entities,
                         (nc, nr), (tc, tr))
        if path and len(path) >= 2:
            # path[0] = 起点, path[1] = 下一步
            nx, ny = path[1]
            if self._state.move_entity(npc, nc, nr, nx, ny):
                return True

        # A* 失败或不可达，fallback 到简单朝向移动
        dc = 1 if tc > nc else (-1 if tc < nc else 0)
        dr = 1 if tr > nr else (-1 if tr < nr else 0)
        for try_dc, try_dr in [(dc, dr), (dc, 0), (0, dr)]:
            nx, ny = nc + try_dc, nr + try_dr
            if self._state.move_entity(npc, nc, nr, nx, ny):
                return True
        return False

    def _npc_melee_attack(self, npc: Creature, action: dict,
                           target: Creature) -> None:
        """NPC 执行近战攻击，按 MVP2.md 武器数据结算。"""
        weapon_name = action.get("weapon", "徒手打击")
        damage_str = action.get("damage", "1d4")
        damage_type = action.get("damage_type", "bludgeoning")
        attack_stat_name = action.get("attack_stat", "str")
        ap_cost = action.get("ap_cost", 2)

        npc.ap -= ap_cost
        weapon = Weapon(
            name=weapon_name, damage=damage_str,
            damage_type=damage_type, attack_stat=attack_stat_name,
            ap_cost=ap_cost)

        npc_pos = self._find_entity_pos(npc)
        target_pos = self._find_entity_pos(target)
        result = resolve_attack(
            npc, target, weapon,
            attacker_pos=npc_pos, target_pos=target_pos,
            grid=self._state.map,
        )
        if result["hit"]:
            self._act_log.add(
                f"{npc.name}使用{weapon_name}击中了{target.name}，"
                f"造成 {result['damage']} 点{damage_type}伤害")
            if target is self._state.player and target.hp <= 0:
                self._act_log.add(f"{self._pn} 被击倒了! [R]长休恢复")
        else:
            dmg_type = result.get("damage_type", "bludgeoning")
            if result.get("blocked_by_cover"):
                self._act_log.add(
                    f"{npc.name}使用{weapon_name}攻击{target.name}，"
                    f"{cover_message(dmg_type)} (roll={result['roll']})")
            else:
                self._act_log.add(
                    miss_message(npc.name, target.name, dmg_type)
                    + f" (roll={result['roll']})")

    def _npc_special_action(self, npc: Creature, action: dict, target,
                             nc: int, nr: int, tc: int, tr: int) -> None:
        """NPC 执行特殊动作，按 MVP2.md 描述结算效果。"""
        name = action.get("name", "特殊动作")
        ap_cost = action.get("ap_cost", 3)
        npc.ap -= ap_cost

        if "扑倒" in name:
            # DC12 敏捷豁免，失败则倒地
            save_roll = roll_d20() + target.stat_adjust("dex")
            if save_roll < 12:
                if not target.has_status("prone"):
                    target.add_status("prone")
                self._act_log.add(
                    f"{npc.name}使用扑倒——{target.name}被扑倒在地!")
            else:
                self._act_log.add(
                    f"{npc.name}使用扑倒，{target.name}稳住了身形 (DC12, roll={save_roll})")

        elif "跃起" in name:
            # 跳向 2 格内目标相邻格，用短棒攻击，部位概率: 头40%/躯干60%
            dist = max(abs(nc - tc), abs(nr - tr))
            if dist <= 2:
                # 移动到相邻格
                for _ in range(dist - 1):
                    self._move_npc_toward(npc, nc, nr, tc, tr)
                    npc.ap -= 1
                    pos = self._find_entity_pos(npc)
                    if pos: nc, nr = pos
                # 近战攻击（单手短棒），部位概率改变
                weapon_action = {"name": "短棒", "weapon": "短棒", "type": "melee_attack",
                                 "damage": "1d4", "damage_type": "bludgeoning",
                                 "attack_stat": "str", "ap_cost": 2, "reach": 1}
                self._act_log.add(f"{npc.name}跃起砸下短棒!")
                self._npc_melee_attack(npc, weapon_action, target)
            else:
                self._act_log.add(f"{npc.name}跃起——距离太远，够不着")

        elif "格挡" in name:
            # AC+1 直到下回合（用 status 标记）
            if not npc.has_status("guarding"):
                npc.add_status("guarding")
            self._act_log.add(f"{npc.name}举起盾牌格挡，全身 AC+1")

        else:
            self._act_log.add(f"{npc.name} 使用了{name}")

    def _npc_action_total_ap(self, npc: Creature, action: dict,
                              nc: int, nr: int, pc: int, pr: int) -> int | None:
        """计算执行动作所需的总 AP（移动 + 动作本身）。不可行返回 None。"""
        atype = action.get("type", "melee_attack")
        reach = action.get("reach", 1)
        ap_cost = action.get("ap_cost", 3)
        dist = max(abs(nc - pc), abs(nr - pr))

        if atype in ("melee_attack", "special"):
            if dist <= reach:
                return ap_cost
            else:
                # 需要移动：每格 1 AP
                move_ap = dist - reach
                return move_ap + ap_cost
        return ap_cost

    def _execute_npc_action(self, npc: Creature, action: dict,
                            nc: int, nr: int, pc: int, pr: int) -> None:
        """执行单个 NPC 动作：包围移动 → 进入范围 → 发动攻击。"""
        atype = action.get("type", "melee_attack")
        reach = action.get("reach", 1)
        dist = max(abs(nc - pc), abs(nr - pr))

        # 移动到攻击范围内：目标为玩家周围最近的空格（包围）
        while dist > reach and npc.ap > 0:
            target = self._find_surround_target(nc, nr, pc, pr)
            moved = self._move_npc_toward(npc, nc, nr, target[0], target[1])
            npc.ap -= 1  # 尝试移动即消耗 AP
            if not moved:
                break
            pos = self._find_entity_pos(npc)
            if pos:
                nc, nr = pos
                dist = max(abs(nc - pc), abs(nr - pr))
            else:
                break

        # 在范围内则发动攻击
        if atype == "melee_attack" and dist <= reach and npc.ap >= action.get("ap_cost", 2):
            self._npc_melee_attack(npc, action, self._state.player)
        elif atype == "special" and dist <= reach and npc.ap >= action.get("ap_cost", 3):
            self._npc_special_action(npc, action, self._state.player,
                                     nc, nr, pc, pr)

    def _find_surround_target(self, nc: int, nr: int,
                               pc: int, pr: int) -> tuple[int, int]:
        """找到玩家周围最佳包围位置（最近且未被占据的相邻格）。"""
        best = None
        best_dist = 999
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                tx, ty = pc + dc, pr + dr
                if not self._state.map.within_bounds(tx, ty):
                    continue
                # 检查是否已被占据
                occupied = False
                for _, (ec, er) in self._state.entities:
                    if (ec, er) == (tx, ty):
                        occupied = True
                        break
                if (tx, ty) == (pc, pr):
                    occupied = True
                if occupied:
                    continue
                d = max(abs(nc - tx), abs(nr - ty))
                if d < best_dist:
                    best_dist = d
                    best = (tx, ty)
        return best or (pc, pr)

    def _npc_turn(self, npc: Creature) -> None:
        """NPC 回合：包围玩家 + 重复执行动作直到 AP 不足。"""
        pc, pr = self._state.player_pos
        pos = self._find_entity_pos(npc)
        if pos is None:
            self._next_turn(); return

        actions_taken = 0
        while npc.ap > 0:
            pos = self._find_entity_pos(npc)
            if pos is None: break
            nc, nr = pos

            # 收集可执行的动作（总 AP 足够 + 条件满足）
            available = []
            for action in npc.actions:
                total = self._npc_action_total_ap(npc, action, nc, nr, pc, pr)
                if total is not None and npc.ap >= total:
                    available.append(action)

            if not available:
                # 无法发动任何动作，包围移动：向玩家周围空格靠近
                if max(abs(nc - pc), abs(nr - pr)) <= 1:
                    if actions_taken == 0:
                        self._act_log.add(f"{npc.name} 没有可用的动作")
                    break
                # 找包围位置并移动
                target = self._find_surround_target(nc, nr, pc, pr)
                moved = self._move_npc_toward(npc, nc, nr, target[0], target[1])
                npc.ap -= 1  # 尝试移动即消耗 AP
                if moved:
                    actions_taken += 1
                else:
                    break
                continue

            action = random.choice(available)
            ap_before = npc.ap
            self._execute_npc_action(npc, action, nc, nr, pc, pr)
            actions_taken += 1
            if npc.ap >= ap_before:
                break

        self._next_turn(); self.refresh_all()

    # ── Long Rest ──

    def action_long_rest(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法长休"); return
        r = long_rest(self._state.player, self._state.clock,
                      self._state.map, self._state.player_pos,
                      self._state.bed_positions)
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
                elif self._state.map[nc, nr] == Terrain.DIFFICULT:
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
        for _ in range(30):
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
    def action_toggle_knockout(self): self._act_log.add("[击晕] 功能待定")
    def _focus_input(self) -> None:
        """聚焦输入栏（战斗流程专用）。"""
        self._input_bar.disabled = False
        self._input_bar.focus()

    def action_show_actions(self):
        """按 A 键 → 委托 CombatFlow 进入攻击方式选择阶段。"""
        self._combat_flow.start_action_phase()
    def action_show_spells(self): self._act_log.add("[法术] 功能待定")
    def action_char_panel(self):
        if self._right_panel.view_mode == "character":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "character"
        self._right_panel.refresh()

    def action_inventory(self):
        if self._right_panel.view_mode == "inventory":
            self._right_panel.view_mode = "default"
        else:
            self._right_panel.view_mode = "inventory"
        self._right_panel.refresh()
    def action_spellbook(self): self._act_log.add("[法术书] 功能待定")
    def action_crafting(self): self._act_log.add("[制作] 功能待定")
    def action_cooking(self): self._act_log.add("[烹饪] 功能待定")
    def action_alchemy(self): self._act_log.add("[炼药] 功能待定")
    def action_height_view(self): self._act_log.add("[高度] 功能待定")
    def action_map_overview(self): self._act_log.add("[地图] 功能待定")
    def action_system_menu(self): self._act_log.add("[系统] 功能待定")

    # ── Scene ──

    def _refresh_scene(self) -> None:
        fov = self._state.fov_cache
        pc, pr = self._state.player_pos
        lines = []
        for creature, (ec, er) in self._state.entities:
            if (ec, er) not in fov or creature.hp <= 0: continue
            if creature is self._state.player: continue
            desc = self._describe_creature(creature, (ec, er), pc, pr)
            if desc: lines.append(desc)
        if not lines: lines = [""]
        if lines != getattr(self, '_last_scene', None):
            self._last_scene = lines; self._scene_log.set_scene(lines)

    def _describe_creature(self, c: Creature, pos: tuple[int, int],
                            pc: int, pr: int) -> str:
        ec, er = pos
        dist = max(abs(ec - pc), abs(er - pr))
        enemy_count = 1 if dist <= c.vision_range else 0
        ally_count = sum(1 for o, _ in self._state.entities
                         if o.faction == c.faction and o.hp > 0 and o is not c)
        ratio = c.hp / max(c.max_hp, 1) * (ally_count + 1) / max(enemy_count, 1)
        try: action, _ = _ai_engine.decide(c, enemy_count, ally_count, ratio)
        except Exception: action = "idle"

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

    # ── Rest ──

    def action_short_rest(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法休息"); return
        r = short_rest(self._state.player, self._state.clock,
                       self._state.map, self._state.player_pos,
                       self._state.bed_positions)
        comfort = "，睡得很舒适" if r.get("comfort") else ""
        self._act_log.add(f"{self._pn} 短休 (HP+{r['hp_restored']} MP+{r['mp_restored']}){comfort}")
        self._post_action_update()

    # ── Save ──

    def action_quick_save(self) -> None:
        """快速存档 — 固定使用 quicksave 槽位（持久化到磁盘）。"""
        if self._state.in_combat:
            self._act_log.add("战斗中无法存档")
            return
        self._save_manager.save(self._state, slot="quicksave")
        self._act_log.add("[快速存档] 已保存")

    def action_quick_load(self) -> None:
        """快速读档 — 从 quicksave 槽位恢复。"""
        if self._state.in_combat:
            self._act_log.add("战斗中无法读档")
            return

        # 检查存档是否存在
        import json
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
