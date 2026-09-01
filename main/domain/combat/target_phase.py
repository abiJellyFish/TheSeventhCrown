"""目标选择阶段 —— 进入瞄准、确认/取消目标、优势点数选择。"""
from dataclasses import dataclass
import random
from domain.entity import Entity, Weapon, are_hostile
from domain.dice import roll_d20, roll_adv_dice, resolve_adv_auto
from domain.combat.attack import hit_check, reduce_tenacity, resolve_attack, miss_message, cover_message, compute_attack_adv
from domain.combat.cover import resolve_cover_line, terrain_cover_info
from domain.movement import Terrain
from domain.combat.shape import weapon_melee_reach


@dataclass(frozen=True)
class TargetRef:
    """伤害结算使用的明确目标引用。"""

    position: tuple[int, int]
    target: object
    target_kind: str


class TargetPhaseMixin:

    def _begin_target_choice(self, candidates, position, resume: str) -> None:
        """同格存在多个目标时，切换到左栏目标选择面板。"""
        pa = self._state.pending_attack
        pa["target_candidates"] = list(candidates)
        pa["target_choice_position"] = position
        pa["target_choice_resume"] = resume
        pa["target_choice_active"] = True
        self._log(
            f"选择目标 ({position[0]},{position[1]})：输入 :A序号确认，:A0取消"
        )
        self._refresh()
        self._wake()

    # ── 辅助 ──

    def _target_can_see_attacker(self, target_pos, target) -> bool:
        """目标能否看到攻击者？（欧几里得距离 ≤ 目标视野范围，圆形）"""
        pc, pr = self._state.controlled_entity_pos
        vr = getattr(target, 'vision_range', 0)
        return (target_pos[0] - pc) ** 2 + (target_pos[1] - pr) ** 2 <= vr * vr

    @staticmethod
    def _weapon_max_range(weapon, wielder=None) -> int:
        """返回武器的瞄准范围：近战用 reach，远程用 range_max。"""
        if weapon is None:
            return weapon_melee_reach(None, wielder)
        if getattr(weapon, 'weapon_type', '') == "ranged":
            return getattr(weapon, 'range_max', 8)
        return weapon_melee_reach(weapon, wielder)

    # ── 攻击流程入口 ──


    def _enter_target_phase(self, weapon) -> None:
        """进入光标瞄准阶段（近战/远程统一）。只看范围，不看视野。"""
        reach = self._weapon_max_range(weapon, self._state.controlled_entity)
        self._state.observe_mode = False
        self._state.combat_phase = "ranged_target"
        self._state.observe_cursor = self._state.controlled_entity_pos
        self._state.pending_attack["max_range"] = reach
        # 多格形状（武器 target_shape，如 "1x3"；缺省单格）
        shape_spec = self._state.pending_attack.get(
            "target_shape", getattr(weapon, 'target_shape', '') or ""
        )
        self._state.pending_attack["target_shape"] = shape_spec
        self._state.pending_attack["target_mode"] = (
            "area" if self._state.pending_attack.get("sweep_selected") else "target"
        )
        tip = " [<[/>旋转]" if shape_spec else ""
        self._log(
            f"选择目标 — 范围:{reach}格{tip} [方向键]移动光标 [Enter]确认 [']取消")
        self._refresh()
        self._wake()

    # ── 阶段二B：光标选目标（近战/远程/法术/投掷/点火通用）──

    def confirm_ranged_target(self) -> None:
        """确认光标目标选择（以格子为单位），进入攻击检定。只看范围，不看视野。
        多格形状：所有光标格须在射程内，不检查视野。"""
        pa = self._state.pending_attack
        if pa is None:
            return
        cursor = self._state.observe_cursor
        weapon = pa.get("weapon")
        max_range = pa.get("max_range") or self._weapon_max_range(weapon)
        pc, pr = self._state.controlled_entity_pos
        # 多格形状：光标 = 锚格 + 形状偏移
        from domain.combat.shape import shape_cells, shape_from_pending_attack
        shape = shape_from_pending_attack(pa)
        cells = shape_cells(cursor, shape)
        if shape.is_single:
            if max(abs(cursor[0] - pc), abs(cursor[1] - pr)) > max_range:
                self._log("目标超出了攻击范围")
                self._refresh()
                return
        else:
            for (c, r) in cells:
                if not (0 <= c < self._state.map.width and 0 <= r < self._state.map.height):
                    self._log("目标范围超出地图边界")
                    self._refresh()
                    return
                if max(abs(c - pc), abs(r - pr)) > max_range:
                    self._log("目标超出了攻击范围")
                    self._refresh()
                    return
            pa["multi_cells"] = cells
        # 目标模式默认选择一个；范围模式保留同格全部对象。
        candidates = self._state.get_damageables_at(cursor[0], cursor[1])
        target_mode = pa.get("target_mode", "target")
        if target_mode == "target" and len(candidates) > 1:
            self._begin_target_choice(candidates, cursor, "ranged")
            return
        target = (
            candidates
            if target_mode == "area"
            else (candidates[0] if candidates else None)
        )
        if target_mode == "area":
            pa["multi_cells"] = cells
            target = None
        self._continue_ranged_target(target, cursor)

    def _continue_ranged_target(self, target, target_pos) -> None:
        """完成目标选择后，继续原有攻击判定链。"""
        pa = self._state.pending_attack
        pa["target_pos"] = target_pos
        pa["target"] = target
        if isinstance(target, Entity) and target.has_status("shield"):
            event = {
                "kind": "shield", "trigger": "target_selected",
                "attacker": self._state.controlled_entity,
                "target": target, "registered_at": len(self._state.pending_reactions),
            }
            self._state.pending_reactions.append(event)
            self._state.interact_phase = "reaction"
            self._state.emit_reaction_required()
            self._refresh()
            self._wake()
            return
        self.execute_attack_roll()
        self._refresh()

    def cancel_ranged_target(self) -> None:
        """取消远程目标选择，返回攻击方式选择。"""
        if (self._state.pending_attack or {}).get("from_reaction"):
            self._end_pending_attack(abandoned=True)
            self._log("取消远程攻击")
            self._refresh()
            return
        self._state.combat_phase = "select_action"
        self._state.pending_attack = self._preserve_from_reaction({})
        self._log("取消远程攻击")
        self._refresh()

    # ── 阶段三：攻击检定 → 进入战技/特殊行动 ──


    def _player_adv_deferred(self, p, adv: int, pa: dict) -> bool:
        """玩家控制实体优势掷骰时进入 adv_select 阶段。返回 True 表示已挂起。"""
        if adv > 0 and getattr(p, 'controlled', False):
            pa["adv"] = adv
            pa["adv_rolls"] = roll_adv_dice(advantage=adv)
            self._state.combat_phase = "adv_select"
            self._log(
                f"[优势] 掷出 {len(pa['adv_rolls'])} 颗骰子，输入序号选择点数")
            self._refresh()
            self._wake()
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
            self._log(f"无效选择: {cmd}")
            return
        if idx < 1 or idx > len(rolls):
            self._log(f"无效选择: 请输入 1-{len(rolls)}")
            return
        roll = rolls[idx - 1]
        pa.pop("adv_rolls", None)
        pa.pop("adv", None)
        self._log(f"[优势] 选择点数 {roll}")
        mode = pa.get("mode", "")
        if mode in ("dual_wield", "dual_attack"):
            self._finish_dual_step(roll)
        else:
            self._finish_single_attack(roll)
        self._refresh()

