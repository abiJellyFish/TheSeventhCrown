"""Textual MVP App — 完整游戏原型。"""

import random
from textual.app import App, ComposeResult
from textual.widgets import Static, Input
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from rich.text import Text

from core.game_state import GameState
from core.entity import Player, Creature
from core.movement import Terrain
from core.grid import Grid
from core.fov import LightLevel, compute_fov
from core.combat.initiative import roll_initiative
from core.combat.attack import hit_check, roll_damage, reduce_tenacity, apply_damage_type_modifiers
from core.dice import roll_d20
from core.ai.engine import BehaviorEngine
from core.rest import short_rest, long_rest
from core.loader import DataLoader
from render.textual.screens.character import CharacterScreen
from render.textual.screens.inventory import InventoryScreen
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_loader = DataLoader(DATA_DIR)
_ai_engine = BehaviorEngine({
    "goblin_brawler": _loader.load_json("ai/goblin_brawler"),
    "skeleton": _loader.load_json("ai/skeleton"),
})

TERRAIN_COLORS = {
    Terrain.PASSABLE: "rgb(80,80,80)",
    Terrain.DIFFICULT: "green",
    Terrain.WALL: "rgb(140,140,140)",
}
FACTION_COLORS = {"hostile": "red", "friendly": "green", "neutral": "yellow"}


def _add_to_inventory(player, item) -> None:
    """添加物品到背包，同名称物品堆叠。"""
    for existing in player.inventory:
        if existing.name == item.name and existing.item_type == item.item_type:
            # 堆叠：合并数量（amount 字段）
            try:
                ea = int(existing.amount)
                ia = int(item.amount)
                existing.amount = str(ea + ia)
            except (ValueError, TypeError):
                pass
            existing.weight += item.weight
            return
    player.inventory.append(item)

# 时间常量
PENDULUMS_PER_DAY = 5000
PENDULUMS_PER_MONTH = 50000     # 10 天
PENDULUMS_PER_YEAR = 250000     # 5 月


def _build_world(state: GameState) -> None:
    """构建 80×60 无缝大地图：村庄 + 平原 + 树林 + 地精营地。"""
    w, h = 80, 60
    state.current_map = "世界"
    state.map = Grid[Terrain](w, h, Terrain.PASSABLE)
    state.entities = []
    random.seed(42)

    # ── 村庄 (20×15, 偏移 3,20) ──
    vx, vy = 3, 20
    village_walls = [
        (2,2),(3,2),(4,2),(5,2),(6,2),(2,3),(6,3),(2,4),(6,4),(2,5),(3,5),(4,5),(5,5),(6,5),
        (9,2),(10,2),(11,2),(12,2),(13,2),(9,3),(13,3),(9,4),(13,4),(9,5),(10,5),(11,5),(12,5),(13,5),
        (20,1),(21,1),(22,1),(23,1),(24,1),(20,2),(24,2),(20,3),(24,3),(20,4),(24,4),(20,5),(21,5),(22,5),(23,5),(24,5),
        (25,8),(26,8),(27,8),(28,8),(25,9),(28,9),(25,10),(28,10),(25,11),(26,11),(27,11),(28,11),
    ]
    for wx, wy in village_walls:
        state.map[vx + wx, vy + wy] = Terrain.WALL
    state.map[vx + 18, vy + 10] = Terrain.DIFFICULT  # 水井

    state.bed_positions = {(vx + 4, vy + 4), (vx + 11, vy + 4), (vx + 22, vy + 3), (vx + 26, vy + 9)}
    state.door_states = {
        (vx + 4, vy + 5): False, (vx + 11, vy + 5): False,
        (vx + 22, vy + 4): False, (vx + 26, vy + 11): False,
    }
    for pos, is_open in state.door_states.items():
        if not is_open:
            state.map[pos] = Terrain.WALL

    village_npcs = [
        ("village_elder", vx + 3, vy + 7), ("merchant", vx + 11, vy + 7),
        ("villager", vx + 7, vy + 8), ("villager", vx + 14, vy + 5),
        ("villager", vx + 4, vy + 10), ("villager", vx + 15, vy + 8),
        ("villager", vx + 22, vy + 7),
    ]
    for key, cx, cy in village_npcs:
        c = _loader.load_creature(key)
        if c:
            c.template_name = key
            state.add_entity(c, (cx, cy))

    # ── 树林 (30×30, 偏移 35,15, 村庄东 15 格) ──
    fx, fy = 35, 15
    for _ in range(200):
        tx = fx + random.randint(0, 29)
        ty = fy + random.randint(0, 29)
        if 0 <= tx < w and 0 <= ty < h and state.map[tx, ty] == Terrain.PASSABLE:
            state.map[tx, ty] = Terrain.DIFFICULT

    # 地下城入口 > 在树林中
    entrance = (fx + random.randint(5, 25), fy + random.randint(5, 25))
    state.map[entrance] = Terrain.PASSABLE  # 入口可通行
    state.dungeon_entrance = entrance

    # ── 地精营地 (10×15, 偏移 68,10, 树林东侧) ──
    gx, gy = 68, 10
    camp_walls = [
        (0,0),(1,0),(2,0),(3,0),(4,0),(5,0),(6,0),(7,0),
        (0,1),(7,1),(0,2),(7,2),(0,3),(7,3),(0,4),(7,4),
        (0,5),(1,5),(2,5),(3,5),(4,5),(5,5),(6,5),(7,5),
    ]
    for wx, wy in camp_walls:
        state.map[gx + wx, gy + wy] = Terrain.WALL
    # 篝火
    state.map[gx + 3, gy + 3] = Terrain.DIFFICULT
    # 木屋门
    state.door_states[(gx + 3, gy + 5)] = False
    state.map[gx + 3, gy + 5] = Terrain.WALL

    camp_enemies = [
        ("goblin_brawler", gx + 2, gy + 2), ("goblin_brawler", gx + 5, gy + 1),
        ("goblin_brawler", gx + 6, gy + 3), ("goblin_brawler", gx + 1, gy + 4),
        ("long_ear_dog", gx + 4, gy + 1), ("long_ear_dog", gx + 5, gy + 4),
        ("long_ear_dog", gx + 2, gy + 3),
    ]
    for key, cx, cy in camp_enemies:
        c = _loader.load_creature(key)
        if c:
            c.template_name = key
            state.add_entity(c, (cx, cy))

    # ── 平原游荡生物 ──
    creatures = ["bird", "squirrel", "cat", "long_ear_dog", "wild_boar"]
    for _ in range(15):
        key = random.choice(creatures)
        c = _loader.load_creature(key)
        if c:
            c.template_name = key
            for _ in range(20):
                px = random.randint(0, w - 1)
                py = random.randint(0, h - 1)
                if state.map[px, py] == Terrain.PASSABLE:
                    state.add_entity(c, (px, py))
                    break

    # ── 平原灌木 ──
    for _ in range(60):
        bx = random.randint(0, w - 1)
        by = random.randint(0, h - 1)
        if state.map[bx, by] == Terrain.PASSABLE:
            state.map[bx, by] = Terrain.DIFFICULT

    state.map_exits = []
    state.loot_spots = []


def _build_dungeon(state: GameState) -> None:
    """BSP 生成地下城 (30×20)。"""
    w, h = 30, 20
    state.current_map = "地下城"
    state.map = Grid[Terrain](w, h, Terrain.WALL)
    state.entities = []
    state.bed_positions = set()
    state.door_states = {}
    state.map_exits = []
    random.seed(123)

    # 挖掘 3-5 个房间 + 走廊
    rooms = []
    for _ in range(random.randint(3, 5)):
        rw, rh = random.randint(4, 8), random.randint(3, 6)
        rx = random.randint(1, w - rw - 1)
        ry = random.randint(1, h - rh - 1)
        rooms.append((rx, ry, rw, rh))
        for x in range(rx, rx + rw):
            for y in range(ry, ry + rh):
                state.map[x, y] = Terrain.PASSABLE

    # 连接走廊
    for i in range(len(rooms) - 1):
        x1 = rooms[i][0] + rooms[i][2] // 2
        y1 = rooms[i][1] + rooms[i][3] // 2
        x2 = rooms[i + 1][0] + rooms[i + 1][2] // 2
        y2 = rooms[i + 1][1] + rooms[i + 1][3] // 2
        for x in range(min(x1, x2), max(x1, x2) + 1):
            state.map[x, y1] = Terrain.PASSABLE
        for y in range(min(y1, y2), max(y1, y2) + 1):
            state.map[x2, y] = Terrain.PASSABLE

    # 入口和出口
    first_room = rooms[0]
    state.map[first_room[0] + 1, first_room[1]] = Terrain.PASSABLE  # 入口标记
    state.dungeon_entrance = (first_room[0] + 1, first_room[1])
    state.dungeon_exit = (first_room[0] + 1, first_room[1])
    state.player_pos = (first_room[0] + 2, first_room[1] + 1)

    # 红宝石在最后一个房间
    last_room = rooms[-1]
    state.map[last_room[0] + last_room[2] // 2, last_room[1] + last_room[3] // 2] = Terrain.DIFFICULT

    # 骷髅兵
    skeleton_positions = []
    for _ in range(4):
        r = random.choice(rooms[1:])
        sx = r[0] + random.randint(1, r[2] - 1)
        sy = r[1] + random.randint(1, r[3] - 1)
        if (sx, sy) not in skeleton_positions:
            skeleton_positions.append((sx, sy))
            sk = _loader.load_creature("skeleton")
            if sk:
                sk.template_name = "skeleton"
                state.add_entity(sk, (sx, sy))


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


# ═══════════════════════════════════════ Widgets ═══════════════════════════════════════

class TopBar(Static):
    state: GameState | None = None
    def render(self) -> str:
        if self.state is None: return ""
        s = self.state
        pc = s.clock.pendulum_count
        day = (pc // PENDULUMS_PER_DAY) % 10 + 1
        month = (pc // PENDULUMS_PER_MONTH) % 5 + 1
        year = pc // PENDULUMS_PER_YEAR + 1

        left = f"[bold]{s.current_map or '???'}[/]  晴"

        if s.in_combat and s.combat_initiative:
            names = []
            for e in s.combat_initiative:
                if e.hp <= 0: continue
                nm = e.name
                if e is s.combat_turn_entity: nm = f"[bold yellow]{nm}[/]"
                names.append(nm)
            center = " > ".join(names)
        else:
            center = ""

        right = f"第{day}天 {month}月 {year}纪年 {pc}钟摆"
        return f" {left}   {center}   {right}"


class LeftPanel(Static):
    state: GameState | None = None
    def render(self) -> str:
        lines = []
        if self.state and self.state.in_combat:
            p = self.state.player
            filled = int(p.ap / max(p.max_ap, 1) * 10)
            lines.append(f"AP [{'|'*filled}{'.'*(10-filled)}]")
            lines.append("S-Tab 结束回合")
        lines.extend([
            "[[0]]交互 [[1]]探查  [[2]]躲藏 [[3]]协助",
            "[[4]]跳跃 [[5]]撤离  [[6]]回避 [[7]]推撞",
            "[[8]]擒抱 [[ / ]]击晕  [[g]]慢速 [[G]]疾走",
            "[[r]]短休 [[R]]长休  [[,]]消磨 [[A]]动作",
            "[[S]]法术 [[X]]观察 [[Q]]退出",
        ])
        return "\n".join(lines)


class MapView(Static):
    can_focus = True
    state: GameState | None = None
    def render(self) -> str:
        if self.state is None: return "Loading..."
        gmap = self.state.map
        pc, pr = self.state.player_pos
        fov = self.state.fov_cache
        r = self.state.player.vision_range
        vw = min(r * 2 + 3, gmap.width)
        vh = min(r * 2 + 1, gmap.height)
        ox = max(0, min(pc - vw // 2, gmap.width - vw))
        oy = max(0, min(pr - vh // 2, gmap.height - vh))

        text = Text()
        for row in range(oy, min(oy + vh, gmap.height)):
            for col in range(ox, min(ox + vw, gmap.width)):
                if (col, row) not in fov:
                    text.append(" ")
                    continue
                ent = self.state.get_entity_at(col, row)
                if ent is not None:
                    ch = "%" if ent.hp <= 0 else ent.char
                    color = FACTION_COLORS.get(ent.faction, "")
                    text.append(ch, style=f"bold {color}" if ent.faction == "hostile" else color)
                elif (col, row) == (pc, pr):
                    text.append("@", style="bold bright_cyan")
                elif (col, row) in self.state.bed_positions:
                    text.append("=", style="bold cyan")
                elif self.state.dungeon_entrance and (col, row) == self.state.dungeon_entrance:
                    text.append(">", style="bold magenta")
                else:
                    t = gmap[col, row]
                    if (col, row) in self.state.door_states:
                        is_open = self.state.door_states[(col, row)]
                        ch = "_" if is_open else "]"
                        text.append(ch, style="bold yellow")
                    else:
                        ch = {".": ".", "#": "#", '"': '"'}.get(
                            {Terrain.WALL: "#", Terrain.DIFFICULT: '"', Terrain.PASSABLE: "."}[t], ".")
                        text.append(ch, style=TERRAIN_COLORS.get(t, ""))
            if row < min(oy + vh, gmap.height) - 1:
                text.append("\n")
        text.append("\n")
        text.append("@玩家 g地精 d犬 w猪 S骷髅 b鸟 c猫 E长老 M商人 v村民", style="dim")
        return text


class RightPanel(Static):
    state: GameState | None = None
    def render(self) -> str:
        if self.state is None: return ""
        p = self.state.player
        slow_tag = " [dim]慢速[/]" if self.state.slow_mode else ""
        lines = [
            f"[bold]{p.name}[/]  人类 Lv.1 {p.char_class}{slow_tag}",
            f"HP [green]{p.hp}/{p.max_hp}[/]  MP [blue]{p.mp}/{p.max_mp}[/]  TEN [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC 头部{p.total_ac('head')} 躯干{p.total_ac('chest')} 双臂{p.total_ac('arms')} 双腿{p.total_ac('legs')}",
            f"SPD {p.speed}  INIT +{p.initiative_bonus()}",
            "",
            "[[C]]角色面板 [[I]]物品栏 [[B]]法术书",
            "[[Z]]制作 [[K]]烹饪 [[Y]]炼药",
            "[[H]]高度 [[M]]地图 [[E]]系统",
        ]
        if p.statuses:
            lines.append(f"[red]{' '.join(p.statuses)}[/]")
        return "\n".join(lines)


class ActionLog(Static):
    messages: list[str] = []
    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 200: self.messages = self.messages[-100:]
        self.refresh()
    def render(self) -> str:
        if not self.messages: return ""
        h = max(self.size.height, 6)
        return "\n".join(self.messages[-h:])


class SceneLog(Static):
    messages: list[str] = []
    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 200: self.messages = self.messages[-100:]
        self.refresh()
    def set_scene(self, lines: list[str]) -> None:
        filtered = [l for l in lines if l]
        if filtered != self.messages:
            self.messages = filtered; self.refresh()
    def render(self) -> str:
        if not self.messages: return ""
        h = max(self.size.height, 6)
        return "\n".join(self.messages[-h:])


# ═══════════════════════════════════════ App ═══════════════════════════════════════

class MVPApp(App):
    CSS = """
    * { margin: 0; padding: 0; overflow: hidden; }

    #top { height: 1; border: solid #444444; padding: 0 1; }

    #main { height: 3fr; min-height: 15; }
    #left { width: 2fr; min-width: 14; border-right: solid #444444; padding: 0 1; }
    MapView { width: 3fr; min-width: 20; content-align: left top; }
    #right { width: 2fr; min-width: 18; border-left: solid #444444; padding: 0 1; }

    #input-bar { height: 1; border: solid #444444; }

    #log-area { height: 2fr; min-height: 6; border: solid #444444; }
    #action-log { width: 1fr; min-width: 20; height: 100%; border-right: solid #444444; padding: 0 1; content-align: left top; }
    #scene-log { width: 1fr; min-width: 20; height: 100%; padding: 0 1; content-align: left top; }
    """

    BINDINGS = [
        Binding("q", "quit", "退出", priority=True),
        Binding("up,w", "move_up", "", priority=True),
        Binding("down,s", "move_down", "", priority=True),
        Binding("left,a", "move_left", "", priority=True),
        Binding("right,d", "move_right", "", priority=True),
        Binding("x", "toggle_observe", "观察", priority=True),
        Binding("r", "short_rest", "短休", priority=True),
        Binding("R", "long_rest", "长休", priority=True),
        Binding("g", "slow_speed", "慢速", priority=True),
        Binding("G", "dash", "疾走", priority=True),
        Binding("0", "action_0", "交互", priority=True),
        Binding("1", "action_1", "探查", priority=True),
        Binding("2", "action_2", "躲藏", priority=True),
        Binding("3", "action_3", "协助", priority=True),
        Binding("4", "action_4", "跳跃", priority=True),
        Binding("5", "action_5", "撤离", priority=True),
        Binding("6", "action_6", "回避", priority=True),
        Binding("7", "action_7", "推撞", priority=True),
        Binding("8", "action_8", "擒抱", priority=True),
        Binding("slash", "toggle_knockout", "击晕", priority=True),
        Binding("comma", "wait", "消磨时间", priority=True),
        Binding("A", "show_actions", "动作", priority=True),
        Binding("S", "show_spells", "法术", priority=True),
        Binding("f5", "quick_save", "存档", priority=True),
        Binding("f9", "quick_load", "读档", priority=True),
        Binding("colon", "focus_input", "", priority=True),
        Binding("C", "char_panel", "角色面板", priority=True),
        Binding("I", "inventory", "物品栏", priority=True),
        Binding("B", "spellbook", "法术书", priority=True),
        Binding("Z", "crafting", "制作", priority=True),
        Binding("K", "cooking", "烹饪", priority=True),
        Binding("Y", "alchemy", "炼药", priority=True),
        Binding("H", "height_view", "高度", priority=True),
        Binding("M", "map_overview", "地图", priority=True),
        Binding("E", "system_menu", "系统", priority=True),
    ]

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
        self._save_data: dict | None = None
        self._last_move: tuple[int, int] = (0, 0)

    def _create_game(self) -> None:
        stats = {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}
        boosted = random.sample(["str", "dex", "con", "int", "wis", "cha"], 2)
        for s in boosted: stats[s] = 10
        player = Player.create_fighter(name="凯恩", stats=stats)
        self._state = GameState(player=player, map_width=80, map_height=60)
        _build_world(self._state)
        self._state.player_pos = (9, 26)  # 村庄长老房旁边
        import core.entity as ent
        sword_data = {"name": "长剑", "weapon_type": "melee", "category": "martial",
                       "damage": "1d8", "damage_type": "slashing", "attack_stat": "str",
                       "ap_cost": 3, "weight": 2.0}
        self._state.player.equipment["right_hand"] = ent.Weapon.from_dict(sword_data)
        # 预置初始物品
        _add_to_inventory(self._state.player, ent.Item.from_dict({
            "name": "治疗药水", "item_type": "consumable",
            "effect": "heal", "amount": "6d4", "ap_cost": 1,
            "weight": 0.5, "price": {"gp": 2},
            "description": "喝掉这瓶清澈红色液体的生物恢复 6d4 点生命值"}))
        _add_to_inventory(self._state.player, ent.Item.from_dict({
            "name": "一包口粮", "item_type": "consumable",
            "effect": "restore_food", "amount": "15000", "ap_cost": 1,
            "weight": 1.0, "price": {"cp": 50},
            "description": "几块晒干的兽肉和浆果，食用恢复饮食值"}))
        _update_fov(self._state)

    def compose(self) -> ComposeResult:
        self._create_game()
        self._top_bar = TopBar(id="top"); yield self._top_bar
        with Horizontal(id="main"):
            self._left_panel = LeftPanel(id="left"); yield self._left_panel
            self._map_view = MapView(); yield self._map_view
            self._right_panel = RightPanel(id="right"); yield self._right_panel
        self._input_bar = Input(placeholder=": 输入命令 (按 Esc 退出输入)", id="input-bar", disabled=True)
        yield self._input_bar
        with Horizontal(id="log-area"):
            self._act_log = ActionLog(id="action-log"); yield self._act_log
            self._scene_log = SceneLog(id="scene-log"); yield self._scene_log

    def on_mount(self) -> None:
        for w in [self._map_view, self._left_panel, self._right_panel, self._top_bar]:
            w.state = self._state
        self._refresh_scene()
        self.refresh_all()
        self._map_view.focus()

    def refresh_all(self) -> None:
        for w in [self._map_view, self._left_panel, self._right_panel,
                  self._top_bar, self._act_log, self._scene_log]:
            if w: w.refresh()

    def on_key(self, event) -> None:
        """处理数字键（Textual binding 对数字键不生效，需手动分发）。"""
        digit_actions = {
            "0": self.action_interact,
            "1": self.action_1,
            "2": self.action_2,
            "3": self.action_3,
            "4": self.action_4,
            "5": self.action_5,
            "6": self.action_6,
            "7": self.action_7,
            "8": self.action_8,
        }
        handler = digit_actions.get(event.key)
        if handler:
            handler()
            event.stop()

    # ── Input ──

    def action_focus_input(self) -> None:
        self._input_bar.disabled = False
        self._input_bar.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        self._input_bar.value = ""
        self._input_bar.disabled = True
        if cmd:
            self._act_log.add(f"> :{cmd}")
            self._act_log.add("此功能待开发")
        self._map_view.focus()

    # ── Movement ──

    def _move_player(self, dc: int, dr: int) -> None:
        if self._state.observe_mode:
            oc, oro = self._state.observe_cursor
            nc, nr = oc + dc, oro + dr
            if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                if (nc, nr) in self._state.fov_cache:
                    self._state.observe_cursor = (nc, nr)
                    self._right_panel.refresh()
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
            # 走进地下城入口
            if (not self._state.in_dungeon and self._state.dungeon_entrance
                    and self._state.player_pos == self._state.dungeon_entrance):
                self._enter_dungeon()

    def action_move_up(self): self._move_player(0, -1)
    def action_move_down(self): self._move_player(0, 1)
    def action_move_left(self): self._move_player(-1, 0)
    def action_move_right(self): self._move_player(1, 0)

    # ── Observe ──

    def action_toggle_observe(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法观察"); return
        self._state.observe_mode = not self._state.observe_mode
        if self._state.observe_mode:
            self._state.observe_cursor = self._state.player_pos
            self._act_log.add("观察模式 — 方向键移动光标, X退出")
        else: self._act_log.add("退出观察模式")
        self.refresh_all()

    # ── Interact ──

    def action_interact(self) -> None:
        if self._state.in_combat: self._player_attack(); return
        pc, pr = self._state.player_pos
        # 地下城入口
        if self._state.dungeon_entrance and (pc, pr) == self._state.dungeon_entrance:
            self._enter_dungeon(); return
        # 地下城出口
        if self._state.in_dungeon and self._state.dungeon_exit and (pc, pr) == self._state.dungeon_exit:
            self._exit_dungeon(); return
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
                    self.refresh_all(); return
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
                        "effect": "restore_food", "amount": str(500 * b),
                        "ap_cost": 1, "weight": 0.1 * b,
                        "price": {"cp": 2 * b},
                        "description": f"多汁的浆果，{b}颗"
                    })
                    _add_to_inventory(self._state.player, berry)
                    self._act_log.add(f"凯恩 从灌木丛摘到 {b} 个浆果")
                    self.refresh_all(); return
        self._act_log.add("凯恩 环顾四周，这里没什么特别的")
        self.refresh_all()

    def _interact_creature(self, c: Creature, pos: tuple[int, int]) -> None:
        if c.faction == "hostile":
            self._act_log.add(f"凯恩 拔剑冲向 {c.name}!"); self._start_combat(c)
        else:
            self._act_log.add(f"凯恩 向 {c.name} 搭话")
            self._act_log.add(self._get_npc_dialogue(c))

    def _get_npc_dialogue(self, c: Creature) -> str:
        """基于 AI 状态生成 NPC 对话，不硬编码角色名。"""
        enemy_count = 0
        ally_count = sum(1 for o, _ in self._state.entities
                         if o.faction == c.faction and o.hp > 0 and o is not c)
        ratio = c.hp / max(c.max_hp, 1) * (ally_count + 1)
        try:
            action, _ = _ai_engine.decide(c, enemy_count, ally_count, ratio)
        except Exception:
            action = "idle"

        brave = getattr(c, "bravery_tier", "medium") or "medium"

        DIALOGUE = {
            "patrol": {"low": "这一带最近不太平...", "medium": "我在巡逻，一切正常", "high": "放心吧，有我在"},
            "hunt": {"low": "希望能找到点吃的...", "medium": "今天的猎物跑得真快", "high": "刚猎到一只肥美的兔子"},
            "idle": {"low": "嗯...你好", "medium": "你好，旅行者", "high": "欢迎！有什么需要帮忙的吗"},
            "sleep": {"low": "呼...别吵...", "medium": "呼...呼...", "high": "打了个盹，精神不错"},
            "flee": {"low": "我得走了！", "medium": "这里不安全", "high": "你也快离开这"},
            "defend": {"low": "别过来...", "medium": "小心为上", "high": "退后！"},
            "advance": {"low": "别靠近我...", "medium": "你来这里做什么", "high": "嘿，站住"},
            "attack": {"low": "不...不要过来！", "medium": "你是在挑衅吗", "high": "想打架吗"},
            "inspect": {"low": "好像有点不对劲...", "medium": "让我看看...", "high": "仔细检查中"},
            "surrender": {"low": "饶了我吧！", "medium": "我投降，别动手", "high": "好吧好吧，你赢了"},
        }
        tier = brave if brave in ("low", "medium", "high") else "medium"
        action_dialogues = DIALOGUE.get(action, DIALOGUE["idle"])
        return f"{c.name}: {action_dialogues.get(tier, action_dialogues['medium'])}"

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
        }
        _build_dungeon(self._state)
        self._state.in_dungeon = True
        self._act_log.add("凯恩 走入了地下城...")
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
        self._state.in_dungeon = False
        self._act_log.add("凯恩 回到了地面")
        self._end_combat(); _update_fov(self._state)
        self._refresh_scene(); self.refresh_all()

    # ── Combat ──

    def _start_combat(self, target: Creature) -> None:
        self._state.in_combat = True; self._state.player.ap = self._state.player.max_ap
        combatants = [self._state.player]
        pc, pr = self._state.player_pos
        for creature, (ec, er) in self._state.entities:
            if creature.hp > 0 and creature.faction == "hostile" and abs(ec - pc) <= 5:
                combatants.append(creature); creature.ap = creature.max_ap
        self._state.combat_initiative = roll_initiative(combatants)
        self._state.combat_turn_index = 0; self._state.combat_turn_entity = combatants[0]
        self._act_log.add("=== 战斗开始 ==="); self._next_turn()

    def _end_combat(self) -> None:
        self._state.in_combat = False; self._state.combat_initiative = []
        self._state.combat_turn_entity = None
        self._state.player.ap = self._state.player.max_ap
        self._act_log.add("=== 战斗结束 ===")

    def _next_turn(self) -> None:
        if not self._state.in_combat: return
        alive = [e for e in self._state.combat_initiative if e is self._state.player or e.hp > 0]
        if not any(e.faction == "hostile" and e.hp > 0 for e in alive):
            self._end_combat(); self.refresh_all(); return
        self._state.combat_initiative = alive
        idx = (self._state.combat_turn_index + 1) % len(alive)
        self._state.combat_turn_index = idx; turn = alive[idx]
        self._state.combat_turn_entity = turn; turn.ap = turn.max_ap
        if turn is self._state.player: self._act_log.add(">>> 凯恩的回合 <<<")
        else: self._npc_turn(turn)
        self.refresh_all()

    def _player_attack(self) -> None:
        pc, pr = self._state.player_pos
        weapon = self._state.player.equipment.get("right_hand")
        if weapon is None:
            self._act_log.add("凯恩 赤手空拳!"); return
        if self._state.player.ap < weapon.ap_cost: self._act_log.add("AP 不足"); return
        target = None
        for creature, (ec, er) in self._state.entities:
            if creature.faction == "hostile" and creature.hp > 0 and abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                target = creature; break
        if target is None: self._act_log.add("凯恩 环顾四周，没有目标"); return
        self._state.player.ap -= weapon.ap_cost
        hit, roll = hit_check(self._state.player, target, weapon)
        if hit:
            dmg = roll_damage(weapon, self._state.player, critical=(roll == 20))
            dmg = apply_damage_type_modifiers(dmg, weapon.damage_type, target)
            target.hp = max(0, target.hp - dmg)
            self._act_log.add(f"凯恩 挥剑砍中了 {target.name}，{target.name} 发出一声惨叫")
            if target.hp <= 0: self._act_log.add(f"{target.name} 倒在地上，不再动弹")
        else:
            reduce_tenacity(target, roll)
            self._act_log.add(f"凯恩 挥剑砍向 {target.name}，被躲开了")
            if target.tenacity == 0 and "incapacitated" not in target.statuses:
                target.statuses.append("incapacitated")
                self._act_log.add(f"{target.name} 被击破防御，陷入失能!")
        if self._state.player.ap <= 0: self._next_turn()
        self.refresh_all()

    def _npc_turn(self, npc: Creature) -> None:
        pc, pr = self._state.player_pos
        npc_pos = None
        for c, (ec, er) in self._state.entities:
            if c is npc: npc_pos = (ec, er); break
        if npc_pos is None: self._next_turn(); return
        nc, nr = npc_pos
        enemy_count = 1 if abs(nc - pc) <= 8 else 0
        ally_count = sum(1 for c, _ in self._state.entities
                         if c.faction == "hostile" and c.hp > 0 and c is not npc)
        ratio = npc.hp / max(npc.max_hp, 1) * (ally_count + 1) / max(enemy_count, 1)
        action, _ = _ai_engine.decide(npc, enemy_count, ally_count, ratio)
        if action in ("flee", "surrender"):
            self._act_log.add(f"{npc.name} 惊慌地逃跑了!"); self._state.remove_entity(npc)
        elif action in ("attack", "advance"):
            if abs(nc - pc) <= 1 and abs(nr - pr) <= 1:
                dmg = max(1, roll_d20() // 4)
                self._state.player.hp = max(0, self._state.player.hp - dmg)
                self._act_log.add(f"{npc.name} 挥动武器击中了凯恩!")
                if self._state.player.hp <= 0: self._act_log.add("凯恩 被击倒了! [R]长休恢复")
            else:
                dc = 1 if pc > nc else (-1 if pc < nc else 0)
                dr = 1 if pr > nr else (-1 if pr < nr else 0)
                if self._state.move_entity(npc, nc, nr, nc + dc, nr + dr):
                    self._act_log.add(f"{npc.name} 向前逼近")
        else: self._act_log.add(f"{npc.name} 警惕地盯着凯恩")
        self._next_turn(); self.refresh_all()

    # ── Long Rest ──

    def action_long_rest(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法长休"); return
        r = long_rest(self._state.player, self._state.clock,
                      self._state.map, self._state.player_pos,
                      self._state.bed_positions)
        comfort = "，睡得很舒适" if r.get("comfort") else ""
        self._act_log.add(f"凯恩 长休 (HP+{r['hp_restored']} MP+{r['mp_restored']}){comfort}")
        self.refresh_all()

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
            self._act_log.add("凯恩 原地踱步")
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
            self._act_log.add(f"凯恩 环顾四周: {', '.join(found)}")
        else:
            self._act_log.add("凯恩 环顾四周，没有特别的东西")
        self.refresh_all()

    # ── Wait ──

    def action_wait(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法消磨时间"); return
        for _ in range(30):
            self._state.clock.tick_action(1.0)
        self._act_log.add("时间流逝...")
        self.refresh_all()

    # ── Stub actions (待实现) ──

    def action_0(self): self.action_interact()
    def action_2(self): self._act_log.add("[躲藏] 此功能待开发")
    def action_3(self): self._act_log.add("[协助] 此功能待开发")
    def action_4(self): self._act_log.add("[跳跃] 此功能待开发")
    def action_5(self): self._act_log.add("[撤离] 此功能待开发")
    def action_6(self): self._act_log.add("[回避] 此功能待开发")
    def action_7(self): self._act_log.add("[推撞] 此功能待开发")
    def action_8(self): self._act_log.add("[擒抱] 此功能待开发")
    def action_toggle_knockout(self): self._act_log.add("[击晕] 此功能待开发")
    def action_show_actions(self): self._act_log.add("[动作] 此功能待开发")
    def action_show_spells(self): self._act_log.add("[法术] 此功能待开发")
    def action_char_panel(self): self.push_screen(CharacterScreen(self._state.player))
    def action_inventory(self): self.push_screen(InventoryScreen(self._state.player))
    def action_spellbook(self): self._act_log.add("[法术书] 此功能待开发")
    def action_crafting(self): self._act_log.add("[制作] 此功能待开发")
    def action_cooking(self): self._act_log.add("[烹饪] 此功能待开发")
    def action_alchemy(self): self._act_log.add("[炼药] 此功能待开发")
    def action_height_view(self): self._act_log.add("[高度] 此功能待开发")
    def action_map_overview(self): self._act_log.add("[地图] 此功能待开发")
    def action_system_menu(self): self._act_log.add("[系统] 此功能待开发")

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

        act_map = {
            "flee": "惊慌失措地试图逃窜", "surrender": "举起双手投降",
            "attack": "死死盯着凯恩" if enemy_count else "警惕地巡视四周",
            "advance": "向前逼近" if enemy_count else "来回踱步",
            "defend": "摆出防御姿态", "patrol": "漫无目的地游荡",
            "hunt": "低头寻觅着食物", "idle": "静静地站在原地",
            "sleep": "蜷缩着打盹",
        }
        return f"{c.name} {hp}{act_map.get(action, '待在原地')}"

    # ── Rest ──

    def action_short_rest(self) -> None:
        if self._state.in_combat: self._act_log.add("战斗中无法休息"); return
        r = short_rest(self._state.player, self._state.clock,
                       self._state.map, self._state.player_pos,
                       self._state.bed_positions)
        comfort = "，睡得很舒适" if r.get("comfort") else ""
        self._act_log.add(f"凯恩 短休 (HP+{r['hp_restored']} MP+{r['mp_restored']}){comfort}")
        self.refresh_all()

    # ── Save ──

    def action_quick_save(self) -> None:
        self._save_data = {"hp": self._state.player.hp, "mp": self._state.player.mp,
                           "pos": self._state.player_pos, "map": self._state.current_map}
        self._act_log.add("[快速存档] 已保存")

    def action_quick_load(self) -> None:
        if not self._save_data: self._act_log.add("没有存档"); return
        d = self._save_data
        self._state.player.hp = d["hp"]; self._state.player.mp = d["mp"]
        self._state.player_pos = d["pos"]
        if d["map"] != self._state.current_map: _load_map(self._state, d["map"])
        self._end_combat(); _update_fov(self._state)
        self._act_log.add("[快速读档] 已恢复"); self.refresh_all()
