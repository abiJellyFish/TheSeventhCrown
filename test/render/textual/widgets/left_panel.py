"""左侧面板 —— 探索/战斗默认面板 + 攻击流程子面板（选武器/选目标/选战技/选特殊行动）。"""

import json
import os
from textual.widgets import Static

from core.game_state import GameState
from core.movement import Terrain

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")


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
        elif phase == "ranged_target":
            return self._render_ranged_target_panel()
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
            f"AP [{'|' * filled}{'.' * (10 - filled)}]",
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

    def _render_ranged_target_panel(self) -> str:
        pa = self.state.pending_attack or {}
        weapon = pa.get("weapon")
        pc, pr = self.state.player_pos
        oc, oro = self.state.observe_cursor

        weapon_name = weapon.name if weapon else "武器"
        max_range = weapon.range_max if weapon and hasattr(weapon, 'range_max') else 1
        dist = max(abs(oc - pc), abs(oro - pr))

        # 地表
        terrain = self.state.map[oc, oro]
        t_names = {Terrain.WALL: "墙壁", Terrain.DIFFICULT: "灌木/困难地形",
                   Terrain.PASSABLE: "草地/平地"}
        terrain_name = t_names.get(terrain, "未知")

        # 目标
        target_info = "(空地)"
        ent = self.state.get_entity_at(oc, oro)
        if terrain == Terrain.WALL:
            target_info = "(墙壁)"
        elif ent and ent.hp > 0 and ent is not self.state.player:
            faction_tag = {"hostile": "[red]敌对[/]", "friendly": "[green]友好[/]",
                           "neutral": "[yellow]中立[/]"}.get(ent.faction, ent.faction)
            target_info = f"{ent.name} {faction_tag} HP:{ent.hp} AC:{ent.total_ac('chest')}"

        lines = [
            "── 远程瞄准 ──",
            f"武器: {weapon_name}  射程: {max_range}",
            f"光标: ({oc}, {oro})  距离: {dist}",
            f"地表: {terrain_name}",
            f"目标: {target_info}",
            "",
            "[[方向键]] 移动光标",
            "[[Enter]] 确认攻击",
            "[[Esc]] 取消瞄准",
        ]
        return "\n".join(lines)

    def _render_target_panel(self) -> str:
        pa = self.state.pending_attack or {}
        weapon = pa.get("weapon")
        pc, pr = self.state.player_pos

        weapon_name = weapon.name if weapon else "武器"
        reach = weapon.reach if weapon and hasattr(weapon, 'reach') and weapon.reach else 1
        lines = ["── 选择目标格子 ──",
                 f"{weapon_name} → 攻击范围: {reach}格"]

        # 收集范围内格子（与 flow._find_melee_tiles 逻辑一致）
        tiles = []
        for dc in range(-reach, reach + 1):
            for dr in range(-reach, reach + 1):
                if dc == 0 and dr == 0:
                    continue
                tc, tr = pc + dc, pr + dr
                if not self.state.map.within_bounds(tc, tr):
                    continue
                if (tc, tr) not in self.state.fov_cache:
                    continue
                dist = max(abs(dc), abs(dr))
                ent = self.state.get_entity_at(tc, tr)
                if ent is self.state.player:
                    ent = None
                if ent and ent.hp <= 0:
                    ent = None
                tiles.append((dist, tc, tr, ent))
        tiles.sort(key=lambda x: (x[0], x[3] is None))

        for i, (_, tc, tr, ent) in enumerate(tiles[:9]):
            if ent:
                faction_tag = {"hostile": "[red]敌对[/]", "friendly": "[green]友好[/]",
                               "neutral": "[yellow]中立[/]"}.get(ent.faction, ent.faction)
                label = f"{ent.name} {faction_tag} HP:{ent.hp}"
            else:
                terrain = self.state.map[tc, tr]
                t_name = {Terrain.WALL: "墙壁", Terrain.DIFFICULT: "灌木", Terrain.PASSABLE: "空地"}.get(terrain, "空地")
                label = t_name
            lines.append(f"[[T{i + 1}]]({tc},{tr}) {label}")
        if len(tiles) > 9:
            lines.append(f"... 还有 {len(tiles) - 9} 个格")
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
            if desc == 'damage_bonus':
                desc_text = f'伤害+{m["value"]}'
            elif desc == 'disarm':
                desc_text = '目标力量豁免失败则武器掉落'
            elif desc == 'knockdown':
                desc_text = '目标敏捷豁免失败则倒地'
            else:
                desc_text = desc
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

        specials = _load_special_actions()
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


_SPECIAL_ACTIONS_CACHE: list | None = None


def _load_special_actions() -> list:
    """加载特殊行动定义。"""
    global _SPECIAL_ACTIONS_CACHE
    if _SPECIAL_ACTIONS_CACHE is not None:
        return _SPECIAL_ACTIONS_CACHE
    path = os.path.join(_DATA_DIR, "maneuvers.json")
    with open(path, "r", encoding="utf-8") as f:
        _SPECIAL_ACTIONS_CACHE = json.load(f).get("special_actions", [])
    return _SPECIAL_ACTIONS_CACHE
