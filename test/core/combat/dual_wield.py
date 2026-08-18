"""双持武器判定 —— 轻型检查、模式判定、AP 计算。"""

from core.entity import Weapon


def is_light(weapon: Weapon) -> bool:
    """武器是否具有轻型 (light) 属性。"""
    props = getattr(weapon, 'properties', None) or []
    return "light" in props


def dual_wield_mode(left, right) -> str | None:
    """判定双持模式。

    Returns:
        "dual_wield"  — 两把都是轻型，消耗一次 AP 同时攻击
        "dual_attack" — 至少一把非轻型，分别消耗 AP 依次攻击
        None          — 不满足双持条件（如任一手为空或不是武器）
    """
    if left is None or right is None:
        return None
    if not hasattr(left, 'weapon_type') or not hasattr(right, 'weapon_type'):
        return None
    if is_light(left) and is_light(right):
        return "dual_wield"
    return "dual_attack"


def dual_wield_ap_cost(left, right) -> int:
    """双持武器模式（两把轻型）的 AP 消耗 = max(两把武器 ap_cost)。"""
    return max(getattr(left, 'ap_cost', 2), getattr(right, 'ap_cost', 2))

import random
from core.entity import Entity, Weapon, are_hostile
from core.dice import roll_d20, roll_adv_dice, resolve_adv_auto
from core.combat.attack import hit_check, reduce_tenacity, resolve_attack, miss_message, cover_message, compute_attack_adv
from core.combat.cover import resolve_cover_line, terrain_cover_info
from core.movement import Terrain


class DualWieldMixin:

    # ── 双持分步结算 ──

    def _execute_dual_step(self) -> None:
        """执行双持模式下的当前步（左手或右手）攻击检定。"""
        pa = self._state.pending_attack
        step = pa.get("step", "left")
        p = self._state.player
        target = pa.get("target")
        target_pos = pa.get("target_pos")

        # 确定当前武器
        if step == "left":
            weapon = pa.get("weapon_left")
        else:
            weapon = pa.get("weapon_right")

        if weapon is None:
            self._act_log.add("双持: 武器丢失")
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            return

        # dual_attack 模式：每步单独扣 AP
        if pa["mode"] == "dual_attack" and self._state.in_combat:
            if p.ap < weapon.weapon.ap_cost:
                hand_name = "左手" if step == "left" else "右手"
                self._act_log.add(f"AP 不足，无法发动{hand_name}攻击")
                # 如果是左手 AP 不足则直接结束；右手则只跳过右手
                if step == "left":
                    self._state.combat_phase = "idle"
                    self._state.pending_attack = {}
                else:
                    self._finish_dual()
                return
            p.ap -= weapon.weapon.ap_cost

        # 攻击掷骰前（仅第一步）：目标能看到攻击者 → 记录临时敌对 + 进战斗
        if step == "left" and not self._state.in_combat and target is not p \
           and self._target_can_see_attacker(target_pos, target) and not are_hostile(target, p):
            if target.faction == "中立" or target.faction == "守序":
                target._attitude[id(p)] = "敌对"
                self._act_log.add(f"{target.name} 被激怒，开始反击!")
            self._start_combat_from_ambush(target)

        # 无目标 → 直接结束双持
        if target is None:
            self._log_empty_target(weapon, target_pos)
            self._finish_dual()
            return

        hand_name = "左手" if step == "left" else "右手"
        attacker_pos = self._state.get_entity_pos(p) or self._state.player_pos
        # 视野外/隐匿优势判定（统一视野 = 相邻一圈∪面前扇形）
        hidden = self._state._is_hidden_to(target, p, attacker_pos)
        dist = max(abs(target_pos[0] - attacker_pos[0]), abs(target_pos[1] - attacker_pos[1]))
        out_of_sight = dist > 1 and not self._state._observer_can_see(target, attacker_pos)
        adv = compute_attack_adv(p, target, weapon,
                                 attacker_pos=attacker_pos,
                                 defender_pos=target_pos,
                                 hidden=hidden, out_of_sight=out_of_sight)
        # 协助攻击优势：本次攻击检定消耗 assisted（与属性检定一致）
        if p.has_status("assisted"):
            p.remove_status("assisted")
        # 玩家优势 → 弹出优势选择面板，等待选择点数
        if self._player_adv_deferred(p, adv, pa):
            return
        roll = resolve_adv_auto(roll_adv_dice(advantage=max(adv, 0),
                                              disadvantage=max(-adv, 0)))
        self._finish_dual_step(roll)

    def _finish_dual_step(self, roll: int) -> None:
        """双持单步掷骰后结算。"""
        pa = self._state.pending_attack
        step = pa.get("step", "left")
        p = self._state.player
        target = pa.get("target")
        if step == "left":
            weapon = pa.get("weapon_left")
            hand_name = "左手"
        else:
            weapon = pa.get("weapon_right")
            hand_name = "右手"

        hit, _ = hit_check(p, target, weapon, chosen_roll=roll)

        pa["attack_roll"] = roll
        pa["hit"] = hit
        self._act_log.add(f"{self._pn} {hand_name}{weapon.name}攻击 {target.name}! (roll={roll})")

        self._unload_ammo(weapon)

        if hit:
            self._state.combat_phase = "select_maneuver"
        else:
            self._state.combat_phase = "select_special"
            self._act_log.add(miss_message(self._pn, target.name, weapon.damage_type)
                              + f" (roll={roll})")
            # 身后1格攻击失手 → 暴露位置（阶段4，D16）
            self._state._hide_attack_expose(p, target)

    def _finish_dual(self) -> None:
        """结束双持流程。"""
        self._state.combat_phase = "idle"
        self._state.pending_attack = {}

    def _continue_dual(self) -> None:
        """左手结算完毕 → 继续右手。"""
        pa = self._state.pending_attack
        pa["step"] = "right"
        pa["attack_roll"] = None
        pa["hit"] = None
        self._execute_dual_step()

    # ── 阶段三A：命中后选择战技 ──

    def _get_active_weapon(self) -> tuple:
        """返回当前步骤应使用的 (weapon, hand_label)。"""
        pa = self._state.pending_attack or {}
        step = pa.get("step", "")
        mode = pa.get("mode", "")
        if mode in ("dual_wield", "dual_attack") and step == "left":
            return pa.get("weapon_left"), "左手"
        if mode in ("dual_wield", "dual_attack") and step == "right":
            return pa.get("weapon_right"), "右手"
        return pa.get("weapon"), ""

