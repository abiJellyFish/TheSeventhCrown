"""Textual MVP App — 完整游戏原型。"""

import random
from textual.app import App, ComposeResult
from textual.widgets import Static, Input
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from textual.events import Key
from rich.text import Text


class GameInput(Input):
    """Input 子类：X 键不消费，阻止输入模式下触发观察模式。"""

    def _on_key(self, event: Key) -> None:
        if event.key == "X":
            event.stop()
            return
        super()._on_key(event)

from core.game_state import GameState
from core.entity import Player, Creature, Weapon
from core.movement import Terrain
from core.grid import Grid
from core.fov import LightLevel, compute_fov
from core.combat.initiative import roll_initiative
from core.combat.attack import hit_check, roll_damage, reduce_tenacity, apply_damage_type_modifiers, parse_dice, roll_dice
from core.dice import roll_d20
from core.ai.engine import BehaviorEngine
from core.rest import short_rest, long_rest
from core.loader import DataLoader
from core.save.database import SaveManager
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
SAVE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "saves")
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
    """添加物品到背包，同名称同类型物品堆叠计数。"""
    for existing in player.inventory:
        if existing.name == item.name and existing.item_type == item.item_type:
            existing.count += item.count
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

    # ── 地精营地 (开放式，偏移 68,10, 树林东侧) ──
    gx, gy = 68, 10
    # 断墙/路障 — 不是封闭房子，而是几段不连通的矮墙
    camp_walls = [
        # 北侧路障（有缺口）
        (0,0),(1,0),(2,0),(3,0),(4,0),           (6,0),(7,0),
        # 东侧断墙
        (7,1),(7,2),
        # 西侧路障
        (0,1),(0,2),(0,3),
        # 南侧散落木桩
        (4,5),(5,5),(7,5),
        # 角落杂物堆
        (0,4),(1,4),
    ]
    for wx, wy in camp_walls:
        state.map[gx + wx, gy + wy] = Terrain.WALL
    # 篝火（营地中央）
    state.map[gx + 3, gy + 3] = Terrain.DIFFICULT

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
    # 固定区域：村庄 (3,20)-(23,35) / 树林 (35,15)-(65,45) / 营地 (68,10)-(78,25)
    RESERVED_ZONES = [
        (vx, vy, 21, 16),   # 村庄
        (fx, fy, 30, 30),   # 树林
        (gx, gy, 9, 15),    # 营地
    ]
    def _in_reserved(px: int, py: int) -> bool:
        for rx, ry, rw, rh in RESERVED_ZONES:
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return True
        return False

    creatures = ["bird", "squirrel", "cat", "long_ear_dog", "wild_boar"]
    for _ in range(15):
        key = random.choice(creatures)
        c = _loader.load_creature(key)
        if c:
            c.template_name = key
            for _ in range(20):
                px = random.randint(0, w - 1)
                py = random.randint(0, h - 1)
                if state.map[px, py] == Terrain.PASSABLE and not _in_reserved(px, py):
                    state.add_entity(c, (px, py))
                    break

    # ── 平原灌木 ──
    for _ in range(60):
        for _ in range(20):
            bx = random.randint(0, w - 1)
            by = random.randint(0, h - 1)
            if state.map[bx, by] == Terrain.PASSABLE and not _in_reserved(bx, by):
                state.map[bx, by] = Terrain.DIFFICULT
                break

    state.map_exits = []
    state.loot_spots = []

    # 位置 → 地名哈希表（O(1) 查询，无分支）
    state.location_map = {}
    for x in range(vx, vx + 21):
        for y in range(vy, vy + 16):
            state.location_map[(x, y)] = "小村庄"
    for x in range(fx, fx + 30):
        for y in range(fy, fy + 30):
            state.location_map.setdefault((x, y), "树林")
    for x in range(gx, gx + 9):
        for y in range(gy, gy + 15):
            state.location_map[(x, y)] = "营地"


def _build_dungeon(state: GameState) -> None:
    """BSP 生成地下城 (30×20)。"""
    w, h = 30, 20
    state.current_map = "地下城"
    state.map = Grid[Terrain](w, h, Terrain.WALL)
    state.entities = []
    state.bed_positions = set()
    state.door_states = {}
    state.map_exits = []
    state.location_map = {}  # 地下城全部标记为地下城1层

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

    @staticmethod
    def _get_location(s) -> str:
        """O(1) 哈希表查询，无分支。"""
        if s.in_dungeon:
            return "地下城1层"
        return s.location_map.get(s.player_pos, "平原")

    def render(self) -> str:
        if self.state is None: return ""
        s = self.state
        width = self.size.width
        pc = s.clock.pendulum_count
        day = (pc // PENDULUMS_PER_DAY) % 10 + 1
        month = (pc // PENDULUMS_PER_MONTH) % 5 + 1
        year = pc // PENDULUMS_PER_YEAR + 1
        current_pc = pc % PENDULUMS_PER_DAY  # 每天 5000 钟摆后清零

        map_name = s.current_map or "???"
        location = self._get_location(s)
        left = f" [bold]{map_name}[/] {location}  晴"

        right = f"{current_pc}钟摆 第{day}天 {month}月 {year}纪年 "

        def visible_len(t: str) -> int:
            return Text.from_markup(t).cell_len

        if s.in_combat and s.combat_initiative:
            # 存活参战者，当前回合生物前后各 2 个，超出用 +N 省略
            alive = [e for e in s.combat_initiative if e.hp > 0 or e is s.player]
            if not alive:
                pad = max(1, width - visible_len(left) - visible_len(right) - 2)
                return f"{left}{' ' * pad}{right}"
            current_idx = 0
            for i, e in enumerate(alive):
                if e is s.combat_turn_entity:
                    current_idx = i; break
            total = len(alive)
            if total <= 5:
                indices = list(range(total))
                prefix = ""
                suffix = ""
            else:
                start = max(0, current_idx - 2)
                end = min(total, current_idx + 3)
                indices = list(range(start, end))
                prefix = f"+{start} " if start > 0 else ""
                suffix = f" +{total - end}" if end < total else ""
            names = []
            for i in indices:
                e = alive[i]
                nm = e.name
                if e is s.combat_turn_entity:
                    nm = f"[bold yellow]{nm}[/]"
                names.append(nm)
            center = f"{prefix}{' > '.join(names)}{suffix}"
            # 确保右侧始终固定在屏幕右端，center 溢出时截断
            right_len = visible_len(right)
            left_len = visible_len(left)
            center_len = visible_len(center)
            if left_len + center_len + right_len > width:
                available = width - left_len - right_len
                if available < 4:
                    center = ""
                elif center_len > available:
                    # 用 Rich Text 安全截断，不破坏 markup 标签
                    t = Text.from_markup(center)
                    t.truncate(available, overflow="ellipsis")
                    center = t.markup
            center_len = visible_len(center)
            used = left_len + center_len + right_len
            remaining = max(0, width - used)
            pad_left = remaining // 2
            pad_right = remaining - pad_left
            return f"{left}{' ' * pad_left}{center}{' ' * pad_right}{right}"
        else:
            # 右侧始终完整显示，不截断
            pad = max(1, width - visible_len(left) - visible_len(right))
            return f"{left}{' ' * pad}{right}"


class LeftPanel(Static):
    state: GameState | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._action_map: dict[int, tuple] = {}
        self._maneuver_map: dict[int, dict] = {}
        self._special_map: dict[int, str] = {}

    def render(self) -> str:
        if self.state is None:
            return ""
        phase = self.state.combat_phase
        # 攻击流程子面板 — 探索/战斗模式共用
        if phase == "select_action":
            return self._render_action_panel()
        elif phase == "select_target":
            return self._render_target_panel()
        elif phase == "select_maneuver":
            return self._render_maneuver_panel()
        elif phase == "select_special":
            return self._render_special_panel()
        # 探索 vs 战斗默认面板
        if self.state.in_combat:
            return self._render_combat_default()
        else:
            return self._render_explore_default()

    def _render_explore_default(self) -> str:
        return "\n".join([
            "[[0]]交互 [[1]]探查  [[2]]躲藏 [[3]]协助",
            "[[4]]跳跃 [[5]]撤离  [[6]]回避 [[7]]推撞",
            "[[8]]擒抱 [[ / ]]击晕  [[g]]慢速 [[G]]疾走",
            "[[r]]短休 [[R]]长休  [[,]]消磨 [[A]]攻击",
            "[[S]]法术",
        ])

    def _render_combat_default(self) -> str:
        p = self.state.player
        filled = int(p.ap / max(p.max_ap, 1) * 10)
        lines = [
            f"AP [{'|'*filled}{'.'*(10-filled)}]",
            "S-Tab 结束战斗轮",
            "[[0]]交互 [[1]]探查  [[2]]躲藏 [[3]]协助",
            "[[4]]跳跃 [[5]]撤离  [[6]]回避 [[7]]推撞",
            "[[8]]擒抱 [[ / ]]击晕  [[g]]慢速 [[G]]疾走",
            "[[r]]短休 [[R]]长休  [[,]]消磨 [[A]]攻击",
            "[[S]]法术",
        ]
        return "\n".join(lines)

    def _render_action_panel(self) -> str:
        p = self.state.player
        left = p.equipment.get("left_hand")
        right = p.equipment.get("right_hand")
        self._action_map = {}

        lines = ["── 选择攻击方式 ──"]
        idx = 1

        if left:
            if hasattr(left, 'weapon_type'):
                self._action_map[idx] = ("left_hand", left)
                lines.append(f"[[A{idx}]]左手武器  {left.name} {left.damage} {left.damage_type} AP:{left.ap_cost}")
            else:
                self._action_map[idx] = ("left_hand_blocked", left)
                lines.append(f"[[A{idx}]]左手武器  {left.name} (不能攻击)")
            idx += 1
        if right:
            if hasattr(right, 'weapon_type'):
                self._action_map[idx] = ("right_hand", right)
                lines.append(f"[[A{idx}]]右手武器  {right.name} {right.damage} {right.damage_type} AP:{right.ap_cost}")
            else:
                self._action_map[idx] = ("right_hand_blocked", right)
                lines.append(f"[[A{idx}]]右手武器  {right.name} (不能攻击)")
            idx += 1
        if left and hasattr(left, 'weapon_type') and right and hasattr(right, 'weapon_type'):
            self._action_map[idx] = ("dual_wield", right)
            lines.append(f"[[A{idx}]]双持武器  {left.name}+{right.name} AP:3")
            idx += 1
        if right and hasattr(right, 'weapon_type') and right.weapon_type == "melee":
            self._action_map[idx] = ("two_hand", right)
            lines.append(f"[[A{idx}]]双手并用  {right.name} 命中+1 伤害+2 AP:{right.ap_cost}")
            idx += 1

        self._action_map[0] = ("cancel", None)
        lines.append("[[A0]]取消")
        return "\n".join(lines)

    def _render_target_panel(self) -> str:
        pa = self.state.pending_attack or {}
        weapon = pa.get("weapon")
        pc, pr = self.state.player_pos

        weapon_name = weapon.name if weapon else "武器"
        lines = ["── 选择目标 ──",
                 f"{weapon_name} → 选择目标:"]

        targets = []
        for creature, (ec, er) in self.state.entities:
            if creature is not self.state.player and creature.hp > 0 \
               and abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                dist = max(abs(ec - pc), abs(er - pr))
                targets.append((dist, creature.hp, creature))
        targets.sort(key=lambda x: (x[0], x[1]))

        for i, (_, _, c) in enumerate(targets[:8]):
            faction_tag = {"hostile": "[red]敌对[/]", "friendly": "[green]友好[/]",
                           "neutral": "[yellow]中立[/]"}.get(c.faction, c.faction)
            lines.append(f"[[T{i+1}]]{c.name} {faction_tag} (HP {c.hp}, AC {c.total_ac('chest')})")
        if len(targets) > 8:
            lines.append(f"... 还有 {len(targets)-8} 个目标")
        lines.append("[[T0]]取消")
        return "\n".join(lines)

    def _render_maneuver_panel(self) -> str:
        pa = self.state.pending_attack or {}
        target = pa.get("target")
        attack_roll = pa.get("attack_roll", 0)
        weapon = pa.get("weapon")

        target_name = target.name if target else "目标"
        target_ac = target.total_ac('chest') if target else 0

        # 从 game_state 读取战技数据
        maneuvers = getattr(self.state, 'maneuvers', [])
        self._maneuver_map = {}
        lines = ["── 命中! 选择战技 ──",
                 f"{weapon.name if weapon else '武器'}击中{target_name} (roll={attack_roll} vs AC={target_ac})"]
        for i, m in enumerate(maneuvers, 1):
            self._maneuver_map[i] = m
            desc = m.get('effect', '')
            if desc == 'damage_bonus': desc_text = f'伤害+{m["value"]}'
            elif desc == 'disarm': desc_text = '目标力量豁免失败则武器掉落'
            elif desc == 'knockdown': desc_text = '目标敏捷豁免失败则倒地'
            else: desc_text = desc
            lines.append(f"[[A{i}]]{m['name']}  AP+{m['ap_extra']}  {desc_text}")
        self._maneuver_map[0] = None
        lines.append("[[A0]]直接攻击  不消耗额外AP，正常结算伤害")
        return "\n".join(lines)

    def _render_special_panel(self) -> str:
        pa = self.state.pending_attack or {}
        target = pa.get("target")
        attack_roll = pa.get("attack_roll", 0)
        weapon = pa.get("weapon")
        p = self.state.player

        target_name = target.name if target else "目标"
        target_ac = target.total_ac('chest') if target else 0

        specials = [
            {"key": "reroll", "name": "奋力一击", "ap_cost": 2, "desc": "额外消耗 2AP，重掷攻击骰"},
            {"key": "feint",  "name": "虚晃一招", "ap_cost": 1, "desc": "消耗 1AP，下次攻击命中+2"},
            {"key": "taunt",  "name": "挑衅",     "ap_cost": 1, "desc": "消耗 1AP，目标下回合更容易攻击你"},
        ]
        self._special_map = {}
        lines = ["── 未命中 ──",
                 f"{weapon.name if weapon else '武器'}挥空{target_name} (roll={attack_roll} vs AC={target_ac})"]
        for i, s in enumerate(specials, 1):
            self._special_map[i] = s["key"]
            ap_note = " [dim]AP不足[/]" if p.ap < s["ap_cost"] else ""
            lines.append(f"[[A{i}]]{s['name']}  {s['desc']}{ap_note}")
        self._special_map[0] = "tenacity"
        lines.append("[[A0]]削韧      不消耗AP，削减目标韧性")
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
        # 单字符渲染，视口宽度翻倍补偿
        vw = min((r + 2) * 2, gmap.width)
        vh = min(r * 2 + 1, gmap.height)
        ox = max(0, min(pc - vw // 2, gmap.width - vw))
        oy = max(0, min(pr - vh // 2, gmap.height - vh))

        # 观察模式：视口扩展确保光标可见
        obs_cur = self.state.observe_cursor if self.state.observe_mode else None
        if obs_cur is not None:
            oc, oro = obs_cur
            ox = min(ox, oc)
            oy = min(oy, oro)
            ox = max(ox, oc - vw + 1)
            oy = max(oy, oro - vh + 1)
            ox = max(0, min(ox, gmap.width - vw))
            oy = max(0, min(oy, gmap.height - vh))

        text = Text()
        for row in range(oy, min(oy + vh, gmap.height)):
            for col in range(ox, min(ox + vw, gmap.width)):
                if (col, row) not in fov:
                    text.append(" ")
                    continue
                cur = " reverse" if (col, row) == obs_cur else ""
                ent = self.state.get_entity_at(col, row)
                if ent is not None:
                    ch = "%" if ent.hp <= 0 else ent.char
                    color = FACTION_COLORS.get(ent.faction, "")
                    text.append(ch, style=f"bold {color}{cur}" if ent.faction == "hostile" else f"{color}{cur}")
                elif (col, row) == (pc, pr):
                    text.append("@", style=f"bold bright_cyan{cur}")
                elif (col, row) in self.state.bed_positions:
                    text.append("=", style=f"bold cyan{cur}")
                elif self.state.dungeon_entrance and (col, row) == self.state.dungeon_entrance:
                    text.append(">", style=f"bold magenta{cur}")
                else:
                    t = gmap[col, row]
                    if (col, row) in self.state.door_states:
                        is_open = self.state.door_states[(col, row)]
                        ch = "_" if is_open else "]"
                        text.append(ch, style=f"bold yellow{cur}")
                    else:
                        ch = {Terrain.WALL: "#", Terrain.DIFFICULT: '"', Terrain.PASSABLE: "."}[t]
                        text.append(ch, style=f"{TERRAIN_COLORS.get(t, '')}{cur}")
            if row < min(oy + vh, gmap.height) - 1:
                text.append("\n")
        text.append("\n")
        # 图例 — FOV 内动态生成
        legend_seen: dict[str, str] = {"@": "玩家"}
        for creature, (ec, er) in self.state.entities:
            if (ec, er) in fov and creature.hp > 0:
                legend_seen[creature.char] = creature.name
        terrain_map = {Terrain.WALL: "#", Terrain.DIFFICULT: '"', Terrain.PASSABLE: "."}
        terrain_labels = {"#": "墙壁", '"': "灌木", ".": "草地"}
        for pos in fov:
            t = gmap[pos]
            ch = terrain_map.get(t)
            if ch:
                legend_seen.setdefault(ch, terrain_labels[ch])
            if pos in self.state.bed_positions:
                legend_seen["="] = "床"
            if pos in self.state.door_states:
                legend_seen["]"] = "门"
            if self.state.dungeon_entrance and pos == self.state.dungeon_entrance:
                legend_seen[">"] = "入口"
        player_part = "@玩家"
        others = " ".join(f"{ch}{name}" for ch, name in legend_seen.items() if ch != "@")
        text.append(f"{player_part} {others}".strip(), style="dim")
        return text


class RightPanel(Static):
    state: GameState | None = None
    view_mode: str = "default"  # "default" | "inventory" | "character"

    def render(self) -> str:
        if self.state is None: return ""
        if self.state.observe_mode:
            return self._render_observe()
        if self.view_mode == "inventory":
            return self._render_inventory()
        elif self.view_mode == "character":
            return self._render_character()
        return self._render_default()

    def _render_default(self) -> str:
        p = self.state.player
        slow_tag = " [dim]慢速[/]" if self.state.slow_mode else ""
        lines = [
            f"[bold]{p.name}[/]  人类 Lv.1 {p.char_class}{slow_tag}",
            f"HP [green]{p.hp}/{p.max_hp}[/]  MP [blue]{p.mp}/{p.max_mp}[/]  TEN [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC 头部{p.total_ac('head')} 躯干{p.total_ac('chest')} 双臂{p.total_ac('arms')} 双腿{p.total_ac('legs')}",
            f"SPD {p.speed}  INIT +{p.initiative_bonus()}",
            "",
            "[[X]]观察 [[Q]]退出",
            "[[C]]角色面板 [[I]]物品栏 [[B]]法术书",
            "[[Z]]制作 [[K]]烹饪 [[Y]]炼药",
            "[[H]]高度 [[M]]地图 [[E]]系统",
        ]
        if p.statuses:
            lines.append(f"[red]{' '.join(p.statuses)}[/]")
        return "\n".join(lines)

    def _render_inventory(self) -> str:
        p = self.state.player
        max_h = self.size.height
        lines = [
            f"[bold]物品栏[/] [dim]I/Esc返回  输入 :I序号 使用[/]",
            f"金币: {p.gp}GP",
            "── 装备 ──",
        ]
        body = [("head","头部"),("chest","躯干"),("arms","双臂"),("legs","双腿")]
        hands = [("left_hand","左手"),("right_hand","右手")]
        accs = [("accessory1","饰品1"),("accessory2","饰品2"),("accessory3","饰品3")]
        lines.append("  " + " ".join(f"{l}:{p.equipment.get(s).name if p.equipment.get(s) else '-'}" for s,l in body))
        lines.append("  " + " ".join(f"{l}:{p.equipment.get(s).name if p.equipment.get(s) else '-'}" for s,l in hands))
        lines.append("  " + " ".join(f"{l}:{p.equipment.get(s).name if p.equipment.get(s) else '-'}" for s,l in accs))
        lines.append("── 背包 ──")
        if p.inventory:
            item_lines = []
            for i, item in enumerate(p.inventory):
                item_lines.append(f"  [{i+1}] {item.name} x{item.count}")
                if item.description:
                    item_lines.append(f"      {item.description[:20]}")
            available = max_h - len(lines) - 1
            if available >= len(item_lines):
                lines.extend(item_lines)
            elif available > 1:
                lines.extend(item_lines[:available - 1])
                lines.append(f"  [dim]... 共{len(p.inventory)}件[/]")
            else:
                lines.extend(item_lines[:max(1, available)])
        else:
            lines.append("  (空)")
        return "\n".join(lines)

    def _render_character(self) -> str:
        p = self.state.player
        max_h = self.size.height
        lines = [
            f"[bold]角色面板[/] [dim]C/Esc返回[/]  {p.name}  {p.char_class} Lv.1",
            f"HP [green]{p.hp}/{p.max_hp}[/]  MP [blue]{p.mp}/{p.max_mp}[/]  TEN [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC 头部{p.total_ac('head')} 躯干{p.total_ac('chest')} 双臂{p.total_ac('arms')} 双腿{p.total_ac('legs')}",
            f"SPD {p.speed}  INIT +{p.initiative_bonus()}  金币: {p.gp}GP",
            "",
        ]
        for key, label in [("str","力量"),("dex","敏捷"),("con","体质"),("int","智力"),("wis","感知"),("cha","魅力")]:
            val = p.stat(key); adj = p.stat_adjust(key)
            sign = "+" if adj >= 0 else ""
            lines.append(f"  {label}: {val} ({sign}{adj})")
        lines.append("")
        lines.append("── 装备 ──")
        body = [("head","头部"),("chest","躯干"),("arms","双臂"),("legs","双腿")]
        hands = [("left_hand","左手"),("right_hand","右手")]
        accs = [("accessory1","饰品1"),("accessory2","饰品2"),("accessory3","饰品3")]
        lines.append("  " + " ".join(f"{l}:{p.equipment.get(s).name if p.equipment.get(s) else '-'}" for s,l in body))
        lines.append("  " + " ".join(f"{l}:{p.equipment.get(s).name if p.equipment.get(s) else '-'}" for s,l in hands))
        lines.append("  " + " ".join(f"{l}:{p.equipment.get(s).name if p.equipment.get(s) else '-'}" for s,l in accs))
        if p.statuses:
            lines.append(f"[red]状态: {' '.join(p.statuses)}[/]")
        return "\n".join(lines[:max_h])

    def _render_observe(self) -> str:
        cursor = self.state.observe_cursor
        cx, cy = cursor
        max_h = self.size.height
        lines = ["[bold]观察模式[/] [dim]X退出 方向键移动光标[/]", ""]

        # 地名 — 从 location_map 哈希表 O(1) 查询，不存在时回退到当前地图名
        loc = self.state.location_map.get(cursor, "")
        if not loc:
            loc = self.state.current_map or ""
        if loc:
            lines.append(f"位置: ({cx}, {cy}) {loc}")
        else:
            lines.append(f"位置: ({cx}, {cy})")

        # 地形
        terrain = self.state.map[cx, cy]
        t_names = {Terrain.WALL: "墙壁", Terrain.DIFFICULT: "灌木/困难地形", Terrain.PASSABLE: "草地/平地"}
        lines.append(f"地表: {t_names.get(terrain, '未知')}")

        # 生物
        ent = self.state.get_entity_at(cx, cy)
        if ent and ent is not self.state.player:
            hp_pct = ent.hp / max(ent.max_hp, 1) * 100
            faction_tag = {"hostile": "[red]敌对[/]", "friendly": "[green]友好[/]",
                           "neutral": "[yellow]中立[/]"}.get(ent.faction, ent.faction)
            lines.append(f"生物: {ent.name} {faction_tag}  HP {ent.hp}/{ent.max_hp} ({hp_pct:.0f}%)")
            if ent.statuses:
                lines.append(f"  状态: {', '.join(ent.statuses)}")

        # 光照
        if cursor in self.state.fov_cache:
            lines.append("亮度: 可见")
        else:
            lines.append("亮度: 不可见")

        return "\n".join(lines[:max_h])


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
        stats = {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}
        boosted = random.sample(["str", "dex", "con", "int", "wis", "cha"], 2)
        for s in boosted: stats[s] = 10
        player = Player.create_fighter(name="凯恩", stats=stats)
        self._state = GameState(player=player, map_width=80, map_height=60)
        # 加载战技数据
        import json
        maneuver_path = os.path.join(DATA_DIR, "maneuvers.json")
        if os.path.exists(maneuver_path):
            with open(maneuver_path, "r", encoding="utf-8") as f:
                self._state.maneuvers = json.load(f)
        else:
            self._state.maneuvers = []
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
        self._save_manager = SaveManager(SAVE_DIR)

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
            "location_map": self._state.location_map,
        }
        _build_dungeon(self._state)
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

    def _start_combat_from_ambush(self, target: Creature) -> None:
        """探索模式主动攻击 → 进入战斗，玩家必定先手（不调用 _next_turn）。"""
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
        self._state.combat_turn_entity = self._state.player
        self._act_log.add("=== 战斗开始 ===")
        self._act_log.add(f">>> {self._pn}的战斗轮 <<<")

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
        """执行一次近战攻击检定，返回结果 dict。不修改 AP，不切换回合。"""
        hit, roll = hit_check(attacker, target, weapon)
        effective_roll = roll + hit_bonus
        if hit:
            critical = (roll == 20)
            dmg = roll_damage(weapon, attacker, critical=critical)
            dmg += damage_bonus
            dmg = apply_damage_type_modifiers(dmg, weapon.damage_type, target)
            target.hp = max(0, target.hp - dmg)
            return {"hit": True, "critical": critical, "roll": roll,
                    "damage": dmg, "target_name": target.name}
        else:
            reduce_tenacity(target, roll)
            return {"hit": False, "roll": roll,
                    "target_name": target.name}

    def _handle_action_input(self, cmd: str) -> None:
        """阶段一：选择攻击方式。按动态 action_map 解析序号。"""
        p = self._state.player
        action_map = self._left_panel._action_map

        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            return

        if num == 0:
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self._input_bar.disabled = True
            self._map_view.focus()
            self._act_log.add("取消攻击")
            self.refresh_all()
            return

        entry = action_map.get(num)
        if entry is None:
            self._act_log.add(f"无效选项: {cmd}")
            return

        mode, weapon = entry
        hit_bonus = 0
        damage_bonus = 0

        if mode.endswith("_blocked"):
            self._act_log.add(f"{weapon.name} 无法用于攻击")
            return
        if mode == "two_hand":
            hit_bonus = 1; damage_bonus = 2

        if self._state.in_combat and p.ap < weapon.ap_cost:
            self._act_log.add("AP 不足")
            return

        self._state.pending_attack = {
            "mode": mode, "weapon": weapon,
            "hit_bonus": hit_bonus, "damage_bonus": damage_bonus,
            "attack_roll": None, "target": None,
        }

        # 找相邻目标
        pc, pr = self._state.player_pos
        targets = []
        for creature, (ec, er) in self._state.entities:
            if creature is not self._state.player and creature.hp > 0 \
               and abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                targets.append(creature)

        if len(targets) == 0:
            self._act_log.add("近战范围内没有目标")
            if not self._state.in_combat:
                # 探索模式无目标，不进入战斗，直接取消
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self._input_bar.disabled = True
                self._map_view.focus()
            else:
                self._state.combat_phase = "select_action"
            self.refresh_all()
        elif len(targets) == 1:
            target = targets[0]
            # 探索模式：仅敌对目标进入战斗，非敌对先攻击再根据阵营反应决定
            if not self._state.in_combat and target.faction == "hostile":
                self._start_combat_from_ambush(target)
            self._state.pending_attack["target"] = target
            self._execute_attack_roll()
            self.refresh_all()
        else:
            # 多目标：存在敌对目标时才进入战斗
            if not self._state.in_combat:
                hostile = [t for t in targets if t.faction == "hostile"]
                if hostile:
                    self._start_combat_from_ambush(hostile[0])
            self._state.combat_phase = "select_target"
            self._focus_input()
            self.refresh_all()

    def _handle_target_input(self, cmd: str) -> None:
        """阶段二：选择目标。输入 T1~Tn。"""
        if cmd == "T0":
            self._state.combat_phase = "select_action"
            self._focus_input()
            self._act_log.add("取消目标选择")
            self.refresh_all()
            return

        try:
            idx = int(cmd[1:]) - 1
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}, 请输入 T序号")
            return

        pc, pr = self._state.player_pos
        targets = []
        for creature, (ec, er) in self._state.entities:
            if creature is not self._state.player and creature.hp > 0 \
               and abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                dist = max(abs(ec - pc), abs(er - pr))
                targets.append((dist, creature.hp, creature))
        targets.sort(key=lambda x: (x[0], x[1]))

        if 0 <= idx < len(targets):
            self._state.pending_attack["target"] = targets[idx][2]
            self._execute_attack_roll()
        else:
            self._act_log.add("目标序号无效")
        self.refresh_all()

    def _execute_attack_roll(self) -> None:
        """执行攻击检定，根据命中/未命中进入阶段三。"""
        pa = self._state.pending_attack
        weapon = pa["weapon"]
        target = pa["target"]
        p = self._state.player

        if self._state.in_combat:
            p.ap -= weapon.ap_cost
        hit, roll = hit_check(p, target, weapon)

        pa["attack_roll"] = roll
        pa["hit"] = hit
        self._act_log.add(f"{self._pn} 挥动{weapon.name}砍向 {target.name}! (roll={roll})")

        if hit:
            self._state.combat_phase = "select_maneuver"
        else:
            self._state.combat_phase = "select_special"
        self._focus_input()

    def _handle_maneuver_input(self, cmd: str) -> None:
        """阶段三A：命中后选择战技。按 maneuver_map 解析。"""
        pa = self._state.pending_attack
        weapon = pa["weapon"]
        target = pa["target"]
        p = self._state.player
        mmap = self._left_panel._maneuver_map

        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            self.refresh_all()
            return

        if num == 0:
            # 直接攻击，正常结算
            pass
        elif num in mmap and mmap[num] is not None:
            m = mmap[num]
            if self._state.in_combat:
                if p.ap < m["ap_extra"]:
                    self._act_log.add("AP 不足"); self.refresh_all(); return
                p.ap -= m["ap_extra"]
            effect = m["effect"]
            if effect == "damage_bonus":
                bonus = roll_d20() % 4 + 1  # 1d4
                pa["damage_bonus"] = pa.get("damage_bonus", 0) + bonus
                self._act_log.add(f"{m['name']}! 伤害+{bonus}")
            elif effect == "disarm":
                t_roll = roll_d20() + target.stat_adjust("str")
                if t_roll < 12:
                    self._act_log.add(f"缴械成功! {target.name} 的武器被打落")
                else:
                    self._act_log.add(f"{target.name} 握紧了武器")
            elif effect == "knockdown":
                t_roll = roll_d20() + target.stat_adjust("dex")
                if t_roll < 12:
                    if "prone" not in target.statuses:
                        target.statuses.append("prone")
                    self._act_log.add(f"扫腿成功! {target.name} 摔倒在地")
                else:
                    self._act_log.add(f"{target.name} 稳住了身形")
        else:
            self._act_log.add(f"无效选项: {cmd}")
            self.refresh_all()
            return

        # 结算伤害 — 命中已确认，不再重做命中检定
        roll = pa.get("attack_roll", 0)
        critical = (roll == 20)
        dmg = roll_damage(weapon, p, critical=critical)
        dmg += pa.get("damage_bonus", 0)
        dmg = apply_damage_type_modifiers(dmg, weapon.damage_type, target)
        target.hp = max(0, target.hp - dmg)
        self._check_faction_reaction(target)

        self._act_log.add(f"{self._pn} 砍中了 {target.name}, 造成 {dmg} 点伤害")
        if target.hp <= 0:
            self._act_log.add(f"{target.name} 倒在地上，不再动弹")

        # 探索模式：攻击后目标变为敌对 → 进入战斗
        if not self._state.in_combat and target.faction == "hostile" and target.hp > 0:
            self._start_combat_from_ambush(target)

        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._input_bar.disabled = True
        self._map_view.focus()
        self.refresh_all()

    def _handle_special_input(self, cmd: str) -> None:
        """阶段三B：未命中后选择特殊行动。输入 A0~A3。"""
        pa = self._state.pending_attack
        target = pa["target"]
        weapon = pa["weapon"]
        p = self._state.player
        roll = pa.get("attack_roll", 0)

        smap = self._left_panel._special_map
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            self.refresh_all()
            return

        action_key = smap.get(num)
        if action_key is None:
            self._act_log.add(f"无效选项: {cmd}")
            self.refresh_all()
            return

        if action_key == "tenacity":
            self._act_log.add(f"削韧: {target.name} 韧性被削减")
        elif action_key == "reroll":
            if self._state.in_combat and p.ap < 2:
                self._act_log.add("AP 不足"); self.refresh_all(); return
            if self._state.in_combat:
                p.ap -= 2
            self._act_log.add("奋力一击! 重掷攻击骰")
            result = self._resolve_melee_attack(p, target, weapon)
            if result["hit"]:
                self._check_faction_reaction(target)
                self._act_log.add(f"命中! 造成 {result['damage']} 点伤害")
            else:
                self._act_log.add("再次未命中...")
        elif action_key == "feint":
            if self._state.in_combat and p.ap < 1:
                self._act_log.add("AP 不足"); self.refresh_all(); return
            if self._state.in_combat:
                p.ap -= 1
            self._act_log.add("虚晃一招 — 下次攻击命中+2")
        elif action_key == "taunt":
            if self._state.in_combat and p.ap < 1:
                self._act_log.add("AP 不足"); self.refresh_all(); return
            if self._state.in_combat:
                p.ap -= 1
            self._act_log.add(f"{self._pn} 挑衅了 {target.name}")

        # 探索模式：攻击后目标变为敌对 → 进入战斗
        if not self._state.in_combat and target.faction == "hostile" and target.hp > 0:
            self._start_combat_from_ambush(target)

        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._input_bar.disabled = True
        self._map_view.focus()
        self.refresh_all()

    def _check_faction_reaction(self, target: Creature) -> None:
        """玩家攻击非敌对生物后检查阵营反应。"""
        if target.faction == "hostile":
            return
        if target.faction == "neutral" and not target.hostility_triggered:
            target.hostility_triggered = True
            target.original_faction = "neutral"
            target.faction = "hostile"
            self._act_log.add(f"{target.name} 被激怒了! 开始反击")
            if self._state.in_combat:
                if target not in self._state.combat_initiative:
                    self._state.combat_initiative.append(target)
        elif target.faction == "friendly":
            target.friendly_attack_count += 1
            if target.friendly_attack_count >= 2:
                target.original_faction = "friendly"
                target.faction = "hostile"
                self._act_log.add(f"{target.name} 怒不可遏! 开始反击")
                if self._state.in_combat:
                    if target not in self._state.combat_initiative:
                        self._state.combat_initiative.append(target)
            else:
                self._act_log.add(f"{target.name} 被{self._pn}的攻击吓了一跳，但忍住了")

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
        """按 A 键 → 进入攻击方式选择阶段。"""
        if self._state.combat_phase != "idle":
            return  # 战斗面板中按 A 不重新聚焦输入栏
        self._state.combat_phase = "select_action"
        self._state.pending_attack = {}
        self._act_log.add("[攻击] 选择武器 — 输入 A序号 确认, A0 取消")
        self._focus_input()
        self.refresh_all()
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

        act_map = {
            "flee": "惊慌失措地试图逃窜", "surrender": "举起双手投降",
            "attack": f"死死盯着{self._pn}" if enemy_count else "警惕地巡视四周",
            "advance": "向前逼近" if enemy_count else "来回踱步",
            "defend": "摆出防御姿态", "patrol": "漫无目的地游荡",
            "hunt": "低头寻觅着食物", "idle": "静静地站在原地",
            "sleep": "蜷缩着打盹",
        }
        status_text = ""
        if c.statuses:
            status_text = f" [{', '.join(c.statuses)}]"
        return f"{c.name}{status_text} {hp}{act_map.get(action, '待在原地')}"

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
                _build_world(self._state)
            elif current_map == "地下城":
                _build_dungeon(self._state)

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
