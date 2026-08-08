"""左侧面板 —— 探索/战斗默认面板 + 攻击流程子面板（选武器/选目标/选战技/选特殊行动）。"""

import json
import os
from textual.widgets import Static

from core.game_state import GameState

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
            lines.append(f"[[T{i + 1}]]{c.name} {faction_tag} (HP {c.hp}, AC {c.total_ac('chest')})")
        if len(targets) > 8:
            lines.append(f"... 还有 {len(targets) - 8} 个目标")
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
    """加载特殊行动定义，fallback 到硬编码默认值。"""
    global _SPECIAL_ACTIONS_CACHE
    if _SPECIAL_ACTIONS_CACHE is not None:
        return _SPECIAL_ACTIONS_CACHE
    path = os.path.join(_DATA_DIR, "maneuvers.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _SPECIAL_ACTIONS_CACHE = data.get("special_actions", [])
    if not _SPECIAL_ACTIONS_CACHE:
        _SPECIAL_ACTIONS_CACHE = [
            {"key": "reroll", "name": "奋力一击", "ap_cost": 2, "desc": "额外消耗 2AP，重掷攻击骰"},
            {"key": "feint", "name": "虚晃一招", "ap_cost": 1, "desc": "消耗 1AP，下次攻击命中+2"},
            {"key": "taunt", "name": "挑衅", "ap_cost": 1, "desc": "消耗 1AP，目标下回合更容易攻击你"},
        ]
    return _SPECIAL_ACTIONS_CACHE
