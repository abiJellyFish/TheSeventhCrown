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
from core.movement import Terrain
from core.grid import Grid
from core.fov import LightLevel, compute_fov
from core.combat.initiative import roll_initiative
from core.combat.attack import hit_check, roll_damage, reduce_tenacity, apply_damage_type_modifiers, parse_dice, roll_dice
from core.combat.flow import CombatFlow
from core.map.generation import build_world, build_dungeon
from core.dice import roll_d20
from core.ai.engine import BehaviorEngine
from core.rest import short_rest, long_rest
from core.loader import DataLoader
from core.save.database import SaveManager
from render.textual.widgets import (
    TopBar, LeftPanel, MapView, RightPanel, ActionLog, SceneLog,
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
    MapView { width: 3fr; min-width: 20; content-align: center middle; }
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
        Binding("f5", "quick_save", "存档", priority=True),
        Binding("f9", "quick_load", "读档", priority=True),
    ]

    # ── 各面板允许的快捷键集合 ──

    _EXPLORE_KEYS = {
        "0", "1", "2", "3", "4", "5", "6", "7", "8",
        "slash", "g", "G", "r", "R", "comma", "A", "S", "Q",
        "X", "C", "I", "B", "Z", "K", "Y", "H", "M", "E",
    }
    _COMBAT_IDLE_KEYS = _EXPLORE_KEYS  # 战斗默认面板与探索相同（shift+tab 走 binding）
    _COMBAT_SUB_KEYS = {"X", "C", "I"}    # 战斗子面板：观察/角色/物品栏
    _RIGHT_PANEL_KEYS = {"X", "C", "I"}   # 物品栏/角色面板：观察/切换键

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
        import core.entity as ent

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

        build_world(self._state, _loader)
        self._state.player_pos = tuple(ps_data["start_pos"])

        # 初始装备
        for slot, item_data in ps_data.get("equipment", {}).items():
            if item_data and slot in self._state.player.equipment:
                self._state.player.equipment[slot] = ent.Weapon.from_dict(item_data)
        # 预置初始物品
        for item_data in ps_data.get("inventory", []):
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
        )

    def compose(self) -> ComposeResult:
        self._create_game()
        self._top_bar = TopBar(id="top"); yield self._top_bar
        with Horizontal(id="main"):
            self._left_panel = LeftPanel(id="left"); yield self._left_panel
            self._map_view = MapView(); yield self._map_view
            self._right_panel = RightPanel(id="right"); yield self._right_panel
        self._input_bar = GameInput(placeholder=": 输入命令 (按 Esc 退出输入)", id="input-bar", disabled=True)
        yield self._input_bar
        with Horizontal(id="log-area"):
            self._act_log = ActionLog(id="action-log"); yield self._act_log
            self._scene_log = SceneLog(id="scene-log"); yield self._scene_log

    def on_mount(self) -> None:
        for w in [self._map_view, self._left_panel, self._right_panel, self._top_bar]:
            w.state = self._state
        self._init_combat_flow()
        self._refresh_scene()
        self.refresh_all()
        self._map_view.focus()

    def refresh_all(self) -> None:
        for w in [self._map_view, self._left_panel, self._right_panel,
                  self._top_bar, self._act_log, self._scene_log]:
            if w: w.refresh()

    def on_key(self, event) -> None:
        """上下文感知的按键分发：只有当前面板显示的键才触发。"""
        key = event.key
        state = self._state

        # ── 0. Escape（全局：退出输入栏 / 退出右侧栏视图）──
        if key == "escape":
            if self._input_bar and self._input_bar.has_focus:
                self._input_bar.disabled = True
                self._map_view.focus()
                event.stop()
                return
            view = self._right_panel.view_mode if self._right_panel else "default"
            if view != "default":
                self._right_panel.view_mode = "default"
                self._right_panel.refresh()
                event.stop()
            return

        # ── 1. 输入栏聚焦时 → 不响应任何快捷键 ──
        if self._input_bar and self._input_bar.has_focus:
            return

        # ── 2. 根据当前上下文确定允许的键 ──
        if state is None:
            return
        view = self._right_panel.view_mode if self._right_panel else "default"
        phase = state.combat_phase

        if view in ("inventory", "character"):
            allowed = self._RIGHT_PANEL_KEYS
        elif phase != "idle":
            allowed = self._COMBAT_SUB_KEYS
        elif state.in_combat:
            allowed = self._COMBAT_IDLE_KEYS
        else:
            allowed = self._EXPLORE_KEYS

        if key not in allowed:
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        self._input_bar.value = ""
        self._input_bar.disabled = True
        if cmd:
            is_combat_cmd = False
            phase = self._state.combat_phase if self._state else "idle"
            if phase == "select_action":
                self._handle_action_input(cmd); is_combat_cmd = True
            elif phase == "select_target":
                self._handle_target_input(cmd); is_combat_cmd = True
            elif phase == "select_maneuver":
                self._handle_maneuver_input(cmd); is_combat_cmd = True
            elif phase == "select_special":
                self._handle_special_input(cmd); is_combat_cmd = True
            elif cmd.startswith("I") and self._right_panel.view_mode == "inventory":
                self._act_log.add(f"> :{cmd}")
                self._use_item(cmd)
                self._map_view.focus()
            else:
                self._act_log.add(f"> :{cmd}")
                self._act_log.add("功能待定")
                self._map_view.focus()
            # 战斗阶段的 handler 自行管理焦点，此处不抢
            if is_combat_cmd:
                return
        self._map_view.focus()

    def _use_item(self, cmd: str) -> None:
        """使用物品：I + 序号，如 I1 使用第 1 个物品。"""
        try:
            idx = int(cmd[1:]) - 1
            inv = self._state.player.inventory
            if 0 <= idx < len(inv):
                item = inv[idx]
                # AP 检查（与武器攻击复用同一模式：item.ap_cost）
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
            # 走进地下城入口
            if (not self._state.in_dungeon and self._state.dungeon_entrance
                    and self._state.player_pos == self._state.dungeon_entrance):
                self._enter_dungeon()

    def action_move_up(self): self._move_player(0, -1)
    def action_move_down(self): self._move_player(0, 1)
    def action_move_left(self): self._move_player(-1, 0)
    def action_move_right(self): self._move_player(1, 0)

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
        # 检查是否有 NPC 触发的战斗（由 clock 回调 → _advance_npcs 设置）
        if self._state.pending_combat_target:
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

    # ── Interact ──

    def action_interact(self) -> None:
        pc, pr = self._state.player_pos
        # 门交互
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                door_pos = (pc + dc, pr + dr)
                if door_pos in self._state.door_states:
                    is_open = self._state.door_states[door_pos]
                    if is_open:
                        self._state.door_states[door_pos] = False
                        self._state.map[door_pos] = Terrain.WALL
                        self._act_log.add("门关上了")
                    else:
                        self._state.door_states[door_pos] = True
                        self._state.map[door_pos] = Terrain.PASSABLE
                        self._act_log.add("门打开了")
                    _update_fov(self._state)
                    self.refresh_all(); return
        # 地下城入口
        if self._state.dungeon_entrance and (pc, pr) == self._state.dungeon_entrance:
            self._enter_dungeon(); return
        # 地下城出口
        if self._state.in_dungeon and self._state.dungeon_exit and (pc, pr) == self._state.dungeon_exit:
            self._exit_dungeon(); return
        # 床交互
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if (pc + dc, pr + dr) in self._state.bed_positions:
                    self._act_log.add("不妨在床上度过舒适的一晚")
                    self.refresh_all(); return
        for creature, (ec, er) in self._state.entities:
            if creature is self._state.player: continue
            if abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                if creature.hp <= 0: self._loot_corpse(creature); return
                self._interact_creature(creature, (ec, er)); return
        # 灌木丛（自身格 + 相邻格）
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                nc, nr = pc + dc, pr + dr
                if not (0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height): continue
                if self._state.map[nc, nr] == Terrain.DIFFICULT:
                    b = random.randint(1, 4)
                    import core.entity as ent
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
                    self.refresh_all(); return
        self._act_log.add(f"{self._pn} 环顾四周，这里没什么特别的")
        self.refresh_all()

    def _interact_creature(self, c: Creature, pos: tuple[int, int]) -> None:
        if c.faction == "hostile":
            self._act_log.add(f"{self._pn} 拔剑冲向 {c.name}!"); self._start_combat(c)
        else:
            self._act_log.add(f"{self._pn} 向 {c.name} 搭话")
            self._act_log.add(self._get_npc_dialogue(c))

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

    def _loot_corpse(self, c: Creature) -> None:
        if getattr(c, '_looted', False): self._act_log.add("已经搜刮过了"); return
        c._looted = True
        self._act_log.add(f"[搜刮] {c.name}: 获得了一些物品")

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
        self._state.in_combat = True
        self._state.player.ap = self._state.player.max_ap
        combatants = [self._state.player]
        pc, pr = self._state.player_pos
        for creature, (ec, er) in self._state.entities:
            if creature.hp > 0 and creature is not self._state.player and abs(ec - pc) <= 5:
                combatants.append(creature)
                creature.ap = creature.max_ap
        self._state.combat_initiative = roll_initiative(combatants)
        self._state.combat_turn_index = 0

        if ambush:
            self._state.combat_turn_entity = self._state.player
            self._act_log.add("=== 战斗开始 ===")
            self._act_log.add(f">>> {self._pn}的战斗轮 <<<")
        else:
            self._state.combat_turn_entity = combatants[0]
            self._act_log.add("=== 战斗开始 ===")
            self._next_turn()

    def _end_combat(self) -> None:
        self._state.in_combat = False; self._state.combat_initiative = []
        self._state.combat_turn_entity = None
        self._state.player.ap = self._state.player.max_ap
        self._act_log.add("=== 战斗结束 ===")

    def _next_turn(self) -> None:
        if not self._state.in_combat: return
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
        target = None
        for creature, (ec, er) in self._state.entities:
            if creature is not self._state.player and creature.hp > 0 and abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                target = creature; break
        if target is None: self._act_log.add(f"{self._pn} 环顾四周，没有目标"); return
        self._state.player.ap -= weapon.ap_cost
        hit, roll = hit_check(self._state.player, target, weapon)
        if hit:
            dmg = roll_damage(weapon, self._state.player, critical=(roll == 20))
            dmg = apply_damage_type_modifiers(dmg, weapon.damage_type, target)
            target.hp = max(0, target.hp - dmg)
            self._check_faction_reaction(target)
            self._act_log.add(f"{self._pn} 挥剑砍中了 {target.name}，{target.name} 发出一声惨叫")
            if target.hp <= 0: self._act_log.add(f"{target.name} 倒在地上，不再动弹")
        else:
            reduce_tenacity(target, roll)
            self._act_log.add(f"{self._pn} 挥剑砍向 {target.name}，被躲开了")
            if target.tenacity == 0 and "incapacitated" not in target.statuses:
                target.statuses.append("incapacitated")
                self._act_log.add(f"{target.name} 被击破防御，陷入失能!")
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

    def _find_entity_pos(self, target: Creature) -> tuple[int, int] | None:
        """查找生物在地图上的坐标。"""
        for c, (ec, er) in self._state.entities:
            if c is target:
                return (ec, er)
        return None

    def _move_npc_toward(self, npc: Creature, nc: int, nr: int,
                         tc: int, tr: int) -> bool:
        """NPC 向目标坐标移动一格。返回是否成功移动。"""
        dc = 1 if tc > nc else (-1 if tc < nc else 0)
        dr = 1 if tr > nr else (-1 if tr < nr else 0)
        # 优先对角线，否则单轴
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

        hit, roll = hit_check(npc, target, weapon)
        if hit:
            critical = (roll == 20)
            dmg = roll_damage(weapon, npc, critical=critical)
            dmg = apply_damage_type_modifiers(dmg, damage_type, target)
            target.hp = max(0, target.hp - dmg)
            self._act_log.add(
                f"{npc.name}使用{weapon_name}击中了{target.name}，"
                f"造成 {dmg} 点{damage_type}伤害")
            if target is self._state.player and target.hp <= 0:
                self._act_log.add(f"{self._pn} 被击倒了! [R]长休恢复")
        else:
            reduce_tenacity(target, roll)
            self._act_log.add(
                f"{npc.name}使用{weapon_name}攻击{target.name}，"
                f"被躲开了 (roll={roll})")

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
                if "prone" not in target.statuses:
                    target.statuses.append("prone")
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
            if "guarding" not in npc.statuses:
                npc.statuses.append("guarding")
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
        """执行单个 NPC 动作：先移动到范围内，再发动。"""
        atype = action.get("type", "melee_attack")
        reach = action.get("reach", 1)
        dist = max(abs(nc - pc), abs(nr - pr))

        # 先移动到攻击范围内
        while dist > reach and npc.ap > 0:
            moved = self._move_npc_toward(npc, nc, nr, pc, pr)
            if not moved:
                break
            npc.ap -= 1
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

    def _npc_turn(self, npc: Creature) -> None:
        """NPC 回合：按 MVP2.md 规则重复执行动作直到 AP 不足。"""
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
                # 无法发动任何动作，但还可以移动：向玩家靠近
                if max(abs(nc - pc), abs(nr - pr)) <= 1:
                    # 已在相邻格，确实无可用动作
                    if actions_taken == 0:
                        self._act_log.add(f"{npc.name} 没有可用的动作")
                    break
                moved = self._move_npc_toward(npc, nc, nr, pc, pr)
                if moved:
                    npc.ap -= 1
                    actions_taken += 1
                else:
                    break
                continue

            action = random.choice(available)
            self._execute_npc_action(npc, action, nc, nr, pc, pr)
            actions_taken += 1

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
            status_text = f" [{', '.join(c.statuses)}]"
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
