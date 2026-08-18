"""战斗流程状态机 —— 攻击方式选择 → 目标选择 → 命中检定 → 战技/特殊行动。"""

import random
from core.entity import Entity, Weapon, are_hostile
from core.dice import roll_d20, roll_adv_dice, resolve_adv_auto
from core.combat.attack import hit_check, reduce_tenacity, resolve_attack, miss_message, cover_message, compute_attack_adv
from core.combat.cover import resolve_cover_line, terrain_cover_info
from core.movement import Terrain
from core.combat.target_phase import TargetPhaseMixin
from core.combat.dual_wield import DualWieldMixin
from core.combat.attack_roll import AttackRollMixin
from core.combat.action_menu import ActionMenuMixin


class CombatFlow(TargetPhaseMixin, DualWieldMixin, AttackRollMixin, ActionMenuMixin):
    """管理玩家攻击流程的五阶段状态机。

    app.py 创建实例并委托调用，只保留 UI 反馈（日志、刷新、开战回调）。
    """

    def __init__(self, state, act_log, left_panel, input_bar, map_view,
                 pn: str, start_combat_cb, refresh_all_cb,
                 on_two_hand_cb=None, wake_cb=None, on_torch_action_cb=None):
        self._state = state
        self._act_log = act_log
        self._left_panel = left_panel
        self._input_bar = input_bar
        self._map_view = map_view
        self._pn = pn
        self._start_combat_from_ambush = start_combat_cb
        self._refresh_all = refresh_all_cb
        self._on_two_hand = on_two_hand_cb
        self._wake_cb = wake_cb
        self._on_torch_action = on_torch_action_cb
    def start_action_phase(self) -> None:
        """按 A 键 → 进入攻击方式选择阶段。"""
        if self._state.combat_phase != "idle":
            return
        self._state.observe_mode = False
        self._state.combat_phase = "select_action"
        self._state.pending_attack = {}
        self._act_log.add("[攻击] 选择武器 — 输入 A序号 确认, A0 取消")
        self._refresh_all()
        if self._wake_cb: self._wake_cb()