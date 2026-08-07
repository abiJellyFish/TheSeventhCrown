"""Textual MVP App —— 完整游戏原型。

启动: python main.py
"""

import random
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive

from core.game_state import GameState
from core.entity import Player, Creature
from core.movement import Terrain
from core.grid import Grid
from core.combat.initiative import roll_initiative
from core.combat.attack import hit_check, roll_damage, reduce_tenacity, AutoHitAttack, apply_damage_type_modifiers
from core.combat.death import DeathSaves
from core.dice import roll_d20
from core.ai.engine import BehaviorEngine
from core.ai.discretize import discretize_state
from core.rest import short_rest, long_rest
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


def _load_map(state: GameState, map_name: str) -> None:
    """加载地图到 GameState。"""
    data = _loader.load_json(f"maps/{map_name}")
    state.current_map = map_name
    state.map = Grid[Terrain](data["width"], data["height"], Terrain.PASSABLE)

    # 地形
    for c, r in data.get("terrain", {}).get("walls", []):
        state.map[c, r] = Terrain.WALL
    for c, r in data.get("terrain", {}).get("water", []):
        state.map[c, r] = Terrain.DIFFICULT
    for c, r in data.get("terrain", {}).get("difficult", []):
        state.map[c, r] = Terrain.DIFFICULT

    # 实体
    state.entities = []
    for ent_data in data.get("entities", []):
        c = _loader.load_creature(ent_data["key"])
        if c:
            c.template_name = ent_data["key"]
            state.add_entity(c, tuple(ent_data["pos"]))

    # 出口
    state.map_exits = data.get("exits", [])
    state.loot_spots = data.get("loot_spots", [])


def _generate_plains(state: GameState) -> None:
    """生成平原区域（程序化）。"""
    w, h = 40, 30
    state.current_map = "plains"
    state.map = Grid[Terrain](w, h, Terrain.PASSABLE)

    # 随机灌木丛和树木
    random.seed(42)
    for _ in range(30):
        c, r = random.randint(0, w - 1), random.randint(0, h - 1)
        if random.random() < 0.6:
            state.map[c, r] = Terrain.DIFFICULT  # 灌木丛

    # 随机动物
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


# ═══════════════════════════════════════════════════
# Widgets
# ═══════════════════════════════════════════════════

class MapView(Static):
    """ASCII 地图渲染。"""
    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return "Loading..."
        gmap = self.state.map
        pc, pr = self.state.player_pos
        vw, vh = 50, 22

        # 视口跟随玩家
        ox = max(0, min(pc - vw // 2, gmap.width - vw))
        oy = max(0, min(pr - vh // 2, gmap.height - vh))
        ox = max(0, ox)
        oy = max(0, oy)

        lines = []
        for row in range(oy, min(oy + vh, gmap.height)):
            line_chars = []
            for col in range(ox, min(ox + vw, gmap.width)):
                # 实体
                ent = self.state.get_entity_at(col, row)
                if ent is not None:
                    ch = ent.name[0]
                    if not ent.is_alive if hasattr(ent, 'is_alive') else ent.hp > 0:
                        if ent.hp <= 0:
                            ch = "%"  # corpse marker
                    if ent.faction == "hostile":
                        line_chars.append(f"[red]{ch}[/]")
                    elif ent.faction == "friendly":
                        line_chars.append(f"[green]{ch}[/]")
                    else:
                        line_chars.append(f"[yellow]{ch}[/]")
                elif (col, row) == (pc, pr):
                    line_chars.append("[bold bright_cyan]@[/]")
                else:
                    t = gmap[col, row]
                    if t == Terrain.WALL:
                        line_chars.append("[grey]#[/]")
                    elif t == Terrain.DIFFICULT:
                        line_chars.append("[dim green]\"[/]")
                    else:
                        line_chars.append("[dim]. [/]")
            lines.append("".join(line_chars))

        # 标题栏
        title = f" {self.state.current_map} "
        if self.state.in_combat:
            title += "[red][COMBAT][/]"
        lines.insert(0, f"[bold]{title}[/]")
        return "\n".join(lines)


class StatusPanel(Static):
    """角色状态。"""
    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return ""
        p = self.state.player
        lines = [
            f"[bold]{p.name}[/] [dim]{p.char_class}[/]",
            f"HP: [green]{p.hp}/{p.max_hp}[/]  MP: [blue]{p.mp}/{p.max_mp}[/]",
            f"TEN: [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC: {p.total_ac('chest')}  SPD: {p.speed}",
        ]
        if self.state.in_combat and self.state.combat_turn_entity:
            e = self.state.combat_turn_entity
            turn_name = e.name if e != p else "你"
            lines.append(f"[bold red]回合: {turn_name}[/]")
        if p.statuses:
            lines.append(f"[red]{' '.join(p.statuses)}[/]")
        return "\n".join(lines)


class LogPanel(Static):
    """日志。"""
    messages: list[str] = []

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 200:
            self.messages = self.messages[-100:]
        self.refresh()

    def render(self) -> str:
        recent = self.messages[-10:] or ["..."]
        return "\n".join(f"[dim]{m}[/]" for m in recent)


# ═══════════════════════════════════════════════════
# App
# ═══════════════════════════════════════════════════

class MVPApp(App):
    """MVP 游戏。"""

    CSS = """
    Horizontal { height: 100%; }
    MapView { width: 65%; height: 100%; border: solid grey; content-align: left top; }
    #right { width: 35%; height: 100%; }
    StatusPanel { height: 35%; border: solid grey; }
    LogPanel { height: 65%; border: solid grey; }
    """

    BINDINGS = [
        ("q", "quit", "退出"),
        ("up,w", "move_up", "上"),
        ("down,s", "move_down", "下"),
        ("left,a", "move_left", "左"),
        ("right,d", "move_right", "右"),
        ("tab", "combat_action", "战斗/交互"),
        ("r", "rest_action", "休息"),
        ("f5", "quick_save", "快速存档"),
        ("f9", "quick_load", "快速读档"),
    ]

    def __init__(self):
        super().__init__()
        self._state: GameState | None = None
        self._log: LogPanel | None = None
        self._map_view: MapView | None = None
        self._status: StatusPanel | None = None

    # ── Init ──

    def _create_game(self) -> None:
        """创建新游戏。"""
        import random
        stats = {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}
        # 随机两项为 10
        boosted = random.sample(["str", "dex", "con", "int", "wis", "cha"], 2)
        for s in boosted:
            stats[s] = 10

        player = Player.create_fighter(name="凯恩", stats=stats)
        self._state = GameState(player=player, map_width=30, map_height=20)
        _load_map(self._state, "village")
        self._state.player_pos = (10, 10)

        # 初始装备
        import core.entity as ent
        sword_data = {"name": "长剑", "weapon_type": "melee", "category": "martial",
                       "damage": "1d8", "damage_type": "slashing", "attack_stat": "str",
                       "ap_cost": 3, "properties": ["versatile(1d10)"], "weight": 2.0}
        self._state.player.equipment["right_hand"] = ent.Weapon.from_dict(sword_data)

        self._log.add("=== 欢迎来到 MVP 原型 ===")
        self._log.add("村庄长老需要你前往地城取回红宝石")
        self._log.add("[方向键/WASD] 移动  [Tab] 攻击/交互  [R] 休息  [Q] 退出")

    def compose(self) -> ComposeResult:
        self._create_game()
        yield Header()
        with Horizontal():
            self._map_view = MapView()
            self._map_view.state = self._state
            yield self._map_view
            with Vertical(id="right"):
                self._status = StatusPanel()
                self._status.state = self._state
                yield self._status
                self._log = LogPanel()
                yield self._log
        yield Footer()

    def refresh_all(self) -> None:
        self._map_view.refresh()
        self._status.refresh()
        self._log.refresh()

    # ── Movement ──

    def _move_player(self, dc: int, dr: int) -> None:
        if self._state.in_combat and self._state.player.ap <= 0:
            self._log.add("AP 不足，无法移动")
            return

        col, row = self._state.player_pos
        nc, nr = col + dc, row + dr

        # 地图出口检测
        for ext in self._state.map_exits:
            if (nc, nr) == tuple(ext["at"]):
                dest = ext["to"]
                if dest == "plains":
                    _generate_plains(self._state)
                else:
                    _load_map(self._state, dest)
                self._state.player_pos = (5, 5)
                self._log.add(f"进入: {dest}")
                self._end_combat()
                self.refresh_all()
                return

        result = self._state.move_player(nc, nr)
        if result:
            if self._state.in_combat:
                self._state.player.ap -= 1
            self._check_map_edge()
            self.refresh_all()
        else:
            self._log.add("无法通过")

    def _check_map_edge(self) -> None:
        """检查是否在地图边缘。"""
        pc, pr = self._state.player_pos
        w, h = self._state.map.width, self._state.map.height
        if pc <= 0 or pc >= w - 1 or pr <= 0 or pr >= h - 1:
            pass  # 边缘出口由 _move_player 中的 exit 检测处理

    def action_move_up(self): self._move_player(0, -1)
    def action_move_down(self): self._move_player(0, 1)
    def action_move_left(self): self._move_player(-1, 0)
    def action_move_right(self): self._move_player(1, 0)

    # ── Combat ──

    def action_combat_action(self) -> None:
        """Tab: 进入战斗模式 / 在战斗中攻击 / 交互 NPC。"""
        if not self._state.in_combat:
            # 检查玩家相邻格是否有敌对生物
            pc, pr = self._state.player_pos
            for creature, (ec, er) in self._state.entities:
                if creature.faction != "hostile" or creature.hp <= 0:
                    continue
                if abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                    # 找到相邻敌人，开始战斗
                    self._start_combat(creature)
                    return

            # 检查是否有友好 NPC 相邻
            for creature, (ec, er) in self._state.entities:
                if creature.faction != "friendly" or creature.hp <= 0:
                    continue
                if abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                    self._log.add(f"与 {creature.name} 交谈（交互功能待扩展）")
                    return

            self._log.add("附近没有可攻击的敌人或可交互的 NPC")
        else:
            # 战斗中：执行攻击
            self._player_attack()

    def _start_combat(self, target: Creature) -> None:
        """进入战斗模式。"""
        self._state.in_combat = True
        self._state.player.ap = self._state.player.max_ap

        # 收集参战生物
        combatants = [self._state.player]
        for creature, (ec, er) in self._state.entities:
            if creature.hp > 0 and creature.faction == "hostile":
                pc, pr = self._state.player_pos
                if abs(ec - pc) <= 5:  # 5 格内的敌人都参战
                    combatants.append(creature)
                    creature.ap = creature.max_ap

        self._state.combat_initiative = roll_initiative(combatants)
        self._state.combat_turn_index = 0
        self._state.combat_turn_entity = self._state.combat_initiative[0]

        self._log.add(f"=== 战斗开始! vs {target.name} ===")
        self._next_turn()

    def _end_combat(self) -> None:
        self._state.in_combat = False
        self._state.combat_initiative = []
        self._state.combat_turn_entity = None
        self._state.player.ap = self._state.player.max_ap
        self._log.add("=== 战斗结束 ===")

    def _next_turn(self) -> None:
        """推进到下一个回合。"""
        if not self._state.in_combat:
            return

        # 移除已死亡的生物
        alive = [e for e in self._state.combat_initiative
                 if e is self._state.player or e.hp > 0]

        # 检查是否还有敌对生物
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
        turn_entity.ap = turn_entity.max_ap  # 新回合恢复 AP

        if turn_entity is self._state.player:
            self._log.add(">>> 你的回合 <<<")
        else:
            # NPC 回合
            self._npc_turn(turn_entity)

        self.refresh_all()

    def _player_attack(self) -> None:
        """玩家攻击最近的敌人。"""
        pc, pr = self._state.player_pos
        weapon = self._state.player.equipment.get("right_hand")
        if weapon is None:
            self._log.add("未装备武器!")
            return
        if self._state.player.ap < weapon.ap_cost:
            self._log.add(f"AP 不足 (需要 {weapon.ap_cost})")
            return

        # 找相邻敌人
        target = None
        for creature, (ec, er) in self._state.entities:
            if creature.faction != "hostile" or creature.hp <= 0:
                continue
            if abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                target = creature
                break

        if target is None:
            self._log.add("没有相邻的敌人!")
            return

        self._state.player.ap -= weapon.ap_cost
        hit, roll = hit_check(self._state.player, target, weapon)
        if hit:
            dmg = roll_damage(weapon, self._state.player, critical=(roll == 20))
            dmg = apply_damage_type_modifiers(dmg, weapon.damage_type, target)
            target.hp = max(0, target.hp - dmg)
            self._log.add(f"命中 {target.name}! 造成 {dmg} 伤害 (HP:{target.hp})")
            if target.hp <= 0:
                self._log.add(f"{target.name} 被击败!")
                self._log.add(f"按 [Tab] 搜刮尸体")
        else:
            reduce_tenacity(target, roll)
            self._log.add(f"未命中 {target.name} (roll:{roll}) TEN:{target.tenacity}")
            if target.tenacity == 0 and "incapacitated" not in target.statuses:
                target.statuses.append("incapacitated")
                self._log.add(f"{target.name} 韧性击破! 陷入失能")

        if self._state.player.ap <= 0:
            self._next_turn()
        self.refresh_all()

    def _npc_turn(self, npc: Creature) -> None:
        """NPC AI 回合。"""
        pc, pr = self._state.player_pos
        # 找 NPC 位置
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

        action, score = _ai_engine.decide(npc, enemy_count, ally_count, power_ratio)

        if action == "flee" or action == "surrender":
            self._log.add(f"{npc.name} 尝试逃离!")
            self._state.remove_entity(npc)
        elif action == "attack" or action == "advance":
            # 向玩家移动或攻击
            dc = 1 if pc > nc else (-1 if pc < nc else 0)
            dr = 1 if pr > nr else (-1 if pr < nr else 0)
            tnc, tnr = nc + dc, nr + dr
            if abs(nc - pc) <= 1 and abs(nr - pr) <= 1:
                # 相邻，攻击
                dmg = max(1, roll_d20() // 4)
                self._state.player.hp = max(0, self._state.player.hp - dmg)
                self._log.add(f"{npc.name} 攻击你! 造成 {dmg} 伤害 (HP:{self._state.player.hp})")
            elif self._state.move_entity(npc, nc, nr, tnc, tnr):
                self._log.add(f"{npc.name} 靠近")
            else:
                self._log.add(f"{npc.name} 移动被阻挡")
        else:
            self._log.add(f"{npc.name} 待机")

        if self._state.player.hp <= 0:
            self._log.add("[red]你被击败了![/] [按 R 长休恢复]")

        self._next_turn()
        self.refresh_all()

    # ── Rest ──

    def action_rest_action(self) -> None:
        if self._state.in_combat:
            self._log.add("战斗中无法休息")
            return
        result = short_rest(self._state.player, self._state.clock,
                            self._state.map, self._state.player_pos)
        self._log.add(f"短休: HP+{result['hp_restored']} MP+{result['mp_restored']}")
        self.refresh_all()

    # ── Save/Load ──

    def action_quick_save(self) -> None:
        self._log.add("[快速存档] MVP 阶段: 状态已暂存到内存")
        self._save_data = {
            "player_hp": self._state.player.hp,
            "player_mp": self._state.player.mp,
            "player_pos": self._state.player_pos,
            "current_map": self._state.current_map,
        }

    def action_quick_load(self) -> None:
        if hasattr(self, "_save_data") and self._save_data:
            d = self._save_data
            self._state.player.hp = d["player_hp"]
            self._state.player.mp = d["player_mp"]
            self._state.player_pos = d["player_pos"]
            if d["current_map"] != self._state.current_map:
                _load_map(self._state, d["current_map"])
            self._end_combat()
            self._log.add("[快速读档] 已恢复")
            self.refresh_all()
        else:
            self._log.add("没有存档数据")
