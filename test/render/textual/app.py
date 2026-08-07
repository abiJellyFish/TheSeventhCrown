"""Textual MVP App — 完整游戏原型。

启动: python main.py
"""

import random
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Input
from textual.containers import Horizontal, Vertical, Container
from textual import events
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
from core.rest import short_rest
from core.loader import DataLoader
import os

# ═══════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_loader = DataLoader(DATA_DIR)
_ai_engine = BehaviorEngine({
    "goblin_brawler": _loader.load_json("ai/goblin_brawler"),
    "skeleton": _loader.load_json("ai/skeleton"),
})

# ═══════════════════════════════════════════════════
# Colors (Rich-compatible names)
# ═══════════════════════════════════════════════════

TERRAIN_COLORS = {
    Terrain.PASSABLE: "rgb(80,80,80)",
    Terrain.DIFFICULT: "green",
    Terrain.WALL: "rgb(140,140,140)",
}

FACTION_COLORS = {
    "hostile": "red",
    "friendly": "green",
    "neutral": "yellow",
}


def _load_map(state: GameState, map_name: str) -> None:
    data = _loader.load_json(f"maps/{map_name}")
    state.current_map = map_name
    state.map = Grid[Terrain](data["width"], data["height"], Terrain.PASSABLE)
    for c, r in data.get("terrain", {}).get("walls", []):
        state.map[c, r] = Terrain.WALL
    for c, r in data.get("terrain", {}).get("water", []):
        state.map[c, r] = Terrain.DIFFICULT
    for c, r in data.get("terrain", {}).get("difficult", []):
        state.map[c, r] = Terrain.DIFFICULT
    state.entities = []
    for ent_data in data.get("entities", []):
        c = _loader.load_creature(ent_data["key"])
        if c:
            c.template_name = ent_data["key"]
            state.add_entity(c, tuple(ent_data["pos"]))
    state.map_exits = data.get("exits", [])
    state.loot_spots = data.get("loot_spots", [])


def _generate_plains(state: GameState) -> None:
    w, h = 40, 30
    state.current_map = "plains"
    state.map = Grid[Terrain](w, h, Terrain.PASSABLE)
    random.seed(42)
    for _ in range(30):
        c, r = random.randint(0, w - 1), random.randint(0, h - 1)
        if random.random() < 0.6:
            state.map[c, r] = Terrain.DIFFICULT
    creatures = ["bird", "squirrel", "cat", "long_ear_dog", "wild_boar"]
    for _ in range(8):
        key = random.choice(creatures)
        c = _loader.load_creature(key)
        if c:
            c.template_name = key
            pos = (random.randint(3, w - 4), random.randint(3, h - 4))
            if state.map[pos] == Terrain.PASSABLE:
                state.add_entity(c, pos)
    state.map_exits = [
        {"to": "village", "at": [0, 15], "direction": "west"},
        {"to": "goblin_camp", "at": [39, 15], "direction": "east"},
    ]
    state.loot_spots = []


def _update_fov(state: GameState) -> None:
    """更新 FOV 缓存。"""
    ox, oy = state.player_pos
    # 构建透明度网格
    transparent = Grid[bool](state.map.width, state.map.height, True)
    for col in range(state.map.width):
        for row in range(state.map.height):
            if state.map[col, row] == Terrain.WALL:
                transparent[col, row] = False
    # 光照：户外明亮
    light = Grid[LightLevel](state.map.width, state.map.height,
                             LightLevel.BRIGHT if state.current_map != "dungeon" else LightLevel.DARK)
    darkvision = state.player.darkvision_range > 0
    state.fov_cache = compute_fov(transparent, (ox, oy), state.player.vision_range,
                                  light, darkvision, state.player.darkvision_range)


# ═══════════════════════════════════════════════════
# Color helpers
# ═══════════════════════════════════════════════════

def _color_for_terrain(t: Terrain) -> str:
    return TERRAIN_COLORS.get(t, "")


def _color_for_faction(faction: str) -> str:
    return FACTION_COLORS.get(faction, "")


# ═══════════════════════════════════════════════════
# Widgets
# ═══════════════════════════════════════════════════

class TopBar(Static):
    """顶部信息栏。"""
    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return ""
        loc = self.state.current_map or "???"
        combat = "[red]COMBAT[/]" if self.state.in_combat else ""
        return f" [bold]{loc}[/]  {combat}"


class LeftPanel(Static):
    """左侧动作栏。"""
    state: GameState | None = None

    def render(self) -> str:
        lines = []
        if self.state and self.state.in_combat:
            p = self.state.player
            bar_len = 10
            filled = int(p.ap / max(p.max_ap, 1) * bar_len)
            ap_bar = "[" + "|" * filled + "." * (bar_len - filled) + "]"
            lines.append(f"AP {ap_bar}")
            lines.append("[SHIFT+TAB] 结束回合")
        lines.append("[0]交互   [1]探查")
        lines.append("[2]躲藏   [3]协助")
        lines.append("[4]跳跃   [5]撤离")
        lines.append("[6]回避   [7]推撞")
        lines.append("[8]擒抱   [ / ] 击晕")
        lines.append("[g]慢速   [G]疾走")
        lines.append("[r]短休   [R]长休")
        lines.append("[,]消磨时间")
        lines.append("[A]动作   [S]法术")
        lines.append("[TAB]攻击/交互")
        lines.append("[X]观察模式")
        lines.append("[Q]退出")
        return "\n".join(lines)


class MapView(Static):
    """ASCII 地图渲染 — FOV 过滤 + 图例。"""
    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return "Loading..."
        gmap = self.state.map
        pc, pr = self.state.player_pos
        fov = self.state.fov_cache
        vw, vh = 40, 18

        # 视口跟随
        ox = max(0, min(pc - vw // 2, gmap.width - vw))
        oy = max(0, min(pr - vh // 2, gmap.height - vh))

        text = Text()
        for row in range(oy, min(oy + vh, gmap.height)):
            for col in range(ox, min(ox + vw, gmap.width)):
                if (col, row) not in fov:
                    text.append(" ", style="")
                    continue
                ent = self.state.get_entity_at(col, row)
                if ent is not None:
                    ch = "%" if ent.hp <= 0 else ent.char
                    color = _color_for_faction(ent.faction)
                    style = f"bold {color}" if ent.faction == "hostile" else color
                    text.append(ch, style=style)
                elif (col, row) == (pc, pr):
                    text.append("@", style="bold bright_cyan")
                else:
                    t = gmap[col, row]
                    ch_map = {Terrain.WALL: "#", Terrain.DIFFICULT: '"', Terrain.PASSABLE: "."}
                    ch = ch_map.get(t, ".")
                    text.append(ch, style=_color_for_terrain(t))
            if row < min(oy + vh, gmap.height) - 1:
                text.append("\n")

        # 图例
        text.append("\n")
        text.append("@ 玩家  g 地精  d 犬  w 野猪  S 骷髅  b 鸟  c 猫  E 长老  M 商人  v 村民",
                    style="dim")
        return text


class RightPanel(Static):
    """右侧状态栏。"""
    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return ""
        p = self.state.player
        lines = [
            f"[bold]{p.name}[/]",
            f"人类  Lv.1  {p.char_class}",
            f"HP: [green]{p.hp}/{p.max_hp}[/]",
            f"MP: [blue]{p.mp}/{p.max_mp}[/]",
            f"TEN: [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC: 头{p.total_ac('head')} 躯{p.total_ac('chest')} 臂{p.total_ac('arms')} 腿{p.total_ac('legs')}",
            f"SPD: {p.speed}  INIT: +{p.initiative_bonus()}",
            f"负重: 轻便",
            "",
            f"[dim][角色面板] [物品栏][/dim]",
            f"[dim][法术书] [制作][/dim]",
            f"[dim][烹饪] [炼药][/dim]",
            "",
            f"[dim][H]高度 [M]地图 [E]系统[/dim]",
        ]
        if p.statuses:
            lines.append(f"[red]{' '.join(p.statuses)}[/]")
        return "\n".join(lines)


class ActionLog(Static):
    """左侧日志 — 战斗/交谈记录。"""
    messages: list[str] = []

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 200:
            self.messages = self.messages[-100:]
        self.refresh()

    def render(self) -> str:
        recent = self.messages[-6:] if self.messages else ["..."]
        return "\n".join(recent)


class SceneLog(Static):
    """右侧日志 — 场景描述 + 检定结果。"""
    messages: list[str] = []

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 200:
            self.messages = self.messages[-100:]
        self.refresh()

    def set_scene(self, lines: list[str]) -> None:
        self.messages = lines
        self.refresh()

    def render(self) -> str:
        return "\n".join(self.messages[-5:] if self.messages else [""])


# ═══════════════════════════════════════════════════
# App
# ═══════════════════════════════════════════════════

class MVPApp(App):
    """MVP 游戏。"""

    CSS = """
    #top { height: 1; border: solid #666666; }
    #main { height: 1fr; }
    #left { width: 16; border: solid #666666; }
    MapView { width: 1fr; border: solid #666666; content-align: left top; }
    #right { width: 24; border: solid #666666; }
    #input-bar { height: 1; border: solid #666666; }
    #log-area { height: 6; }
    #action-log { width: 1fr; border: solid #666666; }
    #scene-log { width: 1fr; border: solid #666666; }
    """

    BINDINGS = [
        ("q", "quit", "退出"),
        ("up,w", "move_up", ""),
        ("down,s", "move_down", ""),
        ("left,a", "move_left", ""),
        ("right,d", "move_right", ""),
        ("tab", "interact", "交互"),
        ("r", "short_rest", "短休"),
        ("x", "toggle_observe", "观察"),
        ("f5", "quick_save", "存档"),
        ("f9", "quick_load", "读档"),
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

    # ── Init ──

    def _create_game(self) -> None:
        stats = {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}
        boosted = random.sample(["str", "dex", "con", "int", "wis", "cha"], 2)
        for s in boosted:
            stats[s] = 10
        player = Player.create_fighter(name="凯恩", stats=stats)
        self._state = GameState(player=player, map_width=30, map_height=20)
        _load_map(self._state, "village")
        self._state.player_pos = (10, 10)
        import core.entity as ent
        sword_data = {"name": "长剑", "weapon_type": "melee", "category": "martial",
                       "damage": "1d8", "damage_type": "slashing", "attack_stat": "str",
                       "ap_cost": 3, "properties": ["versatile(1d10)"], "weight": 2.0}
        self._state.player.equipment["right_hand"] = ent.Weapon.from_dict(sword_data)
        _update_fov(self._state)

    def compose(self) -> ComposeResult:
        self._create_game()
        self._top_bar = TopBar(id="top")
        yield self._top_bar
        with Horizontal(id="main"):
            self._left_panel = LeftPanel(id="left")
            yield self._left_panel
            self._map_view = MapView()
            yield self._map_view
            self._right_panel = RightPanel(id="right")
            yield self._right_panel
        self._input_bar = Input(placeholder=": 输入命令...", id="input-bar")
        yield self._input_bar
        with Horizontal(id="log-area"):
            self._act_log = ActionLog(id="action-log")
            yield self._act_log
            self._scene_log = SceneLog(id="scene-log")
            yield self._scene_log

    def on_mount(self) -> None:
        self._state_obj_to_widgets()
        self._act_log.add("凯恩 握紧了手中的长剑")
        self._refresh_scene()
        self.refresh_all()

    def _state_obj_to_widgets(self) -> None:
        self._map_view.state = self._state
        self._left_panel.state = self._state
        self._right_panel.state = self._state
        self._top_bar.state = self._state

    def refresh_all(self) -> None:
        for w in [self._map_view, self._left_panel, self._right_panel,
                  self._top_bar, self._act_log, self._scene_log]:
            if w:
                w.refresh()

    # ── Scene description ──

    def _refresh_scene(self) -> None:
        fov = self._state.fov_cache
        pc, pr = self._state.player_pos
        lines = []
        # FOV 内生物描述
        for creature, (ec, er) in self._state.entities:
            if (ec, er) not in fov or creature.hp <= 0:
                continue
            if creature is self._state.player:
                continue
            desc = self._describe_creature(creature)
            if desc:
                lines.append(desc)
        # 随机环境氛围
        if random.random() < 0.2:
            ambient = random.choice([
                "树枝沙沙作响",
                "一阵微风吹过草地",
                "远处传来鸟鸣",
                "空气中弥漫着泥土的气息",
            ])
            lines.append(ambient)
        if not lines:
            lines.append("周围一片宁静")
        self._scene_log.set_scene(lines)

    def _describe_creature(self, c: Creature) -> str:
        """生成生物当前动作/神情描述。"""
        if c.faction == "hostile":
            actions = [
                f"{c.name} 紧握着武器，警惕地环顾四周",
                f"{c.name} 咧嘴露出黄牙，低吼着",
                f"{c.name} 挥舞着手中的武器",
            ]
            return random.choice(actions)
        elif c.faction == "friendly":
            return f"{c.name} 安静地站着"
        else:
            if c.name == "野猪":
                return random.choice(["野猪 低头拱着地面觅食", "野猪 抬起头嗅了嗅空气"])
            if c.name == "鸟":
                return random.choice(["一只鸟 在枝头跳跃", "一只鸟 振翅飞过"])
            if c.name == "松鼠":
                return "松鼠 在草丛间窜来窜去"
            if c.name == "猫":
                return random.choice(["猫 慵懒地舔着爪子", "猫 竖起耳朵看向这边"])
            return f"{c.name} 在附近徘徊"
        return ""

    # ── Movement ──

    def _move_player(self, dc: int, dr: int) -> None:
        if self._state.observe_mode:
            # 观察模式移动光标
            oc, oro = self._state.observe_cursor
            nc, nr = oc + dc, oro + dr
            if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                if (nc, nr) in self._state.fov_cache:
                    self._state.observe_cursor = (nc, nr)
                    self._right_panel.refresh()
            return

        if self._state.in_combat and self._state.player.ap <= 0:
            self._act_log.add("AP 不足")
            return

        col, row = self._state.player_pos
        nc, nr = col + dc, row + dr
        for ext in self._state.map_exits:
            if (nc, nr) == tuple(ext["at"]):
                dest = ext["to"]
                if dest == "plains":
                    _generate_plains(self._state)
                else:
                    _load_map(self._state, dest)
                self._state.player_pos = (5, 5)
                self._act_log.add(f"凯恩 前往了 {dest}")
                self._end_combat()
                _update_fov(self._state)
                self._refresh_scene()
                self.refresh_all()
                return

        result = self._state.move_player(nc, nr)
        if result:
            if self._state.in_combat:
                self._state.player.ap -= 1
            _update_fov(self._state)
            self._refresh_scene()
            self.refresh_all()

    def action_move_up(self): self._move_player(0, -1)
    def action_move_down(self): self._move_player(0, 1)
    def action_move_left(self): self._move_player(-1, 0)
    def action_move_right(self): self._move_player(1, 0)

    # ── Observe mode ──

    def action_toggle_observe(self) -> None:
        if self._state.in_combat:
            self._act_log.add("战斗中无法进入观察模式")
            return
        self._state.observe_mode = not self._state.observe_mode
        if self._state.observe_mode:
            self._state.observe_cursor = self._state.player_pos
            self._act_log.add("进入观察模式 — 方向键移动光标, X 退出")
        else:
            self._act_log.add("退出观察模式")
        self.refresh_all()

    # ── Interaction ──

    def action_interact(self) -> None:
        if self._state.in_combat:
            self._player_attack()
            return
        pc, pr = self._state.player_pos
        for creature, (ec, er) in self._state.entities:
            if creature is self._state.player or creature.hp <= 0:
                if creature.hp <= 0 and abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                    self._loot_corpse(creature)
                    return
                continue
            if abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                self._interact_creature(creature, (ec, er))
                return
        # 灌木丛采摘
        tile = self._state.map[pc, pr]
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nc, nr = pc + dc, pr + dr
                if 0 <= nc < self._state.map.width and 0 <= nr < self._state.map.height:
                    if self._state.map[nc, nr] == Terrain.DIFFICULT:
                        berries = random.randint(1, 4)
                        self._act_log.add(f"凯恩 从灌木丛摘到 {berries} 个浆果")
                        self.refresh_all()
                        return

    def _interact_creature(self, c: Creature, pos: tuple[int, int]) -> None:
        if c.faction == "hostile":
            self._act_log.add(f"凯恩 拔剑冲向 {c.name}!")
            self._start_combat(c)
        elif c.faction == "friendly":
            self._act_log.add(f"凯恩 向 {c.name} 搭话")
            if c.name == "村庄长老":
                self._act_log.add("长老: 冒险者，请前往地城取回红宝石")
            elif c.name == "商人":
                self._act_log.add("商人: 看看我的货物吧 (交易功能待扩展)")
            else:
                self._act_log.add(f"{c.name}: 你好，冒险者")
        else:
            self._act_log.add(self._describe_creature(c))

    def _loot_corpse(self, c: Creature) -> None:
        if getattr(c, '_looted', False):
            self._act_log.add("已经搜刮过了")
            return
        c._looted = True
        if c.loot:
            always = c.loot.get("always", [])
            self._act_log.add(f"[搜刮] {c.name}: 获得了一些物品")
        else:
            self._act_log.add(f"[搜刮] {c.name}: 没有可用的物品")

    # ── Combat ──

    def _start_combat(self, target: Creature) -> None:
        self._state.in_combat = True
        self._state.player.ap = self._state.player.max_ap
        combatants = [self._state.player]
        pc, pr = self._state.player_pos
        for creature, (ec, er) in self._state.entities:
            if creature.hp > 0 and creature.faction == "hostile":
                if abs(ec - pc) <= 5:
                    combatants.append(creature)
                    creature.ap = creature.max_ap
        self._state.combat_initiative = roll_initiative(combatants)
        self._state.combat_turn_index = 0
        self._state.combat_turn_entity = combatants[0]
        self._act_log.add(f"=== 战斗开始! ===")
        self._next_turn()

    def _end_combat(self) -> None:
        self._state.in_combat = False
        self._state.combat_initiative = []
        self._state.combat_turn_entity = None
        self._state.player.ap = self._state.player.max_ap
        self._act_log.add("=== 战斗结束 ===")

    def _next_turn(self) -> None:
        if not self._state.in_combat:
            return
        alive = [e for e in self._state.combat_initiative
                 if e is self._state.player or e.hp > 0]
        hostiles_alive = any(e.faction == "hostile" and e.hp > 0 for e in alive)
        if not hostiles_alive:
            self._end_combat()
            self.refresh_all()
            return
        self._state.combat_initiative = alive
        idx = (self._state.combat_turn_index + 1) % len(alive)
        self._state.combat_turn_index = idx
        turn_entity = alive[idx]
        self._state.combat_turn_entity = turn_entity
        turn_entity.ap = turn_entity.max_ap
        if turn_entity is self._state.player:
            self._act_log.add(">>> 凯恩的回合 <<<")
        else:
            self._npc_turn(turn_entity)
        self.refresh_all()

    def _player_attack(self) -> None:
        pc, pr = self._state.player_pos
        weapon = self._state.player.equipment.get("right_hand")
        if weapon is None:
            self._act_log.add("凯恩 挥拳攻击")
            weapon = type('obj', (object,), {'ap_cost': 1, 'damage': '1',
                            'damage_type': 'bludgeoning', 'attack_stat': 'str'})()
        if self._state.player.ap < weapon.ap_cost:
            self._act_log.add("AP 不足")
            return
        target = None
        for creature, (ec, er) in self._state.entities:
            if creature.faction != "hostile" or creature.hp <= 0:
                continue
            if abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                target = creature
                break
        if target is None:
            self._act_log.add("凯恩 环顾四周，没有可攻击的目标")
            return
        self._state.player.ap -= weapon.ap_cost
        hit, roll = hit_check(self._state.player, target, weapon)
        if hit:
            dmg = roll_damage(weapon, self._state.player, critical=(roll == 20))
            dmg = apply_damage_type_modifiers(dmg, weapon.damage_type, target)
            target.hp = max(0, target.hp - dmg)
            body_parts = {"chest": "躯干", "head": "头部", "arms": "双臂", "legs": "双腿"}
            part = body_parts.get("chest", "躯干")
            self._act_log.add(f"凯恩 挥剑砍中了 {target.name} 的{part}，{target.name} 发出一声惨叫")
            if target.hp <= 0:
                self._act_log.add(f"{target.name} 倒在地上，不再动弹")
        else:
            reduce_tenacity(target, roll)
            self._act_log.add(f"凯恩 挥剑砍向 {target.name}，但被躲开了")
            if target.tenacity == 0 and "incapacitated" not in target.statuses:
                target.statuses.append("incapacitated")
                self._act_log.add(f"{target.name} 被击破防御，陷入失能!")
        if self._state.player.ap <= 0:
            self._next_turn()
        self.refresh_all()

    def _npc_turn(self, npc: Creature) -> None:
        pc, pr = self._state.player_pos
        npc_pos = None
        for c, (ec, er) in self._state.entities:
            if c is npc:
                npc_pos = (ec, er)
                break
        if npc_pos is None:
            self._next_turn()
            return
        nc, nr = npc_pos
        enemy_count = 1 if abs(nc - pc) <= 8 else 0
        ally_count = sum(1 for c, _ in self._state.entities
                         if c.faction == "hostile" and c.hp > 0 and c is not npc)
        power = npc.hp / max(npc.max_hp, 1)
        power_ratio = power * (ally_count + 1) / max(enemy_count, 1)
        action, _ = _ai_engine.decide(npc, enemy_count, ally_count, power_ratio)

        if action in ("flee", "surrender"):
            self._act_log.add(f"{npc.name} 惊慌地逃跑了!")
            self._state.remove_entity(npc)
        elif action in ("attack", "advance"):
            if abs(nc - pc) <= 1 and abs(nr - pr) <= 1:
                dmg = max(1, roll_d20() // 4)
                self._state.player.hp = max(0, self._state.player.hp - dmg)
                self._act_log.add(f"{npc.name} 挥动武器击中了凯恩!")
                if self._state.player.hp <= 0:
                    self._act_log.add("凯恩 被击倒了! [按 R 长休恢复]")
            else:
                dc = 1 if pc > nc else (-1 if pc < nc else 0)
                dr = 1 if pr > nr else (-1 if pr < nr else 0)
                tnc, tnr = nc + dc, nr + dr
                if self._state.move_entity(npc, nc, nr, tnc, tnr):
                    self._act_log.add(f"{npc.name} 向前逼近")
        else:
            self._act_log.add(f"{npc.name} 警惕地盯着凯恩")
        self._next_turn()
        self.refresh_all()

    # ── Rest ──

    def action_short_rest(self) -> None:
        if self._state.in_combat:
            self._act_log.add("战斗中无法休息")
            return
        result = short_rest(self._state.player, self._state.clock,
                            self._state.map, self._state.player_pos)
        self._act_log.add(f"凯恩 坐下来休息了一会 (HP+{result['hp_restored']} MP+{result['mp_restored']})")
        self.refresh_all()

    # ── Save/Load ──

    def action_quick_save(self) -> None:
        self._save_data = {
            "player_hp": self._state.player.hp,
            "player_mp": self._state.player.mp,
            "player_pos": self._state.player_pos,
            "current_map": self._state.current_map,
        }
        self._act_log.add("[快速存档] 已保存")

    def action_quick_load(self) -> None:
        if not self._save_data:
            self._act_log.add("没有存档数据")
            return
        d = self._save_data
        self._state.player.hp = d["player_hp"]
        self._state.player.mp = d["player_mp"]
        self._state.player_pos = d["player_pos"]
        if d["current_map"] != self._state.current_map:
            _load_map(self._state, d["current_map"])
        self._end_combat()
        _update_fov(self._state)
        self._act_log.add("[快速读档] 已恢复")
        self.refresh_all()
