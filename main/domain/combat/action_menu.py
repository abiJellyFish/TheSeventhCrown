"""命令路由表 —— 攻击方式/战技/特殊行动的输入解析。"""
import random
from domain.entity import Entity, Weapon, are_hostile
from domain.checks import saving_throw
from domain.dice import roll_d20
from domain.combat.attack import hit_check, reduce_tenacity, resolve_attack, miss_message, cover_message, compute_attack_adv
from domain.combat.cover import resolve_cover_line, terrain_cover_info
from domain.movement import Terrain
from domain.classes import action_conditions_met
from domain.pendulum import spend_ap_or_pendulum


class ActionMenuMixin:

    # ── 阶段一：选择攻击方式 ──

    def handle_action_input(self, cmd: str) -> None:
        """阶段一：选择攻击方式。按动态 action_map 解析序号。"""
        from domain.combat.dual_wield import dual_wield_mode, dual_wield_ap_cost

        p = self._state.controlled_entity
        equip = p.equipment
        action_map = self._action_map

        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._log(f"无效选项: {cmd}")
            return

        if num == 0:
            self._end_pending_attack(abandoned=True)
            self._log("取消攻击")
            self._refresh()
            return

        entry = action_map.get(num)
        if entry is None:
            self._log(f"无效选项: {cmd}")
            return

        mode, weapon = entry
        hit_bonus = 0
        damage_bonus = 0

        # 火把点燃/熄灭 — 无需目标选择，直接结算
        if mode in ("torch_ignite", "torch_extinguish"):
            if not spend_ap_or_pendulum(self._state, p, 10):
                self._log("AP 不足")
                return
            self._on_torch_action(weapon, mode)
            self._end_pending_attack(abandoned=False)
            self._refresh()
            return

        # 火把点火地表 — 进入相邻格选择（max_range=1）
        if mode == "torch_ignite_surface":
            from domain.combat.target_phase import activate_aim
            self._state.pending_attack = self._preserve_from_reaction({
                "mode": "torch_ignite_surface",
                "weapon": weapon,
                "max_range": 1,
                "target_z": self._state.controlled_entity.z,
            })
            if not activate_aim(self._state):
                self._log("无法找到合适的目标")
                self._refresh()
                return
            self._log("选择相邻一格点火 (方向键移动, Enter确认, '取消)")
            self._refresh()
            return

        if mode.endswith("_blocked"):
            self._log(f"{weapon.name} 无法用于攻击")
            return

        # 徒手打击 — 创建临时武器
        if mode in ("unarmed_left", "unarmed_right"):
            weapon = Weapon(name="徒手打击", weapon_type="melee",
                            damage="1", damage_type="bludgeoning",
                            attack_stat="str", ap_cost=1,
                            properties=["light"])

        # 远程武器近战攻击 — 用 melee 数据构造近战武器
        if mode == "ranged_melee":
            m = weapon.melee
            weapon = Weapon(name=f"{weapon.name}(近战)", weapon_type="melee",
                            damage=m["damage"], damage_type=m["damage_type"],
                            attack_stat=m["attack_stat"], ap_cost=m["ap_cost"])

        # 双持中徒手 → weapon 可能是字符串 "unarmed"
        if mode in ("dual_wield", "dual_attack") and (weapon is None or weapon == "unarmed"):
            weapon = Weapon(name="徒手打击", weapon_type="melee",
                            damage="1", damage_type="bludgeoning",
                            attack_stat="str", ap_cost=1,
                            properties=["light"])

        if mode == "two_hand":
            # 双手武器（two_handed）— 不加 bonus，不卸除（已占用两手）
            pass
        elif mode in ("two_hand_left", "two_hand_right"):
            hand = "left" if mode == "two_hand_left" else "right"
            hit_bonus = 1
            damage_bonus = 2
            self._on_two_hand(weapon, hand=hand)

        # ── 双持武器：两把轻型，一次 AP ──
        if mode == "dual_wield":
            left_w = equip.get("left_hand") or Weapon(name="徒手打击", weapon_type="melee",
                damage="1", damage_type="bludgeoning", attack_stat="str", ap_cost=1, properties=["light"])
            right_w = equip.get("right_hand") or Weapon(name="徒手打击", weapon_type="melee",
                damage="1", damage_type="bludgeoning", attack_stat="str", ap_cost=1, properties=["light"])
            ap = dual_wield_ap_cost(left_w, right_w)
            if self._state.in_combat and p.ap < ap:
                self._log("AP 不足")
                return
            if self._state.in_combat:
                p.ap -= ap
            self._state.pending_attack = self._preserve_from_reaction({
                "mode": mode, "weapon": right_w,
                "weapon_left": left_w, "weapon_right": right_w,
                "hit_bonus": 0, "damage_bonus": 0,
                "attack_roll": None, "target": None,
                "step": "left",
            })
            self._enter_target_phase(weapon)
            return

        # ── 双持攻击：至少一把非轻型，分别扣 AP ──
        if mode == "dual_attack":
            left_w = equip.get("left_hand") or Weapon(name="徒手打击", weapon_type="melee",
                damage="1", damage_type="bludgeoning", attack_stat="str", ap_cost=1, properties=["light"])
            right_w = equip.get("right_hand") or Weapon(name="徒手打击", weapon_type="melee",
                damage="1", damage_type="bludgeoning", attack_stat="str", ap_cost=1, properties=["light"])
            if self._state.in_combat and p.ap < left_w.weapon.ap_cost:
                self._log("AP 不足")
                return
            self._state.pending_attack = self._preserve_from_reaction({
                "mode": mode, "weapon": right_w,
                "weapon_left": left_w, "weapon_right": right_w,
                "hit_bonus": 0, "damage_bonus": 0,
                "attack_roll": None, "target": None,
                "step": "left",
            })
            self._enter_target_phase(left_w)
            return

        # ── 单手 / 双手 / 远程 ──
        # 弹药武器未装填 → 需额外 1AP 装填
        ammo_load_cost = 0
        props = getattr(weapon, 'properties', []) or []
        if "ammo" in props and not getattr(weapon, 'loaded', True):
            ammo_load_cost = 1

        total_ap = weapon.weapon.ap_cost + ammo_load_cost
        if self._state.in_combat and p.ap < total_ap:
            suffix = "（含装填）" if ammo_load_cost else ""
            self._log(f"AP 不足{suffix}")
            return

        if self._state.in_combat:
            p.ap -= total_ap
            if ammo_load_cost:
                weapon.loaded = True
                self._log(f"{self._pn} 装填了 {weapon.name}")

        self._state.pending_attack = self._preserve_from_reaction({
            "mode": mode, "weapon": weapon,
            "hit_bonus": hit_bonus, "damage_bonus": damage_bonus,
            "attack_roll": None, "target": None,
        })

        # 近战/远程统一进入光标瞄准模式（max_range 由武器类型决定）
        self._enter_target_phase(weapon)


    def handle_maneuver_input(self, cmd: str) -> None:
        """阶段三A：命中后选择战技。按 maneuver_map 解析。"""
        pa = self._state.pending_attack
        weapon, hand_label = self._get_active_weapon()
        target = pa["target"]
        p = self._state.controlled_entity
        mmap = self._maneuver_map
        selected_maneuver = None
        m = {"effect": ""}

        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._log(f"无效选项: {cmd}")
            self._refresh()
            return

        if num == 0:
            pass
        elif num in mmap and mmap[num] is not None:
            m = mmap[num]
            selected_maneuver = m
            if not action_conditions_met(
                    m, p, target, weapon, self._state.controlled_entity_pos,
                    pa.get("target_pos")):
                self._log("当前条件不满足，无法发动该战技")
                self._refresh()
                return
            from domain.classes import CLASS_EXP_MANEUVER
            p.grant_class_exp(CLASS_EXP_MANEUVER)
            if self._state.in_combat:
                if p.ap < m["ap_extra"]:
                    self._log("AP 不足")
                    self._refresh()
                    return
                p.ap -= m["ap_extra"]
            p.grant_weapon_exp(weapon.category, 0.01)
            effect = m["effect"]
            if m["name"] == "横扫":
                pa["sweep_selected"] = True
                pa["target_shape"] = "1x3"
                pa["target"] = None
                pa["target_pos"] = None
                self._enter_target_phase(weapon)
                self._log("选择横扫的 1×3 范围")
                return
            if effect == "damage_bonus":
                bonus = roll_d20() % 4 + 1
                pa["damage_bonus"] = pa.get("damage_bonus", 0) + bonus
                self._log(f"{m['name']}! 伤害+{bonus}")
            elif effect == "disarm":
                dc = pa.get("attack_roll", 0)
                _, t_roll = saving_throw(target, "str")
                if t_roll < dc:
                    self._log(f"缴械成功! {target.name} 的武器被打落")
                else:
                    self._log(f"{target.name} 握紧了武器")
            elif effect == "knockdown":
                _, t_roll = saving_throw(target, "dex")
                if t_roll < pa.get("attack_roll", 0):
                    if not target.has_status("prone"):
                        target.add_status("prone")
                    self._log(f"扫腿成功! {target.name} 摔倒在地")
                else:
                    self._log(f"{target.name} 稳住了身形")
        else:
            self._log(f"无效选项: {cmd}")
            self._refresh()
            return

        # 结算伤害（复用 execute_attack_roll 阶段已掷出的攻击骰，与 NPC 走同一完整结算）
        result = resolve_attack(p, target, weapon,
                                hit=True, roll=pa.get("attack_roll", 0),
                                damage_bonus=pa.get("damage_bonus", 0),
                                damage_multiplier=(selected_maneuver or {}).get("damage_multiplier", 1),
                                nonlethal=self._state.knockout_mode,
                                award_weapon_experience=False)
        if selected_maneuver and selected_maneuver.get("effect") == "bleeding":
            for _ in range(selected_maneuver.get("bleeding_stacks", 0)):
                target.add_status("流血")
        dmg = result["damage"]
        self.check_faction_reaction(target, p, pa.get("target_pos"))

        # 躲藏中攻击 → 暴露位置（阶段4）
        self._state._hide_attack_expose(p, target)

        # 命中 → 玩家获得职业经验（实体通用，仅玩家升级时提示）
        if result.get("class_leveled"):
            self._log(f"{p.name} 的 {p.char_class} 等级提升至 {p.class_level}!")

        hand_prefix = f"{hand_label}" if hand_label else ""
        self._log(f"{self._pn} {hand_prefix}{weapon.name}砍中了 {target.name}, 造成 {dmg} 点伤害")
        if target.is_dead:
            self._log(f"{target.name} 倒在地上，不再动弹")
        elif target.has_status("濒死"):
            self._log(f"{target.name} 倒地不起，正在死亡边缘挣扎")
        elif target.has_status("昏迷"):
            self._log(f"{target.name} 昏迷过去")

        if not self._state.in_combat and are_hostile(target, self._state.controlled_entity) and not target.is_dead \
           and not target.has_status("濒死") \
           and self._target_can_see_attacker(pa.get("target_pos"), target):
            self._request_combat(target)

        # 双持模式：左手打完继续右手
        if pa.get("mode") in ("dual_wield", "dual_attack") and pa.get("step") == "left":
            self._continue_dual()
            self._refresh()
            self._wake()
            return

        self._end_pending_attack(abandoned=False)
        self._refresh()

    # ── 阶段三B：未命中后选择特殊行动 ──

    def handle_special_input(self, cmd: str) -> None:
        """阶段三B：未命中后选择特殊行动。输入 A0~A3。"""
        pa = self._state.pending_attack
        target = pa["target"]
        weapon, hand_label = self._get_active_weapon()
        p = self._state.controlled_entity

        smap = self._special_map
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._log(f"无效选项: {cmd}")
            self._refresh()
            return

        action_key = smap.get(num)
        if num == 0:
            self._end_pending_attack(abandoned=False)
            self._refresh()
            return
        if action_key is None:
            self._log(f"无效选项: {cmd}")
            self._refresh()
            return

        from domain.classes import COMBAT_ABILITY_DEFS
        action_def = COMBAT_ABILITY_DEFS.get(action_key, {})
        if not action_conditions_met(
                action_def, p, target, weapon,
                self._state.controlled_entity_pos, pa.get("target_pos")):
            self._log("当前条件不满足，无法发动该动作")
            self._refresh()
            return

        if action_key == "削韧":
            pa["tenacity_action"] = True
            from domain.combat.tenacity import settle_attack_tenacity
            settle_attack_tenacity(
                p, target, weapon, pa.get("attack_roll", 0),
                tenacity_action=True,
                combat_state=self._state,
                consume_extra=not pa.get("extra_consumed"),
                note_combo=False,
            )
            pa["extra_consumed"] = True
            self._log(f"削韧: {target.name} 韧性被削减")
        elif action_key == "重整旗鼓":
            if not spend_ap_or_pendulum(self._state, p, 10):
                self._log("AP 不足")
                self._refresh()
                return
            p.tenacity = min(p.tenacity_cap(), p.tenacity + 3)
            self._log("重整旗鼓: 自身韧性恢复 3 点")
        elif action_key == "扫腿":
            if not spend_ap_or_pendulum(self._state, p, 20):
                self._log("AP 不足")
                self._refresh()
                return
            dc = pa.get("attack_roll", 0)
            _, save_total = saving_throw(target, "dex")
            if save_total < dc:
                target.add_status("prone")
                self._log(f"扫腿成功: {target.name} 倒地")
            else:
                self._log(f"{target.name} 稳住了身形")

        if not self._state.in_combat and target and are_hostile(target, self._state.controlled_entity) and not target.is_dead \
           and not target.has_status("濒死") \
           and self._target_can_see_attacker(pa.get("target_pos"), target):
            self._request_combat(target)

        # 双持模式：左手打完继续右手
        if pa.get("mode") in ("dual_wield", "dual_attack") and pa.get("step") == "left":
            self._continue_dual()
            self._refresh()
            self._wake()
            return

        self._end_pending_attack(abandoned=False)
        self._refresh()

    # ── 通用 ──

