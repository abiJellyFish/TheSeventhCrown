"""战斗流程状态机 —— 攻击方式选择 → 目标选择 → 命中检定 → 战技/特殊行动。"""

import random
from domain.entity import Entity, Weapon, are_hostile
from domain.dice import roll_d20, roll_adv_dice, resolve_adv_auto
from domain.combat.attack import hit_check, reduce_tenacity, resolve_attack, miss_message, cover_message, compute_attack_adv
from domain.combat.cover import resolve_cover_line, terrain_cover_info
from domain.movement import Terrain
from domain.combat.target_phase import TargetPhaseMixin
from domain.combat.dual_wield import DualWieldMixin
from domain.combat.attack_roll import AttackRollMixin
from domain.combat.action_menu import ActionMenuMixin
from domain.events import DomainEvent, LogCategory, state_changed


class CombatFlow(TargetPhaseMixin, DualWieldMixin, AttackRollMixin, ActionMenuMixin):
    """管理玩家攻击流程的五阶段状态机。

    只操作领域状态并发布事件，不持有具体 UI 控件。
    """

    def __init__(self, state, pn: str, action_map=None, maneuver_map=None,
                 special_map=None, on_refresh=None):
        self._state = state
        self._pn = pn
        self._on_refresh = on_refresh
        self._action_map = action_map if action_map is not None else {}
        self._maneuver_map = (
            maneuver_map if maneuver_map is not None else {}
        )
        self._special_map = special_map if special_map is not None else {}

    def _log(self, message: str) -> None:
        self._state.emit_log(message, LogCategory.COMBAT)

    def _refresh(self) -> None:
        if self._on_refresh is not None:
            self._on_refresh()
            return
        self._state.emit_event(state_changed(self._state.state_version))

    def _wake(self) -> None:
        self._state.emit_event(DomainEvent("InputWake"))

    def _request_combat(self, target) -> None:
        self._state.emit_event(DomainEvent("CombatRequested", {"target_id": id(target)}))

    def _on_two_hand(self, weapon, hand: str) -> None:
        self._state.emit_event(DomainEvent("TwoHandRequested", {
            "item": weapon, "hand": hand,
        }))

    def _on_torch_action(self, weapon, mode: str) -> None:
        self._state.emit_event(DomainEvent("TorchActionRequested", {
            "item": weapon, "mode": mode,
        }))
    def start_action_phase(self, from_reaction: bool = False) -> None:
        """按 A 键 → 进入攻击方式选择阶段。"""
        if self._state.combat_phase != "idle" and not from_reaction:
            return
        self._state.observe_mode = False
        self._state.combat_phase = "select_action"
        self._state.pending_attack = {"from_reaction": from_reaction}
        self._log("[攻击] 选择武器 — 输入 A序号 确认, A0 取消")
        self._refresh()
        self._wake()

    def _preserve_from_reaction(self, data: dict) -> dict:
        old = self._state.pending_attack or {}
        if old.get("from_reaction"):
            data["from_reaction"] = True
        return data

    def _end_pending_attack(self, *, abandoned: bool = False) -> None:
        pa = self._state.pending_attack or {}
        from_rx = bool(pa.get("from_reaction"))
        if not abandoned:
            self._settle_pending_tenacity(pa)
        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        if from_rx:
            self._state.finish_player_reaction(abandoned=abandoned)

    def _settle_pending_tenacity(self, pa: dict) -> None:
        from domain.combat.tenacity import (
            note_entity_attack, reset_attack_streak, settle_attack_tenacity,
        )
        attacker = self._state.controlled_entity
        target = pa.get("target")
        weapon = pa.get("weapon")
        mode = pa.get("mode", "")
        if mode in ("torch_ignite", "torch_extinguish", "torch_ignite_surface"):
            reset_attack_streak(attacker)
            return
        attacked_entity = pa.get("hit_entity") or isinstance(target, Entity)
        if not attacked_entity:
            reset_attack_streak(attacker)
            return
        if not isinstance(target, Entity):
            note_entity_attack(attacker)
            return
        settle_attack_tenacity(
            attacker, target, weapon, pa.get("attack_roll", 0),
            tenacity_action=False,
            combat_state=self._state,
            consume_extra=not pa.get("extra_consumed"),
            note_combo=True,
        )
