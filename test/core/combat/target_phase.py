"""目标选择阶段 —— 进入瞄准、确认/取消目标、优势点数选择。"""
import random
from core.entity import Entity, Weapon, are_hostile
from core.dice import roll_d20, roll_adv_dice, resolve_adv_auto
from core.combat.attack import hit_check, reduce_tenacity, resolve_attack, miss_message, cover_message, compute_attack_adv
from core.combat.cover import resolve_cover_line, terrain_cover_info
from core.movement import Terrain


class TargetPhaseMixin:

    # ── 辅助 ──

    def _target_can_see_attacker(self, target_pos, target) -> bool:
        """目标能否看到攻击者？（欧几里得距离 ≤ 目标视野范围，圆形）"""
        pc, pr = self._state.player_pos
        vr = getattr(target, 'vision_range', 0)
        return (target_pos[0] - pc) ** 2 + (target_pos[1] - pr) ** 2 <= vr * vr

    @staticmethod
    def _weapon_max_range(weapon) -> int:
        """返回武器的瞄准范围：近战用 reach，远程用 range_max。"""
        if weapon is None:
            return 1
        if getattr(weapon, 'weapon_type', '') == "ranged":
            return getattr(weapon, 'range_max', 8)
        return weapon.reach if hasattr(weapon, 'reach') and weapon.reach else 1

    # ── 攻击流程入口 ──


    def _enter_target_phase(self, weapon) -> None:
        """进入光标瞄准阶段（近战/远程统一）。只看范围，不看视野。"""
        reach = self._weapon_max_range(weapon)
        self._state.observe_mode = False
        self._state.combat_phase = "ranged_target"
        self._state.observe_cursor = self._state.player_pos
        self._state.pending_attack["max_range"] = reach
        self._act_log.add(
            f"选择目标 — 范围:{reach}格 [方向键]移动光标 [Enter]确认 [']取消")
        self._refresh_all()
        if self._wake_cb: self._wake_cb()

    # ── 阶段二B：光标选目标（近战/远程/法术/投掷/点火通用）──

    def confirm_ranged_target(self) -> None:
        """确认光标目标选择（以格子为单位），进入攻击检定。只看范围，不看视野。"""
        pa = self._state.pending_attack
        if pa is None:
            return
        cursor = self._state.observe_cursor
        # 检查目标是否在范围内（优先 pending_attack 的 max_range）
        weapon = pa.get("weapon")
        max_range = pa.get("max_range") or self._weapon_max_range(weapon)
        pc, pr = self._state.player_pos
        if max(abs(cursor[0] - pc), abs(cursor[1] - pr)) > max_range:
            self._act_log.add("目标超出了攻击范围")
            self._refresh_all()
            return
        # 查找格子上的生物（可为 None，范围允许即可选自身/空地，不校验视野）
        target = self._state.get_entity_at(cursor[0], cursor[1])
        if target and target.is_dead:
            target = None
        pa["target_pos"] = cursor
        pa["target"] = target
        self.execute_attack_roll()
        self._refresh_all()

    def cancel_ranged_target(self) -> None:
        """取消远程目标选择，返回攻击方式选择。"""
        self._state.combat_phase = "select_action"
        self._state.pending_attack = {}
        self._act_log.add("取消远程攻击")
        self._refresh_all()

    # ── 阶段三：攻击检定 → 进入战技/特殊行动 ──


    def _player_adv_deferred(self, p, adv: int, pa: dict) -> bool:
        """玩家控制实体优势掷骰时进入 adv_select 阶段。返回 True 表示已挂起。"""
        if adv > 0 and getattr(p, 'controlled', False):
            pa["adv"] = adv
            pa["adv_rolls"] = roll_adv_dice(advantage=adv)
            self._state.combat_phase = "adv_select"
            self._act_log.add(
                f"[优势] 掷出 {len(pa['adv_rolls'])} 颗骰子，输入序号选择点数")
            self._refresh_all()
            if self._wake_cb: self._wake_cb()
            return True
        return False

    def confirm_adv_choice(self, cmd: str) -> None:
        """玩家在优势面板选择点数（输入 1..N 序号）。"""
        pa = self._state.pending_attack
        rolls = pa.get("adv_rolls") if pa else None
        if not rolls:
            return
        try:
            idx = int(cmd)
        except (ValueError, IndexError):
            self._act_log.add(f"无效选择: {cmd}")
            return
        if idx < 1 or idx > len(rolls):
            self._act_log.add(f"无效选择: 请输入 1-{len(rolls)}")
            return
        roll = rolls[idx - 1]
        pa.pop("adv_rolls", None)
        pa.pop("adv", None)
        self._act_log.add(f"[优势] 选择点数 {roll}")
        mode = pa.get("mode", "")
        if mode in ("dual_wield", "dual_attack"):
            self._finish_dual_step(roll)
        else:
            self._finish_single_attack(roll)
        self._refresh_all()

