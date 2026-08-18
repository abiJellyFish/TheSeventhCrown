"""命令路由表 —— 攻击方式/战技/特殊行动的输入解析。"""
import random
from core.entity import Entity, Weapon, are_hostile
from core.dice import roll_d20, roll_adv_dice, resolve_adv_auto
from core.combat.attack import hit_check, reduce_tenacity, resolve_attack, miss_message, cover_message, compute_attack_adv
from core.combat.cover import resolve_cover_line, terrain_cover_info
from core.movement import Terrain


class ActionMenuMixin:

    # ── 阶段一：选择攻击方式 ──

    def handle_action_input(self, cmd: str) -> None:
        """阶段一：选择攻击方式。按动态 action_map 解析序号。"""
        from core.combat.dual_wield import dual_wield_mode, dual_wield_ap_cost

        p = self._state.player
        equip = p.equipment
        action_map = self._left_panel._action_map

        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            return

        if num == 0:
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self._act_log.add("取消攻击")
            self._refresh_all()
            return

        entry = action_map.get(num)
        if entry is None:
            self._act_log.add(f"无效选项: {cmd}")
            return

        mode, weapon = entry
        hit_bonus = 0
        damage_bonus = 0

        # 火把点燃/熄灭 — 无需目标选择，直接结算
        if mode in ("torch_ignite", "torch_extinguish"):
            if self._state.in_combat and p.ap < 10:
                self._act_log.add("AP 不足")
                return
            if self._state.in_combat:
                p.ap -= 10
            if self._on_torch_action:
                self._on_torch_action(weapon, mode)
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self._refresh_all()
            return

        # 火把点火地表 — 进入相邻格选择（max_range=1）
        if mode == "torch_ignite_surface":
            if self._state.in_combat and p.ap < 10:
                self._act_log.add("AP 不足")
                return
            self._state.combat_phase = "ranged_target"
            self._state.observe_mode = False
            self._state.pending_attack = {
                "mode": "torch_ignite_surface",
                "weapon": weapon,
                "max_range": 1,
            }
            self._state.observe_cursor = self._state.player_pos
            self._act_log.add("选择相邻一格点火 (方向键移动, Enter确认, '取消)")
            self._refresh_all()
            return

        if mode.endswith("_blocked"):
            self._act_log.add(f"{weapon.name} 无法用于攻击")
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
            if self._on_two_hand:
                self._on_two_hand(weapon, hand=hand)

        # ── 双持武器：两把轻型，一次 AP ──
        if mode == "dual_wield":
            left_w = equip.get("left_hand") or Weapon(name="徒手打击", weapon_type="melee",
                damage="1", damage_type="bludgeoning", attack_stat="str", ap_cost=1, properties=["light"])
            right_w = equip.get("right_hand") or Weapon(name="徒手打击", weapon_type="melee",
                damage="1", damage_type="bludgeoning", attack_stat="str", ap_cost=1, properties=["light"])
            ap = dual_wield_ap_cost(left_w, right_w)
            if self._state.in_combat and p.ap < ap:
                self._act_log.add("AP 不足")
                return
            if self._state.in_combat:
                p.ap -= ap
            self._state.pending_attack = {
                "mode": mode, "weapon": right_w,
                "weapon_left": left_w, "weapon_right": right_w,
                "hit_bonus": 0, "damage_bonus": 0,
                "attack_roll": None, "target": None,
                "step": "left",
            }
            self._enter_target_phase(weapon)
            return

        # ── 双持攻击：至少一把非轻型，分别扣 AP ──
        if mode == "dual_attack":
            left_w = equip.get("left_hand") or Weapon(name="徒手打击", weapon_type="melee",
                damage="1", damage_type="bludgeoning", attack_stat="str", ap_cost=1, properties=["light"])
            right_w = equip.get("right_hand") or Weapon(name="徒手打击", weapon_type="melee",
                damage="1", damage_type="bludgeoning", attack_stat="str", ap_cost=1, properties=["light"])
            if self._state.in_combat and p.ap < left_w.weapon.ap_cost:
                self._act_log.add("AP 不足")
                return
            self._state.pending_attack = {
                "mode": mode, "weapon": right_w,
                "weapon_left": left_w, "weapon_right": right_w,
                "hit_bonus": 0, "damage_bonus": 0,
                "attack_roll": None, "target": None,
                "step": "left",
            }
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
            self._act_log.add(f"AP 不足{suffix}")
            return

        if self._state.in_combat:
            p.ap -= total_ap
            if ammo_load_cost:
                weapon.loaded = True
                self._act_log.add(f"{self._pn} 装填了 {weapon.name}")

        self._state.pending_attack = {
            "mode": mode, "weapon": weapon,
            "hit_bonus": hit_bonus, "damage_bonus": damage_bonus,
            "attack_roll": None, "target": None,
        }

        # 近战/远程统一进入光标瞄准模式（max_range 由武器类型决定）
        self._enter_target_phase(weapon)


    def handle_maneuver_input(self, cmd: str) -> None:
        """阶段三A：命中后选择战技。按 maneuver_map 解析。"""
        pa = self._state.pending_attack
        weapon, hand_label = self._get_active_weapon()
        target = pa["target"]
        p = self._state.player
        mmap = self._left_panel._maneuver_map

        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            self._refresh_all()
            return

        if num == 0:
            pass
        elif num in mmap and mmap[num] is not None:
            m = mmap[num]
            if self._state.in_combat:
                if p.ap < m["ap_extra"]:
                    self._act_log.add("AP 不足")
                    self._refresh_all()
                    return
                p.ap -= m["ap_extra"]
            effect = m["effect"]
            if effect == "damage_bonus":
                bonus = roll_d20() % 4 + 1
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
                    if not target.has_status("prone"):
                        target.add_status("prone")
                    self._act_log.add(f"扫腿成功! {target.name} 摔倒在地")
                else:
                    self._act_log.add(f"{target.name} 稳住了身形")
        else:
            self._act_log.add(f"无效选项: {cmd}")
            self._refresh_all()
            return

        # 结算伤害（复用 execute_attack_roll 阶段已掷出的攻击骰，与 NPC 走同一完整结算）
        result = resolve_attack(p, target, weapon,
                                hit=True, roll=pa.get("attack_roll", 0),
                                damage_bonus=pa.get("damage_bonus", 0),
                                nonlethal=self._state.knockout_mode)
        dmg = result["damage"]
        self.check_faction_reaction(target, p, pa.get("target_pos"))

        # 躲藏中攻击 → 暴露位置（阶段4）
        self._state._hide_attack_expose(p, target)

        # 命中 → 玩家获得职业经验（实体通用，仅玩家升级时提示）
        if result.get("class_leveled"):
            self._act_log.add(f"{p.name} 的 {p.char_class} 等级提升至 {p.class_level:.1f}!")

        hand_prefix = f"{hand_label}" if hand_label else ""
        self._act_log.add(f"{self._pn} {hand_prefix}{weapon.name}砍中了 {target.name}, 造成 {dmg} 点伤害")
        if target.is_dead:
            self._act_log.add(f"{target.name} 倒在地上，不再动弹")
        elif target.has_status("濒死"):
            self._act_log.add(f"{target.name} 倒地不起，正在死亡边缘挣扎")
        elif target.has_status("昏迷"):
            self._act_log.add(f"{target.name} 昏迷过去")

        if not self._state.in_combat and are_hostile(target, self._state.player) and not target.is_dead \
           and not target.has_status("濒死") \
           and self._target_can_see_attacker(pa.get("target_pos"), target):
            self._start_combat_from_ambush(target)

        # 双持模式：左手打完继续右手
        if pa.get("mode") in ("dual_wield", "dual_attack") and pa.get("step") == "left":
            self._continue_dual()
            self._refresh_all()
            if self._wake_cb: self._wake_cb()
            return

        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._refresh_all()

    # ── 阶段三B：未命中后选择特殊行动 ──

    def handle_special_input(self, cmd: str) -> None:
        """阶段三B：未命中后选择特殊行动。输入 A0~A3。"""
        pa = self._state.pending_attack
        target = pa["target"]
        weapon, hand_label = self._get_active_weapon()
        p = self._state.player

        smap = self._left_panel._special_map
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            self._refresh_all()
            return

        action_key = smap.get(num)
        if action_key is None:
            self._act_log.add(f"无效选项: {cmd}")
            self._refresh_all()
            return

        if action_key == "tenacity":
            self._act_log.add(f"削韧: {target.name} 韧性被削减")
        elif action_key == "reroll":
            if self._state.in_combat and p.ap < 20:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 20
            self._act_log.add("奋力一击! 重掷攻击骰")
            result = self.resolve_melee_attack(p, target, weapon)
            if result["hit"]:
                self.check_faction_reaction(target, p, pa.get("target_pos"))
                self._act_log.add(f"命中! 造成 {result['damage']} 点伤害")
                if result.get("class_leveled"):
                    self._act_log.add(f"{p.name} 的 {p.char_class} 等级提升至 {p.class_level:.1f}!")
            else:
                self._act_log.add("再次未命中...")
        elif action_key == "feint":
            if self._state.in_combat and p.ap < 10:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 10
            self._act_log.add("虚晃一招 — 下次攻击命中+2")
        elif action_key == "taunt":
            if self._state.in_combat and p.ap < 10:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 10
            self._act_log.add(f"{self._pn} 挑衅了 {target.name}")

        if not self._state.in_combat and target and are_hostile(target, self._state.player) and not target.is_dead \
           and not target.has_status("濒死") \
           and self._target_can_see_attacker(pa.get("target_pos"), target):
            self._start_combat_from_ambush(target)

        # 双持模式：左手打完继续右手
        if pa.get("mode") in ("dual_wield", "dual_attack") and pa.get("step") == "left":
            self._continue_dual()
            self._refresh_all()
            if self._wake_cb: self._wake_cb()
            return

        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._refresh_all()

    # ── 通用 ──

