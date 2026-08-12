"""战斗流程状态机 —— 攻击方式选择 → 目标选择 → 命中检定 → 战技/特殊行动。"""

import random
from core.entity import Creature, Weapon, are_hostile
from core.dice import roll_d20
from core.combat.attack import hit_check, roll_damage, reduce_tenacity, apply_damage_type_modifiers, resolve_attack, miss_message, cover_message
from core.combat.cover import resolve_cover_line, terrain_cover_info
from core.movement import Terrain

# 空目标日志 — 按武器类型区分
EMPTY_TARGET_FLAVOR = {
    "ranged": {"wall": "箭矢射在了墙上", "empty": "箭矢射空了"},
    "melee":  {"wall": "{weapon}砍在了墙上", "empty": "{weapon}挥空了"},
}


class CombatFlow:
    """管理玩家攻击流程的五阶段状态机。

    app.py 创建实例并委托调用，只保留 UI 反馈（日志、刷新、开战回调）。
    """

    def __init__(self, state, act_log, left_panel, input_bar, map_view,
                 pn: str, start_combat_cb, refresh_all_cb,
                 on_two_hand_cb=None, wake_cb=None):
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

    # ── 辅助 ──

    def _target_can_see_attacker(self, target_pos, target) -> bool:
        """目标能否看到攻击者？（Chebyshev 距离 ≤ 目标视野范围）"""
        pc, pr = self._state.player_pos
        dist = max(abs(target_pos[0] - pc), abs(target_pos[1] - pr))
        return dist <= getattr(target, 'vision_range', 0)

    def _find_melee_tiles(self, reach: int = 1) -> list[tuple[int, int, object | None]]:
        """返回玩家 Chebyshev 距离 ≤ reach 的所有可攻击格子，按距离排序。
        每项: (col, row, entity_or_None)"""
        pc, pr = self._state.player_pos
        tiles = []
        for dc in range(-reach, reach + 1):
            for dr in range(-reach, reach + 1):
                if dc == 0 and dr == 0:
                    continue
                tc, tr = pc + dc, pr + dr
                if not self._state.map.within_bounds(tc, tr):
                    continue
                if (tc, tr) not in self._state.fov_cache:
                    continue
                dist = max(abs(dc), abs(dr))
                ent = self._state.get_entity_at(tc, tr)
                if ent is self._state.player:
                    ent = None
                if ent and ent.hp <= 0:
                    ent = None
                tiles.append((dist, tc, tr, ent))
        tiles.sort(key=lambda x: (x[0], x[3] is None))
        return [(tc, tr, ent) for _, tc, tr, ent in tiles]

    # ── 攻击流程入口 ──

    def start_action_phase(self) -> None:
        """按 A 键 → 进入攻击方式选择阶段。"""
        if self._state.combat_phase != "idle":
            return
        self._state.combat_phase = "select_action"
        self._state.pending_attack = {}
        self._act_log.add("[攻击] 选择武器 — 输入 A序号 确认, A0 取消")
        self._refresh_all()
        if self._wake_cb: self._wake_cb()

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
            if self._state.in_combat and p.ap < left_w.ap_cost:
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

        total_ap = weapon.ap_cost + ammo_load_cost
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

        # 远程武器 → 进入光标选目标模式
        if weapon.weapon_type == "ranged":
            self._state.combat_phase = "ranged_target"
            self._state.observe_cursor = self._state.player_pos
            self._act_log.add(
                f"选择远程目标 — 射程:{weapon.range_max} "
                f"[方向键]移动光标 [Enter]确认 [Esc]取消")
            self._refresh_all()
            return

        self._enter_target_phase(weapon)

    def _enter_target_phase(self, weapon) -> None:
        """进入目标选择阶段（近战通用）。"""
        reach = weapon.reach if hasattr(weapon, 'reach') and weapon.reach else 1
        tiles = self._find_melee_tiles(reach)

        if len(tiles) == 0:
            self._act_log.add("攻击范围内没有可攻击的格子")
            if not self._state.in_combat:
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
            else:
                self._state.combat_phase = "select_action"
            self._refresh_all()
            if self._wake_cb: self._wake_cb()
        elif len(tiles) == 1:
            tc, tr, target = tiles[0]
            self._state.pending_attack["target_pos"] = (tc, tr)
            self._state.pending_attack["target"] = target
            self.execute_attack_roll()
            self._refresh_all()
            if self._wake_cb: self._wake_cb()
        else:
            self._state.combat_phase = "select_target"
            self._refresh_all()
            if self._wake_cb: self._wake_cb()

    # ── 阶段二：选择目标 ──

    def handle_target_input(self, cmd: str) -> None:
        """阶段二：选择目标格子。输入 T1~Tn。"""
        if cmd == "T0":
            self._state.combat_phase = "select_action"
            self._act_log.add("取消目标选择")
            self._refresh_all()
            return

        try:
            idx = int(cmd[1:]) - 1
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}, 请输入 T序号")
            return

        weapon = self._state.pending_attack.get("weapon") if self._state.pending_attack else None
        reach = weapon.reach if weapon and hasattr(weapon, 'reach') and weapon.reach else 1
        tiles = self._find_melee_tiles(reach)

        if 0 <= idx < len(tiles):
            tc, tr, target = tiles[idx]
            self._state.pending_attack["target_pos"] = (tc, tr)
            self._state.pending_attack["target"] = target
            self.execute_attack_roll()
        else:
            self._act_log.add("目标序号无效")
        self._refresh_all()

    # ── 阶段二B：远程光标选目标 ──

    def confirm_ranged_target(self) -> None:
        """确认远程目标选择（以格子为单位），进入攻击检定。"""
        pa = self._state.pending_attack
        if pa is None:
            return
        cursor = self._state.observe_cursor
        # 检查目标是否在射程内
        weapon = pa.get("weapon")
        max_range = weapon.range_max if weapon else 8
        pc, pr = self._state.player_pos
        if max(abs(cursor[0] - pc), abs(cursor[1] - pr)) > max_range:
            self._act_log.add("目标超出了射程")
            self._refresh_all()
            return
        # 目标必须在视野内
        if cursor not in self._state.fov_cache:
            self._act_log.add("无法瞄准不可见的目标")
            self._refresh_all()
            return
        # 查找格子上的生物（可为 None）
        target = self._state.get_entity_at(cursor[0], cursor[1])
        if target is self._state.player or (target and target.hp <= 0):
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

    def execute_attack_roll(self) -> None:
        """执行攻击检定，根据命中/未命中进入阶段三。

        双持模式委托给 _execute_dual_step() 分步处理。
        """
        pa = self._state.pending_attack
        mode = pa.get("mode", "")

        # 双持模式 → 分步结算
        if mode in ("dual_wield", "dual_attack"):
            self._execute_dual_step()
            return

        weapon = pa["weapon"]
        target = pa.get("target")
        target_pos = pa.get("target_pos")
        p = self._state.player

        # AP 已在 handle_action_input 中扣除（含装填），此处不再重复

        # 无目标（空格子或障碍物）→ 直接结束
        if target is None:
            self._log_empty_target(weapon, target_pos)
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            return

        # 攻击掷骰前：目标能看到攻击者 → 记录临时敌对 + 进战斗
        if not self._state.in_combat and self._target_can_see_attacker(target_pos, target):
            if target.faction == "中立" or target.faction == "守序":
                target._hostile_to.add(id(p))
                self._act_log.add(f"{target.name} 被激怒，开始反击!")
            self._start_combat_from_ambush(target)

        hit, roll = hit_check(p, target, weapon)

        pa["attack_roll"] = roll
        pa["hit"] = hit
        self._act_log.add(f"{self._pn} 使用{weapon.name}攻击 {target.name}! (roll={roll})")

        # 远程武器掩体检查（命中后、进入战技面板前）
        if hit and weapon.weapon_type == "ranged":
            attacker_pos = self._state.get_entity_pos(p) or self._state.player_pos
            tc, tr = target_pos if target_pos else (0, 0)
            blocked, cover_pos = resolve_cover_line(
                roll, attacker_pos, (tc, tr),
                self._state.map, weapon.weapon_type,
                ground_items=self._state.ground_items,
            )
            if blocked:
                hit = False
                pa["hit"] = False
                pa["blocked_by_cover"] = True
                pa["cover_pos"] = cover_pos
                reduce_tenacity(target, roll)
                if cover_pos:
                    cx, cy = cover_pos
                    terrain = self._state.map[cx, cy]
                    info = terrain_cover_info(terrain)
                    if info:
                        cover_ac, cover_type = info
                        self._act_log.add(
                            f"{cover_message(weapon.damage_type)}! roll={roll} < 掩体AC{cover_ac}, "
                            f"位置({cx},{cy}) {cover_type}")
                    else:
                        self._act_log.add(f"{cover_message(weapon.damage_type)}!")
                else:
                    self._act_log.add(f"{cover_message(weapon.damage_type)}!")

        # 弹药武器攻击后变为未装填
        self._unload_ammo(weapon)

        if hit:
            self._state.combat_phase = "select_maneuver"
        else:
            self._state.combat_phase = "select_special"
            if not pa.get("blocked_by_cover"):
                self._act_log.add(miss_message(self._pn, target.name, weapon.damage_type)
                                  + f" (roll={roll})")

    def _unload_ammo(self, weapon) -> None:
        """弹药武器攻击后变为未装填。"""
        props = getattr(weapon, 'properties', []) or []
        if "ammo" in props:
            weapon.loaded = False

    def _log_empty_target(self, weapon, target_pos) -> None:
        """空目标日志 — 按武器类型查表。"""
        tc, tr = target_pos if target_pos else (0, 0)
        terrain = self._state.map[tc, tr]
        flavor = EMPTY_TARGET_FLAVOR.get(weapon.weapon_type, EMPTY_TARGET_FLAVOR["melee"])
        key = "wall" if terrain == Terrain.WALL else "empty"
        self._act_log.add(flavor[key].format(weapon=weapon.name))

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
            if p.ap < weapon.ap_cost:
                hand_name = "左手" if step == "left" else "右手"
                self._act_log.add(f"AP 不足，无法发动{hand_name}攻击")
                # 如果是左手 AP 不足则直接结束；右手则只跳过右手
                if step == "left":
                    self._state.combat_phase = "idle"
                    self._state.pending_attack = {}
                else:
                    self._finish_dual()
                return
            p.ap -= weapon.ap_cost

        # 攻击掷骰前（仅第一步）：目标能看到攻击者 → 记录临时敌对 + 进战斗
        if step == "left" and not self._state.in_combat and target \
           and self._target_can_see_attacker(target_pos, target):
            if target.faction == "中立" or target.faction == "守序":
                target._hostile_to.add(id(p))
                self._act_log.add(f"{target.name} 被激怒，开始反击!")
            self._start_combat_from_ambush(target)

        # 无目标 → 直接结束双持
        if target is None:
            self._log_empty_target(weapon, target_pos)
            self._finish_dual()
            return

        hand_name = "左手" if step == "left" else "右手"
        hit, roll = hit_check(p, target, weapon)

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

        # 结算伤害
        roll = pa.get("attack_roll", 0)
        critical = (roll == 20)
        dmg = roll_damage(weapon, p, critical=critical)
        dmg += pa.get("damage_bonus", 0)
        dmg = apply_damage_type_modifiers(dmg, weapon.damage_type, target)
        target.hp = max(0, target.hp - dmg)
        self.check_faction_reaction(target, pa.get("target_pos"))

        hand_prefix = f"{hand_label}" if hand_label else ""
        self._act_log.add(f"{self._pn} {hand_prefix}{weapon.name}砍中了 {target.name}, 造成 {dmg} 点伤害")
        if target.hp <= 0:
            self._act_log.add(f"{target.name} 倒在地上，不再动弹")

        if not self._state.in_combat and are_hostile(target, self._state.player) and target.hp > 0 \
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
            if self._state.in_combat and p.ap < 2:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 2
            self._act_log.add("奋力一击! 重掷攻击骰")
            result = self.resolve_melee_attack(p, target, weapon)
            if result["hit"]:
                self.check_faction_reaction(target, pa.get("target_pos"))
                self._act_log.add(f"命中! 造成 {result['damage']} 点伤害")
            else:
                self._act_log.add("再次未命中...")
        elif action_key == "feint":
            if self._state.in_combat and p.ap < 1:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 1
            self._act_log.add("虚晃一招 — 下次攻击命中+2")
        elif action_key == "taunt":
            if self._state.in_combat and p.ap < 1:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 1
            self._act_log.add(f"{self._pn} 挑衅了 {target.name}")

        if not self._state.in_combat and target and are_hostile(target, self._state.player) and target.hp > 0 \
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

    def resolve_melee_attack(self, attacker, target, weapon,
                             hit_bonus=0, damage_bonus=0) -> dict:
        """执行一次攻击检定，返回结果 dict。不修改 AP，不切换回合。"""
        attacker_pos = self._state.get_entity_pos(attacker)
        target_pos = self._state.get_entity_pos(target)
        result = resolve_attack(
            attacker, target, weapon,
            attacker_pos=attacker_pos, target_pos=target_pos,
            grid=self._state.map,
            ground_items=self._state.ground_items,
        )
        if result["hit"]:
            result["damage"] += damage_bonus
        return result

    def check_faction_reaction(self, target: Creature,
                                target_pos: tuple = None) -> None:
        """玩家攻击非敌对生物后检查阵营反应。视野外攻击不触发。"""
        if target_pos and not self._target_can_see_attacker(target_pos, target):
            return  # 目标看不到攻击者，不知道谁打的
        if target.faction == "中立" or target.faction == "守序":
            target._hostile_to.add(id(self._state.player))
            self._act_log.add(f"{target.name} 被激怒了! 开始反击")
            if self._state.in_combat:
                if target not in self._state.combat_initiative:
                    self._state.combat_initiative.append(target)
